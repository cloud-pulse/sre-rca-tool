"""
core/kubectl_rca_investigator.py

Sequential RCA pipeline for AI-SRE kubectl mode.

Design:
- Collect ALL evidence first
- No early exit
- Silent investigator (minimal logs only)
- Final rendering handled elsewhere
- Returns RCAReport object
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from core.kubectl_client import (
    get_pods,
    get_pod_events,
    get_pod_logs,
    get_all_container_logs,
    get_node_resources,
    get_cluster_resource_pressure,
    get_containers_for_pod,
    classify_pod_status,
    CRITICAL_STATUSES,
    get_service_endpoints,
    get_virtual_service,
    get_pod_node,
    get_node_describe,
)
from core.logger import get_logger

log = get_logger("incident_recorder")

MAX_DEPENDENCY_DEPTH = 1


# ─────────────────────────────────────────────
# Pattern Detection
# ─────────────────────────────────────────────

PATTERNS = [
    (
        r"OOMKilled|out of memory|memory limit exceeded|Cannot allocate memory",
        "OOM / Memory limit exceeded",
        95,
        [
            "Increase memory limits in deployment spec",
            "Profile application for memory leaks",
            "Check for unbounded caches or large payload processing",
        ],
    ),

    (
        r"CrashLoopBackOff",
        "CrashLoopBackOff — repeated container crash",
        90,
        [
            "Check application startup logs for crash reason",
            "Validate liveness probe configuration",
            "Ensure required env vars and config maps are present",
        ],
    ),

    (
        r"ImagePullBackOff|ErrImagePull|image.*not found|manifest unknown",
        "Image pull failure",
        92,
        [
            "Verify image name and tag in deployment spec",
            "Check image registry credentials",
            "Confirm image exists in registry",
        ],
    ),

    (
        r"CreateContainerConfigError|CreateContainerError|secret.*not found|configmap.*not found",
        "Missing secret or ConfigMap / container config error",
        88,
        [
            "Verify secrets/configmaps exist",
            "Check env vars",
            "Validate deployment spec",
        ],
    ),

    (
        r"Liveness probe failed|Readiness probe failed|Startup probe failed",
        "Probe failure",
        85,
        [
            "Review probe endpoint",
            "Increase timeout thresholds",
            "Check slow startup conditions",
        ],
    ),

    (
        r"connection refused|ECONNREFUSED",
        "Dependency connection refused",
        87,
        [
            "Verify dependency service",
            "Check ports",
            "Inspect dependency logs",
        ],
    ),

    (
        r"timeout|context deadline exceeded|i/o timeout",
        "Request timeout / latency spike",
        75,
        [
            "Check dependency latency",
            "Inspect network policies",
            "Increase timeout settings",
        ],
    ),

    (
        r"panic:|fatal error|SIGSEGV|SIGABRT",
        "Application panic / fatal crash",
        92,
        [
            "Review stack trace",
            "Inspect recent code changes",
            "Check for nil pointer dereference",
        ],
    ),

    (
        r"Evicted|DiskPressure|MemoryPressure|PIDPressure",
        "Node resource pressure / pod eviction",
        88,
        [
            "Check node resource usage",
            "Scale cluster",
            "Review resource requests",
        ],
    ),

    (
        r"Pending",
        "Pod stuck in Pending",
        80,
        [
            "Check node resources",
            "Verify scheduling constraints",
            "Review taints/tolerations",
        ],
    ),
]


def detect_patterns(text: str) -> Optional[tuple[str, int, list[str]]]:

    if not text:
        return None

    best = None
    best_conf = 0

    for pattern, cause, conf, fixes in PATTERNS:

        if re.search(pattern, text, re.IGNORECASE):

            if conf > best_conf:
                best = (cause, conf, fixes)
                best_conf = conf

    return best


# ─────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────

@dataclass
class RCAFinding:

    root_cause: str = "Unknown"
    confidence: int = 0

    affected_service: str = ""
    affected_pod: str = ""

    evidence_stage: str = ""
    raw_evidence: str = ""

    suggested_fixes: list[str] = field(default_factory=list)
    dependency_chain: list[str] = field(default_factory=list)

    def update_if_better(
        self,
        cause: str,
        conf: int,
        fixes: list[str],
        pod: str,
        stage: str,
        evidence: str,
    ) -> None:

        if conf > self.confidence:

            self.root_cause = cause
            self.confidence = conf
            self.affected_pod = pod
            self.evidence_stage = stage
            self.raw_evidence = evidence
            self.suggested_fixes = fixes


@dataclass
class RCAReport:

    target_service: str

    finding: RCAFinding = field(default_factory=RCAFinding)

    all_evidence: dict = field(default_factory=dict)

    dependency_reports: list = field(default_factory=list)

    def to_dict(self) -> dict:

        return {
            "target_service": self.target_service,
            "root_cause": self.finding.root_cause,
            "confidence": self.finding.confidence,
            "affected_service": self.finding.affected_service,
            "affected_pod": self.finding.affected_pod,
            "evidence_stage": self.finding.evidence_stage,
            "suggested_fixes": self.finding.suggested_fixes,
            "dependency_chain": self.finding.dependency_chain,
            "raw_evidence_snippet": (
                self.finding.raw_evidence[:500]
                if self.finding.raw_evidence
                else ""
            ),
            "all_evidence": self.all_evidence,
            "dependency_reports": [
                r.to_dict() for r in self.dependency_reports
            ],
        }


# ─────────────────────────────────────────────
# Investigator
# ─────────────────────────────────────────────

class KubectlRCAInvestigator:

    def __init__(self, service_graph=None):

        self.service_graph = service_graph

    def investigate(
        self,
        service_name: str,
        namespace: str = "default",
        depth: int = 0,
    ) -> RCAReport:

        log.info("[RCA] Investigating '{service_name}' in namespace '{namespace}'")

        finding = RCAFinding(
            affected_service=service_name
        )

        evidence = {}

        # ─────────────────────────────
        # Stage 1 — Pod Status
        # ─────────────────────────────

        log.info("[RCA] Stage 1 — Pod Status")

        pods = get_pods(namespace, service_name)

        evidence["pod_status"] = str(pods)

        pod_name = pods[0]["name"] if pods else None

        for pod in pods:

            status = pod.get("status", "")
            restarts = pod.get("restarts", 0)

            if status in CRITICAL_STATUSES:

                match = detect_patterns(status)

                if match:

                    cause, conf, fixes = match

                    finding.update_if_better(
                        cause,
                        conf,
                        fixes,
                        pod["name"],
                        "pod_status",
                        status,
                    )

            if restarts >= 5 and status != "Running":

                finding.update_if_better(
                    f"High restart count ({restarts})",
                    75,
                    [
                        "Check startup logs",
                        "Validate probes",
                        "Review recent deployment",
                    ],
                    pod["name"],
                    "pod_status",
                    status,
                )

        # ─────────────────────────────
        # Stage 2 — Pod Events
        # ─────────────────────────────

        log.info("[RCA] Stage 2 — Pod Events")

        if pod_name:

            events = get_pod_events(
                pod_name,
                namespace,
            )

            evidence["pod_events"] = events

            match = detect_patterns(events)

            if match:

                cause, conf, fixes = match

                finding.update_if_better(
                    cause,
                    conf,
                    fixes,
                    pod_name,
                    "pod_events",
                    events[:500],
                )

        else:

            evidence["pod_events"] = "(no pods)"

        # ─────────────────────────────
        # Stage 3 — Pod Logs
        # ─────────────────────────────

        log.info("[RCA] Stage 3 — Pod Logs")

        if pod_name:

            containers = get_containers_for_pod(
                pod_name,
                namespace,
            )

            log_map = get_all_container_logs(
                pod_name,
                namespace,
                containers,
                tail=200,
            )

            combined_logs = "\n".join(
                f"[Container: {c}]\n{log}"
                for c, log in log_map.items()
            )

            evidence["pod_logs"] = combined_logs

            match = detect_patterns(combined_logs)

            if match:

                cause, conf, fixes = match

                finding.update_if_better(
                    cause,
                    conf,
                    fixes,
                    pod_name,
                    "pod_logs",
                    combined_logs[:500],
                )

        else:

            evidence["pod_logs"] = "(no pods)"

        # ─────────────────────────────
        # Stage 4 — Cluster Resources
        # ─────────────────────────────

        log.info("[RCA] Stage 4 — Cluster Resources")

        nodes = get_node_resources()

        cluster_pods = get_cluster_resource_pressure(
            namespace
        )

        evidence["resource_pressure"] = {
            "nodes": nodes,
            "pods": cluster_pods,
        }

        # ─────────────────────────────
        # Stage 4b — Node Describe
        # ─────────────────────────────

        log.info("[RCA] Stage 4b — Node Describe")

        if pod_name:

            node_name = get_pod_node(
                pod_name,
                namespace,
            )

            if node_name:

                node_desc = get_node_describe(node_name)

                evidence["node_describe"] = node_desc

                evidence["pod_node"] = node_name

                match = detect_patterns(node_desc)

                if match:

                    cause, conf, fixes = match

                    finding.update_if_better(
                        cause,
                        conf,
                        fixes,
                        pod_name,
                        "node_describe",
                        node_desc[:500],
                    )

        # ─────────────────────────────
        # Stage 5 — Service Endpoints
        # ─────────────────────────────

        log.info("[RCA] Stage 5 — Service Endpoints")

        endpoints = get_service_endpoints(
            service_name,
            namespace,
        )

        evidence["service_endpoints"] = endpoints

        if endpoints and (
            "<none>" in endpoints.lower()
            or "notfound" in endpoints.lower()
        ):

            finding.update_if_better(
                "Service has no healthy endpoints",
                82,
                [
                    "Check readiness probes",
                    "Verify pod labels",
                    "Inspect pod failures",
                ],
                pod_name or "",
                "service_endpoints",
                endpoints[:500],
            )

        # ─────────────────────────────
        # Stage 6 — VirtualService
        # ─────────────────────────────

        log.info("[RCA] Stage 6 — VirtualService")

        vs = get_virtual_service(
            service_name,
            namespace,
        )

        if vs:
            evidence["virtual_service"] = vs

        # ─────────────────────────────
        # Finalise
        # ─────────────────────────────

        if finding.root_cause == "Unknown":

            finding.root_cause = (
                "No issue identified — service appears healthy"
            )

            finding.confidence = 0

            finding.suggested_fixes = [
                "Continue monitoring",
                "Review resource allocation",
                "Validate probe configurations",
            ]

        return RCAReport(
            target_service=service_name,
            finding=finding,
            all_evidence=evidence,
        )


# ─────────────────────────────────────────────
# Evidence Collector
# ─────────────────────────────────────────────

def collect_all_evidence(report: RCAReport) -> str:
    """
    Flatten RCAReport evidence into readable text for LLM prompts.
    """

    sections = []

    ev = report.all_evidence

    def _add(
        label: str,
        content,
        limit: int = 2000,
    ):

        if not content:
            return

        if isinstance(content, dict):
            content = str(content)

        if isinstance(content, list):
            content = "\n".join(str(x) for x in content)

        text = str(content).strip()

        if not text:
            return

        sections.append(
            f"=== {label} ===\n{text[:limit]}"
        )

    _add("POD STATUS", ev.get("pod_status"))
    _add("POD EVENTS", ev.get("pod_events"))
    _add("POD LOGS", ev.get("pod_logs"), 3000)
    _add("RESOURCE PRESSURE", ev.get("resource_pressure"))
    _add("NODE DESCRIBE", ev.get("node_describe"))
    _add("SERVICE ENDPOINTS", ev.get("service_endpoints"))

    if ev.get("virtual_service"):
        _add("VIRTUAL SERVICE", ev.get("virtual_service"))

    for dep in report.dependency_reports:

        dep_ev = dep.all_evidence

        _add(
            f"DEPENDENCY {dep.target_service}",
            dep_ev,
            1500,
        )

    return (
        "\n\n".join(sections)
        if sections
        else "No evidence collected."
    )


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

def run_kubectl_rca(
    service_name: str,
    namespace: str = "default",
    service_graph=None,
) -> RCAReport:

    investigator = KubectlRCAInvestigator(
        service_graph=service_graph
    )

    return investigator.investigate(
        service_name,
        namespace,
    )