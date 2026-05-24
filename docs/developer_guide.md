# Developer Guide (v3)

## 1) Environment setup

### Python + venv
```bash
cd /c/playground/sre-rca-tool
python -m venv jarvis
source jarvis/Scripts/activate
pip install -r requirements.txt
```

### Required runtime files
- `.env` (or environment variables)
- `services.yaml`
- `logs/` data (`logs/test.log`, `logs/services/*.log`, or live cluster)

### `.env` variables (from `flags.py`)

#### System/UI
- `SYSTEM_DEBUG` (default `false`)
- `SYSTEM_LOG_LEVEL` (default `INFO`)
- `UI_SUPPRESS_LOGS` (default `true`)
- `UI_RICH_OUTPUT` (default `true`)
- `UI_SHOW_TIMESTAMPS` (default `true`)

#### LLM/provider
- `LLM_CACHE_ENABLED` (`true`)
- `LLM_CACHE_TTL_SECONDS` (`3600`)
- `LLM_WARMUP_ON_START` (`true`)
- `LLM_KEEP_ALIVE` (`true`)
- `LLM_MAX_TOKENS` (`2000`)
- `LLM_TIMEOUT_SECONDS` (`300`)
- `LLM_PROVIDER` (`ollama`)
- `NVIDIA_API_KEY` (`""`)
- `LLM_BASE_URL` (`https://integrate.api.nvidia.com/v1`)
- `LLM_REASONING_MODEL` (`meta/llama-3.3-70b-instruct`)
- `LLM_REASONING_FALLBACK` (`mistralai/mistral-small-24b-instruct`)
- `LLM_EMBEDDING_MODEL` (`nvidia/nv-embed-v1`)
- `LLM_EMBEDDING_FALLBACK` (`nvidia/llama-nemotron-embed-1b-v2`)
- `OLLAMA_URL` (`http://localhost:11434/api/generate`)
- `OLLAMA_MODEL` (`phi3:mini`)

#### Source/RAG/paths
- `DEMO_MODE` (`false`)
- `LOG_WINDOW_SIZE` (`500`)
- `LOG_CONFIDENCE_THRESHOLD` (`60`)
- `LOG_FILTER_PATTERNS` (`health,metrics,ready,live,heartbeat`)
- `RAG_NEW_INCIDENT_THRESHOLD` (`40`)
- `SOURCE_KUBERNETES` (`false`)
- `SOURCE_NAMESPACE` (`default`)
- `SOURCE_LOG_TAIL_LINES` (`100`)
- `RAG_ENABLED` (`true`)
- `RAG_TOP_K` (`3`)
- `RAG_SIMILARITY_THRESHOLD` (`60`)
- `HISTORICAL_LOGS_DIR` (`logs/historical`)
- `CHROMA_DB_PATH` (`.chromadb`)
- `SOURCE_LOG_PATH` (`logs/test.log`)
- `EMBEDDING_MODEL` (`nvidia/nv-embed-v1`)

---

## 2) Entry points

## `ai_sre.py` (primary interactive entry)
- Main loop in `main()` prints banner and reads `ai-sre>` input.
- Dispatch path:
  1. `_run_input(user_input)`
  2. `resolve(user_input)` from `core.command_registry`
  3. `(handler, args) -> handler.handle(args)`
- If no command is resolved and query is in-scope, fallback uses `_answer_sre_question()` with `provider.generate()`.

## `main.py` (Click CLI + shared pipeline)
- Provides Click commands: `analyze`, `status`, `kubectl_analyze`, `watch`, `cache`, `compare`, `chat`.
- Core helper `run_pipeline(...)` builds classic pipeline:
  - `LogLoader.load_auto` → `LogProcessor` → `ResourceCollector` → `ContextBuilder` → `LLMAnalyzer` (+ optional `RAGEngine`).

---

## 3) Module reference (`core/`)

Below, each module includes purpose, key symbols, main imports, and common importers.

## `core/command_registry.py`
- Purpose: Interactive command dispatch + handler implementations for `ai_sre.py`.
- Key symbols:
  - `class BaseHandler(ABC)` with `handle(self, args: list[str]) -> str`
  - `class AnalyseHandler`, `StatusHandler`, `CompareHandler`, `WatchHandler`, `ChatHandler`, `ExplainHandler`, `CleanHandler`, `CleanLogsHandler`, `HelpHandler`
  - `REGISTRY: dict[str, BaseHandler]`
  - `resolve(user_input: str) -> Optional[tuple[BaseHandler, list[str]]]`
  - `is_out_of_scope(text: str) -> bool`
  - Output helpers: `_print_analysis_result`, `_print_baseline_result`, `_save_compare_report`
- Imports: `yaml`, `rich.*`, flags (`USE_KUBERNETES`, `K8S_NAMESPACE`) and many lazy imports from `core/*`.
- Imported by: `ai_sre.py`.

## `core/context_builder.py`
- Purpose: Convert parsed logs/resources to LLM-ready context.
- Key symbols:
  - `class ContextBuilder`
  - `build(self, filtered_entries: list[dict], resources: dict) -> dict`
  - `format_logs_for_prompt(self, entries: list[dict]) -> str`
  - `format_resources_for_prompt(self, resources: dict) -> str`
  - `get_incident_summary(self, context: dict) -> str`
- Imports: `core.log_processor.LogProcessor`, `core.resource_collector.ResourceCollector`, logger.
- Imported by: `main.py`, `core/llm_analyzer.py` (self-test block).

## `core/incident_recorder.py`
- Purpose: Decide if an incident is new, persist to disk, and embed into ChromaDB.
- Key symbols:
  - `class IncidentRecorder`
  - `check_and_save(self, analysis: str, service: str, lines: list[str]) -> dict`
  - `_query_similarity(self, analysis: str) -> float`
  - `_embed_in_chromadb(self, incident_id: str, analysis: str, service: str) -> bool`
  - `_purge_and_reload(self)` for dimension mismatch healing
  - `_is_dim_error(exc: Exception) -> bool`
- Imports: `core.rag_engine.RAGEngine`, `core.llm_provider.provider`, logger.
- Imported by: `core/window_analyzer.py`, `core/command_registry.py`.

## `core/kubectl_client.py`
- Purpose: Unified kubectl subprocess wrappers.
- Key symbols:
  - `get_pods(namespace: str, service_name: str) -> list[dict]`
  - `get_pod_events(pod_name: str, namespace: str) -> str`
  - `get_pod_logs(..., previous: bool = False) -> str`
  - `get_all_container_logs(...) -> dict[str, str]`
  - `get_node_resources() -> list[dict]`
  - `get_cluster_resource_pressure(namespace: Optional[str] = None) -> list[dict]`
  - `get_deployment_list(namespace: str) -> list[str]`
  - `get_service_endpoints(service_name: str, namespace: str) -> str`
  - `get_virtual_service(service_name: str, namespace: str) -> str`
  - `get_pod_node(pod_name: str, namespace: str) -> str`
  - `get_node_describe(node_name: str) -> str`
- Imports: `subprocess`, logger.
- Imported by: `core/kubectl_rca_investigator.py`, `core/command_registry.py`, `core/service_graph.py`.

## `core/kubectl_rca_investigator.py`
- Purpose: Live Kubernetes evidence collector + pattern detector for RCA.
- Key symbols:
  - `PATTERNS` (regex, cause label, confidence, suggested fixes)
  - `detect_patterns(text: str) -> Optional[tuple[str, int, list[str]]]`
  - `@dataclass RCAFinding`
  - `@dataclass RCAReport`
  - `class KubectlRCAInvestigator`
  - `investigate(self, service_name: str, namespace: str = "default", depth: int = 0) -> RCAReport`
  - `collect_all_evidence(report: RCAReport) -> str`
  - `run_kubectl_rca(service_name: str, namespace: str = "default", service_graph=None) -> RCAReport`
- Imported by: `core/command_registry.py`, `main.py`.

## `core/llm_analyzer.py`
- Purpose: Prompt building, LLM call orchestration, response parsing for baseline/RAG/investigation modes.
- Key symbols:
  - `class LLMAnalyzer`
  - `build_baseline_prompt(self, context: dict) -> str`
  - `analyze_baseline(self, context: dict, query: str = "") -> dict`
  - `build_rag_prompt(self, context: dict, rag_context: str) -> str`
  - `analyze_rag(self, context: dict, rag_context: str, query: str = "") -> dict`
  - `build_investigation_prompt(self, report: InvestigationReport, summary_text: str) -> str`
  - `analyze_investigation(self, report, investigator=None, query: str = "") -> dict`
  - `analyse_with_windows(self, lines: list[str], service: str = "unknown") -> dict`
- Imports: `core.llm_cache.LLMCache`, `core.llm_provider.provider`, `core.sre_investigator.InvestigationReport`.
- Imported by: `main.py`, `core/command_registry.py`.

## `core/llm_cache.py`
- Purpose: JSON file-backed cache for LLM outputs.
- Key symbols:
  - `class LLMCache`
  - `get(self, prompt: str, mode: str, query: str = "") -> dict | None`
  - `set(self, prompt: str, mode: str, result: dict, query: str = "")`
  - `clear(self, older_than_seconds: int = 0)`
  - `stats(self) -> dict`
- Imports: `hashlib`, `json`, `time`, `Path`, logger, flags.
- Imported by: `core/llm_analyzer.py`, `core/command_registry.py`, `main.py`.

## `core/llm_provider.py`
- Purpose: Unified generation + embedding provider abstraction.
- Key symbols:
  - `class LLMProvider`
  - `generate(self, prompt: str, system_prompt: Optional[str] = None, stream: bool = False) -> str`
  - `embed(self, texts: List[str]) -> List[List[float]]`
  - `provider = LLMProvider()` singleton
- Provider behaviors:
  - NVIDIA path uses OpenAI-compatible client and model fallback on HTTP 429.
  - Ollama path uses `OLLAMA_URL` with retries.
- Imported by: `core/window_analyzer.py`, `core/incident_recorder.py`, `core/rag_engine.py`, `core/command_registry.py`, `ai_sre.py`, `core/llm_analyzer.py`.

## `core/log_cleaner.py`
- Purpose: Filter noisy probes/metrics/debug lines before analysis.
- Key symbols:
  - `class LogCleaner`
  - `clean(self, lines: list[str]) -> list[str>`
  - `get_stats(self, original: list[str], cleaned: list[str]) -> dict`
- Imported by: `core/log_loader.py`, `core/command_registry.py`.

## `core/log_loader.py`
- Purpose: Load logs from file, directory, kubectl, mock kubectl assets.
- Key symbols:
  - `class LogLoader`
  - `load(self, filepath: str) -> list[str]`
  - `load_directory(self, dirpath: str) -> dict[str, list[str]]`
  - `get_pod_names(self, namespace: str = "default", service: str = None) -> list[str]`
  - `load_from_kubectl(self, namespace: str = "default", service: str = None, tail: int = 100) -> list[str]`
  - `load_auto(self, filepath: str = None, namespace: str = "default", service: str = None, tail: int = 100) -> list[str]`
  - `load_service_logs(self, service_name: str, fallback_log: str = "logs/test.log") -> list[str]`
  - `load_mock_kubectl(self, resource_type: str, scenario: str) -> str`
- Imported by: `main.py`, `core/rag_engine.py`, `core/sre_investigator.py`, `core/command_registry.py`.

## `core/log_processor.py`
- Purpose: Parse raw lines into structured entries and severity/service filters.
- Key symbols:
  - `class LogProcessor`
  - `process(self, raw_lines: list[str]) -> list[dict]`
  - `filter_by_severity(self, entries: list[dict], severity: str) -> list[dict]`
  - `filter_by_service(self, entries: list[dict], service: str) -> list[dict]`
  - `get_summary(self, entries: list[dict]) -> dict`
  - `get_failure_chain(self, entries: list[dict]) -> list[str]`
- Imported by: `main.py`, `core/context_builder.py`, `core/sre_investigator.py`, `core/command_registry.py`.

## `core/logger.py`
- Purpose: Rich-aware logging abstraction and noisy-lib suppression.
- Key symbols:
  - `_apply_suppressions()`
  - `class SRELogger`
  - `get_logger(module_name: str) -> SRELogger`
- Imported by: almost every `core/*` module and `main.py`.

## `core/rag_engine.py`
- Purpose: Index historical incidents and retrieve relevant context from ChromaDB.
- Key symbols:
  - `class RAGEngine`
  - `_index_historical_logs(self)`
  - `retrieve(self, query_text: str, top_k: int = None) -> Dict[str, Any]`
  - `get_collection_stats(self) -> Dict[str, Any]`
- Key internal constants/behavior:
  - Persistent path: `CHROMA_DB_PATH` (default `.chromadb`)
  - Collection: `sre_historical_incidents_v1`, cosine distance
- Imported by: `main.py`, `core/command_registry.py`, `core/incident_recorder.py`, `core/llm_analyzer.py` (self-test).

## `core/resource_collector.py`
- Purpose: Collect resource metrics via mock or kubectl.
- Key symbols:
  - `class ResourceCollector`
  - `get_mock_resources(self, services: list[str]) -> dict`
  - `get_critical_services(self, resources: dict) -> list[str]`
  - `get_resource_summary(self, resources: dict) -> str`
  - `get_real_resources(self, services: list[str], namespace: str = "default") -> dict`
  - `get_resources(self, services: list[str], namespace: str = "default", use_mock: bool = None) -> dict`
- Imported by: `main.py`, `core/context_builder.py`, `core/sre_investigator.py`.

## `core/service_discovery.py`
- Purpose: Assist unknown service/namespace resolution from live cluster scan.
- Key symbols:
  - `@dataclass PodMatch`
  - `class ServiceDiscovery`
  - `scan_all_pods(self) -> list[dict]`
  - `find_matches(self, service_name: str, top_k: int = 5) -> list[PodMatch]`
  - `prompt_for_namespace(self, service_name: str) -> str | None`
  - `prompt_save_to_yaml(self, service_name: str, namespace: str) -> bool`
- Imported by: currently invoked through explicit module usage, not registry default path.

## `core/service_graph.py`
- Purpose: Load and mutate `services.yaml`, compute blast radius and discovery updates.
- Key symbols:
  - `class ServiceGraph`
  - `get_blast_radius(self, service: str) -> dict`
  - `discover_from_logs(self, log_lines: list[str], source_service: str) -> list[dict]`
  - `apply_discoveries(self, discoveries: list[dict], source_service: str)`
  - `resolve_service(service_name: str, service_graph: ServiceGraph, namespace: str = "default") -> str`
- Imported by: `core/command_registry.py`, `main.py`, `core/sre_investigator.py`, `core/service_discovery.py`.

## `core/sre_investigator.py`
- Purpose: Deep multi-service investigation object model + rule-based pattern detection.
- Key symbols:
  - Dataclasses: `DetectedPattern`, `InvestigationEvidence`, `InvestigationReport`
  - `class PatternDetector` (`RULES`, `detect(...)`)
  - `class EvidenceCollector` with `_collect_from_files` and `_collect_from_kubectl`
  - `class SREInvestigator`
  - `investigate(self, target_service: str, namespace: str = None, use_mock: bool = None) -> InvestigationReport`
  - `get_summary_text(self, report: InvestigationReport) -> str`
- Imported by: `core/llm_analyzer.py` (investigation prompt typing + flow).

## `core/window_analyzer.py`
- Purpose: Sliding-window RCA pass with confidence gating.
- Key symbols:
  - `class WindowAnalyzer`
  - `analyse(self, lines: list[str], service: str = "unknown") -> dict`
  - `_run_window(self, lines: list[str], service: str, label: str) -> tuple[str, int]`
- Behavior:
  - Window 1: first 500 lines.
  - If confidence `< 60`, merges to first 1000 lines and re-runs.
  - Persists via `IncidentRecorder.check_and_save(...)`.
- Imported by: `core/command_registry.py`, `core/llm_analyzer.py`.

---

## 4) Add a new CLI command (registry pattern)

1. In `core/command_registry.py`, create a new handler class extending `BaseHandler`:
```python
class MyCommandHandler(BaseHandler):
    description = "..."
    aliases = ["mycmd"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        ...
        return "ok"
```
2. Instantiate it near existing singletons (`_HELP`, `_CHAT`, etc.).
3. Register it in `REGISTRY` dictionary.
4. Add a row in `HelpHandler.handle()` output table.
5. Run `python ai_sre.py` and test command resolution (`resolve`).

---

## 5) RAG pipeline end-to-end

Interactive `analyse <service>` in file mode:
1. `AnalyseHandler.handle()` loads service log lines via `LogLoader.load_service_logs()`.
2. `WindowAnalyzer.analyse()` runs LLM analysis on Window 1 (500 lines).
3. Confidence extraction uses `CONFIDENCE: <n>%` block.
4. If low confidence (`<60`), merged Window 1+2 (up to 1000 lines) is analyzed.
5. `IncidentRecorder.check_and_save()`:
   - Queries similarity (`_query_similarity`) against ChromaDB through `RAGEngine`.
   - If similarity < threshold (`SIMILARITY_THRESHOLD=0.72`), saves incident to `logs/historical` and embeds chunks.
6. `AnalyseHandler` prints via `_print_analysis_result(...)`.

---

## 6) Kubectl RCA pipeline end-to-end

`analyse <service>` with `SOURCE_KUBERNETES=true`:
1. `AnalyseHandler._handle_kubectl(...)` resolves target service (`services.yaml` + cluster fallback).
2. `run_kubectl_rca(...)` executes staged evidence collection in `KubectlRCAInvestigator.investigate(...)`:
   - Stage 1: Pod status
   - Stage 2: Pod events
   - Stage 3: Pod logs
   - Stage 4: Cluster resources
   - Stage 4b: Node describe
   - Stage 5: Service endpoints
   - Stage 6: VirtualService
3. `collect_all_evidence(report)` flattens evidence text for prompt.
4. LLM call via `provider.generate()` with `_build_kubectl_prompt(...)`.
5. Confidence parsed from `CONFIDENCE:` block.
6. `IncidentRecorder.check_and_save(...)` runs for RAG/compare branch when confidence allows.
7. Final output is printed and persisted (`.last_rca.json`, compare reports when enabled).

---

## 7) `services.yaml` schema

Root key:
- `services` (mapping of service name → config)

Per service fields used by code:
- `description: str`
- `namespace: str`
- `port: int`
- `depends_on: list[str]`
- `exposes_to: list[str]`
- `health_endpoint: str`
- `containers: list[dict{name: str}]`
- `dependency_confidence: str` (examples: `user_defined`, `auto_discovered`, `discovered_high`)

### Add a new service
1. Add new service under `services:` with the fields above.
2. Ensure `namespace` and container names match deployment reality.
3. Define `depends_on` and `exposes_to` edges.
4. Restart shell/command and verify with `status` + `analyse <service>`.

---

## 8) Add a new failure pattern (`kubectl_rca_investigator.py`)

Edit `PATTERNS` list:
```python
(
    r"your-regex|alt-regex",
    "Human-readable cause",
    85,
    [
        "Fix step 1",
        "Fix step 2",
        "Fix step 3",
    ],
),
```
Notes:
- Higher confidence wins when multiple patterns match (`detect_patterns`).
- Keep regex case-insensitive friendly and specific enough to avoid false positives.

---

## 9) ChromaDB operations

### Storage location
- Path from `CHROMA_DB_PATH` flag (default: `.chromadb`).
- Collection created by `RAGEngine`: `sre_historical_incidents_v1`.

### Reset vector store
```bash
rm -rf .chromadb
```
Then rerun analysis to re-initialize index.

### Dimension mismatch fix
The project already includes auto-heal in `IncidentRecorder`:
- Detects mismatch with `_is_dim_error(...)`.
- Calls `_purge_and_reload()` to remove stale `.chromadb` and reinitialize.
- Re-embeds with current provider/model.

If it persists:
1. Ensure `LLM_EMBEDDING_MODEL` and fallback are stable.
2. Delete `.chromadb` manually.
3. Re-run a fresh `analyse` to rebuild.

---

## 10) Troubleshooting

### `kubectl not found. Is it installed and in PATH?`
- Install kubectl and verify with `kubectl version`.
- Or switch to file mode: `SOURCE_KUBERNETES=false`.

### `No logs found for service`
- Ensure `logs/services/<service>.log` exists or service lines exist in `logs/test.log`.
- Check naming consistency with `services.yaml` and command input.

### NVIDIA provider errors / 429
- `LLMProvider` automatically retries using fallback model.
- Verify `NVIDIA_API_KEY` and `LLM_BASE_URL`.

### Empty/weak RCA confidence
- Increase available logs or run compare mode.
- Check window fallback happened (`windows_used=2`).

### Chat says no previous RCA
- Run `analyse <service>` first.
- Ensure `.last_rca.json` was created.

### ChromaDB similarity always zero
- Confirm historical logs exist in `logs/historical`.
- Rebuild `.chromadb` and re-run.

---

## 11) Running tests

There is no dedicated `tests/` suite in this repository currently.

Recommended smoke checks:
```bash
python ai_sre.py
# inside shell:
status
analyse currencyservice
analyse paymentservice --compare
chat
```

Optional module self-tests exist in several files under `if __name__ == "__main__":` blocks (for example `core/log_loader.py`, `core/llm_analyzer.py`, `evaluation/comparator.py`).