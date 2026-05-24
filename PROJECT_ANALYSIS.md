# PROJECT_ANALYSIS.md

## Scope
This file documents the Python AI-SRE RCA framework (code-backed). It includes:
- repo structure
- working `analyze` (kubectl RCA) behavior
- broken features: `--baseline`, `--compare`, `--chat`
- exact kubectl commands invoked in kubectl RCA
- AI provider/model + prompt construction
- baseline/compare/chat storage
- dependencies and Python version
- observed runtime outputs/errors from this environment

---

## 1) Repo structure (major files)
Top-level:
- `ai_sre.py` — interactive shell entry; delegates to `core.command_registry`
- `main.py` — Click CLI entry; provides `analyze/status/kubectl-analyze/compare/chat/...`
- `flags.py` — loads `.env`, defines feature flags
- `services.yaml` — service discovery graph
- `requirements.txt`, `setup.py`
- `core/` — core logic
- `evaluation/` — `comparator.py`
- `output/` — `rca_formatter.py`
- `logs/`, `reports/`, `docs/`, `scripts/`

Core modules (major):
- `core/command_registry.py`
- `core/kubectl_client.py`
- `core/kubectl_rca_investigator.py`
- `core/context_builder.py`
- `core/log_loader.py`
- `core/log_processor.py`
- `core/llm_analyzer.py`
- `core/llm_provider.py`
- `core/llm_cache.py`
- `core/rag_engine.py`
- `core/resource_collector.py`
- `core/incident_recorder.py`
- `core/window_analyzer.py`

Entry points:
- `setup.py` console script: `ai-sre=ai_sre:main`
- `main.py` uses Click subcommands

---

## 2) Working feature: kubectl RCA pipeline ("analyze" via kubectl + minikube)
In this codebase, kubectl RCA is performed by `core/kubectl_rca_investigator.py`, and is triggered by `AnalyseHandler._handle_kubectl()` inside `core/command_registry.py` (or the v2 patched handler in `command_registry_patch_v2.py`).

### 2.1 What kubectl commands are executed (exact list)
All kubectl calls are in `core/kubectl_client.py`.

**Stage 1 — Pod discovery**
1. Primary label-selector attempt:
   - `kubectl get pods -n <namespace> --selector app=<service_name> --no-headers -o wide`
2. Fallback name heuristic:
   - `kubectl get pods -n <namespace> --no-headers`
   - then filters lines containing the service name.

**Stage 2 — Pod events**
1. Events fetch:
   - `kubectl get events -n <namespace> --field-selector involvedObject.name=<pod_name> --sort-by=.lastTimestamp`
2. Fallback:
   - `kubectl describe pod <pod_name> -n <namespace>`
   - extracts `Events:` section or last 3000 chars.

**Stage 3 — Pod logs (all containers)**
1. Container list:
   - `kubectl get pod <pod_name> -n <namespace> -o jsonpath={.spec.containers[*].name}`
2. For each container:
   - current logs:
     - `kubectl logs <pod_name> -n <namespace> --tail=<tail> --timestamps=true -c <container>`
   - if current fails (auto-retry):
     - `kubectl logs <pod_name> -n <namespace> --tail=<tail> --timestamps=true -c <container> --previous`

**Stage 4 — Node + cluster pressure**
1. Node usage:
   - `kubectl top nodes --no-headers`
2. Pod usage (two modes):
   - if namespace provided:
     - `kubectl top pods --no-headers -n <namespace>`
   - else (A-wide):
     - `kubectl top pods --no-headers -A`

**Stage 4b — Node describe**
1. Pod scheduled node:
   - `kubectl get pod <pod_name> -n <namespace> -o jsonpath={.spec.nodeName}`
2. Node describe:
   - `kubectl describe node <node_name>`

**Stage 5 — Endpoints**
- `kubectl get endpoints <service_name> -n <namespace>`

**Stage 6 — Istio VirtualService**
- `kubectl get virtualservice <service_name> -n <namespace> -o yaml`
- returns empty string if not installed/unavailable.

**Stage 7 — Dependencies**
- Uses `services.yaml` dependency hints (one level deep) and repeats Stages 1–4 against dependency services.

### 2.2 How evidence becomes AI input
Evidence is collected into `RCAReport.all_evidence` by `core/kubectl_rca_investigator.py`.

Then the kubectl handler:
- flattens evidence into a single text block using `_collect_kubectl_evidence()` (v2 handler)
- builds a prompt with preliminary regex findings and the evidence text
- calls `provider.generate(prompt)`.

### 2.3 AI output parsing and display
The shared narrative renderer in `core/command_registry.py` prints:
- an “Analysis Complete — kubectl mode” header
- a Rich panel containing the LLM narrative

Confidence extraction is done using:
- regex `CONFIDENCE:\s*(\d+)%`

---

## 3) Broken features analysis (`--baseline`, `--compare`, `--chat`)
Important: this repo has **two different front-ends**.

- `main.py` Click CLI
- `ai_sre.py` interactive shell + `core.command_registry`

Your `--baseline/--compare/--chat` flags/commands may be referring to different systems.

### 3.1 `--baseline` (in interactive shell)
In `core/command_registry.py`, `analyse <service> --baseline` affects the **non-kubectl** file/log pipeline path only.

When `USE_KUBERNETES` is true, `_handle_kubectl()` is called and baseline_mode/compare_mode are not used to change kubectl behavior.

### 3.2 `--compare` (in interactive shell)
Similarly, `analyse <service> --compare` affects the file/log pipeline.

In kubectl mode, compare mode does not implement a separate baseline-vs-rag side-by-side flow.

### 3.3 `--chat`
There are two chat paths:

**A) `ai_sre.py chat` (interactive shell)**
- loads `.last_rca.json` or `.last_analyse.json`
- if none exist prints a “No previous RCA found …” warning
- then runs an LLM loop with `provider.generate(prompt)`

**B) `python main.py chat` (Click CLI)**
- runs/loads analysis and then runs a chat loop
- (observed) this path is currently unstable in this environment due to Click/ctypes import issues.

---

## 4) Observed runtime outputs in this environment
### 4.1 `--baseline` and `--compare` (interactive shell)
Command executed:
- `python ai_sre.py analyse payment-service --baseline`

4. **Prompt construction & LLM call** (`_build_kubectl_prompt()`)
   ```python
   Prompt template:
   ==================
   You are an expert Site Reliability Engineer performing root cause analysis.
   
   Service: <service_name>
   Source: Live Kubernetes cluster (kubectl)
   
   --- KUBECTL EVIDENCE START ---
   <.evidence_text from stage collection>
   --- KUBECTL EVIDENCE END ---
   
   Analyse this evidence and identify:
   1. Root cause of any failures or anomalies
   2. Sequence of events leading to failure
   3. Affected services and impact
   4. Recommended remediation steps
   
   If everything appears healthy, clearly state there are no issues found
   and provide any recommendations to improve reliability.
   
   At the end of your analysis, you MUST include this block exactly:
   CONFIDENCE: <number>%
   REASON: <one sentence explaining your confidence level>
   ```
   - Calls `provider.generate(prompt)` (Ollama or Nvidia NIM)
   - Expects response with CONFIDENCE: XX% block at end

5. **Confidence extraction** (`_handle_kubectl()`)
   ```python
   conf_match = re.search(r"CONFIDENCE:\s*(\d+)%", narrative, re.IGNORECASE)
   confidence = int(conf_match.group(1)) if conf_match else 0
   ```

6. **Incident recording** (`check_and_save()` in IncidentRecorder)
   - Decision: Is issue found?
     - Check narrative for no-issue signals: "no issue", "healthy", "operating normally", etc.
     - AND confidence >= 50
   - If issue found:
     - Query RAG engine for similar historical incidents
     - If similarity < 40%, save as new incident:
       - Generate incident_ID: `incident_YYYYMMDD_HHMMSS`
       - Save to disk: `logs/historical/<incident_id>.txt`
       - Embed in ChromaDB for future retrieval
   - Return record dict with {saved, incident_id, filepath, embedded, similarity_score}

7. **Display output** (`_print_kubectl_context()` + `_print_analysis_result()`)
   ```
   ═══════════════════════════════════════
     Kubernetes Context
   ───────────────────────────────────────
   Namespace       : default
   Analysed Pod    : payment-service-abc123
   Node            : minikube
   Endpoints       : Healthy
   Istio           : (not shown if absent)
   Dependencies    : ✓ db-service ⚠ cache-service
   
   ═══════════════════════════════════════
     Analysis Complete — kubectl mode
   ───────────────────────────────────────
   Service         : payment-service
   Windows used    : Live (kubectl)
   Confidence      : 75%
   Warning         : None
   Incident saved  : No
   Reason          : kubectl_live
   Similarity      : 0.0%
   
   ╭─ Root Cause Analysis ──────────────╮
   │ The payment-service pod is healthy...
   │ Confidence: 75%
   │ Reason: Full evidence visible...
   ╰────────────────────────────────────╯
   ```

### Data Flow (Code Path)
```
ai_sre.py
  ↓ resolve() → route to AnalyseHandler
core/command_registry.py :: AnalyseHandler.handle()
  ├─ if USE_KUBERNETES=true: call _handle_kubectl()
  │   ↓
  │   _resolve_service()  # service name normalization
  │   ↓
  │   run_kubectl_rca()  # import from kubectl_rca_investigator
  │   ├─ KubectlRCAInvestigator.investigate()
  │   ├─  Runs 7 stages, returns RCAReport {target_service, all_evidence, dependency_reports}
  │   └─ Returns RCAReport object
  │   ↓
  │   collect_all_evidence()  # flatten evidence to text
  │   ↓
  │   _build_kubectl_prompt()  # construct LLM prompt
  │   ↓
  │   provider.generate(prompt)  # call Ollama/Nvidia
  │   ↓
  │   conf_match re.search()  # extract CONFIDENCE: XX%
  │   ↓
  │   IncidentRecorder.check_and_save()  # store if new
  │   ↓
  │   _print_kubectl_context()  # display context table
  │   ↓
  │   _print_analysis_result()  # display full result
```

**Connection to Minikube:**
- Uses `subprocess.run()` to execute `kubectl` commands directly
- No Kubernetes Python client library used
- All interaction via command-line: `kubectl get pods`, `kubectl logs`, `kubectl top`, etc.
- Assumes `kubectl` is in PATH and configured to connect to Minikube

---

## 3. BROKEN FEATURES

### Feature 1: `--baseline` Mode

**Intended Behavior:**
- Run LLM analysis WITHOUT RAG (Retrieval-Augmented Generation)
- Pure LLM-only analysis of logs
- Output a baseline narrative to compare against RAG results
- Useful for evaluating RAG effectiveness

**Code Location:** `core/command_registry.py`, lines 179-190 (AnalyseHandler.handle())

**Code:**
```python
if baseline_mode:
    from core.llm_provider import provider
    prompt = (
        f"You are an expert Site Reliability Engineer.\n"
        f"Service: {service}\n"
        f"Analyse the following logs and provide RCA.\n\n"
        f"--- LOGS START ---\n"
        f"{chr(10).join(lines[:500])}\n"
        f"--- LOGS END ---"
    )
    raw_response = provider.generate(prompt)
    _print_baseline_result(raw_response, service)
    return "ok"
```

**Actual Behavior (Error):**
```
$ python ai_sre.py analyze payment-service --baseline
Error: No module named 'openai'
Type 'help' for commands.
```

**Root Cause:**
- Line in `core/llm_provider.py` line 31: `from openai import OpenAI`
- This import only executes when `LLM_PROVIDER=nvidia`
- `requirements.txt` DOES NOT include `openai` package
- **Fix:** Add `openai>=1.0.0` to requirements.txt

**What it tries to use:**
- `WindowAnalyzer.analyse()` — NO (baseline skips RAG)
- `provider.generate()` — YES (LLM call)
- Expected window: first 500 log lines
- No incident recording (baseline is reference only)

**Current Data Storage:**
- None. `_print_baseline_result()` only prints to console
- No file is created
- No database record

**Expected Data Path:**
- Should create baseline report file: `reports/baseline_<service>_<timestamp>.txt` (currently NOT implemented)
- OR: Save to `.baseline_rca.json` for later comparison

---

### Feature 2: `--compare` Mode

**Intended Behavior:**
- Run BOTH RAG + Baseline analyses
- Generate side-by-side comparison report
- Save report to `reports/compare_<service>_<timestamp>.txt`
- Show which mode is more accurate/confident

**Code Location:** `core/command_registry.py`, lines 170-178 (AnalyseHandler.handle())

**Code:**
```python
if compare_mode:
    from core.window_analyzer import WindowAnalyzer
    from core.llm_provider import provider
    analyzer = WindowAnalyzer()
    rag_result = analyzer.analyse(lines, service=service)
    prompt = (
        f"You are an expert Site Reliability Engineer.\n"
        f"Service: {service}\n"
        f"Analyse the following logs and provide RCA.\n\n"
        f"--- LOGS START ---\n"
        f"{chr(10).join(lines[:500])}\n"
        f"--- LOGS END ---"
    )
    baseline_response = provider.generate(prompt)
    report_path = _save_compare_report(service, rag_result, baseline_response)
    console.print(f"\nComparison report saved to: {report_path}")
    _print_analysis_result(rag_result, mode="RAG")
    return "ok"
```

**Actual Behavior (Error):**
```
$ python ai_sre.py analyze payment-service --compare
Error: No module named 'openai'
```

**Root Cause:**
- Same as `--baseline` — missing `openai` package

**What it tries to use:**
1. `WindowAnalyzer.analyse()` → RAG mode (works if LLM works)
   - Collects log lines from file
   - Runs sliding window analysis (window 1 = 500 lines)
   - Calls LLM with window context
   - Returns {confidence, windows_used, analysis, incident_record}

2. `provider.generate(prompt)` → Baseline mode (fails)
   - Pure LLM call without RAG context

3. `_save_compare_report()` → File storage (partially implemented)
   ```python
   def _save_compare_report(service, rag_result, baseline_response) -> str:
       # Creates reports/<service>_<timestamp>.txt
       # Content includes:
       # - RAG confidence, windows used, analysis
       # - Baseline response
       # - Summary with similarity score
       report_path = f"reports/compare_{service}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
       # ... writes content ...
       return report_path
   ```

**Data Storage:**
- RAG result: stored in `logs/historical/<incident_id>.txt` if new + similarity < 40%
- Comparison report: written to `reports/compare_YYYYMMDD_HHMMSS.txt`
- ChromaDB index: `.chromadb/` directory

---

### Feature 3: `--chat` Mode (Interactive Follow-up)

**Intended Behavior:**
- After running `analyze`, enter interactive Q&A session
- Ask follow-up questions about the last RCA
- Chat builds context from `.last_rca.json` file
- Uses LLM to answer questions about the incident
- Guardrails prevent off-topic questions

**Code Location:** `core/command_registry.py`, `ChatHandler` class, lines 631–776

**Code:**
```python
class ChatHandler(BaseHandler):
    description = "Interactive follow-up Q&A"
    aliases = ["chat"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        from core.llm_provider import provider

        console.print(Rule("Interactive Chat", style="bold cyan"))

        # Load last RCA — support both old and new result formats
        last_result = None
        try:
            with open(".last_rca.json") as f:
                last_result = json.load(f)
        except Exception:
            pass

        if not last_result:
            try:
                with open(".last_analyse.json") as f:
                    last_result = json.load(f)
            except Exception:
                pass

        if not last_result:
            console.print(
                "[yellow]No previous RCA found.\n"
                "Run 'analyse <service>' first, then use 'chat'.[/yellow]"
            )
            return "no-rca"

        # Build context from RCA + LLM conversation loop
        # ... (full interactive loop with history tracking)
```

**Actual Behavior (Error):**
```
$ python ai_sre.py analyze payment-service  # (fails due to openai)
$ python ai_sre.py chat
[yellow]No previous RCA found...
```

**Root Causes:**
1. No `.last_rca.json` is ever created (because `_handle_kubectl()` doesn't save it)
2. File mode analysis should save result to `.last_rca.json` but does NOT

**What it uses:**
- File input: `.last_rca.json` or `.last_analyse.json` (looks for both)
- Expects JSON with keys: {service, analysis, confidence, target_service, root_cause}
- Full conversat loop with:
  - User input validation (guardrails)
  - History tracking (max 10 turns)
  - LLM context injection (system prompt + conversation history)
  - "clear" command to reset history
  - "exit" to stop

**Expected Data Flow:**
```
1. analyze <service> runs
   ↓
2. Result dict saved to .last_rca.json:
   {
       "service": "payment-service",
       "analysis": "RCA narrative...",
       "confidence": 75,
       "windows_used": 1,
       "incident_record": {...}
   }
   ↓
3. User: chat
   ↓
4. Load .last_rca.json
   ↓
5. Build context with service + analysis
   ↓
6. Interactive loop:
       User -> Question
       ↓
       LLM -> Answer (with context + history)
       ↓
       Display answer
       ↓
       Save to history
```

**Missing Code:**
- `_handle_kubectl()` should do: `json.dump(result, open(".last_rca.json", "w"))`
- WindowAnalyzer result should do same
- Currently: NO result ever saved to file

---

## 4. DATA FLOW—DETAILED ARCHITECTURE

### Kubernetes Connection

**File:** `core/kubectl_client.py` (359 lines)

**Method:** Pure subprocess, no K8s Python client

**Low-level wrapper:**
```python
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
```

**All kubectl calls (30+ total):**
1. `kubectl get pods -n <ns> --selector app=<svc> --no-headers -o wide`
2. `kubectl get pods -n <ns> --no-headers` (name heuristic fallback)
3. `kubectl logs <pod> -n <ns> --tail=200 --timestamps=true`
4. `kubectl logs <pod> -n <ns> -c <container> --tail=200 --timestamps=true`
5. `kubectl logs <pod> -n <ns> --previous --tail=200` (CrashLoop recovery)
6. `kubectl get events -n <ns> --field-selector involvedObject.name=<pod> --sort-by=.lastTimestamp`
7. `kubectl describe pod <pod> -n <ns>` (event fallback)
8. `kubectl top nodes --no-headers`
9. `kubectl top pods -n <ns> -A` (all namespaces)
10. `kubectl top pods -n <ns>` (scoped)
11. `kubectl get pod <pod> -n <ns> -o jsonpath={.spec.nodeName}`
12. `kubectl describe node <node>`
13. `kubectl get endpoints <svc> -n <ns>`
14. `kubectl get virtualservice <svc> -n <ns> -o yaml`
15. `kubectl get deployments -n <ns> --no-headers`
16. `kubectl get pod <pod> -n <ns> -o jsonpath={.spec.containers[*].name}`

**Connection to Minikube:**
- Assumes `kubectl` is configured via `~/.kube/config`
- Namespace from `flags.py`: `K8S_NAMESPACE = env["SOURCE_NAMESPACE"]` (default: "default")
- kubectl commands run with `-n <namespace>` flag
- No explicit authentication—relies on existing kubeconfig

### Evidence Collection Pipeline

**File:** `core/kubectl_rca_investigator.py` (599 lines)

**Data Structure:**
```python
@dataclass
class RCAReport:
    target_service: str
    all_evidence: dict = field(default_factory=dict)  # stage_name → evidence_text
    dependency_reports: list = field(default_factory=list)  # [RCAReport, ...]
```

**Collection method (KubectlRCAInvestigator.investigate()):**
```python
def investigate(self, service_name, namespace, depth=0) -> RCAReport:
    evidence = {}
    
    # Stage 1
    pods = get_pods(namespace, service_name)
    evidence["pod_status"] = _pods_status_evidence(pods)
    pod_name = pods[0]["name"] if pods else None
    
    # Stage 2
    if pod_name:
        evidence["pod_events"] = get_pod_events(pod_name, namespace)
    
    # Stage 3
    if pod_name:
        containers = get_containers_for_pod(pod_name, namespace)
        log_map = get_all_container_logs(pod_name, namespace, containers, tail=200)
        evidence["pod_logs"] = "\n".join(f"[Container: {c}]\n{log}" for c, log in log_map.items())
    
    # Stage 4
    nodes = get_node_resources()
    cluster_pods = get_cluster_resource_pressure(namespace)
    evidence["resource_pressure"] = _resource_pressure_summary(nodes, cluster_pods)
    
    # Stage 4b
    if pod_name:
        node_name = get_pod_node(pod_name, namespace)
        if node_name:
            evidence["node_describe"] = get_node_describe(node_name)
            evidence["pod_node"] = node_name
    
    # Stage 5
    evidence["service_endpoints"] = get_service_endpoints(service_name, namespace)
    
    # Stage 6
    vs = get_virtual_service(service_name, namespace)
    if vs:
        evidence["virtual_service"] = vs
    
    # Stage 7
    dep_reports = []
    if depth < MAX_DEPENDENCY_DEPTH:
        deps = self._get_dependencies(service_name)
        for dep in deps:
            dep_namespace = self._get_dep_namespace(dep, namespace)
            dep_report = self._investigate_dependency(dep, dep_namespace)
            dep_reports.append(dep_report)
    
    return RCAReport(target_service=service_name, all_evidence=evidence, dependency_reports=dep_reports)
```

**Flattening for LLM (collect_all_evidence()):**
```python
def collect_all_evidence(report: RCAReport) -> str:
    sections = []
    ev = report.all_evidence
    
    def _add(label: str, content: str, limit: int = 2000):
        if content and content.strip() and "(no pods" not in content:
            sections.append(f"=== {label} ===\n{content[:limit]}")
    
    _add("POD STATUS",          ev.get("pod_status", ""),      500)
    _add("POD EVENTS",          ev.get("pod_events", ""),      2000)
    _add("POD LOGS",            ev.get("pod_logs", ""),        3000)
    _add("RESOURCE PRESSURE",   ev.get("resource_pressure",""), 800)
    _add("NODE CONDITIONS",     ev.get("node_describe", ""),   1000)
    _add("SERVICE ENDPOINTS",   ev.get("service_endpoints",""), 500)
    
    if ev.get("virtual_service"):
        _add("VIRTUAL SERVICE", ev.get("virtual_service", ""), 800)
    
    # Dependency evidence
    for dep_report in report.dependency_reports:
        dep_ev = dep_report.all_evidence
        dep_svc = dep_report.target_service
        dep_lines = []
        if dep_ev.get("pod_status"):
            dep_lines.append(dep_ev["pod_status"])
        if dep_ev.get("pod_events"):
            dep_lines.append(dep_ev["pod_events"][:500])
        if dep_ev.get("pod_logs"):
            dep_lines.append(dep_ev["pod_logs"][:800])
        if dep_lines:
            sections.append(f"=== DEPENDENCY: {dep_svc} ===\n" + "\n".join(dep_lines))
    
    return "\n\n".join(sections) if sections else "No evidence collected."
```

---

## 5. AI INTEGRATION

### LLM Provider

**File:** `core/llm_provider.py` (214 lines)

**Supported Providers:**
1. **Nvidia NIM** (Live API)
   - Base URL: `https://integrate.api.nvidia.com/v1`
   - Model: `meta/llama-3.3-70b-instruct` (reasoning)
   - Fallback: `mistralai/mistral-small-24b-instruct`
   - Auth: API key (NVIDIA_API_KEY)
   - Implementation: OpenAI-compatible client

2. **Ollama** (Local inference)
   - URL: `http://localhost:11434/api/generate`
   - Model: `phi3:mini` (configurable)
   - No auth needed
   - Streaming support

**Initialization:**
```python
class LLMProvider:
    def __init__(self):
        provider = (LLM_PROVIDER or "ollama").strip().lower()
        self.provider = "nvidia" if provider == "nvidia" else "ollama"

        if self.provider == "nvidia":
            from openai import OpenAI  # ← FAILS if not installed
            self._client = OpenAI(
                base_url=LLM_BASE_URL,
                api_key=NVIDIA_API_KEY,
            )

    def generate(self, prompt: str, system_prompt=None, stream=False) -> str:
        if self.provider == "nvidia":
            return self._generate_nvidia(prompt, system_prompt, stream, model)
        else:
            return self._generate_ollama(prompt, stream)
```

### Prompt Formatting

**For kubectl mode (current working):**
```python
def _build_kubectl_prompt(self, service: str, evidence_text: str) -> str:
    return f"""You are an expert Site Reliability Engineer performing root cause analysis.

Service: {service}
Source: Live Kubernetes cluster (kubectl)

--- KUBECTL EVIDENCE START ---
{evidence_text}
--- KUBECTL EVIDENCE END ---

Analyse this evidence and identify:
1. Root cause of any failures or anomalies
2. Sequence of events leading to failure
3. Affected services and impact
4. Recommended remediation steps

If everything appears healthy, clearly state there are no issues found
and provide any recommendations to improve reliability.

At the end of your analysis, you MUST include this block exactly:
CONFIDENCE: <number>%
REASON: <one sentence explaining your confidence level>

Confidence should reflect how complete the picture is:
- 80-100%: clear root cause, full evidence visible
- 60-79%: likely root cause but some gaps
- 40-59%: partial picture, more context needed
- below 40%: insufficient data or no issues found"""
```

**For file mode (baseline/compare):**
```python
# _build_prompt in WindowAnalyzer
def _build_prompt(self, lines: list[str], service: str, window_label: str) -> str:
    logs_str = "\n".join(lines)
    return f"""You are an expert Site Reliability Engineer performing root cause analysis.

Service: {service}
Window: {window_label}
Log lines: {len(lines)}

--- LOGS START ---
{logs_str}
--- LOGS END ---

Analyse these logs and identify:
1. Root cause of any failures or anomalies
2. Sequence of events leading to failure
3. Affected services and impact
4. Recommended remediation steps

At the end of your analysis, you MUST include this block exactly:
CONFIDENCE: <number>%
REASON: <one sentence explaining your confidence level>

Confidence should reflect how complete the picture is:
- 80-100%: clear root cause, full failure sequence visible
- 60-79%: likely root cause but some gaps in evidence
- 40-59%: partial picture, more log context needed
- below 40%: insufficient data, cannot determine root cause"""
```

**Context Injection:**
- **Kubectl:** Injects 7 stages of evidence (status, events, logs, metrics, endpoints, istio, dependencies)
- **File:** Injects sliding window of logs (500 lines per window, max 2 windows)
- Both expect response with explicit CONFIDENCE: XX% + REASON block

---

## 6. BASELINE/COMPARE STORAGE

### Baseline Data

**Current:** NOT saved to disk or database

**Directory:** Should be `logs/baseline/` (NOT created)

**Expected Schema:**
```
logs/baseline/
├── baseline_payment-service_20260525_143015.json
├── baseline_user-service_20260525_144030.json
└── ...

Each file:
{
    "service": "payment-service",
    "timestamp": "2026-05-25T14:30:15",
    "analysis": "LLM text response...",
    "confidence": 65,
    "model": "meta/llama-3.3-70b-instruct",
    "provider": "nvidia"
}
```

### Comparison Report Data

**Location:** `reports/compare_<service>_YYYYMMDD_HHMMSS.txt`

**Code that creates it:**
```python
def _save_compare_report(service, rag_result, baseline_response) -> str:
    import datetime
    import os
    os.makedirs("reports", exist_ok=True)
    report_path = f"reports/compare_{service}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    sim = rag_result.get('incident_record', {}).get('similarity_score', 0.0)
    
    content = f"""# Comparison Report
# Service: {service}
# Generated: {datetime.datetime.now().isoformat()}

## RAG Mode
Confidence: {rag_result.get('confidence')}%
Windows used: {rag_result.get('windows_used')}

{rag_result.get('analysis')}

## Baseline Mode (no RAG)

{baseline_response}

## Summary
RAG confidence:      {rag_result.get('confidence')}%
Incident saved:      {rag_result.get('incident_record', {}).get('saved', False)}
Similarity score:    {sim:.1%}"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    return report_path
```

### Incident Storage (RAG Historical)

**Location:** `logs/historical/<incident_id>.txt`

**Schema:**
```python
def _build_incident_text(self, incident_id: str, analysis: str, service: str, lines: list[str]) -> str:
    lines_text = chr(10).join(lines[:50])
    return f"""# Incident: {incident_id} (auto-saved)
# Service: {service}
# Timestamp: {datetime.datetime.now().isoformat()}

## Analysis

{analysis}

## Sample Logs (first 50 lines)

{lines_text}
"""
```

**ChromaDB Index:** `.chromadb/` (Hidden db for vector search)

---

## 7. CLI INTERFACE

**No Click/argparse—Custom resolver instead**

**File:** `core/command_registry.py` + `ai_sre.py`

**Entry point:** `ai_sre.py` (113 lines)

**Interactive shell with command registry:**
```python
def main():
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:]).strip()
        if text:
            _run_input(text)
        return

    print_banner()

    while True:
        try:
            console.print("[bold cyan]ai-sre>[/bold cyan] ", end="")
            user_input = input().strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        _run_input(user_input)
```

**Command registry (resolve function):**
```python
def resolve(user_input: str) -> Optional[tuple[BaseHandler, list[str]]]:
    text = (user_input or "").strip()
    if not text:
        return None

    words = text.split()
    first = words[0].lower()

    # Tier 1: exact match
    if first in REGISTRY:
        return REGISTRY[first], words[1:]

    # Tier 2: fuzzy command match
    fuzzy = _fuzzy_match_command(first)
    if fuzzy:
        confirmed = _prompt_did_you_mean(first, fuzzy)
        if confirmed:
            return REGISTRY[fuzzy], words[1:]
        return None

    # Tier 3: keyword confidence scoring
    keyword_command = _keyword_scored_command(text)
    if keyword_command and keyword_command in REGISTRY:
        if keyword_command == "explain":
            return REGISTRY[keyword_command], [text]
        return REGISTRY[keyword_command], words

    return None
```

**Registered Handlers:**
```python
REGISTRY: dict[str, BaseHandler] = {
    "analyse": AnalyseHandler(),
    "analyze": AnalyseHandler(),
    "status": StatusHandler(),
    "compare": CompareHandler(),
    "watch": WatchHandler(),
    "chat": ChatHandler(),
    "explain": ExplainHandler(),
    "clean": CleanHandler(),
    "clean-logs": CleanLogsHandler(),
    "help": HelpHandler(),
}
```

### Argument Parsing

**Analyze command:**
```
$ ai-sre analyze <service> [--baseline] [--compare]
```

**Parser (manual):**
```python
class AnalyseHandler(BaseHandler):
    def handle(self, args: list[str]) -> str:
        args_str = " ".join(args)
        parts = args_str.strip().split()
        baseline_mode = "--baseline" in parts
        compare_mode  = "--compare"  in parts
        service_parts = [p for p in parts if not p.startswith("--")]
        service = "-".join(service_parts) if service_parts else None
```

**Other commands (no args):**
- `status` — system health check
- `chat` — interactive follow-up (uses .last_rca.json)
- `help` — show command reference
- `explain <concept>` — SRE knowledge Q&A

---

## 8. ERROR OUTPUT & ROOT CAUSES

### Error 1: `--baseline` Mode

```
$ python ai_sre.py analyze payment-service --baseline
Error: No module named 'openai'
Type 'help' for commands.
```

**Root Cause Chain:**
```
AnalyseHandler.handle() → USE_KUBERNETES=false (file mode)
  ↓
analyze payment-service --baseline → baseline_mode=True
  ↓
provider.generate(prompt)
  ↓
LLMProvider.__init__() → LLM_PROVIDER="nvidia"
  ↓
from openai import OpenAI ← MISSING
  ↓
ModuleNotFoundError: No module named 'openai'
```

**Fix:** Add to `requirements.txt`:
```
openai>=1.0.0
```

### Error 2: `--compare` Mode

```
$ python ai_sre.py analyze payment-service --compare
Error: No module named 'openai'
```

**Root Cause:** Same as Error 1

### Note on `--chat` Mode

```
$ python ai_sre.py chat
[yellow]No previous RCA found...
```

**Root Cause Chain:**
```
ChatHandler.handle()
  ↓
Try to load .last_rca.json
  ↓
FileNotFoundError (file doesn't exist)
  ↓
Try to load .last_analyse.json
  ↓
FileNotFoundError (file doesn't exist either)
  ↓
Return "no-rca"
```

**Why files don't exist:**
- `_handle_kubectl()` never creates `.last_rca.json`
- File mode analysis never creates `.last_rca.json` either
- Missing code: `json.dump(result, open(".last_rca.json", "w"))`

---

## 9. DEPENDENCIES

**File:** `requirements.txt`

```
click>=8.1.0
rich>=13.0.0
requests>=2.31.0
ollama>=0.1.0
sentence-transformers>=2.2.0
chromadb>=0.4.0
numpy>=1.24.0
pyyaml>=6.0.0
```

**MISSING (causes failures):**
```
openai>=1.0.0         # Required for Nvidia NIM integration
```

**Python Version:** 3.12+ (checked in main.py)

```python
def check_python_version():
    if sys.version_info < (3, 12):
        log.error(f"Python 3.12+ required. You are on {sys.version}")
        sys.exit(1)
```

**Current Environment:**
- Active: `jarvis/Scripts/activate` (Poetry venv)
- Python: 3.12+
- Packages: listed above + site-packages in jarvis/

---

## 10. EXPECTED END-TO-END BEHAVIOR (Definition of Done)

### Feature: `--baseline` Mode (File-Based)

**When implemented, should do:**

```
$ python ai_sre.py analyze payment-service --baseline
Loading logs for payment-service...
Generating baseline analysis (no RAG)...

═══════════════════════════════════════════════════════════
Status Analysis — BASELINE (no RAG) Mode
───────────────────────────────────────────────────────────
Service      : payment-service
Source       : logs/test.log
Log lines    : 500
Confidence   : 58%
Mode         : LLM-only (no vector retrieval)

╭─ Baseline Analysis ─────────────────────────────────────╮
│ The payment-service logs show repeated timeout errors...
│ Root Cause: Database connection pool exhaustion
│ Confidence: 58%
│ Reason: Some context gaps without historical data
╰─────────────────────────────────────────────────────────╯

[dim]Baseline report saved to: logs/baseline/baseline_payment-service_20260525_143015.json[/dim]
```

**Success Criteria:**
- Accepts `--baseline` flag without error
- Produces LLM analysis WITHOUT RAG query
- Saves baseline report to `logs/baseline/<filename>.json`
- Report contains: service, analysis, confidence, model, provider

### Feature: `--compare` Mode (Side-by-Side)

**When implemented, should do:**

```
$ python ai_sre.py analyze payment-service --compare
Running RAG analysis...
Running baseline analysis...

═══════════════════════════════════════════════════════════
Comparison Report Generated
───────────────────────────────────────────────────────────

Comparison report saved to: reports/compare_payment-service_20260525_143030.txt

RAG Mode Analysis:
  Confidence: 75%
  Windows used: 1
  Analysis: [full RAG narrative]

Baseline Mode Analysis:
  Confidence: 58%
  Analysis: [full baseline narrative]

Summary:
  RAG is 17% more confident
  Incident saved: No
  Historical match: 65% similarity

[dim]Detailed comparison saved to reports/compare_payment-service_20260525_143030.txt[/dim]
```

**Success Criteria:**
- Runs both RAG + Baseline analyses
- Saves comparison report to `reports/compare_*.txt`
- Report shows side-by-side comparison
- Shows confidence delta
- Identifies which mode is more useful

### Feature: `--chat` Mode (Interactive Follow-up)

**When implemented, should do:**

```
$ python ai_sre.py analyze payment-service
[... runs analysis, saves to .last_rca.json ...]

$ python ai_sre.py chat
Loading last RCA for payment-service...

════════════════════════════════════════════════════════╗
                   Interactive Chat                     ║
════════════════════════════════════════════════════════╝

[dim]Chatting about: payment-service (confidence: 75%)[/dim]
[dim]Type 'exit' to leave, 'clear' to reset history[/dim]

ai-sre> what is the root cause?
SRE-AI> The root cause is database connection pool exhaustion...

ai-sre> what pods are affected?
SRE-AI> The affected pod is payment-service-abc123, which is...

ai-sre> what should i do?
SRE-AI> Recommended steps:
  1. Increase connection pool size in deployment
  2. Monitor connection usage...

ai-sre> exit
[dim]Chat ended.[/dim]
```

**Success Criteria:**
- Loads `.last_rca.json` from previous analyze run
- Maintains conversation history (max 10 turns)
- Provides context-aware answers
- Prevents off-topic questions (guardrails)
- Supports "clear" to reset history
- Supports "exit" to quit

---

## SUMMARY TABLE

| Feature | Status | Issue | Fix |
|---------|--------|-------|-----|
| `analyze` (kubectl mode) | ✅ Working | — | — |
| `--baseline` | ❌ Broken | Missing `openai` pkg | Add to requirements.txt |
| `--compare` | ❌ Broken | Missing `openai` pkg | Add to requirements.txt |
| `--chat` | ⚠️ Broken | No .last_rca.json saved | Add `json.dump()` calls in handlers |
| RAG indexing | ✅ Working | — | — |
| ChromaDB storage | ✅ Working | — | — |
| Kubectl integration | ✅ Working | — | — |
| LLM caching | ✅ Working | — | — |
| Service graph lookup | ✅ Working | — | — |

---

**Report Generated:** May 25, 2026  
**Analysis by:** GitHub Copilot
