# Kubernetes RCA — Per-Phase Agent Prompts

**Usage:** Paste one prompt at a time into your coding agent (Copilot / Blackbox / Antigravity).  
Each prompt is self-contained. The agent must read `docs/repo_analysis.md` first, then execute with no clarification questions.

---

## PROMPT — Phase 1: K8s Client, Models, Flags

```
You are implementing Phase 1 of a Kubernetes-aware RCA extension for an existing Python SRE tool.

FIRST: Read `docs/repo_analysis.md` to understand the current codebase. Do not ask questions. Execute directly.

TASK: Create three things.

─── 1. k8s/__init__.py ───────────────────────────────────────────
Create an empty `k8s/` package at the repo root with an `__init__.py` that exports nothing yet.

─── 2. k8s/models.py ────────────────────────────────────────────
Create dataclasses for all Kubernetes resource types. Use Python `dataclasses` with `field(default_factory=list)` for list fields.

Required dataclasses:
- K8sContainerState: name, state (str: running|waiting|terminated), state_reason (str), restart_count (int), ready (bool)
- K8sPod: name, namespace, node_name, image, restart_count, ready, phase (str: Pending|Running|Succeeded|Failed|Unknown), container_states (List[K8sContainerState]), events (List[K8sEvent]), logs (List[str]), previous_logs (List[str])
- K8sDeployment: name, namespace, replicas_desired, replicas_ready, replicas_updated, replicas_available, conditions (List[K8sCondition])
- K8sEvent: name, namespace, type (str: Normal|Warning), reason, message, first_timestamp, last_timestamp, count (int), involved_object (Dict)
- K8sCondition: type, status (str: True|False|Unknown), reason, message, last_transition_time
- K8sNode: name, ready (bool), cpu_capacity, memory_capacity, conditions (List[K8sCondition]), taints (List[str])
- K8sPVC: name, namespace, status (str: Bound|Pending|Lost), storage_class, capacity, access_modes (List[str])
- K8sResourceQuota: name, namespace, hard (Dict[str,str]), used (Dict[str,str])
- K8sNetworkPolicy: name, namespace, pod_selector (Dict), ingress_rules (List[Dict]), egress_rules (List[Dict])
- K8sConfigMap: name, namespace, keys (List[str])  ← key names only, not values
- K8sSecretMeta: name, namespace, type (str), keys (List[str])  ← key names only, NEVER values
- K8sClusterSnapshot: timestamp (str), namespaces (List[str]), pods, deployments, events, nodes, pvcs, quotas, network_policies, configmaps, secret_metadata
- K8sRCAFinding: service, namespace, status (str: Healthy|Degraded|Failed|Unknown), severity (str: Critical|High|Medium|Low|Info), root_cause (str), supporting_causes (List[str]), evidence (List[str]), recommendations (List[str]), affected_resources (List[str]), detected_at (str)

─── 3. k8s/client.py ────────────────────────────────────────────
Create `K8sClientManager` class. Install the `kubernetes` Python SDK if not already in requirements.txt.

Requirements:
- __init__(self, namespaces=None, kubeconfig_path=None, context=None)
  - Read kubeconfig from kubeconfig_path, else auto-detect (~/.kube/config)
  - Use context override if provided
  - On ANY exception during init: log a warning, set self._available = False, do NOT raise
- get_core_v1(self) → kubernetes.client.CoreV1Api
- get_apps_v1(self) → kubernetes.client.AppsV1Api
- get_networking_v1(self) → kubernetes.client.NetworkingV1Api
- is_available(self) → bool  ← returns self._available
- get_cluster_info(self) → dict  ← {context, kubeconfig_path, namespaces}
- All methods check is_available() and return None/empty if not available

─── 4. flags.py update ──────────────────────────────────────────
Append the following block to the END of flags.py. Do NOT modify any existing lines.

```python
# ── Kubernetes Mode ───────────────────────────────────────────────
ENABLE_KUBERNETES_MODE       = os.getenv("ENABLE_KUBERNETES_MODE",       "false").lower() == "true"
KUBE_CONFIG_PATH             = os.getenv("KUBECONFIG",                   None)
KUBE_CONTEXT                 = os.getenv("KUBE_CONTEXT",                 None)
KUBE_NAMESPACES              = os.getenv("KUBE_NAMESPACES",              "default").split(",")
K8S_COLLECT_PODS             = os.getenv("K8S_COLLECT_PODS",             "true").lower() == "true"
K8S_COLLECT_DEPLOYMENTS      = os.getenv("K8S_COLLECT_DEPLOYMENTS",      "true").lower() == "true"
K8S_COLLECT_EVENTS           = os.getenv("K8S_COLLECT_EVENTS",           "true").lower() == "true"
K8S_COLLECT_LOGS             = os.getenv("K8S_COLLECT_LOGS",             "true").lower() == "true"
K8S_COLLECT_NODES            = os.getenv("K8S_COLLECT_NODES",            "true").lower() == "true"
K8S_COLLECT_PVC              = os.getenv("K8S_COLLECT_PVC",              "true").lower() == "true"
K8S_COLLECT_QUOTAS           = os.getenv("K8S_COLLECT_QUOTAS",           "true").lower() == "true"
K8S_COLLECT_NETWORK_POLICIES = os.getenv("K8S_COLLECT_NETWORK_POLICIES", "true").lower() == "true"
K8S_COLLECT_CONFIGMAPS       = os.getenv("K8S_COLLECT_CONFIGMAPS",       "true").lower() == "true"
K8S_COLLECT_SECRETS_META     = os.getenv("K8S_COLLECT_SECRETS_META",     "true").lower() == "true"
K8S_RESTART_COUNT_THRESHOLD  = int(os.getenv("K8S_RESTART_COUNT_THRESHOLD", "5"))
K8S_FAILED_EVENT_THRESHOLD   = int(os.getenv("K8S_FAILED_EVENT_THRESHOLD",  "3"))
K8S_ENABLE_SIMULATION        = os.getenv("K8S_ENABLE_SIMULATION",        "false").lower() == "true"
```

DONE WHEN:
- `python -c "from k8s.client import K8sClientManager; m=K8sClientManager(); print(m.is_available())"` returns True with Minikube running
- Same command returns False (not an exception) with Minikube stopped
- `git diff flags.py` shows only appended lines, zero modifications to existing content
- All dataclasses importable: `from k8s.models import K8sClusterSnapshot, K8sRCAFinding`
```

---

## PROMPT — Phase 2: Unified Collector

```
You are implementing Phase 2 of a Kubernetes-aware RCA extension. Phase 1 (k8s/client.py, k8s/models.py, flags.py) is already complete.

FIRST: Read `docs/repo_analysis.md`. Do not ask questions. Execute directly.

TASK: Create `k8s/collector.py` and minimally modify `core/resource_collector.py`.

─── k8s/collector.py ────────────────────────────────────────────
Create class `K8sCollector` with the following methods. All methods use only GET/LIST operations — never POST, PATCH, or DELETE.

Every method must:
- Wrap SDK calls in try/except ApiException; return empty list on failure, never raise
- Apply a 30-second timeout to every SDK call (_request_timeout=30)
- Log a debug message before each SDK call and a warning on failure

Methods:
- collect_pods(ns: str) → List[K8sPod]
  Parse pod.status.container_statuses for container state, restart count, reason
  
- collect_deployments(ns: str) → List[K8sDeployment]

- collect_events(ns: str) → List[K8sEvent]
  Filter: only Warning type events, or Normal events with reason in [FailedScheduling, BackOff]

- collect_pod_logs(pod_name: str, ns: str, container: str = None, tail: int = 100) → List[str]
  Use read_namespaced_pod_log(); return [] if pod not found or logs not ready

- collect_previous_logs(pod_name: str, ns: str, container: str = None, tail: int = 100) → List[str]
  Use read_namespaced_pod_log(previous=True); return [] on any error

- collect_nodes() → List[K8sNode]
  Use list_node() (cluster-scoped, no namespace)

- collect_pvcs(ns: str) → List[K8sPVC]

- collect_resource_quotas(ns: str) → List[K8sResourceQuota]

- collect_network_policies(ns: str) → List[K8sNetworkPolicy]
  Use networking_v1 client

- collect_configmaps(ns: str) → List[K8sConfigMap]
  Only collect key names from cm.data.keys() — not values

- collect_secret_metadata(ns: str) → List[K8sSecretMeta]
  CRITICAL: Only access secret.metadata and list(secret.data.keys()) — NEVER access secret.data values or secret.string_data

- collect_all(namespaces: List[str]) → K8sClusterSnapshot
  Iterate all namespaces, call all above methods, merge results into one K8sClusterSnapshot
  Set snapshot.timestamp = datetime.utcnow().isoformat()

─── core/resource_collector.py modification ─────────────────────
Make the following MINIMAL changes only. Do not restructure existing code.

In __init__, APPEND after all existing init logic:
```python
self._k8s_collector = None
if ENABLE_KUBERNETES_MODE:
    from k8s.client import K8sClientManager
    from k8s.collector import K8sCollector
    _mgr = K8sClientManager(
        namespaces=KUBE_NAMESPACES,
        kubeconfig_path=KUBE_CONFIG_PATH,
        context=KUBE_CONTEXT
    )
    if _mgr.is_available():
        self._k8s_collector = K8sCollector(_mgr)
```

In collect() or equivalent main method, APPEND after existing file-based collection:
```python
if self._k8s_collector is not None:
    snapshot = self._k8s_collector.collect_all(KUBE_NAMESPACES)
    resources['k8s_snapshot'] = snapshot
```

DONE WHEN:
- With ENABLE_KUBERNETES_MODE=true and Minikube running sock-shop:
  `collect_all(['default'])` returns a K8sClusterSnapshot with len(pods) > 0
- With ENABLE_KUBERNETES_MODE=false: existing collect() returns exactly the same result as before this change
- No secret values (only key names) appear in any collected K8sSecretMeta object
- All methods return empty list (not exception) when called against a stopped cluster
```

---

## PROMPT — Phase 3: Service Mapping + Service Graph Updater

```
You are implementing Phase 3 of a Kubernetes-aware RCA extension. Phases 1–2 are complete.

FIRST: Read `docs/repo_analysis.md`. Do not ask questions. Execute directly.

TASK: Create k8s/service_mapper.py and k8s/graph_updater.py. Also update services.yaml schema.

─── k8s/service_mapper.py ───────────────────────────────────────
Create class K8sServiceMapper.

__init__(self, snapshot: K8sClusterSnapshot, services_yaml_path: str = "services.yaml")
  Load services.yaml into self._config

resolve(self, service_name: str) → dict | None
  Returns: {"deployment": str, "pods": List[K8sPod], "namespace": str} or None

Resolution order (strict — do not skip steps):
1. Check self._config[service_name].get("kubernetes", {}) for explicit deployment name and namespace
   If found: look up matching deployment and pods in snapshot
2. If step 1 fails: scan snapshot.deployments for name containing service_name (case-insensitive)
   Then find pods with matching app label
3. If step 2 fails: return None and log a warning

resolve_all(self) → Dict[str, dict]
  Call resolve() for every service in services.yaml; return dict of results

─── services.yaml update ────────────────────────────────────────
Add an optional `kubernetes:` section to each service in services.yaml.
Example:
  paymentservice:
    port: 8080
    dependencies: [cartservice]
    kubernetes:
      namespace: "default"
      deployment: "paymentservice"
      selector:
        app: "paymentservice"
      container_name: "server"
      expected_replicas: 1

This section is optional. Existing services without it continue to work.

─── k8s/graph_updater.py ────────────────────────────────────────
Create class K8sGraphUpdater.

__init__(self, service_graph, snapshot: K8sClusterSnapshot)
  self.service_graph = service_graph  (existing ServiceGraph object)
  self.snapshot = snapshot

compute_proposed_changes(self) → List[dict]
  Analyse snapshot to find:
  - New services discovered in cluster not yet in service_graph
  - New pod↔deployment relationships
  - Cross-namespace dependencies (pods in different namespaces calling each other via service DNS)
  Return list of change dicts: {"type": "add_service"|"add_dependency", "details": str}

prompt_and_apply(self) → bool
  1. Call compute_proposed_changes()
  2. If no changes: log "Service graph is up to date" and return True
  3. Print a Rich Table showing: Change Type | Details
  4. Print: "Apply these N changes to the service graph? [y/N]: "
  5. Read input from stdin
  6. If input.strip().lower() in ["y", "yes"]:
     - Apply each change to self.service_graph
     - Log "Service graph updated with N changes"
     - Return True
  7. Else:
     - Write proposed changes to logs/k8s_graph_proposals.log (append mode, with timestamp)
     - Log "Service graph update declined. Changes saved to logs/k8s_graph_proposals.log"
     - Return False

CRITICAL: There is NO bypass for the approval gate. Do not add any skip_prompt parameter or env var.

DONE WHEN:
- K8sServiceMapper resolves "paymentservice" from services.yaml kubernetes: section
- K8sServiceMapper falls back to cluster scan when kubernetes: section absent
- K8sServiceMapper returns None (not exception) for unknown service names
- K8sGraphUpdater shows Rich table and waits for input before applying changes
- Answering "n" leaves service_graph object identical to before the call and writes to logs/k8s_graph_proposals.log
```

---

## PROMPT — Phase 4: Event Analyzer + RCA Engine

```
You are implementing Phase 4 of a Kubernetes-aware RCA extension. Phases 1–3 are complete.

FIRST: Read `docs/repo_analysis.md`. Do not ask questions. Execute directly.

TASK: Create k8s/event_analyzer.py and k8s/rca_engine.py.

─── k8s/event_analyzer.py ───────────────────────────────────────
Create class K8sEventAnalyzer.

analyze(self, pod: K8sPod, deployment: K8sDeployment, events: List[K8sEvent],
        snapshot: K8sClusterSnapshot) → List[str]
  Returns a list of detected pattern names (strings from the list below).

Implement one private method per pattern. Each returns bool.

Patterns to detect (exact string names to return):
- "CrashLoopBackOff"   : any container_state.state_reason == "CrashLoopBackOff" OR restart_count > K8S_RESTART_COUNT_THRESHOLD
- "OOMKilled"          : any container_state.state_reason == "OOMKilled"
- "ImagePullBackOff"   : any container_state.state_reason in ["ImagePullBackOff", "ErrImagePull"]
- "FailedScheduling"   : any event.reason == "FailedScheduling"
- "ReadinessFailed"    : pod.ready == False AND pod.phase == "Running"
- "DependencyFailed"   : pod phase=Running but a pod whose name matches a known dependency is not ready (check snapshot.pods)
- "NodeNotReady"       : snapshot.nodes has any node where ready == False and pod.node_name matches
- "PVCUnbound"         : snapshot.pvcs has any pvc in pod's namespace where status != "Bound"
- "QuotaExceeded"      : snapshot.quotas has any quota where int(used[cpu or memory]) >= int(hard[cpu or memory])
- "NetworkPolicyBlock" : any event.reason == "NetworkNotReady" OR ("connection refused" in pod.logs and snapshot.network_policies is non-empty)
- "MissingConfigMap"   : any event.reason == "FailedMount" and "configmap" in event.message.lower()
- "MissingSecret"      : any event.reason == "FailedMount" and "secret" in event.message.lower()

classify_severity(self, patterns: List[str]) → str
  Critical: any of [CrashLoopBackOff, OOMKilled, FailedScheduling, NodeNotReady, QuotaExceeded]
  High:     any of [ImagePullBackOff, ReadinessFailed, PVCUnbound, DependencyFailed]
  Medium:   any of [NetworkPolicyBlock]
  Low:      any of [MissingConfigMap, MissingSecret]
  Info:     empty patterns list
  Return highest applicable severity.

─── k8s/rca_engine.py ───────────────────────────────────────────
Create class K8sRCAEngine. This is the SHARED engine used for both file-based and K8s RCA paths.

FAILURE_PATTERN_TO_ROOT_CAUSE = {
    "CrashLoopBackOff": "Application repeatedly crashing on startup",
    "OOMKilled":        "Container exceeded its memory limit",
    "ImagePullBackOff": "Container image could not be pulled from registry",
    "FailedScheduling": "Pod could not be scheduled — insufficient cluster resources",
    "ReadinessFailed":  "Application failed readiness probe — dependency or config issue",
    "DependencyFailed": "Upstream dependent service is unavailable",
    "NodeNotReady":     "Kubernetes node hosting this pod is unhealthy",
    "PVCUnbound":       "Required PersistentVolumeClaim is not bound to a volume",
    "QuotaExceeded":    "Namespace resource quota exceeded — pod cannot start",
    "NetworkPolicyBlock":"Network policy is blocking required traffic",
    "MissingConfigMap": "Referenced ConfigMap does not exist",
    "MissingSecret":    "Referenced Secret does not exist",
}

FAILURE_PATTERN_TO_RECOMMENDATIONS = {
    "CrashLoopBackOff": [
        "Check previous container logs: kubectl logs <pod> --previous",
        "Verify environment variables and mounted configs",
        "Check application startup dependencies (database, cache, other services)",
    ],
    "OOMKilled": [
        "Increase memory limit in deployment spec",
        "Profile application memory usage under production load",
        "Check for memory leaks in application code",
    ],
    "ImagePullBackOff": [
        "Verify image tag exists: docker manifest inspect <image>",
        "Check imagePullSecrets in deployment spec",
        "Verify network connectivity to image registry from cluster",
    ],
    "FailedScheduling": [
        "Check node resource availability: kubectl top nodes",
        "Review pod resource requests: kubectl describe pod <pod>",
        "Check for node taints and pod tolerations",
    ],
    "ReadinessFailed": [
        "Check readiness probe configuration and endpoint",
        "Verify dependency startup order and health",
        "Check service-to-service network connectivity",
    ],
    "DependencyFailed": [
        "Check health of upstream service pods",
        "Verify service DNS resolution between namespaces",
        "Check network policies between services",
    ],
    "NodeNotReady": [
        "Check node conditions: kubectl describe node <node>",
        "Check node system resources (disk, memory pressure)",
        "Consider draining and restarting the node",
    ],
    "PVCUnbound": [
        "Check PVC status: kubectl describe pvc <pvc>",
        "Verify StorageClass exists and has available provisioner",
        "Check cluster storage capacity",
    ],
    "QuotaExceeded": [
        "Check namespace quota usage: kubectl describe quota -n <ns>",
        "Request quota increase or reduce pod resource requests",
        "Clean up unused resources in namespace",
    ],
    "NetworkPolicyBlock": [
        "Review NetworkPolicy selectors for this service",
        "Test connectivity: kubectl exec <pod> -- curl <upstream>",
        "Check ingress/egress rules allow required traffic",
    ],
    "MissingConfigMap": [
        "Create the missing ConfigMap or correct its name in deployment spec",
        "Check: kubectl get configmaps -n <namespace>",
    ],
    "MissingSecret": [
        "Create the missing Secret or correct its name in deployment spec",
        "Check: kubectl get secrets -n <namespace>",
    ],
}

__init__(self, analyzer: K8sEventAnalyzer, mapper: K8sServiceMapper)

generate_rca(self, service_name: str, snapshot: K8sClusterSnapshot,
             log_context: str = None) → K8sRCAFinding
  1. Resolve service via self.mapper.resolve(service_name)
  2. If not found: return K8sRCAFinding with status="Unknown", root_cause="Service not found in cluster"
  3. Run self.analyzer.analyze(pod, deployment, events, snapshot)
  4. Determine primary root_cause from highest-priority pattern (use FAILURE_PATTERN_TO_ROOT_CAUSE)
  5. Remaining patterns → supporting_causes
  6. Build evidence list: restart counts, log tail (last 20 lines), previous log excerpt, event summaries
  7. If log_context provided: prepend "Log analysis: <log_context[:200]>" to evidence
  8. Collect recommendations from all detected patterns (deduplicated)
  9. severity = self.analyzer.classify_severity(patterns)
  10. status = "Failed" if severity in [Critical, High] else "Degraded" if severity == Medium else "Healthy"
  11. Return K8sRCAFinding with all fields populated

generate_rca_for_all(self, snapshot: K8sClusterSnapshot) → List[K8sRCAFinding]
  Call generate_rca for every service returned by self.mapper.resolve_all()

DONE WHEN:
- Unit test: K8sEventAnalyzer returns ["CrashLoopBackOff"] for a mocked pod with restart_count=10
- Unit test: K8sEventAnalyzer returns ["OOMKilled"] for a mocked pod with terminated.reason="OOMKilled"
- Unit test: classify_severity(["CrashLoopBackOff"]) returns "Critical"
- Unit test: classify_severity([]) returns "Info"
- Integration test against Minikube: generate_rca("paymentservice", snapshot) returns a K8sRCAFinding with non-empty root_cause, evidence, recommendations
- File-based RCA path still passes all existing tests (ENABLE_KUBERNETES_MODE=false)
```

---

## PROMPT — Phase 5: LLM Integration + Rich Output

```
You are implementing Phase 5 of a Kubernetes-aware RCA extension. Phases 1–4 are complete.

FIRST: Read `docs/repo_analysis.md`. Do not ask questions. Execute directly.

TASK: Update context_builder.py and rca_formatter.py. No other existing files need changes.

─── core/context_builder.py ─────────────────────────────────────
Find the AnalysisContext dataclass (or equivalent context object).

Add two new fields (do not modify existing fields):
  k8s_findings: List = field(default_factory=list)   # List[K8sRCAFinding]
  k8s_snapshot: object = None                         # K8sClusterSnapshot | None

In to_string() (or equivalent method that builds the LLM prompt context string):
Append this block AFTER all existing content:
```python
if self.k8s_findings:
    ctx += "\n\n## Kubernetes RCA Findings\n"
    for f in self.k8s_findings:
        ctx += (
            f"- **{f.service}** [{f.namespace}]: {f.status} | "
            f"Severity: {f.severity} | Root cause: {f.root_cause}\n"
        )
        if f.supporting_causes:
            for sc in f.supporting_causes:
                ctx += f"  Supporting: {sc}\n"
```

In the main pipeline (wherever AnalysisContext is populated):
If ENABLE_KUBERNETES_MODE and k8s_snapshot is available, call K8sRCAEngine.generate_rca_for_all(snapshot) and assign results to context.k8s_findings.

─── output/rca_formatter.py ─────────────────────────────────────
Add the following methods. Do NOT modify any existing methods.

1. print_k8s_rca(self, finding: K8sRCAFinding)
   Use Rich Panel. Colour scheme:
   - Critical: red border
   - High: yellow border
   - Medium: blue border
   - Low: green border
   - Info: white border
   Panel title: f"[bold]{finding.service}[/bold] — {finding.namespace}"
   Inside panel: severity, status, root_cause, supporting_causes (bulleted), evidence (bulleted), affected_resources, recommendations (numbered)

2. print_k8s_dashboard(self, findings: List[K8sRCAFinding])
   Use Rich Table with columns: Service | Namespace | Status | Severity | Root Cause
   Colour-code Severity column: Critical=red, High=yellow, Medium=blue, Low=green, Info=white
   Sort rows: Critical first, then High, Medium, Low, Info
   Print summary line after table: "N services analysed — X Critical, Y High, Z Medium"

3. export_k8s_rca_json(self, findings: List[K8sRCAFinding]) → str
   Return JSON string of all findings using dataclasses.asdict()
   Format: {"generated_at": iso_timestamp, "findings": [...]}

DONE WHEN:
- print_k8s_dashboard([...]) renders a Rich Table with correct severity colours when called in the shell
- context.to_string() contains "## Kubernetes RCA Findings" section when findings are present
- context.to_string() does NOT contain "## Kubernetes RCA Findings" when findings list is empty
- export_k8s_rca_json([...]) returns valid JSON parseable with json.loads()
- All existing rca_formatter methods still work unchanged
```

---

## PROMPT — Phase 6: Failure Simulation

```
You are implementing Phase 6 of a Kubernetes-aware RCA extension. Phases 1–5 are complete.

FIRST: Read `docs/repo_analysis.md`. Do not ask questions. Execute directly.

TASK: Create k8s/simulator.py. This module is for dissertation demo only.

CRITICAL SAFETY RULES (enforce in code, not just comments):
1. At module import time, check K8S_ENABLE_SIMULATION from flags.py. If False, raise ImportError("Simulation disabled. Set K8S_ENABLE_SIMULATION=true to enable.") — this prevents accidental import
2. Every public method must print a confirmation prompt and require the user to type "CONFIRM" (exact string, case-sensitive) before executing any mutating API call
3. Every mutating operation must save the original state to self._rollback_state[scenario_name] before mutating
4. All actions logged to logs/k8s_simulation_audit.log with timestamp, action, namespace, resource name

─── k8s/simulator.py ────────────────────────────────────────────
Class K8sSimulator:

__init__(self, client_manager: K8sClientManager)
  if not K8S_ENABLE_SIMULATION: raise ImportError(...)
  self._rollback_state = {}

_confirm(self, description: str) → bool
  Print:
    ⚠️  SIMULATION: {description}
    This will cause a real service disruption in your cluster.
    Type 'CONFIRM' to proceed or anything else to cancel:
  Read stdin. Return True only if input == "CONFIRM"

Scenarios (each follows: confirm → save state → mutate → log → return bool):

crash_loop(self, deployment_name: str, namespace: str = "default") → bool
  Confirm message: f"About to set {deployment_name} image to a nonexistent tag to trigger CrashLoopBackOff"
  Action: patch deployment image to "<current_image>-invalid-crash-loop-demo"
  Save original image to rollback state

oom_kill(self, deployment_name: str, namespace: str = "default") → bool
  Confirm message: f"About to set memory limit on {deployment_name} to 1Mi to trigger OOMKilled"
  Action: patch deployment containers[0].resources.limits.memory = "1Mi"
  Save original memory limit to rollback state

image_pull(self, deployment_name: str, namespace: str = "default") → bool
  Confirm message: f"About to set {deployment_name} image to nonexistent:demo-tag to trigger ImagePullBackOff"
  Action: patch deployment image to "nonexistent-demo-image:demo-tag-xyz"
  Save original image

node_pressure(self, node_name: str) → bool
  Confirm message: f"About to cordon node {node_name} to simulate FailedScheduling"
  Action: patch node spec.unschedulable = True
  Save: unschedulable = False

missing_config(self, deployment_name: str, configmap_name: str, namespace: str = "default") → bool
  Confirm message: f"About to delete ConfigMap {configmap_name} to trigger MissingConfigMap on {deployment_name}"
  Action: delete the configmap; save its full contents to rollback state

rollback(self, scenario_name: str) → bool
  Restore state saved in self._rollback_state[scenario_name]
  Log rollback action to audit log
  Supported: "crash_loop", "oom_kill", "image_pull", "node_pressure", "missing_config"
  Return False if scenario_name not in rollback state

DONE WHEN:
- `from k8s.simulator import K8sSimulator` raises ImportError when K8S_ENABLE_SIMULATION=false
- crash_loop() without typing "CONFIRM" makes zero API calls
- crash_loop() with "CONFIRM" causes the target deployment to enter CrashLoopBackOff within 60s on Minikube
- rollback("crash_loop") restores the original image and pod becomes Running again
- All 5 scenarios and their rollbacks work end-to-end on Minikube sock-shop
- logs/k8s_simulation_audit.log contains one entry per action with timestamp
```

---

## PROMPT — Phase 7: Shell + CLI Integration

```
You are implementing Phase 7 of a Kubernetes-aware RCA extension. Phases 1–6 are complete.

FIRST: Read `docs/repo_analysis.md`. Do not ask questions. Execute directly.

TASK: Create k8s/command_handler.py and make minimal additions to ai_sre.py and main.py.

─── k8s/command_handler.py ──────────────────────────────────────
Create class K8sCommandHandler.

__init__(self, client_manager, collector, rca_engine, formatter, simulator=None)

handle(self, args: List[str]) → None
  Route based on args[0]:
  - "status"      → handle_status()
  - "pods"        → handle_pods(args[1] if len(args)>1 else "default")
  - "deployments" → handle_deployments(args[1] if len(args)>1 else "default")
  - "events"      → handle_events(args[1] if len(args)>1 else "default")
  - "logs"        → handle_logs(pod=args[1], ns=args[2] if len(args)>2 else "default")
  - "rca"         → handle_rca(args[1] if len(args)>1 else "all")
  - "simulate"    → handle_simulate(args[1] if len(args)>1 else None)
  - "rollback"    → handle_rollback(args[1] if len(args)>1 else None)
  - else          → print help text listing all commands

handle_status(self):
  Collect snapshot for all KUBE_NAMESPACES
  Print Rich Table: Namespace | Pods (ready/total) | Deployments | Warning Events
  Print node summary: "N nodes, X ready"

handle_rca(self, service_or_all: str):
  If service_or_all == "all": call rca_engine.generate_rca_for_all(snapshot), then formatter.print_k8s_dashboard(findings)
  Else: call rca_engine.generate_rca(service_or_all, snapshot), then formatter.print_k8s_rca(finding)

handle_simulate(self, scenario: str):
  If self.simulator is None: print "Simulation disabled. Set K8S_ENABLE_SIMULATION=true."
  Else: call self.simulator.<scenario>()

─── ai_sre.py modification ──────────────────────────────────────
Find where shell commands are dispatched (execute() or handle_command() method).

Add this block (ONLY when ENABLE_KUBERNETES_MODE=true):
```python
if ENABLE_KUBERNETES_MODE and user_input.strip().startswith("/k8s"):
    args = user_input.strip().removeprefix("/k8s").strip().split()
    self._k8s_handler.handle(args)
    return
```

In SREShell.__init__(), initialise self._k8s_handler:
```python
if ENABLE_KUBERNETES_MODE:
    from k8s.client import K8sClientManager
    from k8s.collector import K8sCollector
    from k8s.event_analyzer import K8sEventAnalyzer
    from k8s.service_mapper import K8sServiceMapper
    from k8s.rca_engine import K8sRCAEngine
    from k8s.command_handler import K8sCommandHandler
    _mgr = K8sClientManager(KUBE_NAMESPACES, KUBE_CONFIG_PATH, KUBE_CONTEXT)
    _col = K8sCollector(_mgr)
    _ana = K8sEventAnalyzer()
    _snap = _col.collect_all(KUBE_NAMESPACES)
    _mapper = K8sServiceMapper(_snap)
    _engine = K8sRCAEngine(_ana, _mapper)
    _sim = None
    if K8S_ENABLE_SIMULATION:
        from k8s.simulator import K8sSimulator
        _sim = K8sSimulator(_mgr)
    self._k8s_handler = K8sCommandHandler(_mgr, _col, _engine, self.formatter, _sim)
```

If ENABLE_KUBERNETES_MODE=false and user types /k8s: print "K8s mode is disabled. Set ENABLE_KUBERNETES_MODE=true to enable." Do not error.

─── main.py modification ────────────────────────────────────────
Add a new click command group `k8s` with subcommands. Do NOT modify any existing commands.

```python
@cli.group()
def k8s():
    """Kubernetes RCA commands (requires ENABLE_KUBERNETES_MODE=true)"""
    if not ENABLE_KUBERNETES_MODE:
        click.echo("K8s mode is disabled. Set ENABLE_KUBERNETES_MODE=true to enable.")
        raise SystemExit(0)

@k8s.command("status")
def k8s_status():
    """Show cluster health summary"""
    # initialise handler, call handle_status()

@k8s.command("rca")
@click.argument("service", default="all")
def k8s_rca(service):
    """Generate RCA for a service or all services"""
    # initialise handler, call handle_rca(service)

@k8s.command("simulate")
@click.argument("scenario")
def k8s_simulate(scenario):
    """Inject a failure scenario (requires K8S_ENABLE_SIMULATION=true)"""

@k8s.command("rollback")
@click.argument("scenario")
def k8s_rollback(scenario):
    """Rollback an injected failure scenario"""
```

DONE WHEN:
- `/k8s status` in ai_sre.py shell prints a Rich table with cluster health
- `/k8s rca all` prints a Rich dashboard with findings for all resolved services
- `/k8s rca paymentservice` prints a Rich panel with that service's finding
- `python ai_sre.py k8s status` works from CLI
- `python ai_sre.py k8s rca paymentservice` works from CLI
- All pre-existing shell commands work exactly as before
- With ENABLE_KUBERNETES_MODE=false, `/k8s` prints the disabled message without crashing
```

---

## PROMPT — Phase 8: Tests + Validation

```
You are implementing Phase 8 of a Kubernetes-aware RCA extension. Phases 1–7 are complete.

FIRST: Read `docs/repo_analysis.md`. Do not ask questions. Execute directly.

TASK: Create test files and update the existing verify script.

─── tests/test_k8s_event_analyzer.py ────────────────────────────
Write unit tests using pytest and unittest.mock. Mock all K8s SDK calls.

Required test cases (use parametrize where applicable):
- test_crash_loop_by_state_reason: pod with container_state.state_reason="CrashLoopBackOff" → ["CrashLoopBackOff"]
- test_crash_loop_by_restart_count: pod with restart_count=10 (above threshold) → ["CrashLoopBackOff"]
- test_oom_killed: pod with state_reason="OOMKilled" → ["OOMKilled"]
- test_image_pull_backoff: pod with state_reason="ImagePullBackOff" → ["ImagePullBackOff"]
- test_failed_scheduling: event with reason="FailedScheduling" → ["FailedScheduling"]
- test_readiness_failed: pod ready=False, phase="Running" → ["ReadinessFailed"]
- test_pvc_unbound: snapshot with PVC status="Pending" → ["PVCUnbound"]
- test_quota_exceeded: snapshot with quota used=hard → ["QuotaExceeded"]
- test_missing_configmap: event reason="FailedMount", message contains "configmap" → ["MissingConfigMap"]
- test_healthy_pod: pod ready=True, restart_count=0, phase="Running" → []
- test_severity_critical: classify_severity(["CrashLoopBackOff"]) == "Critical"
- test_severity_high: classify_severity(["ReadinessFailed"]) == "High"
- test_severity_info: classify_severity([]) == "Info"
- test_severity_multiple_highest_wins: classify_severity(["MissingConfigMap", "OOMKilled"]) == "Critical"

─── tests/test_k8s_rca_engine.py ────────────────────────────────
Write unit tests. Mock K8sEventAnalyzer and K8sServiceMapper.

Required:
- test_rca_unknown_service: mapper.resolve returns None → K8sRCAFinding.status == "Unknown"
- test_rca_crash_loop: analyzer returns ["CrashLoopBackOff"] → finding.root_cause contains "crash" (case-insensitive), severity="Critical", len(recommendations) > 0
- test_rca_healthy: analyzer returns [] → finding.status == "Healthy"
- test_rca_with_log_context: log_context="timeout" → finding.evidence contains entry starting with "Log analysis:"
- test_generate_rca_for_all: 3 services → returns list of 3 K8sRCAFinding objects

─── tests/test_k8s_backwards_compat.py ──────────────────────────
Verify zero regressions in file-based mode.

- Set ENABLE_KUBERNETES_MODE=false in environment
- Import and instantiate ResourceCollector; call collect()
- Assert result does NOT contain key "k8s_snapshot"
- Run the existing main pipeline test (import test from existing test suite) and assert it passes

─── scripts/verify_final.sh update ─────────────────────────────
Add these functions at the END of verify_final.sh. Do not modify existing functions.

test_k8s_mode_disabled():
  ENABLE_KUBERNETES_MODE=false python ai_sre.py analyze logs/test.log 2>&1 | grep -v "k8s" && echo "PASS" || echo "FAIL"

test_k8s_client_available():
  python -c "from k8s.client import K8sClientManager; m=K8sClientManager(); print('PASS' if m.is_available() else 'FAIL (Minikube not running?)')"

test_k8s_collect_all():
  ENABLE_KUBERNETES_MODE=true python -c "
from k8s.client import K8sClientManager
from k8s.collector import K8sCollector
m = K8sClientManager()
c = K8sCollector(m)
snap = c.collect_all(['default'])
print('PASS' if len(snap.pods) > 0 else 'FAIL (no pods found)')
"

test_k8s_rca_paymentservice():
  ENABLE_KUBERNETES_MODE=true python -c "
from k8s.client import K8sClientManager; from k8s.collector import K8sCollector
from k8s.event_analyzer import K8sEventAnalyzer; from k8s.service_mapper import K8sServiceMapper
from k8s.rca_engine import K8sRCAEngine
m = K8sClientManager(); c = K8sCollector(m); snap = c.collect_all(['default'])
a = K8sEventAnalyzer(); mp = K8sServiceMapper(snap); e = K8sRCAEngine(a, mp)
f = e.generate_rca('paymentservice', snap)
assert f.root_cause, 'root_cause is empty'
assert f.recommendations, 'recommendations is empty'
print('PASS')
"

test_k8s_no_secret_values():
  ENABLE_KUBERNETES_MODE=true python -c "
from k8s.client import K8sClientManager; from k8s.collector import K8sCollector
m = K8sClientManager(); c = K8sCollector(m); snap = c.collect_all(['default'])
for s in snap.secret_metadata:
    assert not hasattr(s, 'data'), 'Secret data exposed!'
print('PASS — no secret values in snapshot')
"

DONE WHEN:
- pytest tests/test_k8s_event_analyzer.py -v: all tests pass
- pytest tests/test_k8s_rca_engine.py -v: all tests pass
- pytest tests/test_k8s_backwards_compat.py -v: all tests pass
- bash scripts/verify_final.sh: all new test functions print PASS (or FAIL with clear message if Minikube not running)
- Existing test suite (all tests excluding new k8s tests) passes with ENABLE_KUBERNETES_MODE=false
```

---

## PROMPT — Phase 9: Documentation

```
You are implementing Phase 9 (final phase) of a Kubernetes-aware RCA extension. Phases 1–8 are complete.

FIRST: Read `docs/repo_analysis.md`. Do not ask questions. Execute directly.

TASK: Create docs/kubernetes_guide.md and update README.md and docs/developer_guide.md.

─── docs/kubernetes_guide.md (NEW) ──────────────────────────────
Write a practical guide with these sections:

1. Prerequisites
   - Python 3.12, virtualenv jarvis active
   - Minikube installed and running (minikube start)
   - kubectl configured (kubectl get pods should work)
   - kubernetes Python package installed (pip install kubernetes)

2. Configuration
   Table of all new environment variables with their default values and descriptions
   (ENABLE_KUBERNETES_MODE, KUBE_NAMESPACES, KUBE_CONTEXT, all K8S_COLLECT_*, K8S_ENABLE_SIMULATION)

3. Quickstart
   Step-by-step: start Minikube → deploy sock-shop → set env vars → run /k8s status → run /k8s rca all

4. Demo Walkthrough (5 simulation scenarios)
   For each scenario: setup command → simulate command → observe RCA → rollback command
   Scenarios: crash_loop, oom_kill, image_pull, node_pressure, missing_config

5. Multi-namespace Support
   How to set KUBE_NAMESPACES="default,sock-shop,monitoring"

6. Troubleshooting
   - K8s client not available: check minikube status, kubectl config current-context
   - Empty snapshot: check KUBE_NAMESPACES matches where pods are running
   - Service not resolved: add kubernetes: section to services.yaml
   - Simulation not available: set K8S_ENABLE_SIMULATION=true

─── README.md update ────────────────────────────────────────────
Add a new section "## Kubernetes Mode" BEFORE the existing "## Configuration" section.

Content:
- One-paragraph description of what K8s mode adds
- Prerequisites (Minikube, kubernetes package)
- Quick enable: `ENABLE_KUBERNETES_MODE=true python ai_sre.py`
- New commands table (both shell /k8s and CLI k8s subcommands)
- Link to docs/kubernetes_guide.md

─── docs/developer_guide.md update ─────────────────────────────
Add section "## Kubernetes Layer Architecture" with:
- ASCII diagram showing: k8s/client.py → k8s/collector.py → k8s/event_analyzer.py + k8s/rca_engine.py → rca_formatter.py
- Module responsibilities table (one row per file in k8s/)
- How to add a new failure pattern detector (step-by-step: add to event_analyzer.py, add to FAILURE_PATTERN_TO_ROOT_CAUSE and FAILURE_PATTERN_TO_RECOMMENDATIONS in rca_engine.py)
- How to add a new simulation scenario (step-by-step)

DONE WHEN:
- docs/kubernetes_guide.md exists and covers all 6 sections
- README.md has ## Kubernetes Mode section with commands table
- docs/developer_guide.md has K8s architecture section with correct module list
- All internal links in docs resolve correctly (no broken anchors)
```