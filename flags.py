import os
import sys
from pathlib import Path

# ─── Load .env file ───────────────────────────
# Read .env from project root before anything else
# Override with real environment variables if set
# Do NOT use python-dotenv — parse manually
# to avoid adding a dependency

def _load_env_file(env_path: str = ".env") -> dict:
    # Read .env file line by line
    # Skip blank lines and lines starting with #
    # Parse KEY=VALUE pairs
    # Strip quotes from values if present
    # Return dict of {KEY: VALUE}
    # Return empty dict if file not found
    env_dict = {}
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # Strip quotes if present
                    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    env_dict[key] = value
    except FileNotFoundError:
        pass
    return env_dict

def _parse_bool(value: str,
                default: bool = False) -> bool:
    # Parse string to bool
    # "true", "1", "yes", "on" → True
    # "false", "0", "no", "off" → False
    # case insensitive
    # return default if value is None or empty
    if not value:
        return default
    lower_value = value.lower()
    if lower_value in ('true', '1', 'yes', 'on'):
        return True
    elif lower_value in ('false', '0', 'no', 'off'):
        return False
    else:
        return default

def _parse_int(value: str,default: int = 0) -> int:
    # Parse string to int
    # return default if value is None or invalid
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default

# ─── Load all flags ───────────────────────────
# Load .env first, then override with real env vars
_env = _load_env_file(".env")

def _get(key: str, default: str = "") -> str:
    # Check real env first, then .env, then default
    return os.environ.get(
        key, _env.get(key, default)
    )

# ─── SYSTEM FLAGS ─────────────────────────────
DEBUG         = _parse_bool(_get("SYSTEM_DEBUG","false"))
LOG_LEVEL     = _get("SYSTEM_LOG_LEVEL", "INFO")

# ─── UI FLAGS ─────────────────────────────────
SUPPRESS_LOGS = _parse_bool(_get("UI_SUPPRESS_LOGS", "true"), True)
RICH_OUTPUT   = _parse_bool(_get("UI_RICH_OUTPUT", "true"), True)
SHOW_TIMESTAMPS = _parse_bool(_get("UI_SHOW_TIMESTAMPS", "true"), True)

# ─── LLM FLAGS ────────────────────────────────
LLM_CACHE_ENABLED  = _parse_bool(_get("LLM_CACHE_ENABLED", "true"), True)
LLM_CACHE_TTL      = _parse_int(_get("LLM_CACHE_TTL_SECONDS", "3600"), 3600)
LLM_WARMUP         = _parse_bool(_get("LLM_WARMUP_ON_START", "true"), True)
LLM_KEEP_ALIVE     = _parse_bool(_get("LLM_KEEP_ALIVE", "true"), True)
LLM_MAX_TOKENS     = _parse_int(_get("LLM_MAX_TOKENS", "2000"), 1000)
LLM_TIMEOUT        = _parse_int(_get("LLM_TIMEOUT_SECONDS", "300"), 300)
LLM_PROVIDER           = _get("LLM_PROVIDER", "ollama")
NVIDIA_API_KEY         = _get("NVIDIA_API_KEY", "")
LLM_BASE_URL           = _get("LLM_BASE_URL","https://integrate.api.nvidia.com/v1")
LLM_REASONING_MODEL    = _get("LLM_REASONING_MODEL","meta/llama-3.3-70b-instruct")
LLM_REASONING_FALLBACK = _get("LLM_REASONING_FALLBACK","mistralai/mistral-small-24b-instruct")
LLM_EMBEDDING_MODEL    = _get("LLM_EMBEDDING_MODEL","nvidia/nv-embed-v1")
LLM_EMBEDDING_FALLBACK = _get("LLM_EMBEDDING_FALLBACK","nvidia/llama-nemotron-embed-1b-v2")
DEMO_MODE              = _parse_bool(_get("DEMO_MODE", "false"))
LOG_WINDOW_SIZE        = _parse_int(_get("LOG_WINDOW_SIZE", "500"), 500)
LOG_CONFIDENCE_THRESHOLD = _parse_int(_get("LOG_CONFIDENCE_THRESHOLD","60"), 60)
LOG_FILTER_PATTERNS    = _get("LOG_FILTER_PATTERNS","health,metrics,ready,live,heartbeat")
RAG_NEW_INCIDENT_THRESHOLD = _parse_int(_get("RAG_NEW_INCIDENT_THRESHOLD","40"), 40)
OLLAMA_URL             = _get("OLLAMA_URL","http://localhost:11434/api/generate")
OLLAMA_MODEL           = _get("OLLAMA_MODEL", "phi3:mini")

# ─── SOURCE FLAGS ─────────────────────────────
USE_KUBERNETES     = _parse_bool(_get("SOURCE_KUBERNETES", "false"), False)
K8S_NAMESPACE      = _get("SOURCE_NAMESPACE", "default")
LOG_TAIL_LINES     = _parse_int(_get("SOURCE_LOG_TAIL_LINES", "100"), 100)

# ─── RAG FLAGS ────────────────────────────────
RAG_ENABLED        = _parse_bool(_get("RAG_ENABLED", "true"), True)
RAG_TOP_K          = _parse_int(_get("RAG_TOP_K", "3"), 3)
RAG_THRESHOLD      = _parse_int(_get("RAG_SIMILARITY_THRESHOLD", "60"), 60)

# ─── CONFIG VALUES (merged from config.py) ────
HISTORICAL_LOGS_DIR    = _get("HISTORICAL_LOGS_DIR","logs/historical")
CHROMA_DB_PATH         = _get("CHROMA_DB_PATH",".chromadb")
DEFAULT_LOG_PATH       = _get("SOURCE_LOG_PATH","logs/test.log")
EMBEDDING_MODEL        = _get("EMBEDDING_MODEL","all-MiniLM-L6-v2")

# ─── HELPER FUNCTIONS ─────────────────────────

def debug_print(*args, **kwargs):
    # Print only when DEBUG=true
    # Prefix with [DEBUG] tag in dim style
    # Works with or without rich
    if DEBUG:
        prefix = "[DEBUG] "
        msg = " ".join(str(a) for a in args)
        try:
            from rich.console import Console
            Console().print(
                f"[dim]{prefix}{msg}[/dim]"
            )
        except ImportError:
            print(f"{prefix}{msg}")

def info_print(*args, **kwargs):
    # Print always (not suppressed by debug flag)
    # Used for important status messages
    msg = " ".join(str(a) for a in args)
    try:
        from rich.console import Console
        Console().print(msg)
    except ImportError:
        print(msg)

def get_all_flags() -> dict:
    # Return all current flag values as a dict
    # Used by status command and debug output
    return {
        "SYSTEM_DEBUG":         DEBUG,
        "LOG_LEVEL":            LOG_LEVEL,
        "UI_SUPPRESS_LOGS":     SUPPRESS_LOGS,
        "UI_RICH_OUTPUT":       RICH_OUTPUT,
        "UI_SHOW_TIMESTAMPS":   SHOW_TIMESTAMPS,
        "LLM_CACHE_ENABLED":    LLM_CACHE_ENABLED,
        "LLM_CACHE_TTL":        LLM_CACHE_TTL,
        "LLM_WARMUP":           LLM_WARMUP,
        "LLM_KEEP_ALIVE":       LLM_KEEP_ALIVE,
        "LLM_MAX_TOKENS":       LLM_MAX_TOKENS,
        "LLM_TIMEOUT":          LLM_TIMEOUT,
        "LLM_PROVIDER":         LLM_PROVIDER,
        "NVIDIA_API_KEY":       NVIDIA_API_KEY,
        "LLM_BASE_URL":         LLM_BASE_URL,
        "LLM_REASONING_MODEL":  LLM_REASONING_MODEL,
        "LLM_REASONING_FALLBACK": LLM_REASONING_FALLBACK,
        "LLM_EMBEDDING_MODEL":  LLM_EMBEDDING_MODEL,
        "LLM_EMBEDDING_FALLBACK": LLM_EMBEDDING_FALLBACK,
        "DEMO_MODE":            DEMO_MODE,
        "LOG_WINDOW_SIZE":      LOG_WINDOW_SIZE,
        "LOG_CONFIDENCE_THRESHOLD": LOG_CONFIDENCE_THRESHOLD,
        "LOG_FILTER_PATTERNS":  LOG_FILTER_PATTERNS,
        "RAG_NEW_INCIDENT_THRESHOLD": RAG_NEW_INCIDENT_THRESHOLD,
        "OLLAMA_URL":           OLLAMA_URL,
        "OLLAMA_MODEL":         OLLAMA_MODEL,
        "USE_KUBERNETES":       USE_KUBERNETES,
        "K8S_NAMESPACE":        K8S_NAMESPACE,
        "LOG_TAIL_LINES":       LOG_TAIL_LINES,
        "RAG_ENABLED":          RAG_ENABLED,
        "RAG_TOP_K":            RAG_TOP_K,
"RAG_THRESHOLD":        RAG_THRESHOLD,
        "HISTORICAL_LOGS_DIR":  HISTORICAL_LOGS_DIR,
        "CHROMA_DB_PATH":       CHROMA_DB_PATH,
        "DEFAULT_LOG_PATH":     DEFAULT_LOG_PATH,
        "EMBEDDING_MODEL":      EMBEDDING_MODEL,
    }

def print_flags():
    # Print all flags in a formatted table
    # Used by: python flags.py
    # and by: python main.py status --verbose
    flags = get_all_flags()
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
        console = Console()
        table = Table(
            title="SRE-AI Feature Flags",
            box=box.ROUNDED,
            show_lines=True
        )
        table.add_column(
            "Flag", style="bold white", width=28
        )
        table.add_column(
            "Value", width=20
        )
        table.add_column(
            "Source", style="dim", width=12
        )
        for key, value in flags.items():
            # Color booleans
            if isinstance(value, bool):
                val_str = (
                    "[bold green]true[/]"
                    if value
                    else "[bold red]false[/]"
                )
            else:
                val_str = (
                    f"[bold cyan]{value}[/]"
                )
            # Show if overridden by real env var
            source = (
                "[yellow]env[/]"
                if key in os.environ or
                   f"SYSTEM_{key}" in os.environ
                else "[dim].env[/]"
            )
            table.add_row(key, val_str, source)
        console.print(table)
    except ImportError:
        for key, value in flags.items():
            print(f"  {key}: {value}")

def is_demo_mode() -> bool:
    return DEMO_MODE

# ─── Also update config.py values ─────────────
# Override config.py values with flag values
# so existing code that imports from config
# still works but now respects flags


if __name__ == "__main__":

    print("=== Task A — Feature Flags Test ===\n")

    print("--- Test 1: Print all flags ---")
    print_flags()

    print("\n--- Test 2: Debug flag ---")
    print(f"DEBUG = {DEBUG}")
    debug_print(
        "This only prints when DEBUG=true"
    )
    print(
        "(if DEBUG=false above line is hidden)"
    )

    print("\n--- Test 3: Bool parsing ---")
    from flags import _parse_bool
    tests = [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("", False),
    ]
    all_passed = True
    for val, expected in tests:
        result = _parse_bool(val)
        status = "OK" if result == expected else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"  _parse_bool('{val}') = "
              f"{result} [{status}]")
    print(
        "All bool tests passed"
        if all_passed
        else "SOME TESTS FAILED"
    )

    print("\n--- Test 4: Kubernetes flag ---")
    print(f"USE_KUBERNETES = {USE_KUBERNETES}")
    print(
        "  kubectl mode: ACTIVE"
        if USE_KUBERNETES
        else "  file mode: ACTIVE (default)"
    )

    print("\n--- Test 5: .env override test ---")
    print("Set SYSTEM_DEBUG=true in .env")
    print("then re-run to see debug output")

    print("\n--- Test 6: get_all_flags() ---")
    all_flags = get_all_flags()
    print(f"Total flags loaded: {len(all_flags)}")
    print(f"Keys: {list(all_flags.keys())}")

    print("\nTask A OK")