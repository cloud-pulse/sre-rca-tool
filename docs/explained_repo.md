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

**Tech Stack**:
| Category | Technologies |
|----------|--------------|
| **Core** | Python 3.12+, Click CLI, Rich TUI |
| **AI/ML** | Ollama (phi3:mini), SentenceTransformers (all-MiniLM-L6-v2), ChromaDB |
| **Data** | PyYAML (services.yaml), kubectl (optional) |
| **UI** | Rich panels/tables/rules/progress |

**Entry Points**:
- `python main.py analyze [log] [--mode rag/baseline]`: Full RCA pipeline
- `ai-sre` (installed): Interactive shell with NL parser
- `python main.py watch logs/test.log`: Live monitoring + auto-RCA

---

## Folder Structure & File Analysis

### `core/` - Domain Logic (Central Engine)
**Role**: Business logic for log processing, analysis, investigation. Highly decoupled modules orchestrated by main.py/ai_sre.py.

| File | Purpose | Key Components | Dependencies | Usage |
|------|---------|----------------|--------------|-------|
| `__init__.py` | Empty package init | - | - | - |
| `context_builder.py` | Formats logs/resources for LLM prompts | `ContextBuilder.build()`, `format_logs_for_prompt()` | LogProcessor, ResourceCollector | Pipeline step 4: Pre-LLM formatting |
| `llm_analyzer.py` | Ollama LLM calls + response parsing | `LLMAnalyzer.analyze_baseline/rag()`, `_parse_response()` | LLMCache, logger | Pipeline step 5: AI analysis |
| `llm_cache.py` | Persistent LLM response caching | `LLMCache.get/set/clear/stats()` | flags, logger | All LLM calls (TTL: 1hr default) |
| `log_loader.py` | Loads logs from files/kubectl | `LogLoader.load_auto()`, `load_from_kubectl()` | flags (USE_KUBERNETES) | Pipeline step 1: Data ingestion |
| `log_processor.py` | Parses logs into structured entries | `LogProcessor.process/filter/summary/get_failure_chain()` | - | Pipeline step 2: Log structuring |
| `logger.py` | Rich-aware logging with suppressions | `SRELogger`, `get_logger()` | flags (DEBUG, SUPPRESS_LOGS) | All modules |
| `rag_engine.py` | Historical log similarity search | `RAGEngine.retrieve()`, ChromaDB + SentenceTransformers | config (HISTORICAL_LOGS_DIR) | RAG mode: Retrieves top-3 similar incidents |
| `resource_collector.py` | Mock/real pod metrics/status | `ResourceCollector.get_resources()` (mock/kubectl top/describe) | flags (USE_KUBERNETES) | Pipeline step 3: Resource data |
| `service_discovery.py` | Scans cluster for unknown services | `ServiceDiscovery.find_matches/prompt_for_namespace()` | kubectl get pods --all-namespaces | Interactive: Suggests namespaces |
| `service_graph.py` | Dependency graph from services.yaml | `ServiceGraph.get_blast_radius()`, auto-discovery from logs | services.yaml | Blast radius, upstream/downstream analysis |
| `sre_investigator.py` | Deep multi-service investigation | `SREInvestigator.investigate()` → `InvestigationReport` | All core/* | `analyze <service>`: Full evidence collection + patterns |

### `output/` - Rich Terminal UI
**Role**: Beautiful TUI dashboards, tables, spinners, panels.

| File | Purpose | Key Components | Dependencies | Usage |
|------|---------|----------------|--------------|-------|
| `__init__.py` | Empty | - | - | - |
| `rca_formatter.py` | RCA dashboards + investigation reports | `RCAFormatter.print_full_result/investigation()` | Rich (Console/Panel/Table/Rule) | main.py/ai_sre.py output |

### `evaluation/` - Research/Evaluation Tools
**Role**: Compare baseline vs RAG performance (dissertation).

| File | Purpose | Key Components | Dependencies | Usage |
|------|---------|----------------|--------------|-------|
| `__init__.py` | Empty | - | - | - |
| `comparator.py` | Baseline vs RAG side-by-side | `Comparator.compare/save_comparison_report()` | Rich | `main.py compare logs/test.log` |

### `docs/` - Developer/Dissertation Documentation
| File | Purpose |
|------|---------|
| `developer_guide.md` | Setup, architecture, contribution guide |
| `dissertation_report.md` | Research paper (RAG vs baseline evaluation) |
| `mythoughts.md` | Personal notes |
| `repo_analysis.md` | Auto-generated repo analysis |

### Root Files - CLI Entry Points & Config
| File | Purpose | Key Logic |
|------|---------|-----------|
| `main.py` | Production CLI | `cli()` → `analyze/status/watch/cache/compare/chat` → `run_pipeline()` |
| `ai_sre.py` | Interactive shell | `SREShell` + `NLParser` (fuzzy matching + SRE keywords) |
| `config.py` | Constants | Ollama URL/model, ChromaDB path, historical logs dir |
| `flags.py` | .env parsing + feature flags | `DEBUG`, `USE_KUBERNETES`, `LLM_CACHE_ENABLED`, `RAG_ENABLED` |
| `requirements.txt` | Dependencies | click, rich, ollama, sentence-transformers, chromadb |
| `setup.py` | Packaging | `pip install -e .` → `ai-sre` command |
| `services.yaml` | Dependency graph | Auto-updated by discovery; api-gateway → payment/auth → db |

### `logs/` - Test Data
- `test.log`: Main demo log
- `historical/incident_00[1-3].log`: RAG training data (tagged with #resolution)
- `services/*.log`: Per-service logs

### `mock/kubectl/` - Fake kubectl Output
Realistic `kubectl describe/events/rollout` output for 9 failure scenarios (OOM, secrets, PVC, etc.).

### `scripts/` - Convenience Scripts
| Script | Purpose |
|--------|---------|
| `ai-sre.sh` | Shell alias setup |
| `check_env.sh` | Environment validation |
| `quick_demo.sh` | Automated demo |
| `setup_alias.sh` | `alias ai-sre=python ...` |
| `setup_minikube.sh` | Minikube + demo services |
| `simulate_new_errors.sh` | Live log injection for `watch` |
| `verify_final.sh` | Final validation checklist |

---

## Dependency Analysis

### External Libraries
| Library | Usage | Critical? |
|---------|--------|-----------|
| `click` | CLI argument parsing | Yes |
| `rich` | TUI (tables/panels/progress) | Yes |
| `requests` | Ollama HTTP API | Yes |
| `ollama` | LLM inference client | Yes |
| `sentence-transformers` | Log embedding (all-MiniLM-L6-v2) | RAG |
| `chromadb` | Vector DB for historical search | RAG |
| `pyyaml` | services.yaml parsing | Yes |
| `numpy` | Embeddings backend | RAG |

**No tight coupling**: Core modules injected via factory functions (`get_logger()`, `LogLoader()`).

### Internal Dependencies
```
main.py/ai_sre.py ─→ core/* ─→ flags/config/logger
                     ↓
               output.rca_formatter (Rich UI)
                     ↓
         evaluation.comparator (research)
```
- **Strong cohesion**: Each core/ module single-responsibility
- **Dependency injection**: Flags control mock/real, RAG/baseline

---

## End-to-End Usage Flow

```
1. Entry: main.py analyze logs/test.log --mode rag
   ↓
2. LogLoader.load_auto() → raw_lines (file or kubectl logs)
   ↓
3. LogProcessor.process/filter() → structured_entries
   ↓
4. ResourceCollector.get_resources() → pod_metrics (mock or kubectl top/describe)
   ↓
5. ContextBuilder.build() → llm_prompt (logs + resources + summary)
   ↓ (RAG mode)
6. RAGEngine.retrieve() → ChromaDB top-3 historical matches
   ↓
7. LLMAnalyzer.analyze_rag() → LLM call (cache hit/miss) → parse_result
   ↓
8. RCAFormatter.print_full_result() → Rich dashboard
```

**Investigation Flow** (`analyze payment-service`):
```
SREInvestigator.investigate() →
ServiceGraph.blast_radius() → affected_services →
EvidenceCollector.collect() per service (logs/events/describe/top) →
PatternDetector.detect() → SRE patterns (OOM, CrashLoop, etc.) →
LLMAnalyzer.analyze_investigation() → deep LLM report
```

---

## Strengths & Patterns
- **Test-driven**: Each core file ends with `__main__` self-tests
- **Mock-first**: Full functionality without Kubernetes (`--mock`)
- **Progressive enhancement**: File → kubectl → real cluster
- **Caching**: LLM responses (TTL 1hr), ChromaDB persistent
- **Extensible rules**: `PatternDetector.RULES` JSON-like, easy to add patterns
- **Auto-discovery**: Logs → services.yaml updates

## Potential Improvements
1. **Metrics server**: Real `kubectl top` integration (Phase 5)
2. **Live tail**: `kubectl logs -f` streaming
3. **Alert integration**: Prometheus/Grafana queries
4. **Multi-cluster**: Context switching
5. **Team sharing**: Save/load investigations as YAML/JSON
6. **Grafana dashboards**: Auto-generate investigation viz
7. **No unused/redundant files**: All files actively used

**Production Ready**: Works end-to-end with mocks; scales to real clusters. Excellent for SRE onboarding & rapid triage. 🚀

