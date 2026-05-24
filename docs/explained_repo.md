# SRE-RCA-Tool: AI-Powered Kubernetes Root Cause Analysis

## Project Overview

**Purpose**: SRE-AI is an intelligent Root Cause Analysis (RCA) tool for Kubernetes microservices incidents. It analyzes logs, resource metrics, Kubernetes events, and historical incidents to automatically identify failure patterns, root causes, and remediation steps. Designed for production SRE teams to reduce MTTR (Mean Time To Resolution).

**Key Features**:
- **Multi-source data collection**: Logs, kubectl describe/events/top, service graphs, historical RAG
- **AI-powered analysis**: phi3:mini LLM (Ollama) + rule-based pattern detection
- **RAG augmentation**: Similarity search against historical incidents
- **Interactive shell**: Natural language commands (`analyze payment-service`, `why is db failing?`)
- **Rich CLI UI**: Color-coded dashboards, timelines, remediation steps
- **Mock/real toggle**: Works without Kubernetes for demos

**Architecture**: Modular Python monorepo with `core/` domain logic, `main.py`/`ai_sre.py` CLIs, Rich TUI, LLM caching, ChromaDB RAG.
# SRE-RCA-Tool: Updated Repository Explanation (May 2026)

## Project Overview

SRE-RCA-Tool is an AI-assisted incident investigation framework for Kubernetes microservices. It combines:
- rule-based pattern detection,
- LLM analysis,
- historical incident retrieval (RAG),
- and service dependency/blast-radius reasoning.

The current user-facing entry is `python ai_sre.py` (interactive shell). Internally, command execution is handled by `core/command_registry.py` handlers.

---

## What Changed vs Older Architecture

This file has been updated to reflect the current codebase:
- ✅ Command registry pattern (`BaseHandler` + `REGISTRY`) is now central.
- ✅ `ai_sre.py` uses `resolve()` and handler dispatch (not `NLParser` classes).
- ✅ No `config.py` in current root architecture; runtime config is in `flags.py` + `.env`.
- ✅ Kubectl RCA flow is implemented in `core/kubectl_rca_investigator.py` with staged evidence collection.
- ✅ Sliding-window analysis and incident recording are active (`window_analyzer.py`, `incident_recorder.py`).

---

## Entry Points

### 1) `ai_sre.py` (primary)
Interactive shell:
1. Reads user input.
2. Calls `resolve(user_input)` from `core.command_registry`.
3. Executes `handler.handle(args)` for matched commands.
4. Falls back to `provider.generate(...)` for in-scope SRE Q&A.

### 2) `main.py` (Click CLI + helpers)
Provides commands like:
- `analyze`
- `status`
- `kubectl_analyze`
- `watch`
- `cache`
- `compare`
- `chat`

Also contains `run_pipeline(...)` used by compare/watch flows.

---

## Current Command Layer (`core/command_registry.py`)

Key handlers:
- `AnalyseHandler`
- `StatusHandler`
- `CompareHandler`
- `WatchHandler`
- `ChatHandler`
- `ExplainHandler`
- `CleanHandler`
- `CleanLogsHandler`
- `HelpHandler`

Primary registry map:
- `analyse` / `analyze`
- `status`
- `compare`
- `watch`
- `chat`
- `explain`
- `clean`
- `clean-logs`
- `help`

Key output helpers:
- `_print_analysis_result(...)`
- `_print_baseline_result(...)`
- `_save_compare_report(...)`

---

## Core Module Map (`core/`)

| File | Role | Key Symbols |
|---|---|---|
| `command_registry.py` | Interactive command dispatch + handlers | `BaseHandler`, `REGISTRY`, `resolve` |
| `llm_provider.py` | Unified generation/embedding provider (NVIDIA/Ollama) | `LLMProvider.generate`, `LLMProvider.embed`, `provider` |
| `llm_analyzer.py` | Prompt builders + LLM response parsing | `analyze_baseline`, `analyze_rag`, `analyze_investigation` |
| `llm_cache.py` | Cache LLM responses on disk | `LLMCache.get/set/stats/clear` |
| `log_loader.py` | Load from file/kubectl/mock sources | `load_auto`, `load_from_kubectl`, `load_service_logs` |
| `log_cleaner.py` | Filter noise from logs | `LogCleaner.clean`, `get_stats` |
| `log_processor.py` | Parse and structure logs | `process`, `filter_by_severity`, `get_summary` |
| `context_builder.py` | Build LLM-ready context | `build`, `format_logs_for_prompt` |
| `resource_collector.py` | Mock/live resource metrics | `get_resources`, `get_real_resources` |
| `rag_engine.py` | ChromaDB indexing + retrieval | `RAGEngine.retrieve`, `_index_historical_logs` |
| `incident_recorder.py` | Known/new incident decision + persistence | `check_and_save`, `_query_similarity` |
| `window_analyzer.py` | Sliding-window RCA | `WindowAnalyzer.analyse` |
| `kubectl_client.py` | Kubectl subprocess wrappers | `get_pods`, `get_pod_events`, `get_service_endpoints`, etc. |
| `kubectl_rca_investigator.py` | Staged live RCA evidence pipeline | `run_kubectl_rca`, `collect_all_evidence`, `PATTERNS` |
| `service_graph.py` | Service dependency graph + blast radius | `get_blast_radius`, `discover_from_logs` |
| `service_discovery.py` | Assist unknown service/namespace matching | `find_matches`, `prompt_for_namespace` |
| `sre_investigator.py` | Deep multi-service investigation model | `SREInvestigator.investigate`, `PatternDetector` |
| `logger.py` | Shared logger + noisy-lib suppression | `SRELogger`, `get_logger` |

---

## Two Investigation Pipelines

### A) File Mode (`SOURCE_KUBERNETES=false`)
Used by `analyse <service>` in interactive shell:
1. `LogLoader.load_service_logs(service)`
2. `WindowAnalyzer.analyse(lines, service=...)`
3. Confidence from `CONFIDENCE: <n>%`
4. Optional merged second window if low confidence
5. `IncidentRecorder.check_and_save(...)`
6. `_print_analysis_result(...)`

### B) Kubectl Live Mode (`SOURCE_KUBERNETES=true`)
Used by `AnalyseHandler._handle_kubectl(...)`:
1. Resolve service (services.yaml + cluster fallback)
2. `run_kubectl_rca(service, namespace, service_graph)`
3. `collect_all_evidence(report)`
4. LLM narrative via `provider.generate(...)`
5. Parse confidence from response
6. `IncidentRecorder.check_and_save(...)` (RAG/compare branches)
7. Print + report save (if compare)

Kubectl staged evidence collection (`KubectlRCAInvestigator.investigate`):
1. Pod Status
2. Pod Events
3. Pod Logs
4. Cluster Resources
5. Node Describe
6. Service Endpoints
7. VirtualService

---

## Data + Config Layers

### `flags.py`
Single source for runtime flags loaded from `.env` + environment variables.
Includes:
- provider/model settings,
- source mode (`SOURCE_KUBERNETES`),
- RAG thresholds,
- cache/warmup controls,
- path defaults (`CHROMA_DB_PATH`, `HISTORICAL_LOGS_DIR`).

### `services.yaml`
Service topology schema with per-service fields such as:
- `namespace`
- `depends_on`
- `exposes_to`
- `containers`
- `dependency_confidence`

Used by `ServiceGraph` and kubectl analyze resolution flow.

### `logs/`
- `logs/test.log` (fallback test source)
- `logs/services/*.log` (per-service file mode inputs)
- `logs/historical/*.log` (incident memory)
- `logs/mock/kubectl/*` (mock evidence scenarios)
- `logs/baseline/*` (baseline compare snapshots)

### Vector store
- ChromaDB path: `.chromadb` (default)
- Collection: `sre_historical_incidents_v1`

---

## Tech Stack (Current)

From `requirements.txt` + `setup.py` + imports:
- Python 3.12+
- `click`
- `rich`
- `requests`
- `ollama`
- `chromadb`
- `sentence-transformers`
- `numpy`
- `pyyaml`
- OpenAI-compatible client path for NVIDIA NIM (`from openai import OpenAI` in `core/llm_provider.py`)

---

## Evaluation + Output Modules

- `evaluation/comparator.py`: Baseline vs RAG output comparison (`Comparator.compare`)
- `output/rca_formatter.py`: Rich rendering for RCA/investigation output
- `reports/compare_*.txt`: generated compare reports

---

## Practical Strengths

- Command-registry architecture is easy to extend (new command = new handler + registry entry).
- Supports both demo/offline and live cluster workflows.
- Incident memory avoids repeating same RCA for known issues.
- Compare mode supports dissertation-style evidence of RAG contribution.
- Guardrails are present in chat/out-of-scope checks.

---

## Suggested Next Documentation Sync

If you keep this file as the "quick repo explainer", keep it in sync with:
- `docs/v3/developer_guide.md` (deep technical reference)
- `README.md` (public overview)
- `docs/v3/dissertation_report.md` (research narrative)

