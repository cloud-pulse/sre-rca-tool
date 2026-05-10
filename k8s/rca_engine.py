from __future__ import annotations

from datetime import datetime, timezone

from core.service_graph import ServiceGraph
from .event_analyzer import K8sEventAnalyzer
from .models import K8sRCAFinding
from .service_mapper import K8sServiceMapper


FAILURE_PATTERN_TO_ROOT_CAUSE = {
    "CrashLoopBackOff": "Pod entered CrashLoopBackOff",
    "OOMKilled": "Container memory limit exceeded",
    "ImagePullBackOff": "Container image could not be pulled",
    "FailedScheduling": "Pod scheduling failed due to cluster constraints",
    "ReadinessFailed": "Readiness probe failed",
    "DependencyFailed": "Upstream dependency is unavailable",
    "NodeNotReady": "Node reported NotReady",
    "PVCUnbound": "PersistentVolumeClaim is not bound",
    "QuotaExceeded": "Resource quota exceeded",
    "NetworkPolicyBlock": "Network policy likely blocking traffic",
    "MissingConfigMap": "Missing ConfigMap mount",
    "MissingSecret": "Missing Secret mount",
}

FAILURE_PATTERN_TO_RECOMMENDATIONS = {
    "CrashLoopBackOff": [
        "Check container startup logs and previous logs",
        "Validate startup configuration and dependency connectivity",
    ],
    "OOMKilled": [
        "Increase memory requests/limits",
        "Profile application memory usage",
    ],
    "ImagePullBackOff": [
        "Verify image tag and registry access",
    ],
    "FailedScheduling": [
        "Check node capacity, taints/tolerations, and affinity constraints",
    ],
    "ReadinessFailed": [
        "Inspect readiness probe configuration and dependent service health",
    ],
    "DependencyFailed": [
        "Validate upstream dependency availability and service DNS",
    ],
    "NodeNotReady": [
        "Investigate node condition and kubelet status",
    ],
    "PVCUnbound": [
        "Check storage class and PV provisioning",
    ],
    "QuotaExceeded": [
        "Adjust namespace resource quota or workload requests",
    ],
    "NetworkPolicyBlock": [
        "Review network policies and allowed ingress/egress rules",
    ],
    "MissingConfigMap": [
        "Restore required ConfigMap and restart affected pods",
    ],
    "MissingSecret": [
        "Restore required Secret and restart affected pods",
    ],
}


class K8sRCAEngine:
    def __init__(self):
        self.analyzer = K8sEventAnalyzer()
        self.graph = ServiceGraph()

    def generate_rca(self, service_name: str, snapshot, log_context: dict | None = None) -> K8sRCAFinding:
        self.mapper = K8sServiceMapper(snapshot)
        mapping = self.mapper.resolve(service_name)
        namespace = mapping["namespace"] if mapping else "default"
        target = service_name.replace("-", "")

        service_pods = [
            pod
            for pod in snapshot.pods
            if pod.namespace == namespace
            and (service_name in pod.name or target in pod.name.replace("-", ""))
        ]
        if not service_pods:
            service_pods = [
                pod
                for pod in snapshot.pods
                if service_name in pod.name or target in pod.name.replace("-", "")
            ]
            if service_pods:
                namespace = service_pods[0].namespace

        service_events = [
            evt
            for evt in snapshot.events
            if evt.namespace == namespace
            and (service_name in evt.message or target in evt.message.replace("-", ""))
        ]
        service_nodes = snapshot.nodes
        service_pvcs = [
            pvc
            for pvc in snapshot.pvcs
            if pvc.namespace == namespace
            and (service_name in pvc.name or target in pvc.name.replace("-", ""))
        ]
        service_quotas = [q for q in snapshot.quotas if q.namespace == namespace]

        patterns = self.analyzer.detect_patterns(
            snapshot=snapshot,
            service_pods=service_pods,
            service_events=service_events,
            service_nodes=service_nodes,
            service_pvcs=service_pvcs,
            service_quotas=service_quotas,
        )

        if not patterns and self._has_dependency_failure(service_name, snapshot):
            patterns.append("DependencyFailed")

        severity = self.analyzer.classify_severity(patterns)
        root_cause = FAILURE_PATTERN_TO_ROOT_CAUSE.get(patterns[0], "No critical Kubernetes issue detected") if patterns else "No critical Kubernetes issue detected"

        evidence = self._build_evidence(service_pods, service_events, patterns)
        recommendations = self._build_recommendations(patterns)

        return K8sRCAFinding(
            service=service_name,
            namespace=namespace,
            status="Failed" if patterns else "Healthy",
            severity=severity,
            root_cause=root_cause,
            supporting_causes=patterns[1:] if len(patterns) > 1 else [],
            evidence=evidence,
            recommendations=recommendations,
            affected_resources=[pod.name for pod in service_pods],
            detected_at=datetime.now(timezone.utc).isoformat(),
        )

    def generate_rca_for_all(self, snapshot, log_context: dict | None = None) -> list[K8sRCAFinding]:
        services = sorted(self.graph.get_all_service_names())
        findings: list[K8sRCAFinding] = []
        for service in services:
            findings.append(self.generate_rca(service, snapshot, log_context=log_context))
        return findings

    def _build_evidence(self, pods, events, patterns: list[str]) -> list[str]:
        evidence = []
        for pod in pods:
            evidence.append(f"Pod {pod.name}: phase={pod.phase}, ready={pod.ready}, restarts={pod.restart_count}")
            for state in pod.container_states:
                if state.state_reason:
                    evidence.append(f"Container {state.name} state={state.state} reason={state.state_reason}")
            if pod.logs:
                evidence.append(f"Recent logs available ({len(pod.logs)} lines)")
            if pod.previous_logs:
                evidence.append(f"Previous logs available ({len(pod.previous_logs)} lines)")
        for event in events[:10]:
            evidence.append(f"Event {event.reason}: {event.message}")
        for pattern in patterns:
            evidence.append(f"Detected pattern: {pattern}")
        return evidence or ["No direct evidence found"]

    def _build_recommendations(self, patterns: list[str]) -> list[str]:
        recommendations = []
        for pattern in patterns:
            recommendations.extend(FAILURE_PATTERN_TO_RECOMMENDATIONS.get(pattern, []))
        return list(dict.fromkeys(recommendations)) or ["No action required"]

    def _has_dependency_failure(self, service_name: str, snapshot) -> bool:
        service_cfg = self.graph.get_service(service_name) or {}
        deps = service_cfg.get("depends_on", [])
        if not deps:
            return False
        for dep in deps:
            dep_pods = [pod for pod in snapshot.pods if dep in pod.name]
            if dep_pods and any(not pod.ready for pod in dep_pods):
                return True
        return False
