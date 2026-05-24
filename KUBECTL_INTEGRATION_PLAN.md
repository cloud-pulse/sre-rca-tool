# KUBECTL_INTEGRATION_PLAN.md

## 1. Current Codebase Summary
- **Modules / files and responsibilities**
  - **`main.py`**: CLI + main orchestration. The primary orchestrator is `run_pipeline()`.
    - Loads logs (file or Kubernetes via `LogLoader.load_auto()`)
    - Processes + filters logs (`LogProcessor`)
    - Collects resource evidence (`ResourceCollector`)
    - Builds LLM context (`ContextBuilder`)
    - Runs LLM analysis (`LLMAnalyzer`)
  - **`ai_sre.py`**: Secondary entry / REPL style, dispatches to command handlers via `core.command_registry`.
  - **`flags.py`**: Feature flags and configuration.
    - Kubernetes mode toggle: `USE_KUBERNETES` (env: `SOURCE_KUBERNETES`)
    - Namespace: `K8S_NAMESPACE` (env: `SOURCE_NAMESPACE`)
  - **`core/log_loader.py`**: Log acquisition.
    - File mode: `load()`, `load_directory()`
    - Kubernetes mode: `load_auto()` → `load_from_kubectl()` (uses `kubectl get pods` + `kubectl logs`)
  - **`core/log_processor.py`**: Parses raw log lines into structured entries; filters; summarizes; extracts a failure chain.
    - Key functions: `process()`, `filter_by_severity()`, `filter_by_service()`, `get_summary()`, `get_failure_chain()`
  - **`core/context_builder.py`**: Converts processed logs + resource metrics into LLM-ready context.
    - Key functions: `build()`, `format_logs_for_prompt()`, `format_resources_for_prompt()`, `get_incident_summary()`
  - **`core/resource_collector.py`**: Resource evidence.
    - Mock mode: `get_mock_resources()`
    - Partial live mode: `get_real_pod_metrics()` + `get_pod_status()` + `get_real_resources()`; entry point `get_resources()` with fallback to mock.
  - **`core/llm_analyzer.py`**: LLM prompt building + parsing.
    - Baseline: `build_baseline_prompt()`, `analyze_baseline()`
    - RAG: `build_rag_prompt()`, `analyze_rag()`
  - **`core/service_graph.py`**: Reads and models dependencies from **`services.yaml`**.
    - Key functions: `get_all_service_names()`, `get_service_name()`, `get_namespace()`, `get_containers()`
    - Blast radius: `get_blast_radius()` (uses `get_downstream()` + `get_upstream()`)
    - Dependency discovery from logs: `discover_from_logs()`, `prompt_user_to_update()`, `apply_discoveries()`
  - **`core/service_discovery.py`**: Interactive Kubernetes scanning/matching of containers/pods.
  - **`core/sre_investigator.py`**: Rule-based investigation engine (patterns + evidence collection).
    - Collects evidence from files/mock or via embedded kubectl calls.
    - Key classes: `EvidenceCollector`, `PatternDetector`, `SREInvestigator`.
- **Main orchestrator / entry point**
  - `main.py` → `run_pipeline()`
- **Where log reading and RCA logic currently lives**
  - Log reading: `core/log_loader.py` (`load_from_kubectl()` for kubectl mode)
  - RCA logic: mostly LLM-based in `run_pipeline()` using:
    - `core/log_processor.py` + `core/context_builder.py` + `core/llm_analyzer.py`
  - Rule-based RCA/investigation exists in `core/sre_investigator.py` but is not currently wired into `run_pipeline()` as the primary sequential early-exit pipeline.

## 2. services.yaml Structure
File: `services.yaml`

- Top-level key: `services:`
- Each service entry (example: `frontend`, `checkoutservice`, etc.) includes:
  - `description` (string)
  - `namespace` (string; commonly `default`)
  - `port` (int)
  - `depends_on` (list of service names)
  - `exposes_to` (list of service names)
  - `health_endpoint` (string)
  - `containers` (list of dicts, each with at least `name`)
  - `dependency_confidence` (string; e.g. `user_defined`)

- Example fields and dependencies:
  - `frontend.depends_on` includes:
    - `productcatalogservice`, `recommendationservice`, `cartservice`, `shippingservice`, `checkoutservice`, `currencyservice`, `adservice`
  - `checkoutservice.depends_on` includes:
    - `paymentservice`, `shippingservice`, `emailservice`, `currencyservice`, `cartservice`, `productcatalogservice`

## 3. kubectl Integration Design
### New module: `core/kubectl_client.py`
Create a centralized kubectl subprocess wrapper + parsers.

Required functions:
1. `get_pods(namespace, service_name)`
   - Uses `kubectl get pods -n <namespace>`.
   - Primary strategy: label selector `--selector app=<service_name>` (matches existing behavior in `core/log_loader.py`).
   - Fallback: pod/container name heuristics if selector doesn’t work.
   - Returns: list of pod names (optionally include container list if you extend later).

2. `get_pod_events(pod_name, namespace)`
   - Uses:
     - `kubectl get events -n <namespace> --field-selector involvedObject.name=<pod_name> --sort-by=.lastTimestamp`
   - Returns: string (formatted excerpt) for embedding into evidence.

3. `get_pod_logs(pod_name, container, namespace, tail=200)`
   - Uses:
     - `kubectl logs <pod_name> -n <namespace> -c <container> --tail=<tail> --timestamps=true`
   - Returns: list of log lines or newline-delimited string.

4. `get_node_resources()`
   - Uses:
     - `kubectl top nodes --no-headers`
   - Returns: parsed dict/list (CPU/memory per node).

5. `get_cluster_resource_pressure()`
   - Uses:
     - `kubectl top pods -A --no-headers` (or scoped namespace)
   - Returns: parsed pressure indicators / top pods by CPU/Mem.

6. `get_deployment_list(namespace)`
   - Uses:
     - `kubectl get deployments -n <namespace> --no-headers`
   - Returns: list of deployment names.

### Design notes
- Existing kubectl interactions are scattered across:
  - `core/log_loader.py` (pods + logs)
  - `core/sre_investigator.py` (describe/events/rollout/top/pvc/hpa/endpoints)
- The new `core/kubectl_client.py` should unify these calls to:
  - reduce duplicated subprocess parsing
  - support the exact evidence retrieval steps required by the sequential early-exit RCA pipeline.

## 4. Service Discovery Flow
### Behavior required
1. **Check `services.yaml` first**
   - Use `core/service_graph.py` to find service config by exact key (or partial match via `get_service_name()`).

2. **If not found, discover via kubectl deployments**
   - Call `kubectl_client.get_deployment_list(namespace)`.
   - Match discovered deployments to the requested/unknown service name.

3. **Auto-update `services.yaml`**
   - Add new service entry with:
     - `depends_on: []`
     - `namespace: <discovered namespace>`
     - Other fields populated with safe defaults (or minimal schema-compatible defaults).
   - Persist back to `services.yaml` (prefer reuse of `ServiceGraph._save()` logic or add an explicit yaml write helper).

## 5. RCA Pipeline (Sequential with early exit)
### Required sequential analysis order
For a target service (and then for dependencies), run evidence collection in this order:

1. **Pod status check**
   - Detect: `CrashLoopBackOff`, `Pending`, `OOMKilled`, etc.
   - If a high-confidence status strongly implies root cause, exit early.

2. **Pod events**
   - Use `kubectl_client.get_pod_events()`.
   - Detect: probe failures, scheduling failures, evictions/node pressure, pull/backoff, secrets/config missing hints.
   - If a high-confidence event category identifies root cause, exit early.

3. **Pod + container logs (tail=200)**
   - Use `kubectl_client.get_pod_logs(..., tail=200)`.
   - Apply existing rule mapping from `core/sre_investigator.py.PatternDetector.RULES` (it already has patterns for OOM, CrashLoop, connection/DNS issues, secrets/config missing, probe failures, etc.).
   - If confidence threshold reached (e.g., >= 90), exit early.

4. **Node and cluster resource pressure**
   - Use `kubectl_client.get_node_resources()` and `get_cluster_resource_pressure()`.
   - If widespread resource pressure explains symptoms, exit early.

5. **Dependency health check (for each dependency in `services.yaml`)**
   - For each `dependency` in `services.yaml[target_service].depends_on`, repeat steps 1–3.
   - Return immediately when root cause is confidently identified in a dependency.

### Early exit definition
- Maintain a current best candidate:
  - `root_cause`, `confidence`, `exit_reason`
- Stop as soon as:
  - a CRITICAL pattern is matched with high confidence, OR
  - confidence crosses a configured threshold.

### Where to reuse existing logic
- Reuse:
  - `core/sre_investigator.py.PatternDetector.detect(evidence)` for rule-based confidence.
- New evidence collector should build `InvestigationEvidence` or a compatible intermediate structure from kubectl outputs.

## 6. Code Changes Required
### Existing files that need modification
1. **`main.py`**
   - Wire a kubectl live RCA path into the CLI.
   - Decide how it integrates with current `run_pipeline()`:
     - Option A: add new CLI command (e.g. `analyze-kubectl`)
     - Option B: extend `analyze` when `USE_KUBERNETES=true`
   - Ensure output fields match current expectations (`root_cause`, `affected_services`, `suggested_fixes`, `confidence`, etc.).

2. **`core/log_loader.py`** (recommended)
   - Replace direct kubectl log calls with `core/kubectl_client.get_pod_logs()` for container-specific logs.

3. **`core/sre_investigator.py`** (recommended)
   - Refactor embedded kubectl subprocess `_collect_from_kubectl()` to use `core/kubectl_client.py`.
   - Or extract the evidence mapping so it can be used by the sequential early-exit engine.

4. **`core/service_graph.py`** (recommended)
   - Add helper(s) to update and persist `services.yaml` for newly discovered deployments.

### New files to create
1. **`core/kubectl_client.py`** (MUST)
   - Implements kubectl interactions listed in your spec.

2. **`core/kubectl_rca_investigator.py`** (RECOMMENDED)
   - Implements the sequential early-exit RCA pipeline.
   - Uses `core/kubectl_client.py` + `PatternDetector`.

## 7. Implementation Order (8-hour timeline)
### MUST-HAVE for demo
- Create `core/kubectl_client.py`
- Service discovery + auto-update `services.yaml`
- Sequential early-exit RCA pipeline
- Wire into CLI entry path (`main.py`)

### NICE-TO-HAVE
- Refactor `core/log_loader.py` to use `kubectl_client`
- Refactor `core/sre_investigator.py` to use `kubectl_client`

#### Time-boxed breakdown
1. (1.0h) Identify integration points in `main.py` + confirm current mode toggles.
2. (1.5h) Implement `core/kubectl_client.py` (all required functions + parsing).
3. (1.5h) Implement deployment discovery + auto-update of `services.yaml`.
4. (1.5h) Implement sequential early-exit RCA engine (`core/kubectl_rca_investigator.py`).
5. (1.0h) Wire RCA engine into `main.py` output schema.
6. (0.5h) Refactor `core/log_loader.py` (optional).
7. (0.5h) Refactor `core/sre_investigator.py` (optional).

## 8. Demo Script
### Scenario 1: OOMKilled
- **Expected input**: target service name from `services.yaml` (namespace default).
- **Expected RCA output**:
  - root cause: memory limit exceeded / OOMKilled
  - confidence: high (>= 90)
  - suggested fix includes increasing memory limit + checking memory leaks.

### Scenario 2: CrashLoopBackOff
- **Expected input**: service that has crashing containers.
- **Expected RCA output**:
  - root cause: CrashLoopBackOff caused by application crash/startup failure
  - confidence: high (>= 85)
  - suggested fix: inspect logs, validate config/health endpoints.

### Scenario 3: Dependency failure (connection/DNS)
- **Expected input**: a service that depends_on a broken dependency.
- **Expected RCA output**:
  - early exit after dependency analysis
  - root cause points to the failing dependency (connection refused / DNS failure category)
  - confidence: high if patterns match strongly.

