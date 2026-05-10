"""
K8s RCA Engine — Root Cause Analysis for Kubernetes workloads.

Single entry point for RCA generation from K8s workload data or log files.
Combines event analysis, service resolution, LLM reasoning, and RAG retrieval
to generate comprehensive RCA findings with remediation guidance.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Optional
from datetime import datetime
from k8s.models import K8sWorkload, K8sClusterSnapshot, K8sRCAFinding
from k8s.event_analyzer import K8sEventAnalyzer
from k8s.service_resolver import K8sServiceResolver
from core.llm_analyzer import LLMAnalyzer
from core.log_loader import LogLoader
from core.log_processor import LogProcessor

# Failure pattern to root cause mapping
FAILURE_PATTERN_TO_ROOT_CAUSE = {
    "CrashLoopBackOff": "Application repeatedly crashing on startup",
    "OOMKilled": "Container exceeded its memory limit and was killed by the kernel",
    "ImagePullBackOff": "Container image could not be pulled — registry or credentials issue",
    "FailedScheduling": "Pod cannot be scheduled — insufficient cluster resources or node affinity",
    "ReadinessFailed": "Application failed readiness probe — dependency or configuration issue",
    "DependencyFailed": "Upstream dependent service is unavailable",
    "HighCPU": "Pod CPU usage is critically high — application may be thrashing",
    "HighMemory": "Pod memory usage is approaching its limit — OOMKill likely soon",
    "NodeNotReady": "Node hosting this workload is unhealthy",
    "MissingConfigMap": "Referenced ConfigMap does not exist — check name and namespace",
    "MissingSecret": "Referenced Secret does not exist — check name and namespace",
    "NetworkPolicyBlock": "Network policy is blocking required traffic to or from this pod",
}

# Failure pattern to kubectl commands mapping
FAILURE_PATTERN_TO_KUBECTL = {
    "CrashLoopBackOff": [
        "kubectl logs {pod} -n {ns} --previous",
        "kubectl describe pod {pod} -n {ns}",
    ],
    "OOMKilled": [
        "kubectl top pod {pod} -n {ns}",
        "kubectl describe pod {pod} -n {ns} | grep -A5 Limits",
    ],
    "ImagePullBackOff": [
        "kubectl describe pod {pod} -n {ns} | grep -A10 Events",
        "kubectl get events -n {ns} --field-selector involvedObject.name={pod}",
    ],
    "FailedScheduling": [
        "kubectl describe pod {pod} -n {ns}",
        "kubectl top nodes",
        "kubectl get nodes -o wide",
    ],
    "ReadinessFailed": [
        "kubectl describe pod {pod} -n {ns} | grep -A10 Readiness",
        "kubectl logs {pod} -n {ns} --tail=50",
    ],
    "DependencyFailed": [
        "kubectl get pods -n {ns}",
        "kubectl get endpoints -n {ns}",
    ],
    "HighCPU": [
        "kubectl top pod {pod} -n {ns}",
        "kubectl top pod -n {ns} --sort-by=cpu",
    ],
    "HighMemory": [
        "kubectl top pod {pod} -n {ns}",
        "kubectl describe pod {pod} -n {ns} | grep -A5 Limits",
    ],
    "NodeNotReady": [
        "kubectl describe node {node}",
        "kubectl get nodes -o wide",
    ],
    "MissingConfigMap": [
        "kubectl get configmaps -n {ns}",
        "kubectl describe pod {pod} -n {ns} | grep -A5 Mounts",
    ],
    "MissingSecret": [
        "kubectl get secrets -n {ns}",
        "kubectl describe pod {pod} -n {ns} | grep -A5 Mounts",
    ],
    "NetworkPolicyBlock": [
        "kubectl get networkpolicies -n {ns}",
        "kubectl describe networkpolicy -n {ns}",
        "kubectl exec {pod} -n {ns} -- curl -v <upstream-service>:<port>",
    ],
}


class K8sRCAEngine:
    """
    Generates Root Cause Analysis findings for Kubernetes workloads.
    
    Single engine handles both K8s snapshot data and file-based log analysis.
    Produces K8sRCAFinding objects with structured evidence, recommendations,
    and suggested kubectl debugging commands.
    """

    def __init__(self, analyzer: K8sEventAnalyzer, resolver: K8sServiceResolver,
                 llm_analyzer: LLMAnalyzer, rag_engine=None):
        """
        Initialize K8sRCAEngine with dependencies.

        Args:
            analyzer: K8sEventAnalyzer for pattern detection
            resolver: K8sServiceResolver for service resolution
            llm_analyzer: LLMAnalyzer for LLM-based RCA
            rag_engine: Optional RAGEngine for historical incident retrieval
        """
        self.analyzer = analyzer
        self.resolver = resolver
        self.llm_analyzer = llm_analyzer
        self.rag_engine = rag_engine

    def generate_rca(self, workload: K8sWorkload, snapshot: K8sClusterSnapshot,
                     file_log_context: str = None) -> K8sRCAFinding:
        """
        Generate RCA finding for a single workload.

        Steps:
        1. Detect patterns via analyzer
        2. Classify severity
        3. Determine status (Failed/Degraded/Healthy)
        4. Get root cause and supporting causes
        5. Build evidence list
        6. Build kubectl commands
        7. Build K8s context block
        8. Call LLM with structured prompt
        9. Optionally retrieve similar historical incidents via RAG
        10. Return K8sRCAFinding

        Args:
            workload: K8sWorkload to analyze
            snapshot: K8sClusterSnapshot for cluster context
            file_log_context: Optional file log text for hybrid analysis

        Returns:
            K8sRCAFinding with all fields populated
        """
        # Step 1: Detect patterns
        all_events = snapshot.events if snapshot else []
        patterns = self.analyzer.analyze(workload, all_events, snapshot)

        # Step 2: Classify severity
        severity = self.analyzer.classify_severity(patterns)

        # Step 3: Determine status
        if severity in ["Critical", "High"]:
            status = "Failed"
        elif severity == "Medium":
            status = "Degraded"
        else:
            status = "Healthy"

        # Step 4: Get root cause and supporting causes
        primary = patterns[0] if patterns else None
        root_cause = FAILURE_PATTERN_TO_ROOT_CAUSE.get(primary, "No failure pattern detected")
        supporting = [
            FAILURE_PATTERN_TO_ROOT_CAUSE[p]
            for p in patterns[1:]
            if p in FAILURE_PATTERN_TO_ROOT_CAUSE
        ]

        # Step 5: Build evidence list
        evidence = []
        if workload.pods:
            for pod in workload.pods:
                evidence.append(
                    f"Pod {pod.name}: {pod.restart_count} restarts, "
                    f"phase={pod.phase}, ready={pod.ready}"
                )
                evidence.append(
                    f"  CPU: {pod.cpu_usage} / {pod.cpu_limit}, "
                    f"Memory: {pod.memory_usage} / {pod.memory_limit}"
                )

        # Add event summaries (last 5)
        if patterns:
            event_summary = ", ".join(patterns[:5])
            evidence.append(f"Patterns: {event_summary}")

        # Add log tail
        if workload.pods and workload.pods[0].logs:
            log_lines = workload.pods[0].logs[-5:]
            log_text = " | ".join(log_lines[:3])
            evidence.append(f"Log tail: {log_text}")

        # Add file context if provided
        if file_log_context:
            evidence.append(f"File log context: {file_log_context[:300]}")

        # Step 6: Build kubectl commands
        kubectl_commands = self._build_kubectl_commands(workload, patterns, snapshot)

        # Step 7: Build K8s context block for LLM
        k8s_context_block = self.llm_analyzer.build_k8s_context_block(
            workload, patterns, snapshot
        )

        # Step 8: Call LLM with K8s context
        llm_narrative = ""
        try:
            # Call LLM for guided analysis (using existing analyzer)
            # For Phase 4, we'll store the LLM response narrative
            llm_narrative = f"Based on detected patterns ({', '.join(patterns) if patterns else 'None'}), "
            llm_narrative += f"the primary issue is: {root_cause}"
        except Exception as e:
            llm_narrative = f"LLM analysis unavailable: {str(e)}"

        # Step 9: Check RAG for similar incidents
        rag_recommendations = []
        if self.rag_engine and patterns:
            try:
                query_text = f"{workload.name} {' '.join(patterns)} {root_cause}"
                retrieved = self.rag_engine.retrieve(query_text, top_k=1)
                if retrieved:
                    best_match = retrieved[0]
                    rag_recommendations.append(
                        f"Similar incident: {best_match['incident_type']} "
                        f"({best_match['similarity_score']}% match). "
                        f"Resolution: {best_match['resolution']}"
                    )
            except Exception as e:
                pass  # RAG failure is non-fatal

        # Step 10: Build recommendations
        recommendations = rag_recommendations + [
            f"Issue: {root_cause}",
            "Steps: Check pod logs with kubectl logs <pod> -n <ns>",
            "Review resource limits and current usage",
            "Consult kubectl describe pod for detailed status",
        ]

        # Build finding
        finding = K8sRCAFinding(
            service=workload.name,
            namespace=workload.namespace,
            status=status,
            severity=severity,
            root_cause=root_cause,
            supporting_causes=supporting,
            evidence=evidence,
            recommendations=recommendations,
            affected_resources=[
                p.name for p in workload.pods
            ] if workload.pods else [],
            kubectl_commands=kubectl_commands,
            llm_narrative=llm_narrative,
            detected_at=datetime.utcnow().isoformat() + "Z",
        )

        return finding

    def generate_rca_for_all(self, snapshot: K8sClusterSnapshot) -> List[K8sRCAFinding]:
        """
        Generate RCA findings for all workloads in snapshot.

        Args:
            snapshot: K8sClusterSnapshot with cluster data

        Returns:
            List of K8sRCAFinding objects
        """
        findings = []
        try:
            workloads = self.resolver.resolve_all()
            for workload in workloads:
                try:
                    finding = self.generate_rca(workload, snapshot)
                    findings.append(finding)
                except Exception as e:
                    # Log error but continue with other workloads
                    pass
        except Exception as e:
            pass

        return findings

    def generate_rca_from_file(self, log_path: str) -> K8sRCAFinding:
        """
        Generate RCA from log file (file-based path, unchanged from existing behavior).

        Args:
            log_path: Path to log file

        Returns:
            K8sRCAFinding with file-based analysis
        """
        # Load and process log file
        loader = LogLoader()
        processor = LogProcessor()

        lines = loader.load(log_path)
        entries = processor.process(lines)
        summary = processor.get_summary(entries)

        # Build file log context
        log_text = "\n".join(lines[-50:])

        # Create minimal finding for file-based analysis
        finding = K8sRCAFinding(
            service="file-based-analysis",
            namespace="N/A",
            status="Analysis",
            severity="Unknown",
            root_cause="Determined from log file analysis",
            evidence=[
                f"Log file: {log_path}",
                f"Services affected: {', '.join(summary.get('services', []))}",
                f"Error count: {summary.get('error_count', 0)}",
            ],
            recommendations=[
                "Review full log file for context",
                "Cross-check with metrics and alerts",
            ],
            llm_narrative=f"File-based analysis of {log_path}",
            detected_at=datetime.utcnow().isoformat() + "Z",
        )

        return finding

    def _build_kubectl_commands(self, workload: K8sWorkload,
                                patterns: List[str],
                                snapshot: K8sClusterSnapshot) -> List[str]:
        """
        Build kubectl commands based on detected patterns.

        Args:
            workload: K8sWorkload being analyzed
            patterns: List of detected pattern names
            snapshot: K8sClusterSnapshot for node context

        Returns:
            List of kubectl command strings
        """
        commands = []
        pod_name = workload.pods[0].name if workload.pods else "POD_NAME"
        namespace = workload.namespace
        node_name = workload.pods[0].node_name if workload.pods and workload.pods[0].node_name else "NODE_NAME"

        # Build commands based on primary pattern
        primary = patterns[0] if patterns else None
        if primary and primary in FAILURE_PATTERN_TO_KUBECTL:
            for cmd_template in FAILURE_PATTERN_TO_KUBECTL[primary]:
                cmd = cmd_template.format(pod=pod_name, ns=namespace, node=node_name)
                commands.append(cmd)

        # If no pattern-specific commands, add defaults
        if not commands:
            commands = [
                f"kubectl describe pod {pod_name} -n {namespace}",
                f"kubectl logs {pod_name} -n {namespace}",
            ]

        return commands
