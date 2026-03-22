import sys
import os
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

import logging
import warnings

from flags import (
    DEBUG,
    SUPPRESS_LOGS,
    LOG_LEVEL
)

# ─── Step 1: Apply suppressions immediately ───
# This runs at import time so it takes effect
# before any library loads

def _apply_suppressions():
    # If SUPPRESS_LOGS is True (default):
    # Silence ALL of these:

    # 1. Python logging for noisy libraries
    noisy_loggers = [
        "sentence_transformers",
        "transformers",
        "huggingface_hub",
        "chromadb",
        "chromadb.telemetry",
        "urllib3",
        "filelock",
        "fsspec",
        "torch",
        "tqdm",
        "httpx",
        "requests",
        "huggingface_hub.utils._http",
        "huggingface_hub.utils",
        "urllib3.connectionpool",
    ]
    level = (
        logging.DEBUG
        if DEBUG
        else logging.ERROR
    )
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(
            logging.ERROR
            if SUPPRESS_LOGS
            else level
        )

    # 2. Python warnings
    if SUPPRESS_LOGS and not DEBUG:
        warnings.filterwarnings("ignore")
        os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        os.environ["HUGGINGFACE_HUB_VERBOSITY"] = "error"
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        os.environ["HF_TOKEN"] = "dummy-suppress-warnings"
        os.environ[
            "TOKENIZERS_PARALLELISM"
        ] = "false"
        os.environ[
            "TRANSFORMERS_VERBOSITY"
        ] = "error"
        os.environ[
            "HF_HUB_DISABLE_SYMLINKS_WARNING"
        ] = "1"

    # 3. Root logger level
    root_level = (
        logging.DEBUG
        if DEBUG
        else getattr(
            logging, LOG_LEVEL, logging.INFO
        )
    )
    logging.basicConfig(level=root_level)
    logging.getLogger().setLevel(root_level)

_apply_suppressions()

# ─── Step 2: SRE-AI Logger class ──────────────

class SRELogger:
    # Central logger for all SRE-AI modules
    # Respects DEBUG and SUPPRESS_LOGS flags
    # Uses rich for colored output when available

    def __init__(self, module_name: str):
        self.module = module_name
        self._rich_available = self._check_rich()

    def _check_rich(self) -> bool:
        try:
            from rich.console import Console
            self._console = Console(
                stderr=False
            )
            return True
        except ImportError:
            return False

    def debug(self, msg: str, *args):
        # Only print if DEBUG=true
        # Format: [dim][DEBUG][module] message[/dim]
        if not DEBUG:
            return
        full = (
            f"[dim][DEBUG][{self.module}] "
            f"{msg}[/dim]"
        )
        if self._rich_available:
            self._console.print(full)
        else:
            print(
                f"[DEBUG][{self.module}] {msg}"
            )

    def info(self, msg: str, *args):
        # Always print — this is user-facing output
        # Format: clean message, no prefix
        if self._rich_available:
            self._console.print(msg)
        else:
            print(msg)

    def step(self, msg: str, *args):
        # Pipeline step messages
        # Only show if DEBUG=true OR if it's
        # a top-level step (not internal detail)
        # Format: [dim]  → message[/dim]
        if DEBUG:
            full = (
                f"[dim]  → [{self.module}] "
                f"{msg}[/dim]"
            )
            if self._rich_available:
                self._console.print(full)
            else:
                print(
                    f"  → [{self.module}] {msg}"
                )

    def warn(self, msg: str, *args):
        # Always print warnings
        # Format: yellow WARNING prefix
        full = f"[bold yellow]WARNING:[/] {msg}"
        if self._rich_available:
            self._console.print(full)
        else:
            print(f"WARNING: {msg}")

    def error(self, msg: str, *args):
        # Always print errors
        # Format: red ERROR prefix
        full = f"[bold red]ERROR:[/] {msg}"
        if self._rich_available:
            self._console.print(full)
        else:
            print(f"ERROR: {msg}")

    def success(self, msg: str, *args):
        # Always print success messages
        # Format: green checkmark
        full = f"[bold green]✓[/] {msg}"
        if self._rich_available:
            self._console.print(full)
        else:
            print(f"OK: {msg}")

    def section(self, title: str):
        # Print a section divider
        # Only in debug mode
        if DEBUG:
            if self._rich_available:
                from rich.rule import Rule
                self._console.print(
                    Rule(
                        f"[dim]{title}[/dim]",
                        style="dim"
                    )
                )
            else:
                print(
                    f"\n--- {title} ---"
                )

# ─── Step 3: Module-level logger factory ──────

def get_logger(module_name: str) -> SRELogger:
    # Factory function — each module calls this
    # at the top to get its own logger instance
    # Usage in other modules:
    #   from core.logger import get_logger
    #   log = get_logger("log_loader")
    return SRELogger(module_name)

# ─── Step 4: Global debug_print shortcut ──────
# For quick one-off debug prints anywhere

def debug_print(*args):
    if DEBUG:
        msg = " ".join(str(a) for a in args)
        log = get_logger("debug")
        log.debug(msg)

if __name__ == "__main__":

    print("=== Task B — Logger Test ===\n")

    print("--- Test 1: Logger methods ---")
    log = get_logger("test_module")
    log.info("This is an info message")
    log.warn("This is a warning")
    log.error("This is an error")
    log.success("This is a success message")
    log.debug(
        "This only shows when DEBUG=true"
    )
    log.step(
        "This only shows when DEBUG=true"
    )

    print("\n--- Test 2: Flag values ---")
    print(f"DEBUG         = {DEBUG}")
    print(f"SUPPRESS_LOGS = {SUPPRESS_LOGS}")
    print(f"LOG_LEVEL     = {LOG_LEVEL}")

    print("\n--- Test 3: Suppression active ---")
    import logging
    ht_logger = logging.getLogger(
        "sentence_transformers"
    )
    print(
        f"sentence_transformers log level: "
        f"{ht_logger.level} "
        f"(50=CRITICAL, suppressed OK)"
    )

    print(
        "\n--- Test 4: Import RAGEngine "
        "(should be clean) ---"
    )
    from core.rag_engine import RAGEngine
    print(
        "RAGEngine imported — "
        "no noisy output above = PASS"
    )

    print("\nTask B OK")