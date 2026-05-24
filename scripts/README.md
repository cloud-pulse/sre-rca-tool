# scripts/

Helper scripts for development, demo, and setup.

## Scripts

| Script | Purpose | When to use |
|--------|---------|-------------|
| `ai-sre.sh` | Bash launcher for the tool | Run instead of `python ai_sre.py` |
| `check_env.sh` | Verify environment setup | Before first run or after .env changes |
| `setup_alias.sh` | Add `ai-sre` shell alias | One-time dev setup |
| `setup_minikube.sh` | Set up local Minikube cluster | Phase 2 — real Kubernetes mode |
| `simulate_new_errors.sh` | Append test errors to a log file | Demo the `watch` command live |
| `quick_demo.sh` | Full dissertation viva demo | Mid-sem and final demo |
| `verify_final.sh` | End-to-end verification suite | Before submission |

## Usage

```bash
# Activate venv first
source jarvis/Scripts/activate

# Run the tool
bash scripts/ai-sre.sh help
bash scripts/ai-sre.sh analyse payment-service

# Verify everything works
bash scripts/verify_final.sh

# Run viva demo
bash scripts/quick_demo.sh

# Simulate errors for watch demo (second terminal)
bash scripts/simulate_new_errors.sh logs/test.log
```

## Entry Points

- `python ai_sre.py` — interactive REPL (primary)
- `python main.py` — internal CLI (called by ai_sre.py)
- `bash scripts/ai-sre.sh` — bash wrapper for ai_sre.py
