# Repo Context / Current Status

## Summary
This repository is an **AI-assisted SRE Root Cause Analysis (RCA) tool** focused on **Kubernetes microservices** incidents. It ingests incident evidence from **logs** (optionally Kubernetes-native data), structures that evidence, optionally **augments analysis with historical incidents via RAG**, and then calls an **LLM** to generate a structured RCA (root cause, affected services, failure chain, and remediation steps). A Rich terminal UI presents results.

The repo also includes an **interactive assistant** (`ai_sre.py`) that can answer SRE-domain questions and (depending on the command resolution logic) trigger RCA flows.

## Current Status (what is “working” right now)
From the existing entry points and core pipeline code, the repo currently supports:

- **Batch RCA pipeline** through `python main.py analyze ...`
  - Loads log lines from a file (default) or from Kubernetes when enabled.
  - Parses and filters log evidence by severity/service.
  - Collects resource/status data per service (mock by default, real Kubernetes when enabled).
  - Builds an LLM-ready context payload including:
    - formatted log excerpts
    - formatted resource summary
    - a computed “failure chain” and incident window
    - optional Kubernetes-derived RCA findings snapshot
  - Runs LLM analysis in either:
    - **baseline** mode (logs/resources only)
    - **rag** mode (adds historical similar incidents)
  - Outputs Rich dashboards (default) or JSON/plain output.

- **RAG support**:
  - `core/rag_engine.py` indexes `logs/historical/*.log` into **ChromaDB** using embeddings.
  - It retrieves top similar chunks by cosine similarity and formats historical resolution snippets for prompt injection.

- **LLM response caching**:
  - `core/llm_cache.py` is used by `core/llm_analyzer.py` to avoid repeated calls for identical prompts.

- **Operational CLI commands**:
  - `python main.py status` checks:
    - Python runtime
    - Ollama connectivity
    - ChromaDB presence/index stats
    - default log file presence
    - last RCA availability
    - LLM cache stats
  - `python main.py watch ...` polls a log file for new errors and triggers RCA when thresholds/cooldowns are met.
  - `python main.py compare ...` runs baseline vs RAG and can save an evaluation report.
  - `python main.py chat` loads last analysis result and performs follow-up questions grounded in the last RCA.

- **Kubernetes-aware extension (gated by flags)**:
  - `main.py` exposes a `k8s` command group that delegates to `k8s/command_handler.py`.
  - `--source` / Kubernetes behavior is controlled by flags such as `SOURCE_KUBERNETES` / `USE_KUBERNETES`.
  - There are commands for listing pods/deployments/events, pulling logs, generating RCA for one/all services, plus guarded simulation/rollback helpers.

## How the repo is structured
Key directories/files:

- `main.py`
  - Production CLI entry point using Click.
  - Implements `analyze`, `status`, `watch`, `compare`, `chat`, and Kubernetes subcommands.
  - Orchestrates the full RCA pipeline via `run_pipeline()`.

- `core/`
  - Domain logic modules for the pipeline:
    - `log_loader.py`: load logs from files and/or Kubernetes
    - `log_processor.py`: parse/filter logs and compute summaries/failure chains
    - `resource_collector.py`: get per-service resource/status data (mock or Kubernetes)
    - `context_builder.py`: turn logs+resources into formatted context for LLM prompts
    - `llm_analyzer.py`: build baseline/RAG prompts, call LLM provider, parse structured responses, cache results
    - `rag_engine.py`: ChromaDB indexing and similarity retrieval of historical incidents
    - `llm_cache.py`: persistent JSON caching for LLM responses
    - `llm_provider.py`: LLM provider abstraction (used by analyzer)
    - `service_discovery.py`, `service_graph.py`, `sre_investigator.py`, `window_analyzer.py`: supporting investigation logic

- `output/rca_formatter.py`
  - Rich UI formatting for RCA results (resource tables, RCA panels, etc.).

- `k8s/`
  - Kubernetes-native helpers: command execution, collectors, model definitions, graph updates, simulators.
  - RCA logic for Kubernetes snapshots lives in `k8s/rca_engine.py`.

- `evaluation/`
  - Evaluation utilities (baseline vs RAG comparison).

- `logs/`
  - Test and historical incident data.
  - `logs/historical/incident_00*.log` are used for RAG (contain header metadata like incident/resolution).

- `docs/`
  - Developer/dissertation documentation.

## Current functionality (what the tool does)

### 1) `analyze` (core RCA)
Command (from README):
- `python main.py analyze logs/test.log --mode rag --severity ERROR` (parameters vary)

Pipeline steps (from `main.py::run_pipeline()`):
1. **Load logs**
   - via `LogLoader.load_auto(...)` (file mode by default)
2. **Process logs**
   - `LogProcessor.process(lines)`
   - filter by severity and optionally service
   - compute summary: error counts and set of affected services
3. **Collect resources**
   - `ResourceCollector.get_resources(services, ...)`
   - compute critical services
4. **Build LLM context**
   - `ContextBuilder.build(filtered_entries, resources)`
   - generates formatted logs/resources strings + failure chain + incident window
   - attempts to add Kubernetes RCA findings if present in the resource snapshot
5. **(Optional) RAG retrieval**
   - `RAGEngine.retrieve(context['formatted_logs'], top_k=3)`
   - `RAGEngine.format_retrieved_context(...)`
6. **LLM analysis**
   - baseline: `LLMAnalyzer.analyze_baseline(context, query=...)`
   - rag: `LLMAnalyzer.analyze_rag(context, rag_context, query=...)`
   - parses the LLM response into a structured dictionary
7. **Return and format output**
   - enrich with incident summary, services found, critical pods, resources, etc.
   - print via Rich formatter or output JSON/plain.

### 2) `watch` (live monitoring)
- `python main.py watch logs/some.log --severity ERROR --threshold 3 --mode rag`

Behavior:
- polls the file for new lines
- extracts entries and checks severity
- triggers RCA when enough new error lines are detected
- uses cooldown to avoid repeated LLM calls

### 3) `chat` (follow-up Q&A)
- `python main.py chat`

Behavior:
- loads `.last_rca.json` saved from the most recent `analyze`
- injects a “system context” containing the last root cause, failure chain, fixes, and summary
- allows additional grounded questions about the incident

### 4) `status`
- `python main.py status`

Reports:
- Python version
- whether Ollama is reachable
- ChromaDB index stats
- test log existence
- last RCA availability
- LLM cache stats

### 5) Kubernetes mode (gated)
If `SOURCE_KUBERNETES` is enabled:
- `python main.py k8s status` and other `k8s` subcommands become active.
- The pipeline can collect logs/resources via Kubernetes instead of files/mocks.

## Configuration / Flags
Flags are primarily loaded from `.env` via `flags.py` (manual parsing, no `python-dotenv`).

Important categories:
- LLM:
  - `LLM_REASONING_MODEL`, `OLLAMA_URL`, `OLLAMA_MODEL`
  - `LLM_CACHE_ENABLED`, `LLM_CACHE_TTL_SECONDS`
- RCA pipeline:
  - `LOG_WINDOW_SIZE`, `LOG_TAIL_LINES`
  - `RAG_ENABLED`, `RAG_TOP_K`, `RAG_SIMILARITY_THRESHOLD`
- Kubernetes gating:
  - `SOURCE_KUBERNETES`, `SOURCE_NAMESPACE`, `KUBE_NAMESPACES`
- UI behavior:
  - `UI_RICH_OUTPUT`, `UI_SUPPRESS_LOGS`

## Notable implementation details
- **Structured LLM contract**: `LLMAnalyzer` requires the model to output fields in an exact format, then parses with regex fallbacks.
- **Prompt shaping**: `ContextBuilder` truncates and formats logs/resources into compact “LLM prompt safe” blocks.
- **RAG chunking/indexing**:
  - historical log files are chunked by lines (overlapping chunks)
  - each chunk is embedded and stored with metadata (incident type/resolution/root cause).
- **Cache-first**: analyzer checks `LLMCache` before calling the LLM.

## Current repo limitations / roadmap signals (from existing docs)
The repo contains documentation and TODOs indicating future improvements (e.g., more comprehensive real Kubernetes integrations, better testing, additional evaluation/visualization). Current functionality is centered around the batch pipeline and RAG indexing/retrieval with mocks or gated Kubernetes behavior.

