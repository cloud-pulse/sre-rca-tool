"""
core/kubectl_client.py
Unified kubectl subprocess wrapper for AI-SRE kubectl mode.
All kubectl interactions go through this module — no scattered subprocess calls elsewhere.
"""

import subprocess
import re
from typing import Optional
from core.logger import get_logger

log = get_logger("Kubectl client")


# ─────────────────────────────────────────────
# Internal helper
# ─────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run a kubectl command. Returns (success, output_or_error)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError:
        return False, "kubectl not found. Is it installed and in PATH?"
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────
# Pod discovery
# ─────────────────────────────────────────────

def get_pods(namespace: str, service_name: str) -> list[dict]:
    """
    Find pods for a service.
    Strategy 1: label selector app=<service_name>
    Strategy 2: name-based heuristic fallback
    Returns list of dicts: [{name, status, ready, restarts, age}]
    """
    # Strategy 1 — label selector
    ok, out = _run([
        "kubectl", "get", "pods",
        "-n", namespace,
        "--selector", f"app={service_name}",
        "--no-headers",
        "-o", "wide",
    ])
    if ok and out:
        return _parse_pod_lines(out)

    # Strategy 2 — name heuristic
    ok, out = _run([
        "kubectl", "get", "pods",
        "-n", namespace,
        "--no-headers",
    ])
    if ok and out:
        matched = [
            line for line in out.splitlines()
            if service_name.lower() in line.lower()
        ]
        if matched:
            return _parse_pod_lines("\n".join(matched))

    log.warn(f"No pods found for service '{service_name}' in namespace '{namespace}'")
    return []


def _parse_pod_lines(raw: str) -> list[dict]:
    pods = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        # NAME  READY  STATUS  RESTARTS  AGE ...
        ready_parts = parts[1].split("/") if "/" in parts[1] else [parts[1], parts[1]]
        pods.append({
            "name": parts[0],
            "ready": parts[1],
            "ready_count": int(ready_parts[0]),
            "ready_total": int(ready_parts[1]) if len(ready_parts) > 1 else 1,
            "status": parts[2],
            "restarts": _parse_restarts(parts[3]),
            "age": parts[4] if len(parts) > 4 else "unknown",
        })
    return pods


def _parse_restarts(val: str) -> int:
    # restarts can be "3" or "3 (2h ago)"
    try:
        return int(val.split()[0])
    except Exception:
        return 0


# ─────────────────────────────────────────────
# Pod events
# ─────────────────────────────────────────────

def get_pod_events(pod_name: str, namespace: str) -> str:
    """
    Fetch events for a specific pod.
    Returns formatted string ready to embed as evidence.
    """
    ok, out = _run([
        "kubectl", "get", "events",
        "-n", namespace,
        "--field-selector", f"involvedObject.name={pod_name}",
        "--sort-by=.lastTimestamp",
    ])
    if ok and out:
        return out
    # Fallback: kubectl describe (broader but always works)
    ok2, out2 = _run([
        "kubectl", "describe", "pod", pod_name,
        "-n", namespace,
    ])
    if ok2 and out2:
        # Extract just the Events section
        if "Events:" in out2:
            return out2[out2.index("Events:"):]
        return out2[-3000:]  # last 3000 chars as fallback
    return f"[No events found for pod {pod_name}]"


# ─────────────────────────────────────────────
# Pod logs
# ─────────────────────────────────────────────

def get_pod_logs(
    pod_name: str,
    namespace: str,
    container: Optional[str] = None,
    tail: int = 200,
    previous: bool = False,
) -> str:
    """
    Fetch container logs for a pod.
    Tries current logs first; if pod is in CrashLoop, also fetches --previous.
    Returns newline-delimited log string.
    """
    cmd = [
        "kubectl", "logs", pod_name,
        "-n", namespace,
        f"--tail={tail}",
        "--timestamps=true",
    ]
    if container:
        cmd += ["-c", container]
    if previous:
        cmd.append("--previous")

    ok, out = _run(cmd, timeout=60)
    if ok and out:
        return out

    # If current logs fail and not already trying previous, auto-retry with --previous
    if not previous:
        ok2, out2 = _run(cmd + ["--previous"], timeout=60)
        if ok2 and out2:
            return f"[PREVIOUS CONTAINER LOGS]\n{out2}"

    return f"[Could not retrieve logs for pod {pod_name}: {out}]"


def get_all_container_logs(pod_name: str, namespace: str, containers: list[str], tail: int = 200) -> dict[str, str]:
    """Fetch logs for every container in a pod. Returns {container_name: log_string}."""
    result = {}
    if not containers:
        result["default"] = get_pod_logs(pod_name, namespace, tail=tail)
    else:
        for c in containers:
            result[c] = get_pod_logs(pod_name, namespace, container=c, tail=tail)
    return result


# ─────────────────────────────────────────────
# Resource pressure
# ─────────────────────────────────────────────

def get_node_resources() -> list[dict]:
    """
    Returns CPU/memory usage per node.
    [{name, cpu, cpu_pct, memory, memory_pct}]
    """
    ok, out = _run(["kubectl", "top", "nodes", "--no-headers"])
    if not ok or not out:
        return [{"error": out}]
    nodes = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5:
            nodes.append({
                "name": parts[0],
                "cpu": parts[1],
                "cpu_pct": parts[2],
                "memory": parts[3],
                "memory_pct": parts[4],
            })
    return nodes


def get_cluster_resource_pressure(namespace: Optional[str] = None) -> list[dict]:
    """
    Returns top pods by resource usage.
    [{namespace, pod, cpu, memory}]
    """
    cmd = ["kubectl", "top", "pods", "--no-headers"]
    if namespace:
        cmd += ["-n", namespace]
    else:
        cmd.append("-A")

    ok, out = _run(cmd)
    if not ok or not out:
        return [{"error": out}]

    pods = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4:  # -A: NAMESPACE POD CPU MEM
            pods.append({"namespace": parts[0], "pod": parts[1], "cpu": parts[2], "memory": parts[3]})
        elif len(parts) == 3:  # scoped: POD CPU MEM
            pods.append({"namespace": namespace or "default", "pod": parts[0], "cpu": parts[1], "memory": parts[2]})
    return pods


# ─────────────────────────────────────────────
# Service / deployment discovery
# ─────────────────────────────────────────────

def get_deployment_list(namespace: str) -> list[str]:
    """Returns list of deployment names in a namespace."""
    ok, out = _run([
        "kubectl", "get", "deployments",
        "-n", namespace,
        "--no-headers",
    ])
    if not ok or not out:
        return []
    return [line.split()[0] for line in out.splitlines() if line.strip()]


def get_containers_for_pod(pod_name: str, namespace: str) -> list[str]:
    """Returns list of container names in a pod."""
    ok, out = _run([
        "kubectl", "get", "pod", pod_name,
        "-n", namespace,
        "-o", "jsonpath={.spec.containers[*].name}",
    ])
    if ok and out:
        return out.strip().split()
    return []


# ─────────────────────────────────────────────
# Quick health helpers
# ─────────────────────────────────────────────

def is_pod_healthy(pod: dict) -> bool:
    return pod.get("status") == "Running" and pod.get("ready_count", 0) == pod.get("ready_total", 1)


CRITICAL_STATUSES = {
    "CrashLoopBackOff", "OOMKilled", "Error",
    "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError",
    "Pending", "Evicted", "Terminating",
}

def classify_pod_status(pod: dict) -> str:
    """Returns 'healthy' | 'warning' | 'critical'"""
    status = pod.get("status", "")
    restarts = pod.get("restarts", 0)
    if status in CRITICAL_STATUSES:
        return "critical"
    if restarts >= 3:
        return "warning"
    if status == "Running":
        return "healthy"
    return "warning"


# Additional helpers appended by patch
def get_service_endpoints(service_name: str, namespace: str) -> str:
    """
    Fetch endpoints for a Kubernetes service.
    Shows whether the service has healthy backing pods.
    Returns formatted string for evidence.
    """
    ok, out = _run([
        "kubectl", "get", "endpoints", service_name,
        "-n", namespace,
    ])
    if ok and out:
        return out
    return f"[No endpoints found for service {service_name}]"


def get_virtual_service(service_name: str, namespace: str) -> str:
    """
    Fetch Istio VirtualService for a service.
    Gracefully returns empty string if Istio is not installed.
    """
    ok, out = _run([
        "kubectl", "get", "virtualservice", service_name,
        "-n", namespace,
        "-o", "yaml",
    ])
    if ok and out:
        return out
    # Not an error — Istio may not be installed
    return ""


def get_pod_node(pod_name: str, namespace: str) -> str:
    """
    Returns the node name that a pod is scheduled on.
    """
    ok, out = _run([
        "kubectl", "get", "pod", pod_name,
        "-n", namespace,
        "-o", "jsonpath={.spec.nodeName}",
    ])
    if ok and out:
        return out.strip()
    return ""


def get_node_describe(node_name: str) -> str:
    """
    Returns kubectl describe node output.
    Useful for detecting taints, conditions, pressure, allocatable resources.
    Truncated to last 3000 chars to keep evidence concise.
    """
    ok, out = _run([
        "kubectl", "describe", "node", node_name,
    ], timeout=30)
    if ok and out:
        # Focus on Conditions and Allocated resources sections
        sections = []
        if "Conditions:" in out:
            start = out.index("Conditions:")
            sections.append(out[start:start + 1500])
        if "Allocated resources:" in out:
            start = out.index("Allocated resources:")
            sections.append(out[start:start + 800])
        return "\n\n".join(sections) if sections else out[-3000:]
    return f"[Could not describe node {node_name}]"