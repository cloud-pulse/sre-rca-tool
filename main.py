#!/usr/bin/env python
"""
SRE-AI Root Cause Analysis Tool

Full production CLI with:
  - analyze: Comprehensive RCA analysis
  - status: System health check
  - Placeholder commands for Tasks 20-22
"""

import sys
import os
import json
import click
from rich.console import Console
from rich.rule import Rule

from core.logger import get_logger

log = get_logger("main")

from core.log_loader import LogLoader
from core.log_processor import LogProcessor
from core.resource_collector import ResourceCollector
from core.context_builder import ContextBuilder
from core.llm_analyzer import LLMAnalyzer
from core.rag_engine import RAGEngine
from output.rca_formatter import RCAFormatter
from evaluation.comparator import Comparator
from flags import HISTORICAL_LOGS_DIR, DEFAULT_LOG_PATH
from flags import LLM_WARMUP, LLM_CACHE_TTL

console = Console()


def check_python_version():
    if sys.version_info < (3, 12):
        log.error(f"Python 3.12+ required. You are on {sys.version}")
        log.error("Make sure Python 3.12 is accessible via 'python' command.")
        sys.exit(1)


check_python_version()


def run_pipeline(
    log_path: str = None,
    severity: str = "ERROR",
    mode: str = "rag",
    service_filter: str = None,
    use_mock: bool = None,
    namespace: str = None,
    verbose: bool = False,
    query: str = "",
) -> dict:
    """Run the full RCA analysis pipeline."""

    from flags import (
        USE_KUBERNETES,
        K8S_NAMESPACE,
        LOG_TAIL_LINES,
    )

    formatter = RCAFormatter()
    loader = LogLoader()
    processor = LogProcessor()
    collector = ResourceCollector()
    builder = ContextBuilder()
    analyzer = LLMAnalyzer()

    active_namespace = namespace or K8S_NAMESPACE

    # Step 1 — Load logs
    if verbose:
        console.print("[dim]Step 1/5: Loading logs...[/dim]")

    lines = loader.load_auto(
        filepath=log_path,
        namespace=active_namespace,
        service=service_filter,
        tail=LOG_TAIL_LINES,
    )

    if not lines:
        source = (
            f"kubectl (namespace={active_namespace})"
            if USE_KUBERNETES
            else f"file ({log_path})"
        )
        console.print(
            f"[bold red]ERROR: No log lines loaded from {source}[/]"
        )
        sys.exit(1)

    # Step 2 — Process logs
    if verbose:
        console.print("[dim]Step 2/5: Processing logs...[/dim]")
    entries = processor.process(lines)
    filtered = processor.filter_by_severity(entries, severity)
    if service_filter:
        filtered = processor.filter_by_service(filtered, service_filter)
    summary = processor.get_summary(entries)
    if verbose:
        console.print(
            f"[dim]  Found {summary['errors']} errors across "
            f"{len(summary['services'])} services[/dim]"
        )

    # Step 3 — Collect resources
    if verbose:
        console.print("[dim]Step 3/5: Collecting resource data...[/dim]")
    resources = collector.get_resources(
        summary["services"],
        namespace=active_namespace,
        use_mock=use_mock,
    )
    critical = collector.get_critical_services(resources)

    # Step 4 — Build context
    if verbose:
        console.print("[dim]Step 4/5: Building incident context...[/dim]")
    context = builder.build(filtered, resources)
    incident_summary = builder.get_incident_summary(context)

    # Step 4.5 — RAG retrieval
    rag_context = ""
    retrieved = []
    if mode == "rag":
        if verbose:
            console.print("[dim]Step 4.5/5: RAG retrieval...[/dim]")
        rag = RAGEngine(HISTORICAL_LOGS_DIR)
        retrieved = rag.retrieve(context["formatted_logs"], top_k=3)
        rag_context = rag.format_retrieved_context(retrieved)

    # Step 5 — LLM analysis
    if verbose:
        console.print(f"[dim]Step 5/5: LLM analysis ({mode} mode)...[/dim]")

    # Warmup model if flag enabled
    if LLM_WARMUP and mode != "cache_test":
        analyzer.warmup()

    if not analyzer.check_ollama_connection():
        console.print(
            "[bold red]ERROR: Ollama not running.\nStart with: ollama serve[/bold red]"
        )
        sys.exit(1)

    # Use spinner while LLM runs
    spinner_msg = f"Analyzing with phi3:mini [bold cyan]({mode} mode)[/bold cyan]..."
    with formatter.spinner(spinner_msg):
        if mode == "rag":
            result = analyzer.analyze_rag(context, rag_context, query=query)
        else:
            result = analyzer.analyze_baseline(context, query=query)

    # Enrich result
    result["incident_summary"] = incident_summary
    result["services_found"] = summary["services"]
    result["critical_pods"] = critical
    result["retrieved_incidents"] = retrieved
    result["rag_context_used"] = rag_context
    result["resources"] = resources

    # Save result for chat command (Task 22)
    _save_last_result(result)

    return result


def _save_last_result(result: dict):
    """Save result to .last_rca.json for chat command."""
    try:
        save_data = {k: v for k, v in result.items() if k != "resources"}
        with open(".last_rca.json", "w") as f:
            json.dump(save_data, f, indent=2)
    except Exception:
        pass  # Non-critical, don't crash


def _load_last_result() -> dict | None:
    """Load last saved result from .last_rca.json."""
    try:
        with open(".last_rca.json", "r") as f:
            return json.load(f)
    except Exception:
        return None


def _timestamp() -> str:
    # Return current time as HH:MM:SS string
    from datetime import datetime

    return datetime.now().strftime("%H:%M:%S")


def _print_watch_rca(result: dict, console, rca_count: int):
    # Print a compact RCA summary for watch mode
    # (not the full rich UI — just key fields)
    # This avoids overwhelming the terminal during
    # live monitoring
    #
    # Print:
    # ┌─────────────────────────────────────┐
    # │  Quick RCA #N                       │
    # │  Root Cause: ...                    │
    # │  Confidence: N%                     │
    # │  Top Fix: [High] ...                │
    # │  Historical: yes/no                 │
    # └─────────────────────────────────────┘
    #
    # Use rich Panel with:
    #   Title: f"Quick RCA #{rca_count}"
    #   Border: green if confidence>=70
    #           yellow if confidence>=50
    #           red if confidence<50
    #
    # Show only:
    #   root_cause (first 150 chars)
    #   confidence with color
    #   first suggested fix only
    #   historical_match (RAG mode only)
    #
    # After panel print Rule(style="dim")

    from rich.panel import Panel

    confidence = result.get("confidence", 0)
    root_cause = result.get("root_cause", "N/A")[:150]
    fixes = result.get("suggested_fixes", [])
    top_fix = fixes[0] if fixes else {"priority": "N/A", "fix": "N/A"}
    historical = result.get("historical_match", "no")

    # Determine border color
    if confidence >= 70:
        border_style = "green"
    elif confidence >= 50:
        border_style = "yellow"
    else:
        border_style = "red"

    # Build content
    content = f"Root Cause: {root_cause}\n"
    content += f"Confidence: {confidence}%\n"
    content += f"Top Fix: [{top_fix['priority']}] {top_fix['fix'][:100]}"
    if result.get("mode") == "rag":
        content += f"\nHistorical: {historical}"

    panel = Panel(
        content,
        title=f"Quick RCA #{rca_count}",
        border_style=border_style,
        padding=(1, 2),
    )

    console.print(panel)
    console.print(Rule(style="dim"))


def _format_fixes_for_context(fixes: list[dict]) -> str:
    # Format suggested fixes list as plain text
    # for injection into the chat system context
    # Returns string like:
    # - [High] Increase DB connection pool size
    # - [Medium] Fix connection leak in retry logic
    # - [Low] Add monitoring alerts
    if not fixes:
        return "No fixes available"
    lines = []
    for fix in fixes:
        lines.append(f"- [{fix.get('priority', 'Unknown')}] {fix.get('fix', '')}")
    return "\n".join(lines)


def _build_chat_prompt(system_context: str, history: list[dict]) -> str:
    # Build the full prompt for LLM chat
    # Combines system context + conversation history
    #
    # Structure:
    # {system_context}
    #
    # === CONVERSATION HISTORY ===
    # User: {message}
    # Assistant: {response}
    # User: {message}
    # ...
    #
    # === CURRENT QUESTION ===
    # User: {last message}
    #
    # Please respond helpfully and concisely.
    # Reference the incident details when relevant.
    #
    # Keep last N turns of history to avoid
    # exceeding prompt limits:
    #   max_turns = 6
    #   Use only last max_turns messages

    max_turns = 6
    recent = history[-max_turns:]

    lines = [system_context.strip()]
    lines.append("\n=== CONVERSATION HISTORY ===")

    # All but last message
    for msg in recent[:-1]:
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{role}: {msg['content']}")

    lines.append("\n=== CURRENT QUESTION ===")
    if recent:
        last = recent[-1]
        role = "User" if last["role"] == "user" else "Assistant"
        lines.append(f"{role}: {last['content']}")

    lines.append(
        "\nPlease respond helpfully and concisely. "
        "Reference the incident details above "
        "when relevant. Keep your answer focused."
    )

    return "\n".join(lines)


def print_result(result: dict):
    """Plain text fallback output for analysis results."""
    console.print("\n" + "=" * 60)
    console.print("RCA RESULT")
    console.print("=" * 60 + "\n")

    console.print(f"Mode: {result.get('mode', 'unknown')}")
    console.print(f"Confidence: {result.get('confidence', 0)}%")
    console.print()

    console.print("ROOT CAUSE:")
    console.print(f"  {result.get('root_cause', 'N/A')}")
    console.print()

    console.print("AFFECTED SERVICES:")
    console.print(f"  {result.get('affected_services', 'N/A')}")
    console.print()

    console.print("FAILURE CHAIN:")
    for line in result.get("failure_chain", "N/A").split("\n"):
        console.print(f"  {line}")
    console.print()

    console.print("SUGGESTED FIXES:")
    for fix in result.get("suggested_fixes", []):
        priority = fix.get("priority", "Unknown")
        fix_text = fix.get("fix", "N/A")
        console.print(f"  [{priority}] {fix_text}")
    console.print()

    console.print("CONFIDENCE REASON:")
    console.print(f"  {result.get('confidence_reason', 'N/A')}")
    console.print()

    if result.get("mode") == "rag":
        console.print("HISTORICAL MATCH:")
        console.print(f"  {result.get('historical_match', 'no')}")
        console.print()

    console.print("=" * 60 + "\n")


@click.group()
@click.version_option(version="1.0.0", prog_name="sre-ai")
def cli():
    """SRE-AI Root Cause Analysis Tool

    Analyze logs with LLM + RAG to generate actionable RCA reports.
    """
    pass


@cli.command()
@click.argument(
    "log_file",
    type=click.Path(),
    required=False,
    default=None
)
@click.option(
    "--mode", "-m",
    type=click.Choice(["baseline", "rag"]),
    default="rag",
    show_default=True
)
@click.option(
    "--severity", "-s",
    type=click.Choice(["ERROR","WARN","ALL"]),
    default="ERROR",
    show_default=True
)
@click.option(
    "--service",
    default=None,
    help="Filter by service name"
)
@click.option(
    "--namespace", "-n",
    default=None,
    help="Kubernetes namespace "
         "(overrides SOURCE_NAMESPACE in .env)"
)
@click.option(
    "--mock",
    is_flag=True,
    default=False,
    help="Force mock resource data "
         "even if SOURCE_KUBERNETES=true"
)
@click.option(
    "--output", "-o",
    type=click.Choice([
        "rich", "json", "plain"
    ]),
    default="rich",
    show_default=True
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False
)
def analyze(log_file, mode, severity,
            service, namespace, mock,
            output, verbose):
    """
    Analyze logs and generate RCA.

    Log file is optional when
    SOURCE_KUBERNETES=true in .env.

    Examples:\n
      python main.py analyze logs/test.log\n
      python main.py analyze logs/test.log
      --mode baseline\n
      python main.py analyze\n
      --namespace sre-demo\n
      python main.py analyze logs/test.log
      --mock
    """
    from flags import USE_KUBERNETES

    if not log_file and not USE_KUBERNETES:
        console.print(
            "[bold red]ERROR: Provide a log "
            "file path, or set "
            "SOURCE_KUBERNETES=true in .env"
            "[/bold red]"
        )
        return

    if log_file and not os.path.exists(
        log_file
    ):
        console.print(
            f"[bold red]ERROR: Log file not "
            f"found: {log_file}[/bold red]"
        )
        return

    result = run_pipeline(
        log_path=log_file,
        severity=severity,
        mode=mode,
        service_filter=service,
        use_mock=True if mock else None,
        namespace=namespace,
        verbose=verbose
    )

    if output == "json":
        output_data = {
            k: v for k, v in result.items()
            if k not in [
                "resources",
                "rag_context_used"
            ]
        }
        click.echo(
            json.dumps(output_data, indent=2)
        )
    elif output == "plain":
        print_result(result)
    else:
        formatter = RCAFormatter()
        resources = result.get("resources", {})
        formatter.print_full_result(
            result, resources
        )


@cli.command()
def status():
    """Check environment and system status."""

    console.print(Rule("SRE-AI System Status", style="bold blue"))

    # Check Python version
    v = sys.version_info
    console.print(
        f"  Python    : [bold green]{v.major}.{v.minor}.{v.micro}[/bold green]"
    )

    # Check virtual env
    venv = os.environ.get("VIRTUAL_ENV", "")
    if venv:
        venv_name = os.path.basename(venv)
        console.print(f"  Venv      : [bold green]{venv_name}[/bold green]")
    else:
        console.print("  Venv      : [bold yellow]not activated[/bold yellow]")

    # Check Ollama
    analyzer = LLMAnalyzer()
    ollama_ok = analyzer.check_ollama_connection()
    if ollama_ok:
        console.print("  Ollama    : [bold green]OK[/bold green]")
    else:
        console.print(
            "  Ollama    : [bold red]NOT RUNNING[/bold red] — run: ollama serve"
        )

    # Check ChromaDB / RAG
    chroma_path = ".chromadb"
    if os.path.exists(chroma_path):
        try:
            rag = RAGEngine(HISTORICAL_LOGS_DIR)
            stats = rag.get_collection_stats()
            console.print(
                f"  ChromaDB  : [bold green]OK[/bold green] — "
                f"{stats['total_chunks']} chunks, "
                f"{len(stats['files_indexed'])} files"
            )
        except Exception:
            console.print("  ChromaDB  : [bold yellow]exists but error[/bold yellow]")
    else:
        console.print("  ChromaDB  : [bold red]NOT INITIALIZED[/bold red]")

    # Check log files
    if os.path.exists(DEFAULT_LOG_PATH):
        console.print(f"  Test log  : [bold green]OK[/bold green] — {DEFAULT_LOG_PATH}")
    else:
        console.print(
            f"  Test log  : [bold red]NOT FOUND[/bold red] — {DEFAULT_LOG_PATH}"
        )

    # Check last RCA
    last = _load_last_result()
    if last:
        console.print(
            f"  Last RCA  : [bold green]available[/bold green] — "
            f"mode: {last.get('mode', 'unknown')}, "
            f"confidence: {last.get('confidence', 0)}%"
        )
    else:
        console.print("  Last RCA  : [dim]none — run analyze first[/dim]")

    # Cache status
    from core.llm_cache import LLMCache

    lc = LLMCache()
    cs = lc.stats()
    if cs["total_entries"] > 0:
        console.print(
            f"  LLM Cache : "
            f"[bold green]"
            f"{cs['total_entries']} entries"
            f"[/bold green]"
            f", {cs['total_size_kb']} KB"
        )
    else:
        console.print("  LLM Cache : [dim]empty[/dim]")

    console.print()


@cli.command()
@click.argument("log_file", type=click.Path(exists=True))
@click.option(
    "--interval", "-i", default=2, show_default=True, help="Poll interval in seconds"
)
@click.option(
    "--severity",
    "-s",
    type=click.Choice(["ERROR", "WARN", "ALL"]),
    default="ERROR",
    show_default=True,
    help="Severity level to watch for",
)
@click.option(
    "--mode",
    "-m",
    type=click.Choice(["baseline", "rag"]),
    default="rag",
    show_default=True,
    help="Analysis mode when errors detected",
)
@click.option(
    "--threshold",
    "-t",
    default=3,
    show_default=True,
    help="Minimum new error lines before triggering RCA",
)
def watch(log_file, interval, severity, mode, threshold):
    """
    Watch a log file in real-time and auto-trigger
    RCA when new errors are detected.

    Polls every N seconds. Press Ctrl+C to stop.

    Examples:\n
      python main.py watch logs/test.log\n
      python main.py watch logs/test.log
      --interval 5\n
      python main.py watch logs/test.log
      --mode baseline --threshold 1
    """

    import time

    console = Console()
    formatter = RCAFormatter()
    processor = LogProcessor()

    # ─── Startup banner ──────────────────────────
    console.print(Rule("SRE-AI Live Log Monitor", style="bold cyan"))
    console.print(
        f"  Watching  : [bold white]{log_file}[/]\n"
        f"  Interval  : [bold white]{interval}s[/]\n"
        f"  Severity  : [bold white]{severity}[/]\n"
        f"  Mode      : [bold white]{mode}[/]\n"
        f"  Threshold : [bold white]{threshold} "
        f"new errors[/]\n",
        style="dim",
    )
    console.print(
        "  [bold green]Monitoring started[/bold green]"
        " — Press [bold red]Ctrl+C[/bold red] "
        "to stop\n"
    )

    # ─── State tracking ───────────────────────────
    seen_line_count = 0
    rca_count = 0
    watch_start = time.time()
    last_rca_time = 0
    # Minimum seconds between RCA triggers
    # to avoid spamming the LLM
    rca_cooldown = 30

    # ─── Initial line count ───────────────────────
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            seen_line_count = len(f.readlines())
        console.print(f"  [dim]Starting at line {seen_line_count}[/dim]\n")
    except Exception as e:
        console.print(f"[bold red]ERROR reading file: {e}[/bold red]")
        return

    # ─── Watch loop ───────────────────────────────
    try:
        while True:
            time.sleep(interval)

            # Read current file state
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
            except Exception as e:
                console.print(f"[bold red]Read error: {e}[/bold red]")
                continue

            current_count = len(all_lines)

            # Detect new lines
            if current_count <= seen_line_count:
                # No new lines — print heartbeat
                # every 10 polls
                elapsed = int(time.time() - watch_start)
                if elapsed % (interval * 10) < interval:
                    console.print(
                        f"  [dim]{_timestamp()} "
                        f"Watching... "
                        f"({elapsed}s elapsed, "
                        f"{rca_count} RCAs triggered)"
                        f"[/dim]"
                    )
                continue

            # Get new lines since last check
            new_lines = [l.rstrip() for l in all_lines[seen_line_count:] if l.strip()]
            seen_line_count = current_count

            if not new_lines:
                continue

            # Show new lines detected
            console.print(
                f"  [bold white]{_timestamp()}[/] "
                f"[dim]{len(new_lines)} new "
                f"line(s) detected[/dim]"
            )

            # Process new lines for errors
            entries = processor.process(new_lines)
            error_entries = processor.filter_by_severity(entries, severity)

            if not error_entries:
                # New lines but no errors
                console.print(
                    f"  [dim]{_timestamp()} No {severity} entries in new lines[/dim]"
                )
                continue

            # Show error alert
            console.print()
            console.print(
                Rule(
                    f"{_timestamp()} — "
                    f"{len(error_entries)} New "
                    f"{severity} Line(s) Detected",
                    style="bold red",
                )
            )

            # Show the new error lines
            for entry in error_entries[:5]:
                console.print(
                    f"  [bold red]"
                    f"[{entry['level']}][/bold red] "
                    f"[cyan][{entry['service']}]"
                    f"[/cyan] "
                    f"[white]{entry['message']}[:200]"
                    f"[/white]"
                )
            if len(error_entries) > 5:
                console.print(f"  [dim]... and {len(error_entries) - 5} more[/dim]")
            console.print()

            # Check threshold
            if len(error_entries) < threshold:
                console.print(
                    f"  [dim]Below threshold "
                    f"({len(error_entries)} < "
                    f"{threshold}) — skipping RCA"
                    f"[/dim]\n"
                )
                continue

            # Check cooldown
            now = time.time()
            since_last = now - last_rca_time
            if last_rca_time > 0 and since_last < rca_cooldown:
                remaining = int(rca_cooldown - since_last)
                console.print(
                    f"  [dim]RCA cooldown: "
                    f"{remaining}s remaining "
                    f"before next analysis[/dim]\n"
                )
                continue

            # Trigger RCA
            rca_count += 1
            last_rca_time = now
            console.print(
                f"  [bold cyan]Triggering RCA "
                f"#{rca_count} ({mode} mode)"
                f"...[/bold cyan]\n"
            )

            try:
                result = run_pipeline(
                    log_path=log_file, severity=severity, mode=mode, verbose=False, query=log_file
                    )
                _print_watch_rca(result, console, rca_count)
            except Exception as e:
                    console.print(f"  [bold red]RCA failed: {e}[/bold red]\n")

            except Exception as e:
                console.print(f"  [bold red]RCA failed: {e}[/bold red]\n")

    except KeyboardInterrupt:
        elapsed = int(time.time() - watch_start)
        console.print()
        console.print(Rule("Monitor Stopped", style="dim"))
        console.print(
            f"  Watched for : {elapsed}s\n"
            f"  RCAs run    : {rca_count}\n"
            f"  Final line  : {seen_line_count}",
            style="dim white",
        )
    console.print()


@cli.command()
@click.option(
    "--clear", is_flag=True, default=False, help="Clear all cached LLM responses"
)
@click.option(
    "--clear-expired",
    is_flag=True,
    default=False,
    help="Clear only expired cache entries",
)
def cache(clear, clear_expired):
    """
    Manage the LLM response cache.

    Examples:\n
      python main.py cache\n
      python main.py cache --clear\n
      python main.py cache --clear-expired
    """
    from core.llm_cache import LLMCache
    from rich.table import Table
    from rich import box

    lc = LLMCache()
    stats = lc.stats()

    if clear:
        count = lc.clear(0)
        console.print(f"[bold green]Cleared {count} cache entries.[/]")
        return

    if clear_expired:
        count = lc.clear(older_than_seconds=LLM_CACHE_TTL)
        console.print(f"[bold green]Cleared {count} expired entries.[/]")
        return

    # Show cache stats
    table = Table(title="LLM Cache Statistics", box=box.ROUNDED)
    table.add_column("Property", style="bold white")
    table.add_column("Value", style="cyan")

    table.add_row(
        "Cache enabled", "[green]yes[/]" if stats["enabled"] else "[red]no[/]"
    )
    table.add_row("Cache directory", stats["cache_dir"])
    table.add_row("Total entries", str(stats["total_entries"]))
    table.add_row("Total size", f"{stats['total_size_kb']} KB")
    table.add_row("TTL", f"{stats['ttl_seconds']}s ({stats['ttl_seconds'] // 60} min)")
    if stats["total_entries"] > 0:
        table.add_row("Newest entry", f"{stats['newest_entry_age']}s ago")
        table.add_row("Oldest entry", f"{stats['oldest_entry_age']}s ago")
    console.print(table)


@cli.command()
@click.argument("log_file", type=click.Path(exists=True))
@click.option(
    "--severity",
    "-s",
    type=click.Choice(["ERROR", "WARN", "ALL"]),
    default="ERROR",
    show_default=True,
    help="Log severity level to analyze",
)
@click.option(
    "--save-report",
    is_flag=True,
    default=False,
    help="Save comparison to evaluation_report.txt",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Show pipeline step progress"
)
def compare(log_file, severity, save_report, verbose):
    """
    Run baseline AND RAG mode, show side-by-side
    comparison. Used for dissertation evaluation.

    Examples:\n
      python main.py compare logs/test.log\n
      python main.py compare logs/test.log
      --save-report\n
      python main.py compare logs/test.log
      --severity WARN
    """

    console = Console()

    console.print(Rule("SRE-AI Evaluation Mode", style="bold magenta"))
    console.print(
        "  Running both baseline and RAG analysis\n"
        "  on the same log file for comparison.\n",
        style="dim white",
    )

    # ─── Run baseline mode ───────────────────────
    console.print(Rule("Step 1 of 2 — Baseline Analysis", style="yellow"))
    console.print(
        "  Running LLM-only analysis (no historical context)...\n", style="dim white"
    )

    baseline_result = run_pipeline(
        log_path=log_file, severity=severity, mode="baseline", verbose=verbose
    )

    console.print(
        f"  [bold yellow]Baseline complete[/] — "
        f"confidence: "
        f"{baseline_result['confidence']}%\n"
    )

    # ─── Run RAG mode ────────────────────────────
    console.print(Rule("Step 2 of 2 — RAG-Augmented Analysis", style="cyan"))
    console.print(
        "  Running RAG-augmented analysis (with historical context)...\n",
        style="dim white",
    )

    rag_result = run_pipeline(
        log_path=log_file, severity=severity, mode="rag", verbose=verbose
    )

    console.print(
        f"  [bold cyan]RAG complete[/] — confidence: {rag_result['confidence']}%\n"
    )

    # ─── Show comparison ─────────────────────────
    comparator = Comparator()
    retrieved = rag_result.get("retrieved_incidents", [])

    comparator.compare(baseline_result, rag_result, retrieved)

    # ─── Save report if requested ────────────────
    if save_report:
        report_path = "evaluation_report.txt"
        comparator.save_comparison_report(
            baseline_result, rag_result, retrieved, report_path
        )
        console.print(f"\n[bold green]Report saved to: {report_path}[/bold green]")

    # ─── Final summary line ───────────────────────
    diff = rag_result["confidence"] - baseline_result["confidence"]
    console.print()
    if diff > 0:
        console.print(
            f"[bold green]RAG improved confidence "
            f"by +{diff} percentage points "
            f"({baseline_result['confidence']}% "
            f"→ {rag_result['confidence']}%)"
            f"[/bold green]"
        )
    elif diff < 0:
        console.print(
            f"[bold yellow]Note: RAG confidence "
            f"lower by {abs(diff)} points this run "
            f"— acceptable with small models and "
            f"mock data. Will improve with real "
            f"kubectl data in Phase 5.[/bold yellow]"
        )
    else:
        console.print("[dim]Confidence equal in both modes this run.[/dim]")
    console.print()


@cli.command()
@click.option(
    "--log-file",
    type=click.Path(exists=True),
    default=None,
    help="Optionally load a fresh log file before starting chat",
)
@click.option(
    "--mode",
    "-m",
    type=click.Choice(["baseline", "rag"]),
    default="rag",
    show_default=True,
    help="Analysis mode if loading fresh log",
)
def chat(log_file, mode):
    """
    Interactive chat session about the last
    analyzed incident. Ask follow-up questions
    about root cause, fixes, and impact.

    Loads the last RCA result automatically.
    Run 'analyze' first if no RCA exists.

    Commands during chat:\n
      exit / quit  — end session\n
      clear        — clear conversation history\n
      history      — show conversation so far\n
      summary      — show last RCA summary\n
      help         — show available commands

    Examples:\n
      python main.py chat\n
      python main.py chat
      --log-file logs/test.log
    """

    import time

    console = Console()
    analyzer = LLMAnalyzer()

    # ─── Startup banner ──────────────────────────
    console.print(Rule("SRE-AI Interactive Chat", style="bold cyan"))
    console.print(
        "  Ask follow-up questions about the\n  last analyzed incident.\n",
        style="dim white",
    )

    # ─── Load last RCA or run fresh analysis ──────
    last_result = None

    if log_file:
        # Run fresh analysis first
        console.print(f"  [dim]Running fresh analysis on {log_file}...[/dim]\n")
        last_result = run_pipeline(log_path=log_file, mode=mode, verbose=False)
        formatter = RCAFormatter()
        formatter.print_full_result(last_result, last_result.get("resources", {}))
    else:
        # Load from saved .last_rca.json
        last_result = _load_last_result()

    if not last_result:
        console.print(
            "[bold red]No RCA found.[/bold red]\n"
            "Run 'python main.py analyze "
            "logs/test.log' first,\n"
            "or use: python main.py chat "
            "--log-file logs/test.log"
        )
        return

    # ─── Build system context for LLM ────────────
    # This is injected into every message to keep
    # the LLM grounded in the incident context

    incident_context = f"""
You are an expert SRE assistant helping to
investigate a Kubernetes microservices incident.

Here is the root cause analysis that was
already performed:

ROOT CAUSE: {last_result.get("root_cause", "N/A")}

AFFECTED SERVICES:
{last_result.get("affected_services", "N/A")}

FAILURE CHAIN:
{last_result.get("failure_chain", "N/A")}

SUGGESTED FIXES:
{_format_fixes_for_context(last_result.get("suggested_fixes", []))}

CONFIDENCE: {last_result.get("confidence", 0)}%

HISTORICAL MATCH:
{last_result.get("historical_match", "N/A")}

INCIDENT SUMMARY:
{last_result.get("incident_summary", "N/A")}

You have full knowledge of this incident.
Answer follow-up questions helpfully and
specifically. Reference the incident details
above in your answers when relevant.
Keep answers concise but complete.
"""

    # ─── Show incident summary ────────────────────
    console.print(Rule("Current Incident Context", style="dim cyan"))
    console.print(
        f"  Root cause : [bold red]"
        f"{last_result.get('root_cause', 'N/A')[:100]}"
        f"[/bold red]\n"
        f"  Confidence : [bold cyan]"
        f"{last_result.get('confidence', 0)}%"
        f"[/bold cyan]\n"
        f"  Mode used  : [bold white]"
        f"{last_result.get('mode', 'N/A')}"
        f"[/bold white]\n"
    )
    console.print("  Type [bold cyan]help[/bold cyan] for available commands.\n")

    # ─── Conversation history ─────────────────────
    # Each entry: {"role": "user"/"assistant",
    #              "content": "..."}
    conversation_history = []

    # ─── Chat loop ────────────────────────────────
    while True:
        try:
            # Get user input
            console.print("[bold green]You:[/bold green] ", end="")
            user_input = input().strip()

        except (KeyboardInterrupt, EOFError):
            console.print()
            console.print("[dim]Session ended.[/dim]")
            break

        if not user_input:
            continue

        # ─── Built-in commands ─────────────────
        cmd = user_input.lower()

        if cmd in ("exit", "quit", "bye"):
            console.print("\n[dim]Chat session ended. Goodbye.[/dim]\n")
            break

        elif cmd == "clear":
            conversation_history = []
            console.print("[dim]Conversation history cleared.[/dim]\n")
            continue

        elif cmd == "history":
            if not conversation_history:
                console.print("[dim]No conversation history yet.[/dim]\n")
            else:
                console.print(Rule("Conversation History", style="dim"))
                for i, msg in enumerate(conversation_history):
                    role = msg["role"]
                    color = "green" if role == "user" else "cyan"
                    label = "You" if role == "user" else "SRE-AI"
                    console.print(
                        f"[bold {color}]{label}:[/bold {color}] {msg['content'][:200]}"
                    )
                console.print()
            continue

        elif cmd == "summary":
            console.print(Rule("Incident Summary", style="dim cyan"))
            console.print(
                f"  Root cause : "
                f"{last_result.get('root_cause')}\n"
                f"  Confidence : "
                f"{last_result.get('confidence')}%\n"
                f"  Services   : "
                f"{last_result.get('affected_services')}\n"
                f"  Fixes      : "
                f"{len(last_result.get('suggested_fixes', []))} "
                f"provided\n"
            )
            continue

        elif cmd == "help":
            console.print(Rule("Available Commands", style="dim"))
            console.print(
                "  [bold cyan]exit/quit[/] "
                "    — end chat session\n"
                "  [bold cyan]clear[/]     "
                "    — clear conversation history\n"
                "  [bold cyan]history[/]   "
                "    — show conversation so far\n"
                "  [bold cyan]summary[/]   "
                "    — show incident summary\n"
                "  [bold cyan]help[/]      "
                "    — show this help\n"
                "\n"
                "  Or just type any question about\n"
                "  the incident and I will answer.\n"
                "\n"
                "  Example questions:\n"
                "  'Why did the database fail?'\n"
                "  'How do I apply the fix?'\n"
                "  'What is a connection pool?'\n"
                "  'How long will the fix take?'\n"
            )
            continue

        # ─── Send to LLM ───────────────────────
        # Add user message to history
        conversation_history.append({"role": "user", "content": user_input})

        # Build full prompt with context +
        # conversation history
        full_prompt = _build_chat_prompt(incident_context, conversation_history)

        # Check Ollama
        if not analyzer.check_ollama_connection():
            console.print(
                "[bold red]Ollama not running. Start with: ollama serve[/bold red]\n"
            )
            continue

        # Call LLM with spinner
        console.print("[bold cyan]SRE-AI:[/bold cyan] ", end="")

        with console.status("[dim]thinking...[/dim]", spinner="dots"):
            response = analyzer._call_ollama(full_prompt)

        if not response:
            console.print("[bold red]No response from LLM. Try again.[/bold red]\n")
            # Remove the failed user message
            conversation_history.pop()
            continue

        # Clean up response
        response = response.strip()

        # Print response
        console.print(f"[cyan]{response}[/cyan]\n")

        # Add to history
        conversation_history.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    cli()
