# Kubernetes-Aware RCA Implementation Plan (Revised)

**Project:** AI-Assisted SRE Root Cause Analysis Framework  
**Objective:** Add Kubernetes-native observability and RCA support without breaking existing functionality  
**Scope:** Optional, flag-driven extension to existing local RCA pipeline  
**Date:** May 10, 2026  
**Revision:** v2.0 — incorporates all design decisions from pre-planning Q&A

---

## 0. Design Decisions (Locked)

| Decision | Choice |
|---|---|
| Kubernetes client | Official `kubernetes` Python SDK (auto-detect kubeconfig); no subprocess kubectl calls |
| File organisation | All new K8s code under `k8s/` folder at repo root |
| Existing files modified | `flags.py`, `resource_collector.py`, `context_builder.py`, `rca_formatter.py`, `ai_sre.py`, `main.py` |
| Existing files untouched | `log_loader.py`, `log_processor.py`, `llm_analyzer.py`, `rag_engine.py`, `service_graph.py` |
| Kubernetes environment | Minikube (local); kubeconfig auto-loaded from `~/.kube/config` |
| Namespace scope | Default namespace for MVP; multi-namespace ready via env var list |
| Service-to-K8s mapping | `services.yaml` first; auto-discover from cluster as fallback |
| Service graph updates | Always prompt user for approval before applying any topology change |
| LLM integration | Dual path — standalone Rich report AND findings injected into LLM context |
| Cluster health depth | Full: pods, deployments, events, nodes, PVCs, quotas, network policies, configmaps, secrets |
| Failure simulation | In scope (Phase 6) — needed for dissertation demo |
| Output formatting | Rich for interactive shell (`ai_sre.py`); plain structured text for CLI (`main.py`) |
| Read-only enforcement | All K8s API calls are GET only, except Phase 6 simulation (requires explicit flag `K8S_ENABLE_SIMULATION=true`) |

---

## 1. Repository Structure After Implementation

```
sre-rca-tool/
├── k8s/                          ← NEW: all Kubernetes logic lives here
│   ├── __init__.py
│   ├── client.py                 ← K8s SDK client manager + kubeconfig handling
│   ├── models.py                 ← Dataclasses: K8sPod, K8sEvent, K8sRCAFinding, etc.
│   ├── collector.py              ← Unified collector: pods, deployments, events, logs,
│   │                                nodes, PVCs, quotas, network policies, configmaps, secrets
│   ├── event_analyzer.py         ← Failure pattern detection + severity classification
│   ├── rca_engine.py             ← RCA generation from K8s findings; same engine for both
│   │                                file-based and K8s paths (flag-switched, not separate)
│   ├── service_mapper.py         ← services.yaml-first mapping + cluster auto-discovery fallback
│   ├── graph_updater.py          ← Updates service_graph.py with K8s topology; user-approval gate
│   ├── simulator.py              ← Failure injection for demo (requires K8S_ENABLE_SIMULATION=true)
│   └── command_handler.py        ← Routes /k8s shell commands and CLI k8s subcommands
│
├── core/                         ← Existing; minimal additions only
│   ├── resource_collector.py     ← MODIFIED: conditionally calls k8s/collector.py
│   └── context_builder.py        ← MODIFIED: adds k8s_findings to AnalysisContext
│
├── output/
│   └── rca_formatter.py          ← MODIFIED: adds print_k8s_rca(), print_k8s_dashboard()
│
├── flags.py                      ← MODIFIED: new K8s flags added, no existing flags changed
├── ai_sre.py                     ← MODIFIED: routes /k8s commands to K8sCommandHandler
├── main.py                       ← MODIFIED: adds k8s CLI command group
└── services.yaml                 ← MODIFIED: optional kubernetes: section per service
```

**Key principle:** The same `k8s/rca_engine.py` handles RCA generation for both file-based and K8s paths. There is no separate "K8s RCA engine" — the flag `ENABLE_KUBERNETES_MODE` switches the data source; the reasoning logic is shared.

---

## 2. Flag Changes (`flags.py`)

Add the following block. Do not modify any existing flags.

```python
# ── Kubernetes Mode ────────────────────────────────────────────────
ENABLE_KUBERNETES_MODE = os.getenv("ENABLE_KUBERNETES_MODE", "false").lower() == "true"

# Connection
KUBE_CONFIG_PATH   = os.getenv("KUBECONFIG", None)           # None = auto ~/.kube/config
KUBE_CONTEXT       = os.getenv("KUBE_CONTEXT", None)          # None = current context
KUBE_NAMESPACES    = os.getenv("KUBE_NAMESPACES", "default").split(",")
                                                               # comma-separated for multi-ns
# Collection toggles
K8S_COLLECT_PODS            = os.getenv("K8S_COLLECT_PODS",            "true").lower() == "true"
K8S_COLLECT_DEPLOYMENTS     = os.getenv("K8S_COLLECT_DEPLOYMENTS",     "true").lower() == "true"
K8S_COLLECT_EVENTS          = os.getenv("K8S_COLLECT_EVENTS",          "true").lower() == "true"
K8S_COLLECT_LOGS            = os.getenv("K8S_COLLECT_LOGS",            "true").lower() == "true"
K8S_COLLECT_NODES           = os.getenv("K8S_COLLECT_NODES",           "true").lower() == "true"
K8S_COLLECT_PVC             = os.getenv("K8S_COLLECT_PVC",             "true").lower() == "true"
K8S_COLLECT_QUOTAS          = os.getenv("K8S_COLLECT_QUOTAS",          "true").lower() == "true"
K8S_COLLECT_NETWORK_POLICIES= os.getenv("K8S_COLLECT_NETWORK_POLICIES","true").lower() == "true"
K8S_COLLECT_CONFIGMAPS      = os.getenv("K8S_COLLECT_CONFIGMAPS",      "true").lower() == "true"
K8S_COLLECT_SECRETS_META    = os.getenv("K8S_COLLECT_SECRETS_META",    "true").lower() == "true"
                                                               # metadata only, never values

# RCA thresholds
K8S_RESTART_COUNT_THRESHOLD = int(os.getenv("K8S_RESTART_COUNT_THRESHOLD", "5"))
K8S_FAILED_EVENT_THRESHOLD  = int(os.getenv("K8S_FAILED_EVENT_THRESHOLD",  "3"))

# Simulation (demo only)
K8S_ENABLE_SIMULATION = os.getenv("K8S_ENABLE_SIMULATION", "false").lower() == "true"
```

---

## 3. Data Models (`k8s/models.py`)

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict

@dataclass
class K8sContainerState:
    name: str
    state: str                   # running | waiting | terminated
    state_reason: str            # CrashLoopBackOff | OOMKilled | ImagePullBackOff | ""
    restart_count: int
    ready: bool

@dataclass
class K8sPod:
    name: str
    namespace: str
    node_name: str
    image: str
    restart_count: int
    ready: bool
    phase: str                   # Pending | Running | Succeeded | Failed | Unknown
    container_states: List[K8sContainerState] = field(default_factory=list)
    events: List['K8sEvent'] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    previous_logs: List[str] = field(default_factory=list)

@dataclass
class K8sDeployment:
    name: str
    namespace: str
    replicas_desired: int
    replicas_ready: int
    replicas_updated: int
    replicas_available: int
    conditions: List['K8sCondition'] = field(default_factory=list)

@dataclass
class K8sEvent:
    name: str
    namespace: str
    type: str                    # Normal | Warning
    reason: str
    message: str
    first_timestamp: str
    last_timestamp: str
    count: int
    involved_object: Dict

@dataclass
class K8sCondition:
    type: str
    status: str                  # True | False | Unknown
    reason: str
    message: str
    last_transition_time: str

@dataclass
class K8sNode:
    name: str
    ready: bool
    cpu_capacity: str
    memory_capacity: str
    conditions: List[K8sCondition] = field(default_factory=list)
    taints: List[str] = field(default_factory=list)

@dataclass
class K8sPVC:
    name: str
    namespace: str
    status: str                  # Bound | Pending | Lost
    storage_class: str
    capacity: str
    access_modes: List[str] = field(default_factory=list)

@dataclass
class K8sResourceQuota:
    name: str
    namespace: str
    hard: Dict[str, str] = field(default_factory=dict)
    used: Dict[str, str] = field(default_factory=dict)

@dataclass
class K8sNetworkPolicy:
    name: str
    namespace: str
    pod_selector: Dict
    ingress_rules: List[Dict] = field(default_factory=list)
    egress_rules: List[Dict] = field(default_factory=list)

@dataclass
class K8sConfigMap:
    name: str
    namespace: str
    keys: List[str] = field(default_factory=list)   # key names only, not values

@dataclass
class K8sSecretMeta:
    name: str
    namespace: str
    type: str
    keys: List[str] = field(default_factory=list)   # key names only, NEVER values

@dataclass
class K8sClusterSnapshot:
    """Full cluster state at a point in time"""
    timestamp: str
    namespaces: List[str]
    pods: List[K8sPod]
    deployments: List[K8sDeployment]
    events: List[K8sEvent]
    nodes: List[K8sNode]
    pvcs: List[K8sPVC]
    quotas: List[K8sResourceQuota]
    network_policies: List[K8sNetworkPolicy]
    configmaps: List[K8sConfigMap]
    secret_metadata: List[K8sSecretMeta]

@dataclass
class K8sRCAFinding:
    service: str
    namespace: str
    status: str                  # Healthy | Degraded | Failed | Unknown
    severity: str                # Critical | High | Medium | Low | Info
    root_cause: str
    supporting_causes: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    affected_resources: List[str] = field(default_factory=list)
    detected_at: str = ""
```

---

## 4. Implementation Phases

### Phase 1 — Kubernetes Client Foundation
**Files:** `k8s/__init__.py`, `k8s/client.py`, `k8s/models.py`, updated `flags.py`

**`k8s/client.py` — K8sClientManager**

- Singleton-pattern; initialised once per process
- Auto-loads kubeconfig from `KUBECONFIG` env or `~/.kube/config`
- Respects `KUBE_CONTEXT` override (e.g. `"minikube"`)
- Exposes: `get_core_v1()`, `get_apps_v1()`, `get_networking_v1()`, `is_available() → bool`, `get_namespaces() → List[str]`, `get_cluster_info() → dict`
- On `ConfigException` or connection failure: logs a warning, sets `_available = False`; never raises to caller
- All callers check `is_available()` before proceeding

**DONE WHEN:**
- `python -c "from k8s.client import K8sClientManager; m=K8sClientManager(); print(m.is_available())"` returns `True` against running Minikube
- Same command returns `False` (not an exception) when Minikube is stopped
- `flags.py` diff shows only additions, zero modifications to existing lines

---

### Phase 2 — Unified Collector (`k8s/collector.py`)

**`K8sCollector` — single class, all resource types**

The collector is the only place that calls the Kubernetes SDK. All other modules receive plain dataclass objects (from `k8s/models.py`).

**Methods:**

| Method | Returns | SDK call |
|---|---|---|
| `collect_pods(ns)` | `List[K8sPod]` | `list_namespaced_pod` |
| `collect_deployments(ns)` | `List[K8sDeployment]` | `list_namespaced_deployment` |
| `collect_events(ns)` | `List[K8sEvent]` | `list_namespaced_event` |
| `collect_pod_logs(pod, ns, tail=100)` | `List[str]` | `read_namespaced_pod_log` |
| `collect_previous_logs(pod, ns, tail=100)` | `List[str]` | `read_namespaced_pod_log(previous=True)` |
| `collect_nodes()` | `List[K8sNode]` | `list_node` |
| `collect_pvcs(ns)` | `List[K8sPVC]` | `list_namespaced_persistent_volume_claim` |
| `collect_resource_quotas(ns)` | `List[K8sResourceQuota]` | `list_namespaced_resource_quota` |
| `collect_network_policies(ns)` | `List[K8sNetworkPolicy]` | `list_namespaced_network_policy` |
| `collect_configmaps(ns)` | `List[K8sConfigMap]` | `list_namespaced_config_map` |
| `collect_secret_metadata(ns)` | `List[K8sSecretMeta]` | `list_namespaced_secret` — keys only |
| `collect_all(namespaces)` | `K8sClusterSnapshot` | calls all above per namespace |

**Rules:**
- Every method wraps its SDK call in try/except `ApiException`; returns empty list on failure
- Timeout on every API call: 30 seconds
- Secrets: collect only `.metadata` and key names — never `.data` or `.stringData`
- `collect_all()` iterates `KUBE_NAMESPACES` and merges results into one `K8sClusterSnapshot`

**Integration into existing `core/resource_collector.py`:**

```python
# In ResourceCollector.__init__():
if ENABLE_KUBERNETES_MODE:
    from k8s.client import K8sClientManager
    from k8s.collector import K8sCollector
    self._k8s_client = K8sClientManager(...)
    if self._k8s_client.is_available():
        self._k8s_collector = K8sCollector(self._k8s_client)

# In ResourceCollector.collect():
resources = self._collect_from_files()          # unchanged
if ENABLE_KUBERNETES_MODE and hasattr(self, '_k8s_collector'):
    snapshot = self._k8s_collector.collect_all(KUBE_NAMESPACES)
    resources['k8s_snapshot'] = snapshot        # merged, not replaced
return resources
```

**DONE WHEN:**
- `collect_all()` returns a populated `K8sClusterSnapshot` against Minikube with sock-shop running
- File-based collection still works unchanged when `ENABLE_KUBERNETES_MODE=false`
- No secrets values ever appear in logs or returned objects

---

### Phase 3 — Service Mapping + Service Graph Updates

**`k8s/service_mapper.py` — K8sServiceMapper**

Maps logical service names (e.g. `"paymentservice"`) to Kubernetes resources.

**Resolution order:**
1. Check `services.yaml` for `kubernetes.deployment` and `kubernetes.selector` fields
2. If not found: scan cluster for deployment/pod whose name or labels contain the service name (fuzzy match)
3. If still not found: return `None` with a warning

**`services.yaml` extension (optional per service):**
```yaml
services:
  paymentservice:
    port: 8080
    dependencies: [cartservice]
    kubernetes:
      namespace: "default"
      deployment: "paymentservice"
      selector: {app: "paymentservice"}
      container_name: "server"
      expected_replicas: 1
```

**`k8s/graph_updater.py` — K8sGraphUpdater**

Enriches the existing `service_graph.py` object with K8s topology data (pod↔deployment relationships, cross-namespace dependencies).

**User approval gate (non-negotiable):**

Before applying any change to the service graph, the updater must:
1. Print a Rich table showing: current graph state vs proposed changes
2. Ask: `"Apply these N changes to the service graph? [y/N]"`
3. Only proceed if user types `y` or `yes` (case-insensitive)
4. If declined: log the proposed changes to a file for review; continue without applying

This applies to every run, including automated/pipeline runs — there is no bypass flag.

**DONE WHEN:**
- Service mapper resolves `paymentservice` correctly from both `services.yaml` and auto-discovery
- Graph updater shows diff and waits for `y/N` before modifying graph
- Declining the prompt leaves the graph unchanged and writes proposed changes to `logs/k8s_graph_proposals.log`

---

### Phase 4 — Event Analysis + RCA Engine

**`k8s/event_analyzer.py` — K8sEventAnalyzer**

Detects failure patterns from `K8sPod`, `K8sDeployment`, `K8sEvent`, and cluster-level resources.

**Failure pattern detectors:**

| Pattern | Detection logic |
|---|---|
| `CrashLoopBackOff` | `container_state.waiting.reason == "CrashLoopBackOff"` OR `restart_count > K8S_RESTART_COUNT_THRESHOLD` |
| `OOMKilled` | `container_state.terminated.reason == "OOMKilled"` |
| `ImagePullBackOff` | `container_state.waiting.reason in ["ImagePullBackOff", "ErrImagePull"]` |
| `FailedScheduling` | Event with `reason == "FailedScheduling"` |
| `ReadinessFailed` | Pod `ready=False` AND `phase=Running` |
| `DependencyFailed` | Pod running but upstream service pod is not ready (via service graph) |
| `NodeNotReady` | `K8sNode.ready == False` |
| `PVCUnbound` | `K8sPVC.status != "Bound"` |
| `QuotaExceeded` | Any quota `used >= hard` for CPU or memory |
| `NetworkPolicyBlock` | Event `reason == "NetworkNotReady"` OR log keyword `connection refused` correlating with a network policy present |
| `MissingConfigMap` | Event `reason == "FailedMount"` referencing a configmap |
| `MissingSecret` | Event `reason == "FailedMount"` referencing a secret |

**Severity classification:**

| Severity | Conditions |
|---|---|
| Critical | CrashLoopBackOff, OOMKilled, FailedScheduling, NodeNotReady, QuotaExceeded |
| High | ImagePullBackOff, ReadinessFailed, PVCUnbound, DependencyFailed |
| Medium | RestartSpike (below threshold), NetworkPolicyBlock |
| Low | MissingConfigMap, MissingSecret (pod running but degraded) |
| Info | Normal pod lifecycle events |

**`k8s/rca_engine.py` — K8sRCAEngine**

This is the same RCA reasoning engine used by both the file-based and K8s paths. When `ENABLE_KUBERNETES_MODE=true`, it receives a `K8sClusterSnapshot` in addition to log-based context.

**`generate_rca(service_name, snapshot, log_context=None) → K8sRCAFinding`:**
1. Resolve service → pod/deployment via `K8sServiceMapper`
2. Run `K8sEventAnalyzer` on resolved resources
3. Correlate K8s findings with log-based analysis if `log_context` provided
4. Map failure patterns → root causes using `FAILURE_PATTERN_TO_ROOT_CAUSE` table
5. Collect evidence: restart counts, log tail (20 lines), previous logs, event list, resource usage vs limits
6. Generate recommendations from `FAILURE_PATTERN_TO_RECOMMENDATIONS` table
7. Return `K8sRCAFinding`

**`generate_rca_for_all(snapshot) → List[K8sRCAFinding]`:** iterates all services in the snapshot.

**DONE WHEN:**
- Analyzer detects all 12 patterns from mocked pod/event objects (unit tests)
- RCA engine produces a finding with non-empty `root_cause`, `evidence`, and `recommendations` for a CrashLoopBackOff pod in Minikube
- File-based RCA path still works unchanged

---

### Phase 5 — LLM Integration + Output

**`core/context_builder.py` changes:**

```python
@dataclass
class AnalysisContext:
    # existing fields unchanged
    services: dict
    service_graph: object
    incidents: list
    # NEW
    k8s_findings: list = field(default_factory=list)   # List[K8sRCAFinding]
    k8s_snapshot: object = None                         # K8sClusterSnapshot

    def to_string(self):
        ctx = "... existing context ..."
        if self.k8s_findings:
            ctx += "\n\n## Kubernetes RCA Findings\n"
            for f in self.k8s_findings:
                ctx += (
                    f"- **{f.service}** [{f.namespace}]: {f.status} | "
                    f"Severity: {f.severity} | Root cause: {f.root_cause}\n"
                )
        return ctx
```

K8s findings are injected into the LLM prompt context so `llm_analyzer.py` can correlate them with log-based analysis. No changes to `llm_analyzer.py` itself — it reads `AnalysisContext.to_string()` which now includes K8s data.

**`output/rca_formatter.py` additions:**

- `print_k8s_rca(finding: K8sRCAFinding)` — Rich Panel with colour-coded severity
- `print_k8s_dashboard(findings: List[K8sRCAFinding])` — Rich Table: service | status | severity | root cause
- `export_k8s_rca_json(findings) → str` — JSON export for dissertation submission
- All existing methods unchanged

**DONE WHEN:**
- `print_k8s_dashboard()` renders a Rich table with correct severity colours (Critical=red, High=yellow, Medium=blue, Low=green)
- `AnalysisContext.to_string()` includes K8s findings section when findings are present
- LLM output references K8s findings when they are present in context

---

### Phase 6 — Failure Simulation (Demo)

**`k8s/simulator.py` — K8sSimulator**

Available only when `K8S_ENABLE_SIMULATION=true`. Every operation requires explicit user confirmation before executing.

**Simulation scenarios for dissertation demo:**

| Scenario | K8s Action | Expected RCA Detection |
|---|---|---|
| `crash_loop` | Scale deployment to 0, then patch to bad image | CrashLoopBackOff |
| `oom_kill` | Apply low memory limit (1Mi) to a pod | OOMKilled |
| `image_pull` | Set deployment image to nonexistent tag | ImagePullBackOff |
| `node_pressure` | Cordon a node | FailedScheduling |
| `missing_config` | Delete a configmap referenced by a pod | MissingConfigMap |

**Rollback:**
- Every simulation method stores the original state before mutating
- `rollback(scenario_name)` restores the original state
- All actions are logged to `logs/k8s_simulation_audit.log`

**Confirmation flow (non-negotiable):**
```
⚠️  SIMULATION: About to scale paymentservice to 0 replicas in namespace default.
    This will cause a real service disruption.
    Type 'CONFIRM' to proceed or anything else to cancel: _
```

**DONE WHEN:**
- Each of the 5 scenarios produces a detectable RCA finding within 30 seconds of injection
- `rollback()` restores original state for all 5 scenarios
- Simulation is completely unavailable (ImportError path) when `K8S_ENABLE_SIMULATION=false`

---

### Phase 7 — Shell + CLI Integration

**Interactive shell (`ai_sre.py`) — new `/k8s` commands:**

```
/k8s status                     cluster health summary (nodes, pod counts, quotas)
/k8s pods [namespace]           list pods with status and restart counts
/k8s deployments [namespace]    list deployments with replica status
/k8s events [namespace]         recent Warning events
/k8s logs <pod> [namespace]     tail 50 lines from pod
/k8s rca <service>              RCA for one service (Rich report)
/k8s rca all                    RCA for all services (Rich dashboard)
/k8s simulate <scenario>        inject failure (requires K8S_ENABLE_SIMULATION=true)
/k8s rollback <scenario>        restore state after simulation
```

Commands routed via `k8s/command_handler.py`. `/k8s` prefix only registered when `ENABLE_KUBERNETES_MODE=true`. When mode is off, `/k8s` prints a friendly message rather than erroring.

**CLI (`main.py`) — new `k8s` command group:**

```bash
python ai_sre.py k8s status
python ai_sre.py k8s pods --namespace default
python ai_sre.py k8s rca paymentservice
python ai_sre.py k8s rca --all
python ai_sre.py k8s simulate crash_loop
python ai_sre.py k8s rollback crash_loop
```

**DONE WHEN:**
- `/k8s rca all` in the shell produces a Rich dashboard with at least one finding
- `python ai_sre.py k8s status` prints cluster health in plain text
- All existing shell commands still work unchanged
- `/k8s` with `ENABLE_KUBERNETES_MODE=false` prints: `"K8s mode is disabled. Set ENABLE_KUBERNETES_MODE=true to enable."`

---

### Phase 8 — Testing + Validation

**Unit tests (`tests/test_k8s_*.py`):**
- `test_k8s_client.py`: client init, graceful fallback when Minikube off
- `test_k8s_collector.py`: mocked SDK responses for all 11 resource types
- `test_k8s_event_analyzer.py`: all 12 pattern detectors with mocked pod/event objects
- `test_k8s_rca_engine.py`: RCA generation with mocked analyzer output
- `test_k8s_service_mapper.py`: yaml-first + auto-discover fallback

**Integration tests (`tests/test_k8s_integration.py`):**
- Requires `ENABLE_KUBERNETES_MODE=true` and Minikube running
- End-to-end: simulate crash_loop → collect → analyze → generate RCA → verify finding

**Backwards compatibility test:**
- Run existing test suite with `ENABLE_KUBERNETES_MODE=false`
- Zero failures permitted

**Test execution matrix:**

| Test | Mode | Minikube | Expected |
|---|---|---|---|
| Unit: all pattern detectors | false | not needed | ✓ pass |
| Integration: collect_all | true | running | ✓ snapshot populated |
| Integration: RCA for crash_loop | true | running | ✓ Critical finding |
| Simulation: inject + detect + rollback | true + sim | running | ✓ all 5 scenarios |
| Backwards compat: existing suite | false | not needed | ✓ zero regressions |

---

### Phase 9 — Documentation

- `docs/kubernetes_guide.md`: Minikube setup, `.env` config, demo walkthrough for all 5 simulation scenarios
- `README.md`: new K8s mode section, environment variable table, new commands
- `docs/developer_guide.md`: updated architecture diagram showing K8s layer, module overview, extension points

---

## 5. Implementation Checkpoints

| CP | Deliverable | Files | DONE WHEN |
|---|---|---|---|
| CP1 | K8s client + models + flags | `k8s/client.py`, `k8s/models.py`, `flags.py` | `is_available()` returns correctly; flags diff is additive only |
| CP2 | Unified collector | `k8s/collector.py`, updated `resource_collector.py` | `collect_all()` returns snapshot; file mode unchanged |
| CP3 | Service mapping + graph updater | `k8s/service_mapper.py`, `k8s/graph_updater.py` | Mapping resolves; approval gate blocks unapproved changes |
| CP4 | Event analyzer + RCA engine | `k8s/event_analyzer.py`, `k8s/rca_engine.py` | All 12 patterns detected; RCA finding generated |
| CP5 | LLM integration + output | updated `context_builder.py`, `rca_formatter.py` | K8s findings in LLM context; Rich dashboard renders |
| CP6 | Simulation | `k8s/simulator.py` | 5 scenarios inject, detect, rollback correctly |
| CP7 | Shell + CLI | updated `ai_sre.py`, `main.py`, `k8s/command_handler.py` | All commands work; existing commands unchanged |
| CP8 | Tests | `tests/test_k8s_*.py` | Zero regressions; all new tests pass |
| CP9 | Docs | `docs/kubernetes_guide.md`, updated `README.md` | Demo walkthrough complete |

---

## 6. Risk Mitigation

| Risk | Mitigation |
|---|---|
| Breaking existing file-based flows | All new code executes only when `ENABLE_KUBERNETES_MODE=true`; guarded by `hasattr` checks |
| Minikube unavailable during development | `is_available()` gates all SDK calls; unit tests use mocks |
| Secret values leaked | Collector reads only metadata and key names; value fields never accessed |
| Simulation causes unrecoverable state | Every simulation method saves original state before mutating; rollback restores it |
| User bypasses approval gate | Gate has no bypass flag; all graph updates require `y` at the terminal |
| Multi-namespace complexity | `KUBE_NAMESPACES` is a comma-separated list; `collect_all()` iterates it; single-namespace MVP works by default |

---

## 7. Success Criteria

**Functional:**
- `ENABLE_KUBERNETES_MODE=false` → zero behaviour change vs current tool
- `ENABLE_KUBERNETES_MODE=true` + Minikube running → full cluster snapshot, RCA for all services, Rich dashboard
- All 12 failure patterns detected
- All 5 simulation scenarios inject, produce a Critical/High RCA finding, and roll back cleanly
- Service graph update always requires user approval

**Quality:**
- Zero regressions in existing test suite
- Every new class has docstrings
- Secrets: no values in logs, objects, or LLM context — ever

**Performance:**
- `K8sClientManager` init < 2s
- `collect_all()` for 10-pod cluster < 10s
- RCA generation < 15s end-to-end

---

## 8. Out of Scope (MVP)

- Prometheus / metrics-server integration
- Helm release introspection
- Multi-cluster support
- Web dashboard
- Automated remediation
- etcd direct access (service graph populated via API, not etcd)