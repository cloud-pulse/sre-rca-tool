from __future__ import annotations

from datetime import datetime, timezone

from core.logger import get_logger
from flags import (
    K8S_COLLECT_CONFIGMAPS,
    K8S_COLLECT_DEPLOYMENTS,
    K8S_COLLECT_EVENTS,
    K8S_COLLECT_LOGS,
    K8S_COLLECT_NODES,
    K8S_COLLECT_NETWORK_POLICIES,
    K8S_COLLECT_PODS,
    K8S_COLLECT_PVC,
    K8S_COLLECT_QUOTAS,
    K8S_COLLECT_SECRETS_META,
)
from .models import (
    K8sClusterSnapshot,
    K8sCondition,
    K8sConfigMap,
    K8sContainerState,
    K8sDeployment,
    K8sEvent,
    K8sNetworkPolicy,
    K8sNode,
    K8sPVC,
    K8sPod,
    K8sResourceQuota,
    K8sSecretMeta,
)

log = get_logger("k8s_collector")


class K8sCollector:
    def __init__(self, client_manager, timeout_seconds: int = 30, guard=None):
        self.client = client_manager
        self.timeout_seconds = timeout_seconds
        self.guard = guard
        # If no guard provided, create a default one
        if self.guard is None:
            try:
                from .namespace_guard import NamespaceGuard
                self.guard = NamespaceGuard()
            except Exception as e:
                log.debug(f"NamespaceGuard initialization skipped: {e}")
                self.guard = None

    def _api_exc(self):
        try:
            from kubernetes.client.exceptions import ApiException
            return ApiException
        except Exception:
            return Exception

    def collect_pod_logs(self, pod: str, ns: str, tail: int = 100, container: str | None = None) -> list[str]:
        if not K8S_COLLECT_LOGS or not self.client.is_available():
            return []
        core = self.client.get_core_v1()
        try:
            raw = core.read_namespaced_pod_log(
                name=pod,
                namespace=ns,
                tail_lines=tail,
                container=container,
                _request_timeout=self.timeout_seconds,
            )
            return [line for line in (raw or "").splitlines() if line.strip()]
        except self._api_exc() as exc:
            log.warn(f"Failed to collect pod logs for {pod}: {exc}")
            return []

    def collect_previous_logs(self, pod: str, ns: str, tail: int = 100, container: str | None = None) -> list[str]:
        if not K8S_COLLECT_LOGS or not self.client.is_available():
            return []
        core = self.client.get_core_v1()
        try:
            raw = core.read_namespaced_pod_log(
                name=pod,
                namespace=ns,
                tail_lines=tail,
                previous=True,
                container=container,
                _request_timeout=self.timeout_seconds,
            )
            return [line for line in (raw or "").splitlines() if line.strip()]
        except self._api_exc():
            return []

    def collect_pods(self, ns: str) -> list[K8sPod]:
        if not K8S_COLLECT_PODS or not self.client.is_available():
            return []
        core = self.client.get_core_v1()
        pods: list[K8sPod] = []
        try:
            response = core.list_namespaced_pod(ns, _request_timeout=self.timeout_seconds)
            for item in response.items:
                statuses = item.status.container_statuses or []
                container_states: list[K8sContainerState] = []
                restart_count = 0
                for c in statuses:
                    state = "unknown"
                    reason = ""
                    if c.state and c.state.running:
                        state = "running"
                    elif c.state and c.state.waiting:
                        state = "waiting"
                        reason = c.state.waiting.reason or ""
                    elif c.state and c.state.terminated:
                        state = "terminated"
                        reason = c.state.terminated.reason or ""
                    restart_count += c.restart_count or 0
                    container_states.append(
                        K8sContainerState(
                            name=c.name,
                            state=state,
                            state_reason=reason,
                            restart_count=c.restart_count or 0,
                            ready=bool(c.ready),
                        )
                    )

                images = [c.image for c in item.spec.containers or [] if c.image]
                logs = self.collect_pod_logs(item.metadata.name, ns, container=None)
                previous_logs = self.collect_previous_logs(item.metadata.name, ns, container=None)

                pods.append(
                    K8sPod(
                        name=item.metadata.name,
                        namespace=ns,
                        node_name=item.spec.node_name or "",
                        image=", ".join(images),
                        restart_count=restart_count,
                        ready=all(cs.ready for cs in statuses) if statuses else False,
                        phase=item.status.phase or "Unknown",
                        container_states=container_states,
                        logs=logs,
                        previous_logs=previous_logs,
                    )
                )
            return pods
        except self._api_exc() as exc:
            log.warn(f"Failed to collect pods for namespace {ns}: {exc}")
            return []

    def collect_deployments(self, ns: str) -> list[K8sDeployment]:
        if not K8S_COLLECT_DEPLOYMENTS or not self.client.is_available():
            return []
        apps = self.client.get_apps_v1()
        output: list[K8sDeployment] = []
        try:
            response = apps.list_namespaced_deployment(ns, _request_timeout=self.timeout_seconds)
            for item in response.items:
                conditions = []
                for c in item.status.conditions or []:
                    conditions.append(
                        K8sCondition(
                            type=c.type or "",
                            status=c.status or "Unknown",
                            reason=c.reason or "",
                            message=c.message or "",
                            last_transition_time=str(c.last_transition_time or ""),
                        )
                    )
                output.append(
                    K8sDeployment(
                        name=item.metadata.name,
                        namespace=ns,
                        replicas_desired=item.spec.replicas or 0,
                        replicas_ready=item.status.ready_replicas or 0,
                        replicas_updated=item.status.updated_replicas or 0,
                        replicas_available=item.status.available_replicas or 0,
                        conditions=conditions,
                    )
                )
            return output
        except self._api_exc() as exc:
            log.warn(f"Failed to collect deployments for namespace {ns}: {exc}")
            return []

    def collect_events(self, ns: str) -> list[K8sEvent]:
        if not K8S_COLLECT_EVENTS or not self.client.is_available():
            return []
        core = self.client.get_core_v1()
        events: list[K8sEvent] = []
        try:
            response = core.list_namespaced_event(ns, _request_timeout=self.timeout_seconds)
            for item in response.items:
                event_type = item.type or "Normal"
                reason = item.reason or ""
                # Filter: only Warning type events, or Normal events with reason in [FailedScheduling, BackOff]
                if event_type == "Warning" or (event_type == "Normal" and reason in ["FailedScheduling", "BackOff"]):
                    events.append(
                        K8sEvent(
                            name=item.metadata.name,
                            namespace=ns,
                            type=event_type,
                            reason=reason,
                            message=item.message or "",
                            first_timestamp=str(item.first_timestamp or ""),
                            last_timestamp=str(item.last_timestamp or ""),
                            count=item.count or 0,
                            involved_object={
                                "kind": getattr(item.involved_object, "kind", ""),
                                "name": getattr(item.involved_object, "name", ""),
                            },
                        )
                    )
            return events
        except self._api_exc() as exc:
            log.warn(f"Failed to collect events for namespace {ns}: {exc}")
            return []

    def collect_nodes(self) -> list[K8sNode]:
        if not K8S_COLLECT_NODES or not self.client.is_available():
            return []
        core = self.client.get_core_v1()
        nodes: list[K8sNode] = []
        try:
            response = core.list_node(_request_timeout=self.timeout_seconds)
            for item in response.items:
                conditions = []
                ready = False
                for c in item.status.conditions or []:
                    cond = K8sCondition(
                        type=c.type or "",
                        status=c.status or "Unknown",
                        reason=c.reason or "",
                        message=c.message or "",
                        last_transition_time=str(c.last_transition_time or ""),
                    )
                    conditions.append(cond)
                    if cond.type == "Ready" and cond.status == "True":
                        ready = True
                nodes.append(
                    K8sNode(
                        name=item.metadata.name,
                        ready=ready,
                        cpu_capacity=(item.status.capacity or {}).get("cpu", ""),
                        memory_capacity=(item.status.capacity or {}).get("memory", ""),
                        conditions=conditions,
                        taints=[str(t) for t in (item.spec.taints or [])],
                    )
                )
            return nodes
        except self._api_exc() as exc:
            log.warn(f"Failed to collect nodes: {exc}")
            return []

    def collect_pvcs(self, ns: str) -> list[K8sPVC]:
        if not K8S_COLLECT_PVC or not self.client.is_available():
            return []
        core = self.client.get_core_v1()
        output: list[K8sPVC] = []
        try:
            response = core.list_namespaced_persistent_volume_claim(ns, _request_timeout=self.timeout_seconds)
            for item in response.items:
                output.append(
                    K8sPVC(
                        name=item.metadata.name,
                        namespace=ns,
                        status=(item.status.phase or "Unknown"),
                        storage_class=item.spec.storage_class_name or "",
                        capacity=(item.status.capacity or {}).get("storage", ""),
                        access_modes=item.spec.access_modes or [],
                    )
                )
            return output
        except self._api_exc() as exc:
            log.warn(f"Failed to collect PVCs for namespace {ns}: {exc}")
            return []

    def collect_resource_quotas(self, ns: str) -> list[K8sResourceQuota]:
        if not K8S_COLLECT_QUOTAS or not self.client.is_available():
            return []
        core = self.client.get_core_v1()
        output: list[K8sResourceQuota] = []
        try:
            response = core.list_namespaced_resource_quota(ns, _request_timeout=self.timeout_seconds)
            for item in response.items:
                output.append(
                    K8sResourceQuota(
                        name=item.metadata.name,
                        namespace=ns,
                        hard=dict(item.status.hard or {}),
                        used=dict(item.status.used or {}),
                    )
                )
            return output
        except self._api_exc() as exc:
            log.warn(f"Failed to collect resource quotas for namespace {ns}: {exc}")
            return []

    def collect_network_policies(self, ns: str) -> list[K8sNetworkPolicy]:
        if not K8S_COLLECT_NETWORK_POLICIES or not self.client.is_available():
            return []
        networking = self.client.get_networking_v1()
        output: list[K8sNetworkPolicy] = []
        try:
            response = networking.list_namespaced_network_policy(ns, _request_timeout=self.timeout_seconds)
            for item in response.items:
                output.append(
                    K8sNetworkPolicy(
                        name=item.metadata.name,
                        namespace=ns,
                        pod_selector=dict((item.spec.pod_selector or {}).match_labels or {}),
                        ingress_rules=[dict(r.to_dict()) for r in (item.spec.ingress or [])],
                        egress_rules=[dict(r.to_dict()) for r in (item.spec.egress or [])],
                    )
                )
            return output
        except self._api_exc() as exc:
            log.warn(f"Failed to collect network policies for namespace {ns}: {exc}")
            return []

    def collect_configmaps(self, ns: str) -> list[K8sConfigMap]:
        if not K8S_COLLECT_CONFIGMAPS or not self.client.is_available():
            return []
        core = self.client.get_core_v1()
        output: list[K8sConfigMap] = []
        try:
            response = core.list_namespaced_config_map(ns, _request_timeout=self.timeout_seconds)
            for item in response.items:
                output.append(
                    K8sConfigMap(
                        name=item.metadata.name,
                        namespace=ns,
                        keys=sorted(list((item.data or {}).keys())),
                    )
                )
            return output
        except self._api_exc() as exc:
            log.warn(f"Failed to collect configmaps for namespace {ns}: {exc}")
            return []

    def collect_secret_metadata(self, ns: str) -> list[K8sSecretMeta]:
        if not K8S_COLLECT_SECRETS_META or not self.client.is_available():
            return []
        core = self.client.get_core_v1()
        output: list[K8sSecretMeta] = []
        try:
            response = core.list_namespaced_secret(ns, _request_timeout=self.timeout_seconds)
            for item in response.items:
                output.append(
                    K8sSecretMeta(
                        name=item.metadata.name,
                        namespace=ns,
                        type=item.type or "",
                        keys=sorted(list((item.data or {}).keys())),
                    )
                )
            return output
        except self._api_exc() as exc:
            log.warn(f"Failed to collect secret metadata for namespace {ns}: {exc}")
            return []

    def collect_all(self, namespaces: list[str]) -> K8sClusterSnapshot:
        namespaces = [ns.strip() for ns in namespaces if ns and ns.strip()] or ["default"]
        
        # Filter namespaces using guard if available
        if self.guard:
            safe_namespaces = self.guard.get_safe_namespaces(namespaces)
            if safe_namespaces != namespaces:
                log.info(f"Filtered namespaces: {namespaces} → {safe_namespaces} (protected excluded)")
                namespaces = safe_namespaces
        
        pods = []
        deployments = []
        events = []
        pvcs = []
        quotas = []
        netpol = []
        cms = []
        secret_meta = []

        for ns in namespaces:
            pods.extend(self.collect_pods(ns))
            deployments.extend(self.collect_deployments(ns))
            events.extend(self.collect_events(ns))
            pvcs.extend(self.collect_pvcs(ns))
            quotas.extend(self.collect_resource_quotas(ns))
            netpol.extend(self.collect_network_policies(ns))
            cms.extend(self.collect_configmaps(ns))
            secret_meta.extend(self.collect_secret_metadata(ns))

        nodes = self.collect_nodes()
        return K8sClusterSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            namespaces=namespaces,
            pods=pods,
            deployments=deployments,
            events=events,
            nodes=nodes,
            pvcs=pvcs,
            quotas=quotas,
            network_policies=netpol,
            configmaps=cms,
            secret_metadata=secret_meta,
        )
