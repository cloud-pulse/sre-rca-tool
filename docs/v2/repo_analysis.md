# AI-SRE Repository Analysis
## Project Purpose

AI-SRE is a command-line Root Cause Analysis (RCA) tool for Kubernetes microservices, designed for Site Reliability Engineers (SREs). It automates incident investigation by loading logs (file or kubectl), cleaning noise (health probes/metrics/debug spam), applying sliding window analysis, retrieving historical incidents via RAG/ChromaDB, and generating structured RCA using Nvidia NIM LLMs (meta/llama-3.3-70b-instruct). Key differentiator: blast radius analysis across service dependencies defined in services.yaml, with 20+ rule-based pattern detectors (OOMKilled, CrashLoop etc.) before LLM. Reduces MTTR from hours to <60s. Supports demo (mock data) and live K8s modes via flags.py.

Target: SREs debugging production incidents. Entry: `python ai_sre.py analyse payment-service`.

(~85 words)

## Directory Tree

```
c:/playground/sre-rca-tool/
├── ai_sre.py                    # Interactive CLI entrypoint (Rich console)
├── flags.py                     # .env parser — single config source (50+ flags)
├── main.py                      # Legacy/internal CLI (ai_sre imports)
├── services.yaml                 # Service graph (4 services: api-gateway→payment→db)
├── requirements.txt              # ChromaDB, Rich, OpenAI (Nvidia), sentence-transformers
├── .gitignore                   # Standard Python ignores
├── TODO.md                      # Task tracking
├── verify.py                    # Verification utils
├── core/                        # Business logic modules
│   ├── command_registry.py      # CLI dispatcher: analyse/status/watch/chat (BaseHandler pattern)
│   ├── log_cleaner.py           # Noise removal (health/metrics/debug — ~17% reduction)
│   ├── window_analyzer.py       # Sliding window (500→1000 lines if conf<60%)
│   ├── incident_recorder.py     # RAG similarity check, auto-save/embed new incidents
│   ├── llm_provider.py          # Nvidia NIM primary + Ollama fallback
│   ├── rag_engine.py            # ChromaDB sre_historical_incidents (20-line chunks)
│   ├── log_loader.py            # File/kubectl loader + auto-clean
│   ├── sre_investigator.py      # Multi-service blast radius + 20 pattern rules
│   └── ... (logger.py etc.)
├── docs/                        # Markdown docs (dissertation, guides)
├── logs/                        # Input data
│   ├── test.log                 # Default fallback
│   ├── mock/kubectl/            # kubectl describe/events/rollout mocks
│   └── historical/              # Auto-saved incidents (*.log)
├── scripts/                     # Helpers (verify_final.sh, quick_demo.sh)
├── evaluation/                  # comparator.py (RAG vs baseline)
├── output/                      # .last_rca.json etc.
└── reports/                     # analyse --compare outputs
```

(~210 words)

## Entry Points & Flow

**Primary**: `python ai_sre.py` → interactive loop → `command_registry.resolve(input)` → handler (e.g. AnalyseHandler.handle()) → LogLoader.load() → LogCleaner.clean() → WindowAnalyzer.analyse() → RAG.retrieve() → LLMProvider.generate() → IncidentRecorder.save() → Rich Panel output.

**Single-shot**: `python ai_sre.py analyse payment-service`.

**Flow**: User input → fuzzy command match → handler → evidence collection → pattern detection → RAG context → enriched LLM prompt → structured RCA (conf%, reason, fixes).

## Data Flow: Input → Output

```
Input: "analyse payment-service"
    ↓
LogLoader: logs/mock or kubectl logs payment-xyz
    ↓  
LogCleaner: remove \"GET /health OK\", metrics spam
    ↓
WindowAnalyzer: Window1(500 lines) → LLM → conf=45% → merge Window1+2
    ↓
RAG: ChromaDB cosine top-3 historical → 75% similarity to incident_20260404.log
    ↓
LLM: Nvidia NIM prompt(enriched: patterns+RAG+metrics) → \"DB pool exhausted\"
    ↓
IncidentRecorder: similarity=75%>40% → \"Known pattern, no auto-save\"
    ↓
Rich CLI: Table(confidence, windows_used, patterns) + Markdown RCA
Output: \"[80% conf] Root cause: DB connection pool exhaustion\"
```

## Key Design Decisions

1. **Flags.py as single source**: Manual .env parser (no python-dotenv). All 50+ configs (LLM_PROVIDER=nvidia, LOG_CONFIDENCE_THRESHOLD=60). No config.py.
2. **Command registry pattern**: BaseHandler ABC → REGISTRY dict. Extensible: add handler → register alias.
3. **Nvidia NIM primary**: Production-grade inference (llama-3.3-70b-instruct), Ollama fallback. Embeddings: nv-embed-v1.
4. **Mock-first**: logs/mock/kubectl/ for describe/events/rollout. Toggle USE_KUBERNETES=false|true.
5. **Auto-everything**: Log cleaning, incident saving (<40% similarity), pattern detection pre-LLM.

## Module Dependency Map

```
ai_sre.py → command_registry → {llm_provider, log_loader, window_analyzer}
log_loader → log_cleaner
window_analyzer → llm_provider → rag_engine → chromadb
incident_recorder → rag_engine
sre_investigator → service_graph(services.yaml) → log_loader
No cycles. Core modules self-contained.
```

## Recent Changes (New Modules)

- **log_cleaner.py** (B1): Noise reduction before LLM.
- **window_analyzer.py** (B2): Dynamic window expansion.
- **incident_recorder.py** (B3): Auto-save/embed pipeline.
- **llm_provider.py** (D1): Nvidia integration.
- **command_registry.py** (C3): Full CLI handlers.

**Word count**: 612
