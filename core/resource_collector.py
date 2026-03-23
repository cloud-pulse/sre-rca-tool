import sys
import os
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

import random
import subprocess
from core.logger import get_logger

log = get_logger("resource_collector")

class ResourceCollector:
    """
    Collects pod resource consumption data from Kubernetes cluster.
    Phase 1 uses realistic mock data. Real kubectl implementation in Task 23.
    """



    def get_mock_resources(self,
                        services: list[str]
                        ) -> dict:
        import hashlib
        import random

        result = {}

        # Identify which service gets CRITICAL
        # Prefer DB-like services
        db_services = [
            s for s in services
            if any(k in s.lower()
                   for k in [
                       "database", "db",
                       "postgres", "mysql",
                       "redis", "mongo"
                   ])
        ]
        critical_svc = (
            db_services[0]
            if db_services
            else (services[0] if services else None)
        )
        warning_svc = next(
            (s for s in services
             if s != critical_svc),
            None
        )

        for svc in services:
            # Deterministic pod name per service
            seed = int(
                hashlib.md5(
                    svc.encode()
                ).hexdigest()[:8],
                16
            )
            rng = random.Random(seed)
            chars = (
                "abcdefghijklmnopqrstuvwxyz"
                "0123456789"
            )
            suffix1 = "".join(
                rng.choices(chars, k=5)
            )
            suffix2 = "".join(
                rng.choices(chars, k=5)
            )
            pod_name = f"{svc}-{suffix1}-{suffix2}"

            if svc == critical_svc:
                result[svc] = {
                    "pod_name": pod_name,
                    "cpu_usage": "920m",
                    "cpu_limit": "1000m",
                    "cpu_percent": 92,
                    "memory_usage": "1.8Gi",
                    "memory_limit": "2Gi",
                    "memory_percent": 90,
                    "restarts": 5,
                    "status": "CrashLoopBackOff",
                    "age": "2d",
                    "namespace": "sre-demo"
                }
            elif svc == warning_svc:
                result[svc] = {
                    "pod_name": pod_name,
                    "cpu_usage": "450m",
                    "cpu_limit": "500m",
                    "cpu_percent": 90,
                    "memory_usage": "800Mi",
                    "memory_limit": "1Gi",
                    "memory_percent": 78,
                    "restarts": 2,
                    "status": "Running",
                    "age": "2d",
                    "namespace": "sre-demo"
                }
            else:
                result[svc] = {
                    "pod_name": pod_name,
                    "cpu_usage": "120m",
                    "cpu_limit": "500m",
                    "cpu_percent": 24,
                    "memory_usage": "210Mi",
                    "memory_limit": "512Mi",
                    "memory_percent": 41,
                    "restarts": 0,
                    "status": "Running",
                    "age": "2d",
                    "namespace": "sre-demo"
                }

        return result

    def get_critical_services(self, resources: dict) -> list[str]:
        """
        Identify services with critical resource issues.
        
        Args:
            resources: Dictionary with resource data per service
            
        Returns:
            List of service names that are critical
        """
        critical = []

        for service, data in resources.items():
            is_critical = False

            # Check resource thresholds
            if data.get("cpu_percent", 0) > 80:
                is_critical = True
            if data.get("memory_percent", 0) > 80:
                is_critical = True

            # Check restart count
            if data.get("restarts", 0) > 3:
                is_critical = True

            # Check pod status
            status = data.get("status", "")
            if status in ["CrashLoopBackOff", "OOMKilled", "Error"]:
                is_critical = True

            if is_critical:
                critical.append(service)

        return sorted(critical)

    def get_resource_summary(self, resources: dict) -> str:
        """
        Generate human-readable resource summary for LLM prompts.
        
        Args:
            resources: Dictionary with resource data per service
            
        Returns:
            Formatted string with resource details and warnings
        """
        lines = []

        # Sort services for consistent output
        for service in sorted(resources.keys()):
            data = resources[service]
            lines.append(f"[{service}]")

            # Pod name
            lines.append(f"  Pod: {data.get('pod_name', 'unknown')}")

            # CPU with critical/warning label
            cpu_percent = data.get("cpu_percent", 0)
            cpu_usage = data.get("cpu_usage", "unknown")
            cpu_limit = data.get("cpu_limit", "unknown")
            cpu_label = ""
            if cpu_percent > 80:
                cpu_label = " ← CRITICAL"
            elif cpu_percent >= 60:
                cpu_label = " ← WARNING"
            lines.append(f"  CPU: {cpu_usage} / {cpu_limit} ({cpu_percent}%){cpu_label}")

            # Memory with critical/warning label
            mem_percent = data.get("memory_percent", 0)
            mem_usage = data.get("memory_usage", "unknown")
            mem_limit = data.get("memory_limit", "unknown")
            mem_label = ""
            if mem_percent > 80:
                mem_label = " ← CRITICAL"
            elif mem_percent >= 60:
                mem_label = " ← WARNING"
            lines.append(f"  Memory: {mem_usage} / {mem_limit} ({mem_percent}%){mem_label}")

            # Restarts with high label
            restarts = data.get("restarts", 0)
            restart_label = ""
            if restarts > 3:
                restart_label = " ← HIGH"
            lines.append(f"  Restarts: {restarts}{restart_label}")

            # Status with critical label
            status = data.get("status", "unknown")
            status_label = ""
            if status in ["CrashLoopBackOff", "OOMKilled", "Error"]:
                status_label = " ← CRITICAL"
            lines.append(f"  Status: {status}{status_label}")
            lines.append("")

        return "\n".join(lines)

    def get_real_pod_metrics(self,
                              namespace: str = "default") -> dict:
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "top",
                    "pods",
                    "-n",
                    namespace,
                    "--no-headers",
                ],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            log.error(
                "kubectl not found. Install kubectl or set SOURCE_KUBERNETES=false"
            )
            return {}

        if result.returncode != 0:
            log.error(
                f"Failed to retrieve pod metrics: {result.stderr.strip()}"
            )
            return {}

        metrics = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            pod_name = parts[0]
            cpu_usage = parts[1]
            memory_usage = parts[2]

            cpu_percent = 0
            if cpu_usage.endswith("m"):
                try:
                    millicores = int(cpu_usage[:-1])
                    cpu_percent = millicores / 10
                except ValueError:
                    cpu_percent = 0
            else:
                try:
                    cpu_percent = int(cpu_usage) * 100
                except ValueError:
                    cpu_percent = 0

            memory_percent = 0
            if memory_usage.endswith("Mi"):
                try:
                    mem_mb = int(memory_usage[:-2])
                    memory_percent = (mem_mb / 512) * 100
                except ValueError:
                    memory_percent = 0
            elif memory_usage.endswith("Gi"):
                try:
                    mem_mb = float(memory_usage[:-2]) * 1024
                    memory_percent = (mem_mb / 2048) * 100
                except ValueError:
                    memory_percent = 0
            else:
                memory_percent = 0

            metrics[pod_name] = {
                "pod_name": pod_name,
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "cpu_percent": round(cpu_percent, 2),
                "memory_percent": round(memory_percent, 2),
            }

        return metrics

    def get_pod_status(self,
                       namespace: str = "default") -> dict:
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-n",
                    namespace,
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            log.error(
                "kubectl not found. Install kubectl or set SOURCE_KUBERNETES=false"
            )
            return {}

        if result.returncode != 0:
            log.error(f"Failed to retrieve pod status: {result.stderr.strip()}")
            return {}

        try:
            import json
            data = json.loads(result.stdout)
        except Exception as e:
            log.error(f"Failed to parse pods JSON: {e}")
            return {}

        status_map = {}
        for item in data.get("items", []):
            metadata = item.get("metadata", {})
            spec = item.get("spec", {})
            pod_status = item.get("status", {})

            pod_name = metadata.get("name")
            if not pod_name:
                continue

            status = pod_status.get("phase", "Unknown")
            restarts = 0
            for cs in pod_status.get("containerStatuses", []):
                restarts += cs.get("restartCount", 0)

                state = cs.get("state", {})
                if "waiting" in state and state["waiting"].get("reason") == "CrashLoopBackOff":
                    status = "CrashLoopBackOff"
                if "terminated" in state and state["terminated"].get("reason") == "OOMKilled":
                    status = "OOMKilled"

            cpu_limit = "0m"
            memory_limit = "0Mi"
            containers = spec.get("containers", [])
            if containers:
                limits = containers[0].get("resources", {}).get("limits", {})
                cpu_limit = limits.get("cpu", "0m")
                memory_limit = limits.get("memory", "0Mi")

            status_map[pod_name] = {
                "pod_name": pod_name,
                "status": status,
                "restarts": restarts,
                "cpu_limit": cpu_limit,
                "memory_limit": memory_limit,
            }

        return status_map

    def get_real_resources(self,
                           services: list[str],
                           namespace: str = "default") -> dict:
        metrics = self.get_real_pod_metrics(namespace)
        statuses = self.get_pod_status(namespace)

        result = {}
        for service in services:
            target_pod = None
            for pod_name in metrics.keys():
                if pod_name.startswith(service) or service in pod_name:
                    target_pod = pod_name
                    break
            if not target_pod:
                for pod_name in statuses.keys():
                    if pod_name.startswith(service) or service in pod_name:
                        target_pod = pod_name
                        break

            if target_pod:
                metric_data = metrics.get(target_pod, {})
                status_data = statuses.get(target_pod, {})
                result[service] = {
                    "pod_name": target_pod,
                    "cpu_usage": metric_data.get("cpu_usage", "0m"),
                    "cpu_limit": status_data.get("cpu_limit", "0m"),
                    "cpu_percent": metric_data.get("cpu_percent", 0),
                    "memory_usage": metric_data.get("memory_usage", "0Mi"),
                    "memory_limit": status_data.get("memory_limit", "0Mi"),
                    "memory_percent": metric_data.get("memory_percent", 0),
                    "restarts": status_data.get("restarts", 0),
                    "status": status_data.get("status", "Running"),
                    "namespace": namespace,
                }
            else:
                result[service] = {
                    "pod_name": f"{service}-unknown",
                    "cpu_usage": "0m",
                    "cpu_limit": "0m",
                    "cpu_percent": 0,
                    "memory_usage": "0Mi",
                    "memory_limit": "0Mi",
                    "memory_percent": 0,
                    "restarts": 0,
                    "status": "Running",
                    "namespace": namespace,
                }

        return result

    def get_resources(self,
                      services: list[str],
                      namespace: str = "default",
                      use_mock: bool = None) -> dict:
        from flags import USE_KUBERNETES

        if use_mock is True:
            active_mock = True
        elif use_mock is False:
            active_mock = False
        else:
            active_mock = not USE_KUBERNETES

        if active_mock:
            log.info("[dim]Resources: mock data[/]")
            return self.get_mock_resources(services)

        log.info(f"[dim]Resources: kubectl (namespace={namespace})[/]")

        real_data = self.get_real_resources(services, namespace)
        if not real_data:
            log.warn("kubectl data unavailable, falling back to mock")
            return self.get_mock_resources(services)

        return real_data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 5 HOOKS — leave these commented
# exactly as written, Task 23 will
# uncomment and implement them
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# def get_real_pod_metrics(self, namespace="default"):
#     """TASK 23: Replace mock with real kubectl top pods"""
#     import subprocess
#     result = subprocess.run(
#         ["kubectl", "top", "pods", "-n", namespace,
#          "--no-headers"],
#         capture_output=True, text=True
#     )
#     # parse output: pod-name  cpu  memory per line
#     # return dict keyed by pod name

# def get_pod_status(self, namespace="default"):
#     """TASK 23: Replace mock with real kubectl get pods"""
#     import subprocess
#     result = subprocess.run(
#         ["kubectl", "get", "pods", "-n", namespace,
#          "-o", "json"],
#         capture_output=True, text=True
#     )
#     # parse JSON: pod_name, phase, restartCount,
#     # resource requests and limits
#     # return dict keyed by pod name

# def get_pod_logs(self, pod_name, namespace="default",
#                  tail=100):
#     """TASK 23: Fetch live pod logs via kubectl"""
#     import subprocess
#     result = subprocess.run(
#         ["kubectl", "logs", pod_name,
#          "-n", namespace, f"--tail={tail}"],
#         capture_output=True, text=True
#     )
#     # return list of log lines


if __name__ == "__main__":
    from core.log_loader import LogLoader
    from core.log_processor import LogProcessor

    loader = LogLoader()
    processor = LogProcessor()
    collector = ResourceCollector()

    print("--- Test 1: Get mock resources ---")
    lines = loader.load("logs/test.log")
    entries = processor.process(lines)
    summary = processor.get_summary(entries)
    services = summary["services"]
    print(f"Services from log: {services}")

    resources = collector.get_mock_resources(services)
    print(f"Resource keys: {list(resources.keys())}")

    print("\n--- Test 2: Critical services ---")
    critical = collector.get_critical_services(resources)
    print(f"Critical services: {critical}")

    print("\n--- Test 3: Resource summary ---")
    summary_text = collector.get_resource_summary(resources)
    print(summary_text)

    print("--- Test 4: get_resources() entry point ---")
    result = collector.get_resources(services, use_mock=True)
    print(f"Returned {len(result)} services")

    print("\n--- Test 5: Unknown service fallback ---")
    unknown = collector.get_mock_resources(["unknown-service"])
    print(f"Unknown service data: {unknown}")

    print("\nTask 8 OK")
