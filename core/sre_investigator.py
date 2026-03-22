import sys
import os

try:
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

import re
import json
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
from core.logger import get_logger
from core.service_graph import ServiceGraph
from core.log_loader import LogLoader
from core.log_processor import LogProcessor
from core.resource_collector import (
    ResourceCollector
)
from flags import USE_KUBERNETES, K8S_NAMESPACE

log = get_logger("sre_investigator")

@dataclass
class DetectedPattern:
    pattern_id: str
    category: str
    severity: str
    description: str
    evidence: str
    confidence: int
    source: str
    remediation_hint: str

@dataclass
class InvestigationEvidence:
    service_name: str
    namespace: str
    container_logs: dict = field(default_factory=dict)
    describe_output: str = ""
    events_output: str = ""
    resource_metrics: dict = field(default_factory=dict)
    rollout_history: str = ""
    deployment_age_minutes: Optional[int] = None
    endpoints_output: str = ""
    hpa_output: str = ""
    pvc_output: str = ""
    exit_codes: list = field(default_factory=list)
    detected_patterns: list = field(default_factory=list)
    health_status: str = "UNKNOWN"
    role_in_incident: str = "unknown"
    error_count: int = 0
    warning_count: int = 0

@dataclass
class InvestigationReport:
    target_service: str
    namespace: str
    investigation_time: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    evidence: dict = field(default_factory=dict)
    blast_radius: dict = field(default_factory=dict)
    cascade_timeline: list = field(default_factory=list)
    probable_root_cause: str = ""
    patterns_by_category: dict = field(default_factory=dict)
    data_source: str = "file"
    pending_discoveries: list = field(default_factory=list)


class PatternDetector:
    RULES = [
        {
            "id": "OOM_KILLED",
            "category": "Resource",
            "severity": "CRITICAL",
            "sources": ["logs", "events", "describe"],
            "patterns": [
                r"oomkill", r"out of memory", r"exit code.*137",
                r"memory.*limit.*exceeded", r"killed.*memory",
                r"OOMKilling", r"oom_score",
            ],
            "confidence": 95,
            "description": "Container was killed by the kernel due to memory limit being exceeded",
            "remediation_hint": "Increase memory limit in deployment spec. Check for memory leaks in application. kubectl set resources or edit deployment"
        },
        {
            "id": "CPU_THROTTLING",
            "category": "Resource",
            "severity": "HIGH",
            "sources": ["metrics"],
            "patterns": [
                r"cpu.*throttl", r"cpu_percent.*[89][0-9]", r"cpu_percent.*100",
            ],
            "confidence": 80,
            "description": "Container CPU is being throttled \u2014 hitting CPU limit",
            "remediation_hint": "Increase CPU limit or optimize application CPU usage. Check for infinite loops or expensive operations"
        },
        {
            "id": "CRASH_LOOP",
            "category": "Resource",
            "severity": "CRITICAL",
            "sources": ["logs", "events", "describe"],
            "patterns": [
                r"crashloopbackoff", r"back-off restarting",
                r"restart.*[5-9]\d", r"restart.*[1-9]\d{2,}",
            ],
            "confidence": 90,
            "description": "Container is in CrashLoopBackOff \u2014 repeatedly crashing and restarting",
            "remediation_hint": "Check container logs for root cause of crash. kubectl logs --previous to see last crash logs"
        },
        {
            "id": "NODE_PRESSURE",
            "category": "Resource",
            "severity": "CRITICAL",
            "sources": ["events", "describe"],
            "patterns": [
                r"evict", r"node.*pressure", r"diskpressure",
                r"memorypressure", r"pidpressure", r"low on resource",
                r"threshold.*quantity",
            ],
            "confidence": 90,
            "description": "Pod evicted due to node resource pressure",
            "remediation_hint": "Check node capacity: kubectl describe node. Consider adding nodes or reducing resource requests"
        },
        {
            "id": "CONNECTION_FAILURE",
            "category": "Network",
            "severity": "HIGH",
            "sources": ["logs", "events"],
            "patterns": [
                r"connection refused", r"connection reset",
                r"connection timed? ?out", r"no route to host",
                r"network.*unreachable", r"dial.*failed", r"connect.*failed",
            ],
            "confidence": 85,
            "description": "Service cannot connect to a dependency \u2014 connection actively refused or timed out",
            "remediation_hint": "Check if target service is running. Verify network policies allow traffic. Check service endpoints"
        },
        {
            "id": "DNS_FAILURE",
            "category": "Network",
            "severity": "HIGH",
            "sources": ["logs", "events"],
            "patterns": [
                r"dns.*fail", r"no such host", r"name.*resolution.*fail",
                r"could not resolve", r"unknown host", r"lookup.*no such host",
            ],
            "confidence": 90,
            "description": "DNS resolution failing \u2014 service cannot resolve hostname of dependency",
            "remediation_hint": "Check CoreDNS is running. Verify service name and namespace. Check network policies for DNS port 53"
        },
        {
            "id": "ISTIO_UPSTREAM_RESET",
            "category": "Network",
            "severity": "HIGH",
            "sources": ["logs", "events"],
            "patterns": [
                r"upstream reset", r"upstream connect error",
                r"istio.*503", r"envoy.*503", r"no healthy upstream",
                r"upstream overflow", r"reset before headers",
            ],
            "confidence": 85,
            "description": "Istio/Envoy proxy reporting upstream connection failures or circuit breaker open",
            "remediation_hint": "Check upstream service health. Review Istio DestinationRule and VirtualService config. Check circuit breaker settings"
        },
        {
            "id": "ISTIO_SIDECAR_CRASH",
            "category": "Network",
            "severity": "CRITICAL",
            "sources": ["describe", "events"],
            "patterns": [
                r"istio.*proxy.*crash", r"istio-proxy.*backoff",
                r"istio-proxy.*exit", r"envoy.*crash",
                r"sidecar.*crashloop", r"pilot.*disconnect",
            ],
            "confidence": 88,
            "description": "Istio sidecar proxy container is crashing \u2014 all service mesh traffic affected",
            "remediation_hint": "Restart pod to get fresh sidecar. Check istiod health. kubectl rollout restart deployment"
        },
        {
            "id": "TLS_CERT_EXPIRED",
            "category": "Network",
            "severity": "CRITICAL",
            "sources": ["logs", "events"],
            "patterns": [
                r"certificate.*expired", r"tls.*expired", r"x509.*expired",
                r"cert.*not valid", r"ssl.*expire", r"certificate.*invalid",
                r"handshake.*fail",
            ],
            "confidence": 92,
            "description": "TLS certificate has expired or is invalid \u2014 encrypted connections failing",
            "remediation_hint": "Renew TLS certificate. Check cert-manager if used. Verify certificate validity dates with openssl"
        },
        {
            "id": "ENDPOINT_NOT_READY",
            "category": "Network",
            "severity": "HIGH",
            "sources": ["events", "describe"],
            "patterns": [
                r"endpoint.*not ready", r"no endpoints available",
                r"endpoints.*empty", r"readiness.*fail",
                r"pod.*not ready", r"0/[1-9].*ready",
            ],
            "confidence": 85,
            "description": "Service has no ready endpoints \u2014 pods exist but none are passing readiness checks",
            "remediation_hint": "Check readiness probe config. Inspect pod logs for startup errors. Verify readiness endpoint returns 200"
        },
        {
            "id": "SECRET_MISSING",
            "category": "Config",
            "severity": "CRITICAL",
            "sources": ["logs", "events", "describe"],
            "patterns": [
                r"secret.*not found", r"secret.*does not exist",
                r"mountvolume.*failed.*secret", r"secretkeyref.*not found",
                r"keyvault.*error", r"keyvault.*not found",
                r"env.*secret.*missing", r"secret.*unavailable",
            ],
            "confidence": 95,
            "description": "Required Kubernetes secret or KeyVault reference is missing or inaccessible",
            "remediation_hint": "Verify secret exists: kubectl get secret. Check KeyVault access policies. Recreate secret if deleted"
        },
        {
            "id": "CONFIGMAP_MISSING",
            "category": "Config",
            "severity": "HIGH",
            "sources": ["logs", "events", "describe"],
            "patterns": [
                r"configmap.*not found", r"configmap.*does not exist",
                r"mountvolume.*failed.*config", r"config.*missing",
                r"configuration.*not found",
            ],
            "confidence": 90,
            "description": "Required ConfigMap is missing \u2014 application cannot load configuration",
            "remediation_hint": "Verify ConfigMap exists: kubectl get configmap. Reapply ConfigMap from source manifests"
        },
        {
            "id": "ENV_VAR_MISSING",
            "category": "Config",
            "severity": "HIGH",
            "sources": ["logs"],
            "patterns": [
                r"environment.*variable.*not set", r"env.*not.*set",
                r"missing.*env", r"undefined.*env",
                r"required.*config.*missing", r"getenv.*empty",
            ],
            "confidence": 85,
            "description": "Required environment variable is not set \u2014 application cannot start or function correctly",
            "remediation_hint": "Check deployment env section. Verify secret/configmap references are correct and exist in the namespace"
        },
        {
            "id": "IMAGE_PULL_FAILURE",
            "category": "Config",
            "severity": "CRITICAL",
            "sources": ["events", "describe"],
            "patterns": [
                r"imagepullbackoff", r"errimagepull", r"failed to pull image",
                r"image.*not found", r"repository.*not found",
                r"unauthorized.*registry", r"pull.*access denied",
            ],
            "confidence": 95,
            "description": "Container image cannot be pulled \u2014 wrong tag, missing registry credentials, or image does not exist",
            "remediation_hint": "Verify image tag exists in registry. Check imagePullSecret is configured. Consider rolling back: kubectl rollout undo"
        },
        {
            "id": "RECENT_DEPLOYMENT",
            "category": "Deployment",
            "severity": "HIGH",
            "sources": ["rollout", "describe"],
            "patterns": [
                r"deployment.*[0-9]+ ?min",
            ],
            "confidence": 75,
            "description": "A deployment was made recently \u2014 errors may be caused by the new version",
            "remediation_hint": "Consider rollback: kubectl rollout undo deployment/{name} -n {namespace}. Check diff between current and previous image"
        },
        {
            "id": "PROBE_FAILURE",
            "category": "Deployment",
            "severity": "HIGH",
            "sources": ["events", "describe"],
            "patterns": [
                r"liveness probe failed", r"readiness probe failed",
                r"probe.*failed.*statuscode", r"probe.*timeout", r"unhealthy.*probe",
            ],
            "confidence": 88,
            "description": "Kubernetes health probe is failing \u2014 pod being killed and restarted by k8s",
            "remediation_hint": "Check if health endpoint is correct and returns 200. May indicate app not starting correctly or probe path is wrong"
        },
        {
            "id": "PVC_NOT_BOUND",
            "category": "Storage",
            "severity": "CRITICAL",
            "sources": ["events", "describe"],
            "patterns": [
                r"persistentvolumeclaim.*pending", r"pvc.*not bound",
                r"volume.*not found", r"failedmount", r"unable to mount volumes",
                r"attach.*volume.*fail", r"pvc.*wrong.*namespace", r"claimed.*another",
            ],
            "confidence": 92,
            "description": "PersistentVolumeClaim is not bound \u2014 storage not available to the pod. May be claimed by another namespace",
            "remediation_hint": "Check PVC status: kubectl get pvc. Verify StorageClass exists. Check if PV is bound to correct namespace"
        },
        {
            "id": "DISK_PRESSURE",
            "category": "Storage",
            "severity": "HIGH",
            "sources": ["events", "describe"],
            "patterns": [
                r"disk.*pressure", r"disk.*full", r"no space left",
                r"filesystem.*full", r"ephemeral.*storage", r"diskpressure",
            ],
            "confidence": 90,
            "description": "Node or container running out of disk space",
            "remediation_hint": "Free up disk space or increase storage limits. Check log rotation settings. Expand PVC if applicable"
        },
        {
            "id": "CONNECTION_POOL_EXHAUSTED",
            "category": "Resource",
            "severity": "CRITICAL",
            "sources": ["logs"],
            "patterns": [
                r"connection pool.*exhaust", r"pool.*full",
                r"max.*connections.*reached", r"too many connections",
                r"connection.*limit.*reached", r"pool.*timeout",
                r"acquire.*connection.*fail", r"no.*connection.*available",
            ],
            "confidence": 92,
            "description": "Database or service connection pool is exhausted \u2014 no available connections",
            "remediation_hint": "Increase connection pool size. Check for connection leaks. Add connection timeout settings. Review retry logic"
        },
        {
            "id": "HPA_MAX_REACHED",
            "category": "Resource",
            "severity": "HIGH",
            "sources": ["events", "describe"],
            "patterns": [
                r"hpa.*max.*replicas", r"maxreplicas.*reached",
                r"unable to scale.*max", r"horizontalpodautoscaler.*max",
                r"metrics.*server.*unavailable",
            ],
            "confidence": 80,
            "description": "HorizontalPodAutoscaler has reached maximum replicas \u2014 cannot scale further under load",
            "remediation_hint": "Increase maxReplicas in HPA. Check if metrics-server is running. Consider vertical scaling or code optimization"
        },
    ]

    def detect(self, evidence: "InvestigationEvidence") -> list[DetectedPattern]:
        results = []
        found_ids = set()

        sources = {
            "logs": "\n".join(["\n".join(lines) for lines in evidence.container_logs.values()]),
            "events": evidence.events_output,
            "describe": evidence.describe_output,
            "rollout": evidence.rollout_history,
            "metrics": json.dumps(evidence.resource_metrics)
        }

        for rule in self.RULES:
            if rule["id"] in found_ids:
                continue
            
            matched = False
            for src_name in rule["sources"]:
                if matched:
                    break
                text = sources.get(src_name, "")
                if not text:
                    continue
                
                for pattern in rule["patterns"]:
                    m = re.search(pattern, text, re.IGNORECASE)
                    if m:
                        match_start = m.start()
                        line_start = text.rfind("\n", 0, match_start)
                        line_start = line_start + 1 if line_start != -1 else 0
                        line_end = text.find("\n", match_start)
                        if line_end == -1: line_end = len(text)
                        ev_str = text[line_start:line_end].strip()[:100]
                        
                        results.append(DetectedPattern(
                            pattern_id=rule["id"],
                            category=rule["category"],
                            severity=rule["severity"],
                            description=rule["description"],
                            evidence=ev_str,
                            confidence=rule["confidence"],
                            source=src_name,
                            remediation_hint=rule["remediation_hint"]
                        ))
                        found_ids.add(rule["id"])
                        matched = True
                        break

        if evidence.deployment_age_minutes is not None and evidence.deployment_age_minutes < 15:
            if "RECENT_DEPLOYMENT" not in found_ids:
                results.append(DetectedPattern(
                    pattern_id="RECENT_DEPLOYMENT",
                    category="Deployment",
                    severity="HIGH",
                    description="A deployment was made recently \u2014 errors may be caused by the new version",
                    evidence=f"Deployed {evidence.deployment_age_minutes} minutes ago",
                    confidence=95,
                    source="rollout",
                    remediation_hint="Consider rollback: kubectl rollout undo deployment"
                ))
                found_ids.add("RECENT_DEPLOYMENT")

        for code in evidence.exit_codes:
            if code == 137 and "OOM_KILLED" not in found_ids:
                results.append(DetectedPattern(
                    pattern_id="OOM_KILLED",
                    category="Resource",
                    severity="CRITICAL",
                    description="Container was killed by the kernel due to memory limit being exceeded",
                    evidence="Exit code 137 found",
                    confidence=95,
                    source="describe",
                    remediation_hint="Increase memory limit in deployment spec."
                ))
                found_ids.add("OOM_KILLED")
            elif code == 1 and "CRASH_EXIT_1" not in found_ids:
                results.append(DetectedPattern(
                    pattern_id="CRASH_EXIT_1",
                    category="Resource",
                    severity="CRITICAL",
                    description="Container crashed with exit code 1",
                    evidence="Exit code 1 found",
                    confidence=90,
                    source="describe",
                    remediation_hint="Check logs for application error."
                ))
                found_ids.add("CRASH_EXIT_1")
            elif code in (126, 127) and "MISSING_BINARY" not in found_ids:
                results.append(DetectedPattern(
                    pattern_id="MISSING_BINARY",
                    category="Config",
                    severity="CRITICAL",
                    description="Command or binary missing (Exit code 126/127)",
                    evidence=f"Exit code {code} found",
                    confidence=95,
                    source="describe",
                    remediation_hint="Check container image and entrypoint."
                ))
                found_ids.add("MISSING_BINARY")

        return results


class EvidenceCollector:
    def __init__(self):
        self.loader = LogLoader()
        self.collector = ResourceCollector()

    def collect(self,
                 service_name: str,
                 namespace: str,
                 use_mock: bool = True
                 ) -> InvestigationEvidence:
        ev = InvestigationEvidence(
            service_name=service_name,
            namespace=namespace
        )

        if USE_KUBERNETES and not use_mock:
            self._collect_from_kubectl(
                ev, service_name, namespace
            )
        else:
            self._collect_from_files(
                ev, service_name, namespace
            )

        return ev

    def _collect_from_files(self,
                             ev: InvestigationEvidence,
                             service_name: str,
                             namespace: str):
        graph = ServiceGraph()
        processor = LogProcessor()

        all_lines = self.loader.load_service_logs(
            service_name
        )
        ev.container_logs["main"] = all_lines

        containers = graph.get_containers(
            service_name
        )
        for container in containers:
            if container != service_name:
                c_lines = (
                    self.loader
                    .load_container_logs(
                        service_name, container
                    )
                )
                if c_lines:
                    ev.container_logs[
                        container
                    ] = c_lines

        scenario = self._detect_mock_scenario(
            all_lines
        )
        ev.describe_output = (
            self.loader.load_mock_kubectl(
                "describe", scenario
            )
        )
        ev.events_output = (
            self.loader.load_mock_kubectl(
                "events", scenario
            )
        )

        ev.rollout_history = (
            self.loader.load_mock_kubectl(
                "rollout", "history"
            )
        )
        ev.deployment_age_minutes = (
            self._parse_deployment_age(
                ev.rollout_history
            )
        )

        ev.resource_metrics = (
            self.collector.get_resources(
                [service_name],
                use_mock=True
            ).get(service_name, {})
        )

        ev.exit_codes = self._extract_exit_codes(
            ev.describe_output
        )

        if all_lines:
            entries = processor.process(all_lines)
            summary = processor.get_summary(
                entries
            )
            ev.error_count = summary["errors"]
            ev.warning_count = summary["warnings"]

        log.step(
            f"File mode evidence collected "
            f"for {service_name}: "
            f"{ev.error_count} errors, "
            f"{ev.warning_count} warnings"
        )

    def _collect_from_kubectl(self,
                               ev: InvestigationEvidence,
                               service_name: str,
                               namespace: str):
        graph = ServiceGraph()
        processor = LogProcessor()

        def _run(cmd: list) -> str:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    return result.stdout
                log.debug(
                    f"kubectl error: "
                    f"{result.stderr[:100]}"
                )
                return ""
            except Exception as e:
                log.debug(f"kubectl failed: {e}")
                return ""

        pods_out = _run([
            "kubectl", "get", "pods",
            "-n", namespace,
            f"--selector=app={service_name}",
            "--no-headers",
            "-o", "custom-columns=NAME:.metadata.name"
        ])
        pods = [
            p.strip() for p in
            pods_out.strip().split("\n")
            if p.strip()
        ]
        pod_name = pods[0] if pods else ""

        log.step(
            f"Found pod for {service_name}: "
            f"{pod_name or 'none'}"
        )

        containers = graph.get_containers(
            service_name
        )
        for container in containers:
            if not pod_name:
                break
            logs_out = _run([
                "kubectl", "logs",
                pod_name,
                "-n", namespace,
                "-c", container,
                "--tail=200",
                "--timestamps=true"
            ])
            if logs_out:
                ev.container_logs[container] = (
                    logs_out.split("\n")
                )

        if pod_name:
            ev.describe_output = _run([
                "kubectl", "describe", "pod",
                pod_name, "-n", namespace
            ])

        if pod_name:
            ev.events_output = _run([
                "kubectl", "get", "events",
                "-n", namespace,
                "--field-selector",
                f"involvedObject.name={pod_name}",
                "--sort-by=.lastTimestamp"
            ])

        ev.rollout_history = _run([
            "kubectl", "rollout", "history",
            f"deployment/{service_name}",
            "-n", namespace
        ])
        ev.deployment_age_minutes = (
            self._parse_deployment_age_kubectl(
                service_name, namespace, _run
            )
        )

        metrics_out = _run([
            "kubectl", "top", "pod",
            "-n", namespace,
            f"--selector=app={service_name}",
            "--no-headers"
        ])
        ev.resource_metrics = (
            self._parse_top_output(metrics_out)
        )

        ev.endpoints_output = _run([
            "kubectl", "get", "endpoints",
            service_name, "-n", namespace
        ])

        ev.hpa_output = _run([
            "kubectl", "get", "hpa",
            "-n", namespace
        ])

        ev.pvc_output = _run([
            "kubectl", "get", "pvc",
            "-n", namespace
        ])

        ev.exit_codes = self._extract_exit_codes(
            ev.describe_output
        )

        all_lines = []
        for lines in ev.container_logs.values():
            all_lines.extend(lines)

        if all_lines:
            entries = processor.process(all_lines)
            summary = processor.get_summary(
                entries
            )
            ev.error_count = summary["errors"]
            ev.warning_count = summary["warnings"]

        log.step(
            f"K8s evidence collected for "
            f"{service_name}: "
            f"{len(pods)} pod(s), "
            f"{ev.error_count} errors"
        )

    def _detect_mock_scenario(self,
                               log_lines: list
                               ) -> str:
        joined = "\n".join(
            log_lines
        ).lower()
        if any(k in joined for k in [
            "oomkill", "out of memory",
            "memory limit"
        ]):
            return "oom-killed"
        if any(k in joined for k in [
            "secret", "keyvault",
            "vault", "credential"
        ]):
            return "secret-missing"
        if any(k in joined for k in [
            "imagepull", "image pull",
            "errimagepull"
        ]):
            return "image-pull-backoff"
        if any(k in joined for k in [
            "pvc", "persistentvolume",
            "volume mount", "failedmount"
        ]):
            return "pvc-not-bound"
        if any(k in joined for k in [
            "liveness probe", "readiness probe",
            "probe failed"
        ]):
            return "probe-failure"
        if any(k in joined for k in [
            "evict", "node pressure",
            "diskpressure", "memorypressure"
        ]):
            return "node-pressure"
        if any(k in joined for k in [
            "istio", "envoy", "sidecar"
        ]):
            return "istio-crash"
        return "connection-pool-exhaustion"

    def _parse_deployment_age(self,
                               rollout_history: str
                               ) -> Optional[int]:
        if rollout_history:
            return 8
        return None

    def _parse_deployment_age_kubectl(
            self,
            service_name: str,
            namespace: str,
            run_fn) -> Optional[int]:
        try:
            out = run_fn([
                "kubectl", "get", "deployment",
                service_name,
                "-n", namespace,
                "-o",
                "jsonpath={.metadata.creationTimestamp}"
            ])
            if out:
                created = datetime.fromisoformat(
                    out.replace("Z", "+00:00")
                )
                now = datetime.now(timezone.utc)
                age = (now - created).seconds // 60
                return age
        except Exception:
            pass
        return None

    def _extract_exit_codes(self,
                              describe: str
                              ) -> list[int]:
        codes = []
        for match in re.finditer(
            r"exit code[:\s]+(\d+)",
            describe,
            re.IGNORECASE
        ):
            try:
                codes.append(int(match.group(1)))
            except ValueError:
                pass
        return list(set(codes))

    def _parse_top_output(self,
                           top_output: str
                           ) -> dict:
        if not top_output:
            return {}
        lines = [
            l for l in top_output.split("\n")
            if l.strip()
        ]
        if not lines:
            return {}
        parts = lines[0].split()
        if len(parts) >= 3:
            return {
                "pod_name": parts[0],
                "cpu_usage": parts[1],
                "memory_usage": parts[2]
            }
        return {}


class SREInvestigator:
    def __init__(self):
        self.graph = ServiceGraph()
        self.collector = EvidenceCollector()
        self.detector = PatternDetector()

    def investigate(self,
                     target_service: str,
                     namespace: str = None,
                     use_mock: bool = None
                     ) -> InvestigationReport:
        canonical = (
            self.graph.get_service_name(
                target_service
            ) or target_service
        )
        if not namespace:
            namespace = (
                self.graph.get_namespace(
                    canonical, K8S_NAMESPACE
                )
            )

        log.info(
            f"\n[bold cyan]SRE Investigation"
            f"[/bold cyan] \u2014 "
            f"[bold white]{canonical}[/bold white]"
            f" in [dim]{namespace}[/dim]\n"
        )

        blast = self.graph.get_blast_radius(
            canonical
        )

        report = InvestigationReport(
            target_service=canonical,
            namespace=namespace,
            blast_radius=blast,
            data_source=(
                "kubernetes"
                if USE_KUBERNETES and
                not use_mock
                else "file"
            )
        )

        all_services = blast["all_affected"]
        total = len(all_services)

        for i, svc in enumerate(all_services, 1):
            svc_ns = self.graph.get_namespace(
                svc, namespace
            )
            log.info(
                f"[dim]  [{i}/{total}] "
                f"Collecting evidence: "
                f"{svc}...[/dim]"
            )

            if use_mock is None:
                _use_mock = not USE_KUBERNETES
            else:
                _use_mock = use_mock

            ev = self.collector.collect(
                svc, svc_ns, _use_mock
            )

            ev.detected_patterns = (
                self.detector.detect(ev)
            )

            ev.health_status = (
                self._determine_health(ev)
            )

            all_log_lines = []
            for lines in (
                ev.container_logs.values()
            ):
                all_log_lines.extend(lines)

            if all_log_lines:
                discoveries = (
                    self.graph.discover_from_logs(
                        all_log_lines, svc
                    )
                )
                if discoveries:
                    report.pending_discoveries.extend(discoveries)

            report.evidence[svc] = ev

        report.cascade_timeline = (
            self._build_cascade_timeline(report)
        )

        report.probable_root_cause = (
            self._find_root_cause(report)
        )

        for svc, ev in report.evidence.items():
            if svc == report.probable_root_cause:
                ev.role_in_incident = "root_cause"
            elif svc in blast["all_affected"]:
                if ev.error_count > 0:
                    ev.role_in_incident = (
                        "cascade_victim"
                    )
                else:
                    ev.role_in_incident = (
                        "unaffected"
                    )

        report.patterns_by_category = (
            self._group_patterns(report)
        )

        if report.pending_discoveries:
            confirmed = (
                self.graph.prompt_user_to_update(
                    report.pending_discoveries,
                    canonical
                )
            )
            if confirmed:
                self.graph.apply_discoveries(
                    report.pending_discoveries,
                    canonical
                )

        log.info(
            f"\n[bold green]Investigation "
            f"complete[/bold green] \u2014 "
            f"{len(report.evidence)} services "
            f"analysed\n"
        )

        return report

    def _determine_health(self,
                           ev: InvestigationEvidence
                           ) -> str:
        severities = [
            p.severity for p in
            ev.detected_patterns
        ]
        if (
            "CRITICAL" in severities or
            137 in ev.exit_codes or
            ev.error_count > 10
        ):
            return "CRITICAL"
        if (
            "HIGH" in severities or
            ev.error_count > 0 or
            ev.warning_count > 5
        ):
            return "WARNING"
        if (
            not ev.detected_patterns and
            ev.error_count == 0 and
            (
                ev.container_logs or
                ev.describe_output
            )
        ):
            return "OK"
        return "UNKNOWN"

    def _build_cascade_timeline(
            self,
            report: InvestigationReport
            ) -> list[dict]:
        timeline = []
        for svc, ev in report.evidence.items():
            all_lines = []
            for lines in (
                ev.container_logs.values()
            ):
                all_lines.extend(lines)

            first_error_time = "unknown"
            if all_lines:
                processor = LogProcessor()
                entries = processor.process(
                    all_lines
                )
                errors = (
                    processor.filter_by_severity(
                        entries, "ERROR"
                    )
                )
                if errors:
                    first_error_time = errors[0].get(
                        "timestamp", "unknown"
                    )

            if ev.health_status in (
                "CRITICAL", "WARNING"
            ):
                top_pattern = (
                    ev.detected_patterns[0]
                    .description
                    if ev.detected_patterns
                    else f"{ev.error_count} errors"
                )
                timeline.append({
                    "service": svc,
                    "time": first_error_time,
                    "event": top_pattern,
                    "severity": ev.health_status,
                    "role": ev.role_in_incident,
                    "error_count": ev.error_count
                })
            elif ev.health_status == "OK":
                timeline.append({
                    "service": svc,
                    "time": "N/A",
                    "event": "Service healthy",
                    "severity": "OK",
                    "role": "unaffected",
                    "error_count": 0
                })

        severity_order = {
            "CRITICAL": 0,
            "WARNING": 1,
            "OK": 2,
            "UNKNOWN": 3
        }
        timeline.sort(key=lambda x: (
            severity_order.get(
                x["severity"], 3
            ),
            -(x.get("error_count", 0))
        ))
        return timeline

    def _find_root_cause(
            self,
            report: InvestigationReport
            ) -> str:
        target = report.target_service
        downstream = report.blast_radius.get(
            "downstream", []
        )

        for svc in reversed(downstream):
            ev = report.evidence.get(svc)
            if ev and ev.health_status == (
                "CRITICAL"
            ):
                return svc

        target_ev = report.evidence.get(target)
        if (
            target_ev and
            target_ev.health_status == "CRITICAL"
        ):
            return target

        max_errors = 0
        probable = target
        for svc, ev in report.evidence.items():
            if ev.error_count > max_errors:
                max_errors = ev.error_count
                probable = svc

        return probable

    def _group_patterns(
            self,
            report: InvestigationReport
            ) -> dict:
        grouped = {}
        for svc, ev in report.evidence.items():
            for pattern in ev.detected_patterns:
                cat = pattern.category
                if cat not in grouped:
                    grouped[cat] = []
                grouped[cat].append({
                    "service": svc,
                    "pattern": pattern
                })
        return grouped

    def get_summary_text(
            self,
            report: InvestigationReport
            ) -> str:
        lines = []
        lines.append(
            "=== SRE INVESTIGATION REPORT ==="
        )
        lines.append(
            f"Target service: "
            f"{report.target_service}"
        )
        lines.append(
            f"Namespace: {report.namespace}"
        )
        lines.append(
            f"Data source: {report.data_source}"
        )
        lines.append(
            f"Probable root cause: "
            f"{report.probable_root_cause}"
        )
        lines.append("")

        lines.append("=== SERVICE HEALTH ===")
        for ev in report.evidence.values():
            lines.append(
                f"{ev.service_name}: "
                f"{ev.health_status} "
                f"({ev.error_count} errors, "
                f"{ev.warning_count} warnings)"
            )
        lines.append("")

        lines.append("=== DETECTED PATTERNS ===")
        for cat, patterns in (
            report.patterns_by_category.items()
        ):
            lines.append(f"\n{cat}:")
            for item in patterns:
                p = item["pattern"]
                lines.append(
                    f"  [{p.severity}] "
                    f"{item['service']}: "
                    f"{p.description}"
                )
                lines.append(
                    f"    Evidence: {p.evidence}"
                )
                lines.append(
                    f"    Hint: "
                    f"{p.remediation_hint}"
                )
        lines.append("")

        lines.append(
            "=== CASCADE TIMELINE ==="
        )
        for entry in report.cascade_timeline:
            lines.append(
                f"{entry['service']} "
                f"[{entry['severity']}]: "
                f"{entry['event']}"
            )
        lines.append("")

        lines.append("=== EVIDENCE DETAILS ===")
        for svc, ev in report.evidence.items():
            lines.append(f"\n--- {svc} ---")
            if ev.container_logs:
                for container, c_lines in (
                    ev.container_logs.items()
                ):
                    processor = LogProcessor()
                    entries = processor.process(
                        c_lines
                    )
                    errors = (
                        processor
                        .filter_by_severity(
                            entries, "ERROR"
                        )
                    )
                    if errors:
                        lines.append(
                            f"  [{container}] "
                            f"Last errors:"
                        )
                        for e in errors[-5:]:
                            lines.append(
                                f"    "
                                f"{e['raw'][:120]}"
                            )
            if ev.exit_codes:
                lines.append(
                    f"  Exit codes: "
                    f"{ev.exit_codes}"
                )
            if ev.events_output:
                lines.append(
                    f"  Recent events (excerpt):"
                )
                for el in (
                    ev.events_output
                    .split("\n")[:5]
                ):
                    if el.strip():
                        lines.append(
                            f"    {el[:120]}"
                        )

        return "\n".join(lines)


if __name__ == "__main__":
    print(
        "=== Task H \u2014 SRE Investigator "
        "Test ===\n"
    )
    investigator = SREInvestigator()
    graph = ServiceGraph()
    all_services = graph.get_all_service_names()

    if not all_services:
        print("No services in services.yaml!")
        exit(1)

    target = None
    for svc in all_services:
        br = graph.get_blast_radius(svc)
        if br["downstream"]:
            target = svc
            break
    if not target:
        target = all_services[0]

    print(
        f"--- Test 1: Investigate "
        f"{target} ---"
    )
    report = investigator.investigate(
        target,
        use_mock=True
    )

    print(f"\nTarget: {report.target_service}")
    print(
        f"Services analysed: "
        f"{list(report.evidence.keys())}"
    )
    print(
        f"Probable root cause: "
        f"{report.probable_root_cause}"
    )
    print(
        f"Data source: {report.data_source}"
    )

    print("\n--- Test 2: Service health ---")
    for svc, ev in report.evidence.items():
        status_color = {
            "CRITICAL": "CRITICAL",
            "WARNING":  "WARNING",
            "OK":       "OK",
            "UNKNOWN":  "UNKNOWN"
        }.get(ev.health_status, "UNKNOWN")
        print(
            f"  {svc}: {status_color} "
            f"({ev.error_count} errors, "
            f"{len(ev.detected_patterns)} "
            f"patterns)"
        )

    print("\n--- Test 3: Detected patterns ---")
    for cat, items in (
        report.patterns_by_category.items()
    ):
        print(f"  {cat}:")
        for item in items:
            p = item["pattern"]
            print(
                f"    [{p.severity}] "
                f"{item['service']}: "
                f"{p.pattern_id}"
            )

    print("\n--- Test 4: Cascade timeline ---")
    for entry in report.cascade_timeline:
        print(
            f"  [{entry['severity']}] "
            f"{entry['service']}: "
            f"{entry['event'][:60]}"
        )

    print(
        "\n--- Test 5: Summary text "
        "(first 500 chars) ---"
    )
    summary = investigator.get_summary_text(
        report
    )
    print(summary[:500])
    print("...")

    print(
        f"\n--- Test 6: All services ---"
    )
    for svc in all_services:
        if svc == target:
            continue
        print(f"\nQuick check: {svc}")
        r2 = investigator.investigate(
            svc, use_mock=True
        )
        print(
            f"  Health: "
            f"{r2.evidence.get(svc, {}).health_status if hasattr(r2.evidence.get(svc, {}), 'health_status') else 'N/A'}"
        )
        for s, e in r2.evidence.items():
            if hasattr(e, "health_status"):
                print(
                    f"  {s}: "
                    f"{e.health_status}"
                )

    print("\nTask H OK")
