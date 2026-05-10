# Kubernetes-Aware RCA Implementation Plan

**Project:** AI-Assisted SRE Root Cause Analysis Framework  
**Objective:** Add Kubernetes-native observability and RCA support without breaking existing functionality  
**Scope:** Optional, environment-driven extension to existing local RCA pipeline  
**Date:** May 10, 2026

---

## 1. Repository Architecture Summary

### Entry Points
- **CLI:** `main.py` → `main.cli()` (analyze, status, generate commands)
- **Interactive Shell:** `ai_sre.py` → `SREShell` + `NLParser` (interactive investigation mode)
- **Programmatic:** `main.run_pipeline()` (direct pipeline invocation)

### Core Pipeline Flow
```
log_loader.py → log_processor.py → resource_collector.py 
→ context_builder.py → rag_engine.py (optional) 
→ llm_analyzer.py → rca_formatter.py → output
```

### Investigation Path (Parallel)
```
sre_investigator.py → EvidenceCollector (file OR kubectl)
→ PatternDetector → InvestigationReport
```

### Key Modules
- **Config/Flags:** `flags.py`, `config.py` (feature control)
- **Kubernetes Detection:** Already partially supported via `USE_KUBERNETES` flag in `flags.py`
- **Service Topology:** `service_graph.py` (service dependency modeling)
- **Output:** `rca_formatter.py` (report rendering)
- **Utils:** `logger.py`, `command_registry.py`, `incident_recorder.py`

### Current State
- **Kubernetes Support:** Rudimentary; `EvidenceCollector._collect_from_kubectl()` exists but is incomplete
- **Log Source:** File-based primary; kubectl as fallback
- **Configuration:** Flag-driven; `USE_KUBERNETES` partially implemented
- **Output Format:** Text-based; structured internal representation

---

## 2. Integration Strategy

### Design Principle: Additive, Not Destructive
- No existing file-based flows modified
- New Kubernetes logic implemented in separate modules (user: No seperate module need, try to have teh similar/same module to reaf teh file based logs/ Kubernetes based logs us ethe sflag kubernetes is true or fals, if kubernetes is false, read the logs form file other wise do the kubectl commands/ use any inbuild / pythin package to talk to kubernetes, make sure it use teh existing credentials to talk to kubernetes, and get the logs and other details)
- Feature flags control activation path
- Graceful fallback when Kubernetes unavailable or misconfigured, with clear logging.

### Architecture Decision
```
┌─────────────────────────────────────────────┐
│  Existing Pipeline (File-Based)             │
│  ✓ Continue working unchanged               │
└──────────────────┬──────────────────────────┘
                   │
                   ├─► ENABLE_KUBERNETES_MODE=false
                   │   (Current behavior)
                   │
                   └─► ENABLE_KUBERNETES_MODE=true
                       ┌─────────────────────────────────────────┐
                       │  NEW: Kubernetes-Aware Pipeline          │
                       │  - K8s Client Setup (kubeconfig)         │
                       │  - K8s Resource Collection               │
                       │  - K8s Log Collection                    │
                       │  - K8s Event Detection                   │
                       │  - K8s RCA Rule Engine  ( why can't we us eteh same RCS engine for both..?)                 │
                       │  - Simulation Helpers (optional)         │
                       └─────────────────────────────────────────┘
```

---

## 3. Implementation Phases

### Phase 1: Kubernetes Foundation (Core Services)
**Goal:** Establish reusable Kubernetes abstractions and client management

#### 3.1.1 Create `core/k8s_client.py` (NEW)
**Purpose:** Centralized Kubernetes client management with kubeconfig auto-load

**Key Classes:**
- `K8sClientManager`: Singleton-pattern client initialization
  - `__init__(namespace=None, kubeconfig_path=None, kubeconfig_context=None)`
  - `get_client()` → `kubernetes.client.CoreV1Api`
  - `get_apps_client()` → `kubernetes.client.AppsV1Api`
  - `get_events_client()` → `kubernetes.client.CoreV1Api` (for events)
  - `is_available()` → bool (graceful availability check)
  - `get_current_namespace()` → str (from context or default)
  - `get_cluster_info()` → dict (cluster name, kubeconfig path, etc.)
  - `update relation across services" - > lest say we gto multiple services in multiple name scapec our initail and the backbone od RCA is to have a service graph and the relation between the services and the pods and the deployments in kubernetes, so we need to have a method which can update the service graph with the details of the pods and the deployments in kubernetes, so that when we do the RCA we can correlate the logs with the events in kubernetes and get a better RCA finding, so we need to have a method like `update_service_graph(service_graph)` which will take the existing service graph and update it with the details of the pods and the deployments in kubernetes, this will help us to correlate the logs with the events in kubernetes and get a better RCA finding But while updating teh service grap if shoudl promt for teh user approval forund these update can i update it in teh service graph and then update the service graph with the details of the pods and the deployments in kubernetes, this will help us to correlate the logs with the events in kubernetes and get a better RCA finding`
  - `While doing teh RCA it shoudl alos check teh pods cpu , memory status, node memory, if any PV/PVC issues, if any network policies issues, if any service discovery issues, if any configmap or secret issues, if any resource quota issues, if any node issues, if any cluster level issues, and then correlate all these with the logs and the events in kubernetes and get a better RCA finding`
  - `alawsy check teh whole cluster status and the health of the cluster and then correlate it with the logs and the events in kubernetes and get a better RCA finding`
  - ` always excclude making any chnage to teh cluser, but if we find any issue in the cluster we can log it and then correlate it with the logs and the events in kubernetes and get a better RCA finding`

**Error Handling:**
- Catch `kubernetes.config.ConfigException` at init time
- Auto-fallback to file mode if Minikube unavailable
- Log warnings, not errors, for graceful degradation

**Configuration:**
- Environment variables: `KUBECONFIG`, `KUBE_CONTEXT`, 
- Defaults: `~/.kube/config`, current context, `default` namespace
- Support explicit context override (e.g., `minikube`)

**Testing:**
- Unit test: Mock K8sClientManager initialization
- Integration test: Verify connection to running Minikube (if available)
- Fallback test: Verify graceful handling when kubeconfig missing

---

#### 3.1.2 Create `core/k8s_models.py` (NEW)
**Purpose:** Structured data models for Kubernetes resources and RCA findings

**Key Data Classes:**
```python
@dataclass
class K8sPod:
    name: str
    namespace: str
    image: str
    restart_count: int
    ready: bool
    phase: str  # Pending, Running, Succeeded, Failed, Unknown
    container_states: List['K8sContainerState']
    events: List['K8sEvent']
    logs: List[str]
    previous_logs: List[str]

@dataclass
class K8sContainerState:
    name: str
    state: str  # running, waiting, terminated
    state_reason: str  # CrashLoopBackOff, OOMKilled, etc.
    restart_count: int
    ready: bool

@dataclass
class K8sDeployment:
    name: str
    namespace: str
    replicas_desired: int
    replicas_ready: int
    replicas_updated: int
    replicas_available: int
    status_conditions: List['K8sCondition']

@dataclass
class K8sEvent:
    name: str
    namespace: str
    type: str  # Normal, Warning
    reason: str  # FailedScheduling, CrashLoopBackOff, etc.
    message: str
    first_timestamp: str
    last_timestamp: str
    count: int
    involved_object: dict

@dataclass
class K8sCondition:
    type: str
    status: str  # True, False, Unknown
    reason: str
    message: str
    last_transition_time: str

@dataclass
class K8sRCAFinding:
    service: str
    namespace: str
    status: str  # Healthy, Degraded, Failed, Unknown
    root_cause: str  # Primary failure reason
    supporting_causes: List[str]  # Secondary factors
    evidence: List[str]  # Observed facts
    recommendations: List[str]  # Remediation steps
    severity: str  # Critical, High, Medium, Low, Info
    affected_resources: List[str]  # Pod names, deployment names
    last_transition_time: str  # When failure detected
```

**Validation:**
- Schema validation at instantiation
- Type checking for enum fields (phase, state, type, etc.)

---

#### 3.1.3 Update `flags.py`
**Purpose:** Add Kubernetes mode switches; preserve existing behavior

**Changes:**
```python
# Add new flags (do not modify existing flags)
ENABLE_KUBERNETES_MODE = os.getenv("ENABLE_KUBERNETES_MODE", "false").lower() == "true"
KUBE_CONFIG_PATH = os.getenv("KUBECONFIG")
KUBE_CONTEXT = os.getenv("KUBE_CONTEXT", None)  # e.g., "minikube"
KUBE_NAMESPACE = os.getenv("KUBE_NAMESPACE", "default")

# Kubernetes collection options
K8S_COLLECT_PODS = os.getenv("K8S_COLLECT_PODS", "true").lower() == "true"
K8S_COLLECT_DEPLOYMENTS = os.getenv("K8S_COLLECT_DEPLOYMENTS", "true").lower() == "true"
K8S_COLLECT_EVENTS = os.getenv("K8S_COLLECT_EVENTS", "true").lower() == "true"
K8S_COLLECT_LOGS = os.getenv("K8S_COLLECT_LOGS", "true").lower() == "true"
K8S_COLLECT_METRICS = os.getenv("K8S_COLLECT_METRICS", "false").lower() == "true"  # Future

# Simulation options
K8S_ENABLE_SIMULATION = os.getenv("K8S_ENABLE_SIMULATION", "false").lower() == "true"

# RCA thresholds
K8S_RESTART_COUNT_THRESHOLD = int(os.getenv("K8S_RESTART_COUNT_THRESHOLD", "5"))
K8S_FAILED_EVENT_THRESHOLD = int(os.getenv("K8S_FAILED_EVENT_THRESHOLD", "3"))
```

**Validation:**
- ✓ Existing flags unchanged
- ✓ New flags only added, not modifying existing
- ✓ Defaults disable Kubernetes mode
- ✓ Environment variable precedence maintained

---

### Phase 2: Kubernetes Resource Collection

#### 3.2.1 Create `core/k8s_resource_collector.py` (NEW)
**Purpose:** Collect Kubernetes resources (pods, deployments, namespaces, events)

**Key Classes:**
- `K8sResourceCollector`
  - `__init__(client_manager, namespace=None)`
  - `collect_pods(label_selector=None)` → List[K8sPod]
  - `collect_deployments(label_selector=None)` → List[K8sDeployment]
  - `collect_namespaces()` → List[str]
  - `collect_events(namespace, field_selector=None)` → List[K8sEvent]
  - `collect_pod_status(pod_name)` → K8sPod
  - `get_pod_restart_count(pod_name)` → int
  - `is_pod_ready(pod_name)` → bool
  - `get_container_state(pod_name, container_name)` → K8sContainerState

**Implementation Details:**
1. Use `kubernetes.client.CoreV1Api` for pod/event queries
2. Use `kubernetes.client.AppsV1Api` for deployment queries
3. Parse `pod.status.container_statuses` for restart counts and state
4. Extract reason from `pod.status.container_statuses[i].state.waiting.reason`
5. Parse pod events for failure reasons
6. Handle multi-container pods with per-container status
7. Timeout queries (30 seconds default) to avoid hanging

**Error Handling:**
- Catch `kubernetes.client.exceptions.ApiException` and log
- Return empty list on failure, don't raise
- Log all API calls (debug level)

**Testing:**
- Mock API responses for unit tests
- Integration test against Minikube test namespace
- Verify restart count extraction from YAML pod spec
- Verify event filtering and parsing

---

#### 3.2.2 Create `core/k8s_log_collector.py` (NEW)
**Purpose:** Collect and normalize Kubernetes pod logs

**Key Classes:**
- `K8sLogCollector`
  - `__init__(client_manager, namespace=None)`
  - `get_pod_logs(pod_name, container_name=None, tail_lines=100)` → List[str]
  - `get_previous_logs(pod_name, container_name=None, tail_lines=100)` → List[str]
  - `stream_pod_logs(pod_name, container_name=None, follow=False)` → Iterator[str]
  - `get_all_pod_logs(pod_name)` → Dict[container_name, List[str]]
  - `normalize_logs(raw_logs)` → List['LogEntry']

**Implementation Details:**
1. Use `v1.read_namespaced_pod_log()` for current logs
2. Use `previous=True` parameter for previous container logs
3. Handle container filtering; list all if not specified
4. Parse log timestamps and structure into `LogEntry` objects
5. Tail lines configurable (default 100 per pod)
6. Stream mode support for real-time monitoring (future)

**Error Handling:**
- Catch `kubernetes.client.exceptions.ApiException` (no logs available)
- Return empty list if pod not found or logs not ready
- Log warnings for container-not-found scenarios

**Testing:**
- Mock log API responses
- Integration test against Minikube pods (e.g., payment-service)
- Verify multiline log entry parsing
- Verify previous log access

---

#### 3.2.3 Update `core/resource_collector.py`
**Purpose:** Extend existing resource collector to include Kubernetes resources

**Changes:**
1. Add conditional initialization of `K8sResourceCollector` if `ENABLE_KUBERNETES_MODE`
2. Add method `collect_k8s_resources()` that:
   - Calls `K8sResourceCollector.collect_pods()`
   - Calls `K8sResourceCollector.collect_deployments()`
   - Calls `K8sResourceCollector.collect_events()`
   - Returns dict with all resources
3. Integrate into existing `ResourceCollector.collect()` pipeline
4. Preserve file-based collection when `ENABLE_KUBERNETES_MODE=false`

**Integration Point:**
```python
class ResourceCollector:
    def __init__(self, ...):
        # Existing init logic
        if ENABLE_KUBERNETES_MODE:
            self.k8s_client_manager = K8sClientManager(
                namespace=KUBE_NAMESPACE,
                kubeconfig_path=KUBE_CONFIG_PATH,
                kubeconfig_context=KUBE_CONTEXT
            )
            if self.k8s_client_manager.is_available():
                self.k8s_resource_collector = K8sResourceCollector(
                    self.k8s_client_manager
                )
                self.k8s_log_collector = K8sLogCollector(
                    self.k8s_client_manager
                )

    def collect(self):
        # Existing file-based collection
        resources = self._collect_from_files()
        
        # NEW: Add Kubernetes resources if mode enabled
        if ENABLE_KUBERNETES_MODE and hasattr(self, 'k8s_resource_collector'):
            k8s_resources = self.collect_k8s_resources()
            resources = self._merge_resources(resources, k8s_resources)
        
        return resources
```

**Backward Compatibility:**
- ✓ No existing code paths modified
- ✓ File-based collection unchanged when K8S mode disabled
- ✓ K8S collection optional merge, not replacement

---

### Phase 3: Kubernetes Event Detection and RCA Rules

#### 3.3.1 Create `core/k8s_event_analyzer.py` (NEW)
**Purpose:** Detect Kubernetes failure patterns and classify severity

**Key Classes:**
- `K8sEventAnalyzer`
  - `__init__()`
  - `analyze_pod(pod, events)` → List['K8sFailurePattern']
  - `analyze_deployment(deployment, events)` → List['K8sFailurePattern']
  - `detect_crash_loop_backoff(pod)` → bool + reason
  - `detect_oom_killed(pod)` → bool + reason
  - `detect_image_pull_backoff(pod)` → bool + reason
  - `detect_failed_scheduling(events)` → bool + reason
  - `detect_readiness_failure(pod)` → bool + reason
  - `detect_dependency_failure(pod, service_graph)` → bool + reason
  - `classify_severity(failure_patterns)` → str (Critical, High, Medium, Low, Info)

**Failure Pattern Detection:**
1. **CrashLoopBackOff:** `container_state.waiting.reason == "CrashLoopBackOff"` OR `restart_count > K8S_RESTART_COUNT_THRESHOLD`
2. **OOMKilled:** `container_state.terminated.reason == "OOMKilled"`
3. **ImagePullBackOff:** `container_state.waiting.reason == "ImagePullBackOff"`
4. **FailedScheduling:** Event with `reason == "FailedScheduling"`
5. **Readiness Failure:** Pod ready=False AND pod phase=Running (app crashed but container running)
6. **Dependency Failure:** Pod running but dependent services unhealthy (via service_graph)

**Severity Classification:**
```
Critical: CrashLoopBackOff + restart_count > threshold, OOMKilled, FailedScheduling
High: Readiness failure, Image pull failure, Dependency failure
Medium: Restart spike, Multiple pod restarts
Low: Single transient restart, warning events
Info: Normal pod lifecycle events
```

**Implementation Details:**
- Use `K8sContainerState` objects from resource collector
- Cross-reference events for additional context
- Support service_graph for dependency checks
- Collect reasoning for each detection

**Testing:**
- Unit test: Mock pod/event objects with various failure modes
- Integration test: Simulate failures on Minikube (scale pod to zero, create crash loop)
- Verify severity classification logic
- Verify all pattern detectors work correctly

---

#### 3.3.2 Create `core/k8s_rca_engine.py` (NEW)
**Purpose:** Generate RCA findings from Kubernetes analysis

**Key Classes:**
- `K8sRCAEngine`
  - `__init__(event_analyzer, resource_collector, service_graph)`
  - `generate_rca(service_name, namespace=None)` → K8sRCAFinding
  - `generate_rca_for_all_services(namespace=None)` → List[K8sRCAFinding]
  - `_correlate_failures(pod, deployment, events)` → Dict (root cause data)
  - `_generate_recommendations(root_cause, failure_patterns)` → List[str]

**RCA Generation Logic:**
1. Collect pod for service
2. Collect deployment for service
3. Collect all recent events
4. Run event analyzer on all resources
5. Correlate findings into single RCA
6. Map failure patterns to root causes
7. Generate evidence list
8. Generate recommendations
9. Classify severity
10. Return structured `K8sRCAFinding`

**Root Cause Mapping:**
```python
FAILURE_PATTERN_TO_ROOT_CAUSE = {
    "CrashLoopBackOff": {
        "root_cause": "Application crash (repeated)",
        "short": "App crash loop",
        "priority": 1
    },
    "OOMKilled": {
        "root_cause": "Container memory limit exceeded",
        "short": "OOM",
        "priority": 1
    },
    "ImagePullBackOff": {
        "root_cause": "Container image unavailable or invalid",
        "short": "Image pull failure",
        "priority": 1
    },
    "FailedScheduling": {
        "root_cause": "Pod could not be scheduled (insufficient resources, node affinity, etc.)",
        "short": "Scheduling failure",
        "priority": 1
    },
    "ReadinessFailed": {
        "root_cause": "Application readiness probe failed (dependency or configuration issue)",
        "short": "Readiness probe failure",
        "priority": 2
    },
    "DependencyFailed": {
        "root_cause": "Dependent service unavailable",
        "short": "Upstream dependency down",
        "priority": 2
    },
    "RestartSpike": {
        "root_cause": "Unexpected pod restart spike (transient failure or leak)",
        "short": "Restart spike",
        "priority": 3
    }
}

FAILURE_PATTERN_TO_RECOMMENDATIONS = {
    "CrashLoopBackOff": [
        "Check container startup logs for errors: kubectl logs <pod> --previous",
        "Verify environment variables and config mounts",
        "Check application dependencies (database, cache, etc.)"
    ],
    "OOMKilled": [
        "Increase memory request/limit in deployment spec",
        "Profile application memory usage under load",
        "Check for memory leaks in application"
    ],
    "ImagePullBackOff": [
        "Verify image exists in registry: docker pull <image>",
        "Check image pull secrets and registry credentials",
        "Verify network connectivity to image registry"
    ],
    "FailedScheduling": [
        "Check node resources: kubectl top nodes",
        "Check pod resource requests: kubectl describe pod <pod>",
        "Check node affinity and taints/tolerations"
    ],
    "ReadinessFailed": [
        "Check readiness probe configuration",
        "Verify application startup sequence and dependency order",
        "Check network connectivity between services"
    ],
    "DependencyFailed": [
        "Check upstream service health",
        "Verify service discovery and DNS resolution",
        "Check network policies and firewall rules"
    ]
}
```

**Evidence Collection:**
- Pod restart count
- Current log tail (last 20 lines)
- Previous container logs (if available)
- Recent events (last 5 minutes)
- Pod resource requests/limits vs actual usage
- Dependent service status

**Testing:**
- Unit test: Mock analyzer results, verify RCA generation
- Integration test: Run against Minikube with injected failures
- Verify evidence collection and weighting
- Verify recommendation mapping

---

#### 3.3.3 Extend `services.yaml` Structure (Existing File)
**Purpose:** Add Kubernetes resource mappings to existing service definitions

**Changes:**
```yaml
services:
  paymentservice:
    # Existing fields
    port: 8080
    dependencies:
      - cartservice
      
    # NEW: Kubernetes mappings
    kubernetes:
      namespace: "default"
      deployment: "paymentservice"
      selector:
        app: "paymentservice"
        version: "v1"
      container_name: "server"
      probe_config:
        readiness_path: "/readiness"
        liveness_path: "/liveness"
      expected_replicas: 1
      resource_limits:
        memory: "256Mi"
        cpu: "250m"
```

**Validation:**
- ✓ Backward compatible; Kubernetes section optional
- ✓ Supports optional deployment discovery
- ✓ Provides hints for RCA context

---

### Phase 4: Output and Reporting

#### 3.4.1 Update `output/rca_formatter.py`
**Purpose:** Add Kubernetes RCA report rendering

**Changes:**
1. Add method `print_k8s_rca(finding: K8sRCAFinding)`:
   ```python
   def print_k8s_rca(self, finding: K8sRCAFinding):
       """Print Kubernetes RCA finding in human-readable format"""
       print(f"\n{'='*60}")
       print(f"KUBERNETES RCA REPORT")
       print(f"{'='*60}\n")
       
       print(f"SERVICE: {finding.service}")
       print(f"NAMESPACE: {finding.namespace}")
       print(f"STATUS: {finding.status}")
       print(f"SEVERITY: {finding.severity}\n")
       
       print(f"ROOT CAUSE:")
       print(f"  {finding.root_cause}\n")
       
       if finding.supporting_causes:
           print(f"SUPPORTING CAUSES:")
           for cause in finding.supporting_causes:
               print(f"  • {cause}\n")
       
       print(f"EVIDENCE:")
       for evidence in finding.evidence:
           print(f"  • {evidence}")
       print()
       
       print(f"AFFECTED RESOURCES:")
       for resource in finding.affected_resources:
           print(f"  • {resource}")
       print()
       
       print(f"RECOMMENDATIONS:")
       for i, rec in enumerate(finding.recommendations, 1):
           print(f"  {i}. {rec}")
       print()
   ```

2. Add method `export_k8s_rca_json(findings: List[K8sRCAFinding])` → str (JSON)

3. Update `print_incident_summary()` to include K8S findings if present

4. Add method `print_k8s_dashboard(findings: List[K8sRCAFinding])`:
   - Health summary table (service, status, severity)
   - Top issues (by severity)
   - Timeline of events

**Backward Compatibility:**
- ✓ Existing report methods unchanged
- ✓ K8S methods additive only
- ✓ No changes to file-based output when K8S mode disabled

---

#### 3.4.2 Update `core/context_builder.py`
**Purpose:** Include Kubernetes findings in analysis context

**Changes:**
1. If `ENABLE_KUBERNETES_MODE`:
   - Collect K8S findings via `K8sRCAEngine.generate_rca_for_all_services()`
   - Add findings to `AnalysisContext.k8s_findings` (new field)
   - Include in RAG context if RAG enabled

2. Pass K8S findings to LLM analyzer for correlation with log-based analysis

**Integration:**
```python
class AnalysisContext:
    # Existing fields
    services: dict
    service_graph: ServiceGraph
    incidents: List[Incident]
    
    # NEW field
    k8s_findings: List[K8sRCAFinding] = None
    
    def to_string(self):
        # Existing string conversion
        context_str = "..."
        if self.k8s_findings:
            context_str += "\n## Kubernetes RCA Findings\n"
            for finding in self.k8s_findings:
                context_str += f"- {finding.service}: {finding.status}\n"
        return context_str
```

---

### Phase 5: Integration with Existing Pipeline

#### 3.5.1 Update `ai_sre.py` (SREShell)
**Purpose:** Add Kubernetes commands to interactive shell

**New Commands:**
```
/k8s status                    # Show K8S cluster health
/k8s pods <namespace>          # List pods
/k8s deployments <namespace>   # List deployments
/k8s events <namespace>        # Show recent events
/k8s logs <pod> <namespace>    # Tail pod logs
/k8s rca <service>             # Generate RCA for service
/k8s rca all                   # Generate RCA for all services
/k8s analyze <pod>             # Deep analysis of pod
```

**Changes to `SREShell.execute()`:
1. Route `/k8s` commands to new `K8sCommandHandler` class
2. Maintain existing `/investigate`, `/chat`, `/watch` commands
3. Add help text for new commands

**New Class: `K8sCommandHandler`**
```python
class K8sCommandHandler:
    def __init__(self, client_manager, resource_collector, rca_engine):
        self.client_manager = client_manager
        self.resource_collector = resource_collector
        self.rca_engine = rca_engine
    
    def handle_status(self):
        # Print cluster info, node count, pod count, etc.
    
    def handle_pods(self, namespace):
        # List pods in namespace with status
    
    def handle_rca(self, service):
        # Generate and print RCA for service
```

**Backward Compatibility:**
- ✓ Existing commands preserved
- ✓ `/k8s` commands only available if `ENABLE_KUBERNETES_MODE=true`
- ✓ Error handling for unavailable Kubernetes

---

#### 3.5.2 Update `main.py`
**Purpose:** Add Kubernetes commands to CLI

**New CLI Commands:**
```bash
python main.py k8s status
python main.py k8s pods --namespace default
python main.py k8s rca paymentservice
python main.py k8s analyze paymentservice
```

**Implementation:**
1. Add new `@click.group("k8s")` command group
2. Add `k8s status`, `k8s pods`, `k8s deployments`, `k8s rca`, `k8s analyze` subcommands
3. Wire to `K8sRCAEngine` and `K8sResourceCollector`
4. Print results via `RCAFormatter`

**Backward Compatibility:**
- ✓ Existing `analyze` and `status` commands work as-is
- ✓ New commands in separate `k8s` group
- ✓ `--help` shows K8S commands only if mode enabled

---

### Phase 6: Failure Simulation (Optional)

#### 3.6.1 Create `core/k8s_simulator.py` (NEW, Optional Phase)
**Purpose:** Inject failures for testing RCA accuracy

**Key Classes:**
- `K8sSimulator`
  - `__init__(client_manager)`
  - `scale_deployment_to_zero(deployment_name, namespace)` → bool
  - `restart_pod(pod_name, namespace)` → bool
  - `simulate_restart_spike(deployment_name, namespace, restart_count)` → bool
  - `simulate_oom_pressure(deployment_name, namespace, memory_usage_mb)` → bool
  - `rollback_scale(deployment_name, namespace, replicas)` → bool
  - `kill_pod_container(pod_name, namespace, container_name)` → bool

**Implementation Details:**
1. Only available if `K8S_ENABLE_SIMULATION=true`
2. Use Kubernetes API to patch deployments (scale), delete pods (restart)
3. For OOM simulation: use K8S resource quota or actual pod memory injection (future)
4. Log all actions for audit trail
5. Provide rollback helpers

**Error Handling:**
- Confirm before destructive operations
- Provide rollback commands
- Log all simulation actions

**Testing:**
- Integration test: Simulate each failure type
- Verify RCA engine detects injected failures
- Verify rollback restores state

**Notes:**
- This is optional; mark as Phase 6 (future enhancement)
- Not required for MVP
- Can be implemented after core RCA validation

---

### Phase 7: Testing and Validation

#### 3.7.1 Update `scripts/verify_final.sh`
**Purpose:** Add Kubernetes verification steps

**New Shell Functions:**
```bash
test_k8s_mode_disabled()
  # Verify existing behavior works when ENABLE_KUBERNETES_MODE=false
  # Run: python main.py analyze logs/test.log

test_k8s_client_initialization()
  # Verify K8sClientManager initializes (if Minikube available)
  # Test: python -c "from core.k8s_client import K8sClientManager; m = K8sClientManager(); print(m.is_available())"

test_k8s_resource_collection()
  # Collect pods, deployments, events from Minikube
  # verify count > 0

test_k8s_pod_logs()
  # Collect logs from payment-service pod
  # Verify logs non-empty

test_k8s_rca_generation()
  # Generate RCA for payment-service
  # Verify output includes SERVICE, STATUS, ROOT_CAUSE, EVIDENCE, RECOMMENDATIONS

test_k8s_event_detection()
  # Simulate pod restart
  # Trigger RCA
  # Verify detection of restart event

test_backwards_compatibility()
  # Run full pipeline with ENABLE_KUBERNETES_MODE=false
  # Verify output == baseline

test_k8s_graceful_fallback()
  # Temporarily disconnect from Minikube
  # Verify app doesn't crash, falls back to file mode
```

**Test Execution Matrix:**
| Test | Mode | Minikube | Expected |
|------|------|----------|----------|
| test_k8s_mode_disabled | false | - | ✓ (existing behavior) |
| test_k8s_client_initialization | true | Available | ✓ (initialized) |
| test_k8s_client_initialization | true | Unavailable | ✓ (graceful) |
| test_k8s_resource_collection | true | Available | ✓ (pods collected) |
| test_k8s_rca_generation | true | Available | ✓ (RCA generated) |
| test_backwards_compatibility | false | - | ✓ (baseline match) |

---

#### 3.7.2 Create `tests/test_k8s_integration.py` (NEW)
**Purpose:** Comprehensive K8S integration tests

**Test Classes:**
- `TestK8sClientManager`: Client initialization, kubeconfig loading, availability check
- `TestK8sResourceCollector`: Pod/deployment collection, event parsing
- `TestK8sLogCollector`: Log retrieval, multi-container handling
- `TestK8sEventAnalyzer`: Failure pattern detection, severity classification
- `TestK8sRCAEngine`: RCA generation, root cause mapping
- `TestK8sIntegration`: End-to-end pipeline with Minikube

**Mock Strategy:**
- Mock `kubernetes.client.CoreV1Api` for unit tests
- Use real Minikube cluster for integration tests (if available)
- Mock data: Pod YAML specs with various states (running, crashed, pending)

**Coverage Target:**
- ✓ 80% of core K8S logic (event analyzer, RCA engine)
- ✓ 60% of API collector logic (mocked)
- ✓ 100% of error handling (graceful fallback)

---

### Phase 8: Documentation

#### 3.8.1 Create `docs/kubernetes_guide.md` (NEW)
**Content:**
- Setup Minikube locally
- Enable `ENABLE_KUBERNETES_MODE`
- Run example RCA command
- Example output
- Troubleshooting

#### 3.8.2 Update `README.md`
- Add Kubernetes mode description
- Add new CLI commands
- Add environment variables table

#### 3.8.3 Update `docs/developer_guide.md`
- Architecture diagram including K8S layer
- K8S module overview
- Extension points for future enhancements

---

## 4. Implementation Checkpoints

| Checkpoint | Deliverable | Files | Validation |
|------------|-------------|-------|-----------|
| CP1 | K8S Foundation | `k8s_client.py`, `k8s_models.py`, updated `flags.py` | Client init test, graceful fallback |
| CP2 | Resource Collection | `k8s_resource_collector.py`, updated `resource_collector.py` | Collect pods from Minikube |
| CP3 | Log Collection | `k8s_log_collector.py` | Retrieve pod logs |
| CP4 | Event Analysis | `k8s_event_analyzer.py` | Detect all failure patterns |
| CP5 | RCA Engine | `k8s_rca_engine.py` | Generate structured RCA findings |
| CP6 | Reporting | Updated `rca_formatter.py` | Print K8S RCA, JSON export |
| CP7 | Integration | Updated `main.py`, `ai_sre.py` | CLI and shell commands work |
| CP8 | Validation | Updated `verify_final.sh`, `test_k8s_integration.py` | All tests pass |
| CP9 | Docs | Kubernetes guide, README updates | Documentation complete |

---

## 5. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Cluster unavailable | Graceful fallback to file mode; no errors |
| Breaking existing flows | Flag-driven; new code only executes when `ENABLE_KUBERNETES_MODE=true` |
| API version incompatibility | Test against Minikube version; pin `kubernetes` package version |
| Timeout failures | Implement 30-second timeouts; graceful degradation |
| Permission issues | Document RBAC setup; provide clear error messages |
| Data duplication | Merge K8S and file data carefully; deduplicate by resource name |

---

## 6. Success Criteria

### Functional
- ✓ `ENABLE_KUBERNETES_MODE=false` → existing behavior unchanged
- ✓ `ENABLE_KUBERNETES_MODE=true` + Minikube available → full K8S RCA
- ✓ `ENABLE_KUBERNETES_MODE=true` + Minikube unavailable → graceful fallback
- ✓ All failure patterns detected: CrashLoopBackOff, OOMKilled, ImagePullBackOff, FailedScheduling, ReadinessFailed, DependencyFailed
- ✓ RCA output includes: SERVICE, NAMESPACE, STATUS, SEVERITY, ROOT CAUSE, EVIDENCE, RECOMMENDATIONS
- ✓ CLI commands: `python main.py k8s status`, `python main.py k8s rca <service>`, etc.
- ✓ Interactive shell commands: `/k8s status`, `/k8s rca <service>`, etc.

### Quality
- ✓ All existing tests pass
- ✓ All new K8S tests pass (unit + integration)
- ✓ Zero breaking changes to public API
- ✓ Logging coverage: all major code paths logged
- ✓ Error handling: all exceptions caught and logged gracefully

### Performance
- ✓ K8S mode initialization < 2 seconds
- ✓ Pod collection < 5 seconds (10 pods)
- ✓ RCA generation < 10 seconds
- ✓ No memory leaks in collector loops

### Documentation
- ✓ Kubernetes setup guide written
- ✓ README updated with new commands
- ✓ Developer guide updated with K8S architecture
- ✓ All new classes have docstrings

---

## 7. Phase-Based Resource Estimation

| Phase | Scope | Estimate | Risk |
|-------|-------|----------|------|
| 1 | Foundation (K8S client, models, flags) | 4-6 hours | Low |
| 2 | Resource collection (pods, logs) | 4-5 hours | Low |
| 3 | Event analysis and RCA rules | 5-7 hours | Medium |
| 4 | Output/reporting | 3-4 hours | Low |
| 5 | Pipeline integration | 2-3 hours | Medium |
| 6 | Simulation (optional) | 4-5 hours | High |
| 7 | Testing and validation | 6-8 hours | Medium |
| 8 | Documentation | 2-3 hours | Low |
| **TOTAL** | **MVP (Phases 1-5)** | **18-25 hours** | **Medium** |
| **TOTAL** | **Full (Phases 1-8)** | **28-40 hours** | **Medium** |

---

## 8. Rollback Plan

If critical issues emerge:

1. **Partial Rollback:** Disable `ENABLE_KUBERNETES_MODE` environment variable
2. **Full Rollback:** Revert commits before Phase 1 checkpoint
3. **Data Safety:** No data modified; K8S reads are non-destructive until Phase 6 (simulation)

---

## 9. Future Enhancements (Out of Scope - MVP)

1. **Metrics Collection:** CPU/memory from Prometheus or kubelet
2. **Advanced Simulation:** Resource pressure injection, network partition simulation
3. **Helm Integration:** Read values from Helm releases
4. **Multi-cluster:** Support multiple K8S clusters
5. **Dashboard:** Web-based visualization of RCA findings
6. **Alerting:** Integration with Prometheus AlertManager
7. **Automated Recovery:** Auto-execute recommendations

---

## 10. Questions for Clarification

Before proceeding with Phase 1, please confirm:

1. **Minikube Availability:** Will Minikube be running locally during testing, or should we mock K8S API responses?
2. **Namespace Scope:** Should RCA focus on a specific namespace (e.g., `default`), or support multi-namespace scanning?
3. **Service Discovery:** Should service-to-Kubernetes mapping be auto-discovered, or configured via `services.yaml`?
4. **LLM Integration:** Should K8S findings be merged with log-based analysis in LLM context, or kept separate?
5. **Report Format:** Should JSON export follow a specific schema (e.g., Kubernetes audit logs format)?

---

**Document Version:** 1.0  
**Status:** Ready for Review  
**Next Step:** User approval + Phase 1 implementation start
