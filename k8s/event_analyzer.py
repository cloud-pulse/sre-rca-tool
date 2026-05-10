from __future__ import annotations

from flags import K8S_RESTART_COUNT_THRESHOLD


class K8sEventAnalyzer:
    def detect_patterns(self, snapshot, service_pods: list, service_events: list, service_nodes: list, service_pvcs: list, service_quotas: list) -> list[str]:
        patterns: list[str] = []

        for pod in service_pods:
            if pod.restart_count > K8S_RESTART_COUNT_THRESHOLD:
                patterns.append("CrashLoopBackOff")
            if not pod.ready and pod.phase == "Running":
                patterns.append("ReadinessFailed")
            for state in pod.container_states:
                reason = state.state_reason or ""
                if reason == "CrashLoopBackOff":
                    patterns.append("CrashLoopBackOff")
                if reason == "OOMKilled":
                    patterns.append("OOMKilled")
                if reason in ("ImagePullBackOff", "ErrImagePull"):
                    patterns.append("ImagePullBackOff")

        for event in service_events:
            if event.reason == "FailedScheduling":
                patterns.append("FailedScheduling")
            if event.reason == "FailedMount" and "configmap" in event.message.lower():
                patterns.append("MissingConfigMap")
            if event.reason == "FailedMount" and "secret" in event.message.lower():
                patterns.append("MissingSecret")
            if event.reason == "NetworkNotReady":
                patterns.append("NetworkPolicyBlock")

        for node in service_nodes:
            if not node.ready:
                patterns.append("NodeNotReady")

        for pvc in service_pvcs:
            if pvc.status != "Bound":
                patterns.append("PVCUnbound")

        for quota in service_quotas:
            if self._quota_exceeded(quota):
                patterns.append("QuotaExceeded")

        return sorted(set(patterns))

    def classify_severity(self, patterns: list[str]) -> str:
        critical = {"CrashLoopBackOff", "OOMKilled", "FailedScheduling", "NodeNotReady", "QuotaExceeded"}
        high = {"ImagePullBackOff", "ReadinessFailed", "PVCUnbound", "DependencyFailed"}
        medium = {"NetworkPolicyBlock", "RestartSpike"}
        low = {"MissingConfigMap", "MissingSecret"}

        if any(p in critical for p in patterns):
            return "Critical"
        if any(p in high for p in patterns):
            return "High"
        if any(p in medium for p in patterns):
            return "Medium"
        if any(p in low for p in patterns):
            return "Low"
        return "Info"

    def _quota_exceeded(self, quota) -> bool:
        for key in ("limits.cpu", "limits.memory", "requests.cpu", "requests.memory"):
            hard = quota.hard.get(key)
            used = quota.used.get(key)
            if not hard or not used:
                continue
            try:
                if self._to_number(used) >= self._to_number(hard):
                    return True
            except Exception:
                continue
        return False

    def _to_number(self, value: str) -> float:
        text = (value or "").strip().lower()
        if text.endswith("mi"):
            return float(text[:-2])
        if text.endswith("gi"):
            return float(text[:-2]) * 1024
        if text.endswith("m"):
            return float(text[:-1]) / 1000
        return float(text)
