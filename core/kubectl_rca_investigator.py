"""
core/kubectl_rca_investigator.py

Sequential early-exit RCA pipeline for AI-SRE kubectl mode.

Pipeline order (per service, then per dependency):
  1. Pod status check
  2. Pod events
  3. Pod + container logs
  4. Node / cluster resource pressure
  5. Dependency health check (recurse steps 1-3)

Stops and returns as soon as confidence >= CONFIDENCE_THRESHOLD.
"""

import logging
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
)

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 80   # exit early at or above this confidence
MAX_DEPENDENCY_DEPTH = 2    # how deep to recurse into dependencies


# ─────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────

@dataclass
class RCAFinding:
    root_cause: str = "Unknown"
    confidence: int = 0                       # 0–100
    affected_service: str = ""
    affected_pod: str = ""
    evidence_stage: str = ""                  # which pipeline stage found it
    raw_evidence: str = ""                    # key log/event snippet
    suggested_fixes: list[str] = field(default_factory=list)
    dependency_chain: list[str] = field(default_factory=list)


@dataclass
class RCAReport:
    target_service: str
    finding: RCAFinding
    all_evidence: dict = field(default_factory=dict)  # stage -> evidence text
    dependency_reports: list["RCAReport"] = field(default_factory=list)

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
            "raw_evidence_snippet": self.finding.raw_evidence[:500] if self.finding.raw_evidence else "",
            "all_evidence": self.all_evidence,
            "dependency_reports": [r.to_dict() for r in self.dependency_reports],
        }


# ─────────────────────────────────────────────
# Pattern detection (extends PatternDetector from sre_investigator)
# ─────────────────────────────────────────────

PATTERNS = [
    # (regex, root_cause_label, confidence, suggested_fixes)
    (r"OOMKilled|out of memory|memory limit exceeded|Cannot allocate memory",
     "OOM / Memory limit exceeded", 95,
     ["Increase memory limits in deployment spec",
      "Profile application for memory leaks",
      "Check for unbounded caches or large payload processing"]),

    (r"CrashLoopBackOff",
     "CrashLoopBackOff — repeated container crash", 90,
     ["Check application startup logs for crash reason",
      "Validate liveness probe configuration",
      "Ensure required env vars and config maps are present"]),

    (r"ImagePullBackOff|ErrImagePull|image.*not found|manifest unknown",
     "Image pull failure", 92,
     ["Verify image name and tag in deployment spec",
      "Check image registry credentials (imagePullSecrets)",
      "Confirm image exists in registry"]),

    (r"CreateContainerConfigError|secret.*not found|configmap.*not found|env.*not found",
     "Missing secret or ConfigMap", 88,
     ["Verify all referenced secrets/configmaps exist in namespace",
      "Check env var injection in deployment spec"]),

    (r"Liveness probe failed|Readiness probe failed|probe.*timeout|health check.*fail",
     "Probe failure (liveness/readiness)", 85,
     ["Review probe endpoint availability",
      "Increase probe timeout/period thresholds",
      "Check if application is starting up too slowly (initialDelaySeconds)"]),

    (r"connection refused|ECONNREFUSED|dial tcp.*connection refused",
     "Dependency connection refused", 87,
     ["Verify the dependency service is running and its pods are healthy",
      "Check service name and port in the calling service config",
      "Inspect dependency pod logs"]),

    (r"no such host|DNS.*NXDOMAIN|could not resolve|name resolution fail",
     "DNS resolution failure", 85,
     ["Verify service name is correct and matches Kubernetes service object",
      "Check CoreDNS pod health in kube-system namespace",
      "Confirm the dependency service exists in the correct namespace"]),

    (r"timeout|context deadline exceeded|i/o timeout|request timeout",
     "Request timeout / latency spike", 75,
     ["Check resource pressure on the dependency service",
      "Look for network policies blocking traffic",
      "Increase timeout thresholds if dependency is under heavy load"]),

    (r"panic:|fatal error|SIGSEGV|SIGABRT|goroutine.*\[running\]",
     "Application panic / fatal crash", 92,
     ["Review stack trace in logs",
      "Check for nil pointer dereference or uncaught exception",
      "Review recent code changes"]),

    (r"Evicted|eviction|node.*pressure|DiskPressure|MemoryPressure|PIDPressure",
     "Node resource pressure / pod eviction", 88,
     ["Check node resource usage (kubectl top nodes)",
      "Scale up cluster or reduce pod resource requests",
      "Review pod priority and eviction policies"]),

    (r"Pending",
     "Pod stuck in Pending — scheduling failure", 80,
     ["Check node resources (kubectl describe node)",
      "Verify resource requests fit on available nodes",
      "Check for taints/tolerations or affinity rules blocking scheduling"]),
]


def detect_patterns(text: str) -> Optional[tuple[str, int, list[str]]]:
    """
    Scan text against all patterns.
    Returns (root_cause, confidence, fixes) for highest-confidence match, or None.
    """
    best = None
    best_conf = 0
    for pattern, cause, conf, fixes in PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            if conf > best_conf:
                best = (cause, conf, fixes)
                best_conf = conf
    return best


# ─────────────────────────────────────────────
# Evidence helpers
# ─────────────────────────────────────────────

def _pods_status_evidence(pods: list[dict]) -> str:
    lines = []
    for p in pods:
        lines.append(
            f"  {p['name']}: status={p['status']} ready={p['ready']} restarts={p['restarts']} age={p['age']}"
        )
    return "\n".join(lines) if lines else "  (no pods found)"


def _resource_pressure_summary(nodes: list[dict], cluster_pods: list[dict]) -> str:
    node_lines = [f"  {n.get('name','?')}: CPU={n.get('cpu','?')} ({n.get('cpu_pct','?')}) MEM={n.get('memory','?')} ({n.get('memory_pct','?')})" for n in nodes if "error" not in n]
    pod_lines = [f"  {p.get('pod','?')}: CPU={p.get('cpu','?')} MEM={p.get('memory','?')}" for p in cluster_pods[:10] if "error" not in p]
    return "Nodes:\n" + ("\n".join(node_lines) or "  (unavailable)") + \
           "\nTop Pods:\n" + ("\n".join(pod_lines) or "  (unavailable)")


# ─────────────────────────────────────────────
# Core investigator
# ─────────────────────────────────────────────

class KubectlRCAInvestigator:
    def __init__(self, service_graph=None):
        """
        service_graph: instance of core.service_graph.ServiceGraph
        Pass None to skip dependency analysis.
        """
        self.service_graph = service_graph

    def investigate(
        self,
        service_name: str,
        namespace: str = "default",
        depth: int = 0,
    ) -> RCAReport:
        """
        Run the full sequential RCA pipeline for a service.
        Returns RCAReport.
        """
        logger.info(f"[RCA] Investigating '{service_name}' in namespace '{namespace}' (depth={depth})")
        finding = RCAFinding(affected_service=service_name)
        all_evidence = {}

        # ── 1. Pod status check ──────────────────────────────
        pods = get_pods(namespace, service_name)
        status_evidence = _pods_status_evidence(pods)
        all_evidence["pod_status"] = status_evidence
        logger.info(f"[RCA] Stage 1 — Pod status:\n{status_evidence}")

        for pod in pods:
            status = pod.get("status", "")
            restarts = pod.get("restarts", 0)

            # Direct critical status match
            if status in CRITICAL_STATUSES:
                match = detect_patterns(status)
                if match:
                    cause, conf, fixes = match
                    if conf >= CONFIDENCE_THRESHOLD:
                        finding.root_cause = cause
                        finding.confidence = conf
                        finding.affected_pod = pod["name"]
                        finding.evidence_stage = "pod_status"
                        finding.raw_evidence = f"Pod {pod['name']} status: {status}, restarts: {restarts}"
                        finding.suggested_fixes = fixes
                        return RCAReport(service_name, finding, all_evidence)

            # High restart count is a strong signal even without matching status
            if restarts >= 5 and status not in ("Running",):
                finding.root_cause = f"High restart count ({restarts}) — likely CrashLoopBackOff or startup failure"
                finding.confidence = 75
                finding.affected_pod = pod["name"]
                finding.evidence_stage = "pod_status"
                finding.raw_evidence = f"Pod {pod['name']} restarts={restarts} status={status}"
                finding.suggested_fixes = [
                    "Check pod logs for crash reason",
                    "Validate liveness probe and startup configuration",
                ]
                # Don't exit yet — try to get higher confidence from events/logs

        # ── 2. Pod events ─────────────────────────────────────
        if pods:
            pod_name = pods[0]["name"]  # focus on first (usually most relevant) pod
            events = get_pod_events(pod_name, namespace)
            all_evidence["pod_events"] = events
            logger.info(f"[RCA] Stage 2 — Events for {pod_name}")

            match = detect_patterns(events)
            if match:
                cause, conf, fixes = match
                if conf >= CONFIDENCE_THRESHOLD:
                    finding.root_cause = cause
                    finding.confidence = conf
                    finding.affected_pod = pod_name
                    finding.evidence_stage = "pod_events"
                    finding.raw_evidence = events[:600]
                    finding.suggested_fixes = fixes
                    return RCAReport(service_name, finding, all_evidence)
                elif conf > finding.confidence:
                    # Keep as best candidate so far
                    finding.root_cause = cause
                    finding.confidence = conf
                    finding.affected_pod = pod_name
                    finding.evidence_stage = "pod_events"
                    finding.raw_evidence = events[:600]
                    finding.suggested_fixes = fixes

        # ── 3. Pod + container logs ───────────────────────────
        if pods:
            pod_name = pods[0]["name"]
            containers = get_containers_for_pod(pod_name, namespace)
            log_map = get_all_container_logs(pod_name, namespace, containers, tail=200)
            combined_logs = "\n".join(log_map.values())
            all_evidence["pod_logs"] = combined_logs
            logger.info(f"[RCA] Stage 3 — Logs for {pod_name} containers={containers}")

            match = detect_patterns(combined_logs)
            if match:
                cause, conf, fixes = match
                if conf >= CONFIDENCE_THRESHOLD:
                    finding.root_cause = cause
                    finding.confidence = conf
                    finding.affected_pod = pod_name
                    finding.evidence_stage = "pod_logs"
                    # Surface the most relevant 3 lines
                    snippet = self._extract_relevant_lines(combined_logs, cause)
                    finding.raw_evidence = snippet
                    finding.suggested_fixes = fixes
                    return RCAReport(service_name, finding, all_evidence)
                elif conf > finding.confidence:
                    finding.root_cause = cause
                    finding.confidence = conf
                    finding.affected_pod = pod_name
                    finding.evidence_stage = "pod_logs"
                    finding.suggested_fixes = fixes

        # ── 4. Node / cluster resource pressure ──────────────
        nodes = get_node_resources()
        cluster_pods = get_cluster_resource_pressure(namespace)
        resource_summary = _resource_pressure_summary(nodes, cluster_pods)
        all_evidence["resource_pressure"] = resource_summary
        logger.info(f"[RCA] Stage 4 — Resource pressure check")

        match = detect_patterns(resource_summary)
        if match:
            cause, conf, fixes = match
            if conf >= CONFIDENCE_THRESHOLD:
                finding.root_cause = cause
                finding.confidence = conf
                finding.evidence_stage = "resource_pressure"
                finding.raw_evidence = resource_summary[:600]
                finding.suggested_fixes = fixes
                return RCAReport(service_name, finding, all_evidence)
            elif conf > finding.confidence:
                finding.root_cause = cause
                finding.confidence = conf
                finding.evidence_stage = "resource_pressure"
                finding.suggested_fixes = fixes

        # ── 5. Dependency health check ────────────────────────
        dep_reports = []
        if depth < MAX_DEPENDENCY_DEPTH and self.service_graph:
            deps = self._get_dependencies(service_name)
            logger.info(f"[RCA] Stage 5 — Checking {len(deps)} dependencies: {deps}")

            for dep in deps:
                dep_namespace = self._get_dep_namespace(dep, namespace)
                dep_report = self.investigate(dep, dep_namespace, depth=depth + 1)
                dep_reports.append(dep_report)

                dep_finding = dep_report.finding
                if dep_finding.confidence >= CONFIDENCE_THRESHOLD:
                    # Dependency is the likely root cause
                    root_cause = (
                        f"Dependency '{dep}' failure: {dep_finding.root_cause}"
                    )
                    finding.root_cause = root_cause
                    finding.confidence = dep_finding.confidence
                    finding.affected_service = dep
                    finding.affected_pod = dep_finding.affected_pod
                    finding.evidence_stage = f"dependency:{dep}"
                    finding.raw_evidence = dep_finding.raw_evidence
                    finding.suggested_fixes = dep_finding.suggested_fixes
                    finding.dependency_chain = [service_name, dep] + dep_finding.dependency_chain
                    return RCAReport(service_name, finding, all_evidence, dep_reports)

        # ── Final: return best candidate found so far ─────────
        if not finding.root_cause or finding.root_cause == "Unknown":
            finding.root_cause = "No clear root cause identified — service may be healthy or issue is intermittent"
            finding.confidence = 0
            finding.suggested_fixes = [
                "Monitor service over time for intermittent failures",
                "Enable verbose/debug logging",
                "Check recent deployments or config changes",
            ]

        return RCAReport(service_name, finding, all_evidence, dep_reports)

    def _get_dependencies(self, service_name: str) -> list[str]:
        if not self.service_graph:
            return []
        try:
            config = self.service_graph.services.get(service_name, {})
            return config.get("depends_on", [])
        except Exception:
            return []

    def _get_dep_namespace(self, dep: str, fallback: str) -> str:
        if not self.service_graph:
            return fallback
        try:
            return self.service_graph.get_namespace(dep) or fallback
        except Exception:
            return fallback

    @staticmethod
    def _extract_relevant_lines(log_text: str, cause: str) -> str:
        """Return up to 5 most relevant lines from the log for the given cause."""
        keywords = cause.lower().split()
        scored = []
        for line in log_text.splitlines():
            score = sum(1 for kw in keywords if kw in line.lower())
            if score > 0:
                scored.append((score, line))
        scored.sort(key=lambda x: -x[0])
        return "\n".join(line for _, line in scored[:5])


# ─────────────────────────────────────────────
# Convenience entry point
# ─────────────────────────────────────────────

def run_kubectl_rca(
    service_name: str,
    namespace: str = "default",
    service_graph=None,
) -> dict:
    """
    Top-level function. Wire this into main.py.
    Returns a plain dict matching the existing RCA output schema.
    """
    investigator = KubectlRCAInvestigator(service_graph=service_graph)
    report = investigator.investigate(service_name, namespace)
    return report.to_dict()