import random
import sys
import os

# Allow imports to work when running this file directly
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ResourceCollector:
    """
    Collects pod resource consumption data from Kubernetes cluster.
    Phase 1 uses realistic mock data. Real kubectl implementation in Task 23.
    """

    # Mock data for services that appeared in the incident
    MOCK_DATA = {
        "database-service": {
            "pod_name": "database-service-7d9f8b-xkq2p",
            "cpu_usage": "920m",
            "cpu_limit": "1000m",
            "cpu_percent": 92,
            "memory_usage": "1.8Gi",
            "memory_limit": "2Gi",
            "memory_percent": 90,
            "restarts": 5,
            "status": "CrashLoopBackOff",
            "age": "2d",
            "namespace": "sre-demo",
        },
        "payment-service": {
            "pod_name": "payment-service-abc12-p9xq1",
            "cpu_usage": "450m",
            "cpu_limit": "500m",
            "cpu_percent": 90,
            "memory_usage": "800Mi",
            "memory_limit": "1Gi",
            "memory_percent": 78,
            "restarts": 2,
            "status": "Running",
            "age": "2d",
            "namespace": "sre-demo",
        },
        "api-gateway": {
            "pod_name": "api-gateway-6cf4d-m2np1",
            "cpu_usage": "120m",
            "cpu_limit": "500m",
            "cpu_percent": 24,
            "memory_usage": "210Mi",
            "memory_limit": "512Mi",
            "memory_percent": 41,
            "restarts": 0,
            "status": "Running",
            "age": "2d",
            "namespace": "sre-demo",
        },
        "auth-service": {
            "pod_name": "auth-service-9ba3e-xt7kp",
            "cpu_usage": "85m",
            "cpu_limit": "500m",
            "cpu_percent": 17,
            "memory_usage": "175Mi",
            "memory_limit": "512Mi",
            "memory_percent": 34,
            "restarts": 0,
            "status": "Running",
            "age": "2d",
            "namespace": "sre-demo",
        },
    }

    def get_mock_resources(self, services: list[str]) -> dict:
        """
        Returns realistic mock pod resource data per service.
        
        Args:
            services: List of service names to get data for
            
        Returns:
            Dictionary with resource data keyed by service name
        """
        result = {}

        for service in services:
            if service in self.MOCK_DATA:
                # Use predefined mock data
                result[service] = self.MOCK_DATA[service].copy()
            else:
                # Generate reasonable default healthy stats for unknown services
                cpu_percent = random.randint(10, 30)
                memory_percent = random.randint(20, 40)
                result[service] = {
                    "pod_name": f"{service}-{random.randint(1000, 9999)}-{random.choice('abcdefghijkmnpqrstuvwxyz')}{random.choice('abcdefghijkmnpqrstuvwxyz')}{random.choice('abcdefghijkmnpqrstuvwxyz')}{random.choice('abcdefghijkmnpqrstuvwxyz')}",
                    "cpu_usage": f"{cpu_percent * 5}m",
                    "cpu_limit": "500m",
                    "cpu_percent": cpu_percent,
                    "memory_usage": f"{memory_percent * 10}Mi",
                    "memory_limit": "512Mi",
                    "memory_percent": memory_percent,
                    "restarts": 0,
                    "status": "Running",
                    "age": "2d",
                    "namespace": "sre-demo",
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

    def get_resources(self, services: list[str], 
                      namespace: str = "default",
                      use_mock: bool = True) -> dict:
        """
        Main entry point to collect pod resources.
        
        Args:
            services: List of service names
            namespace: Kubernetes namespace (default: "default")
            use_mock: Use mock data (True) or kubectl (False)
            
        Returns:
            Dictionary with resource data per service
        """
        if use_mock:
            print("Using mock resource data (Phase 1)")
            return self.get_mock_resources(services)
        else:
            print("Note: kubectl integration not yet available (Task 23)")
            print("Falling back to mock resource data")
            return self.get_mock_resources(services)


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
