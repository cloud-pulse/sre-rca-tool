# AI-SRE Developer Guide

## Quick Start (Windows MINGW64/Git Bash)

```bash
# 1. Clone & venv
git clone <repo>
cd sre-rca-tool
python -m venv venv
source venv/Scripts/activate  # or venv\Scripts\activate.bat

# 2. Install deps
pip install -r requirements.txt

# 3. Verify
python flags.py
python scripts/verify_final.sh  # or bash scripts/verify_final.sh

# 4. Run
python ai_sre.py help
python ai_sre.py status
python ai_sre.py analyse payment-service
```

**Expected status output**:
```
┌─ System Status ───┐
│ Python       OK    3.11.9    │
│ Virtual env  OK    venv      │
│ LLM          OK    nvidia    │
│ ChromaDB     OK    124 chunks│
│ services.yaml OK   4 services│
└────────────────────┘
```

(~80 words)

## .env Configuration Reference

**Location**: Project root `.env` file. Edit → `python flags.py` to verify.

| Key | Type | Default | Purpose | Valid |
|----|------|---------|---------|-------|
| `SYSTEM_DEBUG` | bool | false | Verbose debug prints | true/false |
| `UI_SUPPRESS_LOGS` | bool | true | Hide raw logs in CLI | true/false |
| `LLM_PROVIDER` | str | nvidia | LLM backend | nvidia/ollama |
| `NVIDIA_API_KEY` | str | \"\" | NIM API key | Your NIM key |
| `LLM_REASONING_MODEL` | str | meta/llama-3.3-70b-instruct | Primary reasoning | NIM model ID |
| `LLM_REASONING_FALLBACK` | str | mistralai/mistral-small-24b-instruct | 429 fallback | NIM model ID |
| `LLM_EMBEDDING_MODEL` | str | nvidia/nv-embed-v1 | RAG embeddings | NIM embed ID |
| `LLM_MAX_TOKENS` | int | 2000 | Max output tokens | 500-4000 |
| `LLM_TIMEOUT_SECONDS` | int | 300 | Request timeout | 60-600 |
| `DEMO_MODE` | bool | false | Mock data only | true/false |
| `LOG_WINDOW_SIZE` | int | 500 | WindowAnalyzer Window 1 | 200-1000 |
| `LOG_CONFIDENCE_THRESHOLD` | int | 60 | Window expansion % | 50-80 |
| `LOG_FILTER_PATTERNS` | str | health,metrics,ready,live | LogCleaner keep patterns | comma-list |
| `RAG_NEW_INCIDENT_THRESHOLD` | int | 40 | IncidentRecorder save % | 30-50 |
| `RAG_TOP_K` | int | 3 | ChromaDB similarity results | 1-10 |
| `RAG_SIMILARITY_THRESHOLD` | int | 60 | RAG activation % | 50-80 |
| `USE_KUBERNETES` | bool | false | kubectl vs file mode | true/false |
| `SOURCE_LOG_PATH` | str | logs/test.log | Default log file | path |
| `CHROMA_DB_PATH` | str | .chromadb | Persistent vector DB | path |
| `HISTORICAL_LOGS_DIR` | str | logs/historical | Auto-saved incidents | path |

**Full list**: `python flags.py` (Rich table). Real env vars override .env.

(~320 words)

## All CLI Commands

| Command | Aliases | Example | Expected Output |
|---------|---------|---------|-----------------|
| `analyse payment-service` | analyze | `analyse payment --compare` | RCA table (conf%, windows, patterns) + Markdown analysis |
| `status` | health | `python ai_sre.py status` | Component health table (LLM/ChromaDB/services/cache) |
| `watch payment-service` | monitor | Ctrl+C to stop | Live tail + instant RCA on new ERRORs |
| `chat` | - | After `analyse` | Interactive Q&A on last RCA (SRE guardrails) |
| `explain OOMKilled` | - | `explain HPA` | 3-8 sentence SRE explanation (no code) |
| `clean-logs logs/test.log` | clean | - | Stats table + cleaned log preview |
| `compare` | - | `compare logs/test.log` | Baseline vs RAG side-by-side + report |
| `help` | - | - | Rich command table w/ examples |

**analyse --baseline**: LLM-only (no RAG). `--compare`: Both + reports/compare_*.txt.

**Out-of-scope**: `weather?` → \"I help with SRE topics only\".

(~180 words)

## Project Structure

| Path | Purpose |
|------|---------|
| `ai_sre.py` | Rich CLI loop + banner |
| `flags.py` | .env → typed flags (DEBUG, LLM_PROVIDER etc.) |
| `core/command_registry.py` | REGISTRY dict → BaseHandler.handle(args) |
| `core/log_loader.py` | File/kubectl logs + auto-clean |
| `core/log_cleaner.py` | Drop health/metrics noise (keep ERROR) |
| `core/window_analyzer.py` | Window1(500) → conf<60% → Window1+2 |
| `core/rag_engine.py` | ChromaDB query/embed (20-line chunks) |
| `core/llm_provider.py` | Nvidia NIM + Ollama fallback |
| `core/incident_recorder.py` | RAG similarity → auto-save/embed |
| `core/sre_investigator.py` | Blast radius + 20 patterns (OOM etc.) |
| `services.yaml` | Dependency graph |
| `logs/mock/kubectl/` | describe/events/rollout mocks |
| `scripts/*.sh` | verify_final.sh, quick_demo.sh |

## Add New Command (Registry Pattern)

1. **Inherit BaseHandler** (`core/command_registry.py`):
```python
class NewHandler(BaseHandler):
    description = \"Your command\"
    aliases = [\"new-cmd\"]
    
    def handle(self, args: list[str]) -> str:
        console.print(\"[bold green]Hello from new command![/]\")
        return \"ok\"
```

2. **Register**:
```python
_NEW = NewHandler()
REGISTRY[\"new\"] = _NEW
REGISTRY[\"new-cmd\"] = _NEW  # alias
```

3. **Test**: `python ai_sre.py new-cmd args`.

**Extensible**: No CLI parser rewrites. 100% runtime dispatch.

## Add Log Filter Rule

`core/log_cleaner.py`:
```python
class LogCleaner:
    def __init__(self):
        self.health_patterns += [\"your-health-endpoint\"]  # Rule 1
        self.debug_patterns += [\"your-debug-noise\"]       # Rule 4
        self.keep_patterns += [\"must-keep-error\"]         # Bypass all
```

Reload: `python ai_sre.py clean logs/test.log`.

## Add New Service

`services.yaml`:
```yaml
your-service:
  depends_on: [db-service]
  exposes_to: [api-gateway]
  namespace: sre-demo
  containers: [your-app, istio-proxy]
```

Blast radius auto-updates.

## Testing

**verify_final.sh**: End-to-end (flags → analyse → RAG → output).
**quick_demo.sh**: Viva demo sequence.
**Run**: `bash scripts/verify_final.sh`.

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| \"kubectl not found\" | USE_KUBERNETES=true | `flags: USE_KUBERNETES=false` or install kubectl |
| \"LLM error: 429\" | NIM rate limit | Falls back to mistral-small automatically |
| \"No logs found\" | Empty logs/test.log | `bash scripts/simulate_new_errors.sh logs/test.log` |
| \"ChromaDB error\" | Missing .chromadb | Delete → auto-reindex on next `status` |
| \"Low confidence\" | Short logs | Increase LOG_WINDOW_SIZE=1000 |
| \"Out of scope\" | Non-SRE query | Guardrail working — try \"explain HPA\" |

**Known Issues**:
- phi3:mini CPU slow (~2min). GPU Docker next.
- Mock data static. Minikube sock-shop pending.
- Large clusters: Add pagination to sre_investigator.

**Word count**: 1492
