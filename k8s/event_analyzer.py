"""
K8s Event Analyzer — Pattern detection for Kubernetes workload failures.

This module detects failure patterns by analyzing workload state, events, and metrics.
Used by K8sRCAEngine to populate findings with immediate pattern classification.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List
from k8s.models import K8sWorkload, K8sEvent, K8sClusterSnapshot

# Restart threshold for CrashLoopBackOff detection
K8S_RESTART_THRESHOLD = 3


class K8sEventAnalyzer:
    """
    Detects failure patterns from K8s workload state.
    
    Patterns: CrashLoopBackOff, OOMKilled, ImagePullBackOff, FailedScheduling,
              ReadinessFailed, DependencyFailed, HighCPU, HighMemory, NodeNotReady,
              MissingConfigMap, MissingSecret, NetworkPolicyBlock
    """

    def analyze(self, workload: K8sWorkload, all_events: List[K8sEvent],
                snapshot: K8sClusterSnapshot) -> List[str]:
        """
        Analyze a workload and return detected pattern names.

        Args:
            workload: K8sWorkload to analyze
            all_events: List of K8sEvent from the cluster
            snapshot: K8sClusterSnapshot for node/dependency context

        Returns:
            List of detected pattern name strings (ordered by severity)
        """
        patterns = []

        # Check each pattern
        if self._detect_crash_loop_backoff(workload):
            patterns.append("CrashLoopBackOff")
        if self._detect_oom_killed(workload):
            patterns.append("OOMKilled")
        if self._detect_image_pull_backoff(workload):
            patterns.append("ImagePullBackOff")
        if self._detect_failed_scheduling(workload, all_events):
            patterns.append("FailedScheduling")
        if self._detect_readiness_failed(workload):
            patterns.append("ReadinessFailed")
        if self._detect_dependency_failed(workload, snapshot):
            patterns.append("DependencyFailed")
        if self._detect_high_cpu(workload):
            patterns.append("HighCPU")
        if self._detect_high_memory(workload):
            patterns.append("HighMemory")
        if self._detect_node_not_ready(workload, snapshot):
            patterns.append("NodeNotReady")
        if self._detect_missing_configmap(workload, all_events):
            patterns.append("MissingConfigMap")
        if self._detect_missing_secret(workload, all_events):
            patterns.append("MissingSecret")
        if self._detect_network_policy_block(workload, snapshot):
            patterns.append("NetworkPolicyBlock")

        return patterns

    def _detect_crash_loop_backoff(self, workload: K8sWorkload) -> bool:
        """
        Detect CrashLoopBackOff: container state == "CrashLoopBackOff"
        OR pod restart_count > threshold.
        """
        if not workload.pods:
            return False

        for pod in workload.pods:
            # Check container states
            for cs in pod.container_states:
                if cs.state_reason == "CrashLoopBackOff":
                    return True
            # Check high restart count
            if pod.restart_count > K8S_RESTART_THRESHOLD:
                return True

        return False

    def _detect_oom_killed(self, workload: K8sWorkload) -> bool:
        """Detect OOMKilled: container state_reason == "OOMKilled"."""
        if not workload.pods:
            return False

        for pod in workload.pods:
            for cs in pod.container_states:
                if cs.state_reason == "OOMKilled":
                    return True

        return False

    def _detect_image_pull_backoff(self, workload: K8sWorkload) -> bool:
        """
        Detect ImagePullBackOff: state_reason in ["ImagePullBackOff", "ErrImagePull"].
        """
        if not workload.pods:
            return False

        for pod in workload.pods:
            for cs in pod.container_states:
                if cs.state_reason in ["ImagePullBackOff", "ErrImagePull"]:
                    return True

        return False

    def _detect_failed_scheduling(self, workload: K8sWorkload,
                                  all_events: List[K8sEvent]) -> bool:
        """
        Detect FailedScheduling: any event.reason == "FailedScheduling"
        for pods in this workload.
        """
        if not workload.pods:
            return False

        pod_names = {pod.name for pod in workload.pods}

        for event in all_events:
            if event.reason == "FailedScheduling":
                if event.involved_object.get("name") in pod_names:
                    return True

        return False

    def _detect_readiness_failed(self, workload: K8sWorkload) -> bool:
        """
        Detect ReadinessFailed: pod.ready==False AND pod.phase=="Running".
        """
        if not workload.pods:
            return False

        for pod in workload.pods:
            if not pod.ready and pod.phase == "Running":
                return True

        return False

    def _detect_dependency_failed(self, workload: K8sWorkload,
                                  snapshot: K8sClusterSnapshot) -> bool:
        """
        Detect DependencyFailed: pod phase=Running but a workload it depends on
        (from service_graph) has ready==False.
        
        NOTE: This is a simplified check. In production, would query service_graph
        to find dependencies. For Phase 4, we assume no dependencies detected.
        """
        # Placeholder: in full implementation, would query service_graph
        # For now, return False (no dependency detection in Phase 4)
        return False

    def _detect_high_cpu(self, workload: K8sWorkload) -> bool:
        """
        Detect HighCPU: pod.cpu_usage > 80% of pod.cpu_limit.
        Skip if either is "N/A".
        """
        if not workload.pods:
            return False

        for pod in workload.pods:
            if pod.cpu_usage == "N/A" or pod.cpu_limit == "N/A":
                continue

            try:
                # Parse millicores (e.g., "500m" -> 500, "1" -> 1000)
                usage = self._parse_cpu(pod.cpu_usage)
                limit = self._parse_cpu(pod.cpu_limit)

                if limit > 0 and (usage / limit) > 0.80:
                    return True
            except (ValueError, ZeroDivisionError):
                continue

        return False

    def _detect_high_memory(self, workload: K8sWorkload) -> bool:
        """
        Detect HighMemory: pod.memory_usage > 85% of pod.memory_limit.
        """
        if not workload.pods:
            return False

        for pod in workload.pods:
            if pod.memory_usage == "N/A" or pod.memory_limit == "N/A":
                continue

            try:
                usage = self._parse_memory(pod.memory_usage)
                limit = self._parse_memory(pod.memory_limit)

                if limit > 0 and (usage / limit) > 0.85:
                    return True
            except (ValueError, ZeroDivisionError):
                continue

        return False

    def _detect_node_not_ready(self, workload: K8sWorkload,
                               snapshot: K8sClusterSnapshot) -> bool:
        """
        Detect NodeNotReady: snapshot.nodes has any node where ready==False
        AND workload pods are scheduled on that node.
        """
        if not workload.pods or not snapshot.nodes:
            return False

        # Get nodes where pods are scheduled
        pod_node_names = {pod.node_name for pod in workload.pods if pod.node_name}

        # Find if any are unhealthy
        for node in snapshot.nodes:
            if not node.ready and node.name in pod_node_names:
                return True

        return False

    def _detect_missing_configmap(self, workload: K8sWorkload,
                                  all_events: List[K8sEvent]) -> bool:
        """
        Detect MissingConfigMap: any event.reason=="FailedMount"
        AND "configmap" in event.message.lower().
        """
        if not workload.pods:
            return False

        pod_names = {pod.name for pod in workload.pods}

        for event in all_events:
            if event.reason == "FailedMount":
                if event.involved_object.get("name") in pod_names:
                    if "configmap" in event.message.lower():
                        return True

        return False

    def _detect_missing_secret(self, workload: K8sWorkload,
                               all_events: List[K8sEvent]) -> bool:
        """
        Detect MissingSecret: any event.reason=="FailedMount"
        AND "secret" in event.message.lower().
        """
        if not workload.pods:
            return False

        pod_names = {pod.name for pod in workload.pods}

        for event in all_events:
            if event.reason == "FailedMount":
                if event.involved_object.get("name") in pod_names:
                    if "secret" in event.message.lower():
                        return True

        return False

    def _detect_network_policy_block(self, workload: K8sWorkload,
                                     snapshot: K8sClusterSnapshot) -> bool:
        """
        Detect NetworkPolicyBlock: any event.reason=="NetworkNotReady"
        OR ("connection refused" in any pod log line
            AND snapshot has network policies in workload's namespace).
        """
        if not workload.pods:
            return False

        # Check for NetworkNotReady events
        for pod in workload.pods:
            for event in pod.events:
                if event.reason == "NetworkNotReady":
                    return True

        # Check for connection errors in logs + network policies exist
        namespace = workload.namespace
        has_policies = any(np.namespace == namespace for np in snapshot.network_policies)

        if has_policies:
            for pod in workload.pods:
                for log_line in pod.logs:
                    if "connection refused" in log_line.lower():
                        return True

        return False

    def classify_severity(self, patterns: List[str]) -> str:
        """
        Classify overall severity based on detected patterns.

        Severity levels:
        - Critical: CrashLoopBackOff, OOMKilled, FailedScheduling, NodeNotReady
        - High: ImagePullBackOff, ReadinessFailed, DependencyFailed, HighMemory
        - Medium: HighCPU, NetworkPolicyBlock
        - Low: MissingConfigMap, MissingSecret
        - Info: empty list

        Args:
            patterns: List of detected pattern names

        Returns:
            Severity string: "Critical", "High", "Medium", "Low", or "Info"
        """
        if not patterns:
            return "Info"

        critical_patterns = {"CrashLoopBackOff", "OOMKilled", "FailedScheduling", "NodeNotReady"}
        high_patterns = {"ImagePullBackOff", "ReadinessFailed", "DependencyFailed", "HighMemory"}
        medium_patterns = {"HighCPU", "NetworkPolicyBlock"}
        low_patterns = {"MissingConfigMap", "MissingSecret"}

        pattern_set = set(patterns)

        if pattern_set & critical_patterns:
            return "Critical"
        elif pattern_set & high_patterns:
            return "High"
        elif pattern_set & medium_patterns:
            return "Medium"
        elif pattern_set & low_patterns:
            return "Low"
        else:
            return "Info"

    @staticmethod
    def _parse_cpu(cpu_str: str) -> float:
        """
        Parse CPU string to millicores.
        Examples: "500m" -> 500, "1" -> 1000, "0.5" -> 500.
        """
        cpu_str = cpu_str.strip()
        if cpu_str.endswith("m"):
            return float(cpu_str[:-1])
        else:
            return float(cpu_str) * 1000

    @staticmethod
    def _parse_memory(mem_str: str) -> float:
        """
        Parse memory string to bytes.
        Examples: "512Mi" -> 536870912, "1Gi" -> 1073741824, "100" -> 100.
        """
        mem_str = mem_str.strip()
        units = {
            "Ki": 1024,
            "Mi": 1024 ** 2,
            "Gi": 1024 ** 3,
            "Ti": 1024 ** 4,
            "K": 1000,
            "M": 1000 ** 2,
            "G": 1000 ** 3,
            "T": 1000 ** 4,
        }

        # Find unit
        for unit, multiplier in units.items():
            if mem_str.endswith(unit):
                return float(mem_str[:-len(unit)]) * multiplier

        # No unit, assume bytes
        return float(mem_str)
