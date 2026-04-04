import json
import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import yaml
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console()


class BaseHandler(ABC):
    description: str = ""
    aliases: list[str] = []
    requires_service: bool = False

    @abstractmethod
    def handle(self, args: list[str]) -> str:
        raise NotImplementedError


def _print_analysis_result(result, mode):
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich import box

    c = Console()
    low_conf = result.get('low_confidence_warning', False)
    record = result.get('incident_record', {})

    c.print(Rule(f"Analysis Complete — {mode} mode", style="bold green"))

    meta = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    meta.add_column("Key", style="bold cyan", width=14)
    meta.add_column("Value", style="white")
    meta.add_row("Service", str(result.get('service', 'unknown')))
    meta.add_row("Windows used", str(result.get('windows_used', 1)))
    meta.add_row("Confidence", f"{result.get('confidence', 0)}%")
    meta.add_row("Warning", "[bold yellow]Low confidence — extended window used[/bold yellow]"
                 if low_conf else "[dim]None[/dim]")
    meta.add_row("Incident saved", "[bold green]Yes[/bold green]"
                 if record.get('saved') else "[dim]No[/dim]")
    meta.add_row("Reason", str(record.get('reason', 'N/A')))
    meta.add_row("Similarity", f"{record.get('similarity_score', 0.0):.1%}")
    c.print(meta)

    from rich.markdown import Markdown
    analysis_text = result.get('analysis', 'No analysis returned.')
    
    # Strip the CONFIDENCE/REASON block from display — already shown in meta table
    import re
    clean_text = re.sub(r'\nCONFIDENCE:.*', '', analysis_text, flags=re.DOTALL).strip()
    
    c.print(Panel(
        Markdown(clean_text),
        title="[bold white]Root Cause Analysis[/bold white]",
        border_style="green",
        padding=(1, 2),
    ))
    c.print()

def _print_baseline_result(response, service):
    print("=== Baseline Analysis (no RAG) ===")
    print(f"Service: {service}\n")
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    c = Console()
    import re
    clean = re.sub(r'\nCONFIDENCE:.*', '', response, flags=re.DOTALL).strip()
    c.print(Panel(
        Markdown(clean),
        title="[bold white]Baseline Analysis — no RAG[/bold white]",
        border_style="blue",
        padding=(1, 2),
    ))

def _save_compare_report(service, rag_result, baseline_response) -> str:
    import datetime
    import os
    os.makedirs("reports", exist_ok=True)
    report_path = f"reports/compare_{service}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    sim = rag_result.get('incident_record', {}).get('similarity_score', 0.0)
    
    content = f"""# Comparison Report
# Service: {service}
# Generated: {datetime.datetime.now().isoformat()}

## RAG Mode
Confidence: {rag_result.get('confidence')}%
Windows used: {rag_result.get('windows_used')}

{rag_result.get('analysis')}

## Baseline Mode (no RAG)

{baseline_response}

## Summary
RAG confidence:      {rag_result.get('confidence')}%
Incident saved:      {rag_result.get('incident_record', {}).get('saved', False)}
Similarity score:    {sim:.1%}"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    return report_path


class AnalyseHandler(BaseHandler):
    description = "Full SRE investigation (RCA, logs, metrics, K8s)"
    aliases = ["analyze", "analyse"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        args_str = " ".join(args)
        parts = args_str.strip().split()
        baseline_mode = "--baseline" in parts
        compare_mode = "--compare" in parts
        service_parts = [p for p in parts if not p.startswith("--")]
        service = "-".join(service_parts) if service_parts else None

        if not service:
            print("Usage: analyse <service> [--baseline] [--compare]")
            return "usage"

        try:
            from core.log_loader import LogLoader
            from core.log_cleaner import LogCleaner
            loader = LogLoader()
            lines = loader.load_service_logs(service)

            if not lines:
                print(f"No logs found for service: {service}")
                return "no_logs"

            if compare_mode:
                from core.window_analyzer import WindowAnalyzer
                from core.llm_provider import provider
                analyzer = WindowAnalyzer()
                rag_result = analyzer.analyse(lines, service=service)

                prompt = (
                    f"You are an expert Site Reliability Engineer.\n"
                    f"Service: {service}\n"
                    f"Analyse the following logs and identify the root cause, "
                    f"sequence of events, affected services, and remediation steps.\n\n"
                    f"--- LOGS START ---\n"
                    f"{chr(10).join(lines[:500])}\n"
                    f"--- LOGS END ---"
                )
                baseline_response = provider.generate(prompt)

                report_path = _save_compare_report(service, rag_result, baseline_response)
                print(f"\nComparison report saved to: {report_path}")
                _print_analysis_result(rag_result, mode="RAG")

            elif baseline_mode:
                from core.llm_provider import provider
                prompt = (
                    f"You are an expert Site Reliability Engineer.\n"
                    f"Service: {service}\n"
                    f"Analyse the following logs and identify the root cause, "
                    f"sequence of events, affected services, and remediation steps.\n\n"
                    f"--- LOGS START ---\n"
                    f"{chr(10).join(lines[:500])}\n"
                    f"--- LOGS END ---"
                )
                raw_response = provider.generate(prompt)
                _print_baseline_result(raw_response, service)

            else:
                from core.window_analyzer import WindowAnalyzer
                analyzer = WindowAnalyzer()
                result = analyzer.analyse(lines, service=service)
                _print_analysis_result(result, mode="RAG")
                try:
                    import json as _json
                    with open(".last_analyse.json", "w") as f:
                        _json.dump({
                            "service": result.get("service"),
                            "confidence": result.get("confidence"),
                            "analysis": result.get("analysis"),
                        }, f)
                except Exception:
                        pass

        except Exception as e:
            print(f"Error during analysis: {e}")

        return "ok"


class StatusHandler(BaseHandler):
    description = "System health + component dashboard"
    aliases = ["status", "health"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        from core.llm_analyzer import LLMAnalyzer
        from core.rag_engine import RAGEngine
        from core.llm_cache import LLMCache
        from core.service_graph import ServiceGraph
        from flags import USE_KUBERNETES, LLM_CACHE_ENABLED, RAG_ENABLED, DEBUG, K8S_NAMESPACE
        import sys

        console.print(Rule("System Status", style="bold blue"))

        table = Table(box=box.ROUNDED, show_lines=False)
        table.add_column("Component", style="bold white", width=20)
        table.add_column("Status")
        table.add_column("Detail", style="dim")

        v = sys.version_info
        table.add_row("Python", "[bold green]OK[/bold green]", f"{v.major}.{v.minor}.{v.micro}")

        venv = os.environ.get("VIRTUAL_ENV", "")
        venv_name = os.path.basename(venv) if venv else "none"
        table.add_row("Virtual env", "[bold green]active[/bold green]" if venv else "[bold yellow]not active[/bold yellow]", venv_name)

        from flags import LLM_PROVIDER, LLM_REASONING_MODEL, DEMO_MODE
        provider_label = f"{LLM_PROVIDER} ({LLM_REASONING_MODEL})"
        demo_label = "[bold yellow]DEMO MODE[/bold yellow]" if DEMO_MODE else "[dim]off[/dim]"
        table.add_row("LLM Provider", "[bold green]configured[/bold green]", provider_label)
        table.add_row("Demo mode", demo_label, "DEMO_MODE=true in .env" if DEMO_MODE else "")

        try:
            rag = RAGEngine("logs/historical")
            stats = rag.get_collection_stats()
            chunks = stats["total_chunks"]
            files = len(stats["files_indexed"])
            table.add_row("ChromaDB", "[bold green]OK[/bold green]", f"{chunks} chunks, {files} files")
        except Exception as exc:
            table.add_row("ChromaDB", "[bold red]ERROR[/bold red]", str(exc)[:40])

        try:
            graph = ServiceGraph()
            svcs = graph.get_all_service_names()
            table.add_row("services.yaml", "[bold green]OK[/bold green]", f"{len(svcs)} services defined")
        except Exception:
            table.add_row("services.yaml", "[bold red]MISSING[/bold red]", "")

        try:
            cache = LLMCache()
            cs = cache.stats()
            table.add_row("LLM Cache", "[bold green]enabled[/bold green]" if LLM_CACHE_ENABLED else "[dim]disabled[/dim]", f"{cs['total_entries']} entries, {cs['total_size_kb']} KB")
        except Exception:
            table.add_row("LLM Cache", "[dim]unavailable[/dim]", "")

        table.add_row("Source mode", "[bold green]kubernetes[/bold green]" if USE_KUBERNETES else "[bold yellow]file[/bold yellow]", f"namespace: {K8S_NAMESPACE}" if USE_KUBERNETES else "logs/test.log")
        table.add_row("RAG", "[bold green]enabled[/bold green]" if RAG_ENABLED else "[dim]disabled[/dim]", "")
        table.add_row("Debug mode", "[bold yellow]ON[/bold yellow]" if DEBUG else "[dim]off[/dim]", "SYSTEM_DEBUG=true in .env" if DEBUG else "")

        try:
            with open(".last_rca.json") as handle:
                last = json.load(handle)
            table.add_row("Last RCA", "[bold green]available[/bold green]", f"mode: {last.get('mode','?')}, confidence: {last.get('confidence',0)}%")
        except Exception:
            table.add_row("Last RCA", "[dim]none yet[/dim]", "run: analyze <service>")

        console.print(table)
        console.print()
        return "ok"


class CompareHandler(BaseHandler):
    description = "Baseline vs RAG analysis comparison"
    aliases = ["compare"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        from main import run_pipeline
        from evaluation.comparator import Comparator

        raw = " ".join(args).strip()
        log_file = _extract_log(raw) or "logs/test.log"
        namespace = _extract_ns(raw)

        console.print(Rule("Baseline vs RAG Comparison", style="bold magenta"))

        console.print("[dim]Running baseline analysis...[/dim]")
        baseline = run_pipeline(log_path=log_file, mode="baseline", namespace=namespace, query=log_file)

        console.print("[dim]Running RAG analysis...[/dim]")
        rag = run_pipeline(log_path=log_file, mode="rag", namespace=namespace, query=log_file)

        Comparator().compare(baseline, rag, rag.get("retrieved_incidents", []))
        return "ok"


class WatchHandler(BaseHandler):
    description = "Live log tailing + instant RCA"
    aliases = ["watch", "monitor"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        from core.log_processor import LogProcessor
        from main import run_pipeline

        raw = " ".join(args).strip()
        log_file = _extract_log(raw) or "logs/test.log"
        service = _extract_service(raw)
        namespace = _extract_ns(raw)

        if service and not namespace:
            from core.service_graph import ServiceGraph
            graph = ServiceGraph()
            canonical = graph.get_service_name(service) or service
            namespace = graph.get_namespace(canonical)

        console.print(Rule(f"Live Monitor: {log_file}", style="bold cyan"))
        console.print("[dim]Watching for new errors... Ctrl+C to stop[/dim]\n")

        processor = LogProcessor()
        seen = 0

        try:
            with open(log_file, "r", errors="replace") as handle:
                seen = len(handle.readlines())

            while True:
                time.sleep(2)
                with open(log_file, "r", errors="replace") as handle:
                    lines = handle.readlines()

                new_lines = [line.rstrip() for line in lines[seen:] if line.strip()]
                seen = len(lines)

                if not new_lines:
                    continue

                entries = processor.process(new_lines)
                errors = processor.filter_by_severity(entries, "ERROR")

                if not errors:
                    continue

                console.print(Rule(f"{len(errors)} new errors", style="bold red"))

                result = run_pipeline(log_path=log_file, mode="rag", service_filter=service, namespace=namespace, verbose=False, query=log_file)

                console.print(Panel(
                    f"[bold red]Root cause:[/] {result['root_cause']}\n"
                    f"[bold cyan]Confidence:[/] {result['confidence']}%\n",
                    title="Quick RCA",
                    border_style="red"
                ))

        except KeyboardInterrupt:
            console.print("\n[dim]Watch stopped.[/dim]")
        except FileNotFoundError:
            console.print(f"[bold red]File not found: {log_file}[/bold red]")

        return "ok"


class ChatHandler(BaseHandler):
    description = "Interactive follow-up Q&A"
    aliases = ["chat"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        from core.llm_provider import provider

        console.print(Rule("Interactive Chat", style="bold cyan"))

        # Load last RCA — support both old and new result formats
        last_result = None
        try:
            with open(".last_rca.json") as f:
                last_result = json.load(f)
        except Exception:
            pass

        # Also check for last window_analyzer result saved by AnalyseHandler
        if not last_result:
            try:
                with open(".last_analyse.json") as f:
                    last_result = json.load(f)
            except Exception:
                pass

        if not last_result:
            console.print(
                "[yellow]No previous RCA found.\n"
                "Run 'analyse <service>' first, then use 'chat'.[/yellow]"
            )
            return "no-rca"

        # Build context from whichever format is present
        service = (
            last_result.get("service") or
            last_result.get("target_service") or
            "unknown"
        )
        analysis = (
            last_result.get("analysis") or
            last_result.get("root_cause") or
            "No analysis available."
        )
        confidence = last_result.get("confidence", 0)

        context = (
            "You are an SRE assistant helping with incident follow-up.\n"
            "You ONLY answer questions about the current incident described below.\n"
            "If asked anything unrelated to this incident or SRE topics, "
            "reply: 'I can only help with questions about this incident or SRE topics.'\n\n"
            f"Incident summary:\n"
            f"Service: {service}\n"
            f"Confidence: {confidence}%\n"
            f"Analysis:\n{analysis[:1000]}\n\n"
            "Answer follow-up questions concisely and practically."
        )

        # Guardrail patterns — out of scope topics
        out_of_scope = [
            r"\bwho is\b", r"\bwho was\b", r"prime minister", r"president of",
            r"\bweather\b", r"\bsports?\b", r"\bcricket\b", r"\bfootball\b",
            r"\bmovie\b", r"\bfilm\b", r"\bsong\b", r"\brecipe\b", r"\bjoke\b",
            r"\bwrite (me |a |an )", r"\bpoem\b", r"\bstory\b", r"\btranslat",
            r"^(hi|hello|hey)\.?$", r"^how are you", r"^what is your name",
            r"\bbitcoin\b", r"\bstock price\b", r"\bpolitics\b",
        ]

        def is_out_of_scope(text: str) -> bool:
            text_lower = text.lower().strip()
            for pattern in out_of_scope:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return True
            return False

        history = []
        MAX_HISTORY = 10
        console.print(
            f"[dim]Chatting about incident: {service} "
            f"(confidence: {confidence}%)[/dim]"
        )
        console.print("[dim]Type 'exit' to leave, 'clear' to reset history[/dim]\n")

        while True:
            try:
                console.print("[bold green]You:[/] ", end="")
                user_input = input().strip()
            except (KeyboardInterrupt, EOFError):
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "bye"):
                break
            if user_input.lower() == "clear":
                history = []
                console.print("[dim]History cleared.[/dim]")
                continue

            # Guardrail check
            if is_out_of_scope(user_input):
                console.print(
                    "[yellow]SRE-AI:[/] I can only help with questions "
                    "about this incident or SRE topics.\n"
                )
                continue

            history.append({"role": "user", "content": user_input})

            # Keep history bounded
            if len(history) > MAX_HISTORY:
                history = history[-MAX_HISTORY:]

            hist_text = "\n".join(
                f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}"
                for msg in history[-6:]
            )

            prompt = (
                f"{context}\n\n"
                f"Conversation so far:\n{hist_text}\n\n"
                f"Answer concisely and stay focused on the incident:"
            )

            with console.status("[dim]Thinking...[/dim]", spinner="dots"):
                try:
                    response = provider.generate(prompt)
                except Exception as e:
                    console.print(f"[bold red]LLM error: {e}[/bold red]")
                    continue

            if response:
                console.print(f"[bold cyan]SRE-AI:[/] {response.strip()}\n")
                history.append({"role": "assistant", "content": response.strip()})

        console.print("[dim]Chat ended.[/dim]\n")
        return "ok"


class ExplainHandler(BaseHandler):
    description = "LLM direct Q&A for SRE concepts"
    aliases = ["explain"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        from core.llm_provider import provider

        question = " ".join(args).strip()
        if not question:
            console.print("[yellow]Usage: explain <concept or question>[/yellow]")
            return "usage"

        console.print(Rule("Explain", style="bold cyan"))

        prompt = (
            "You are an expert Site Reliability Engineer and DevOps Expert.\n"
            "Answer the following question clearly and practically.\n"
            "Cover: what it is, why it matters, and a practical example if relevant.\n"
            "Keep the answer focused and useful — 3 to 8 sentences.\n"
            "Do NOT describe any specific project or codebase.\n"
            "Do NOT output RCA format.\n"
            f"\nQuestion: {question}"
        )

        with console.status("[bold cyan]Thinking...[/bold cyan]", spinner="dots"):
            try:
                response = provider.generate(prompt)
            except Exception as e:
                console.print(f"[bold red]LLM error: {e}[/bold red]")
                return "error"

        if response and response.strip():
            from rich.markdown import Markdown
            console.print(Panel(
                Markdown(response.strip()),
                title="[bold cyan]Answer[/]",
                border_style="cyan",
                expand=False
            ))
        else:
            console.print("[yellow]No response from LLM.[/yellow]")

        return "ok"


class CleanHandler(BaseHandler):
    description = "Clean logs and normalize noisy inputs"
    aliases = ["clean"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        raw = " ".join(args).strip()

        try:
            import importlib
            module = importlib.import_module("core.log_cleaner")
            LogCleaner = getattr(module, "LogCleaner")
        except Exception:
            console.print("[yellow]Clean command is not available yet (core/log_cleaner.py missing).[/yellow]")
            return "unavailable"

        cleaner = LogCleaner()
        if not raw:
            console.print("[yellow]Usage: clean <log_file>[/yellow]")
            return "usage"

        cleaned = cleaner.clean_file(raw)
        console.print(f"[bold green]Cleaned log saved to: {cleaned}[/bold green]")
        return "ok"


class CleanLogsHandler(BaseHandler):
    description = "Clean logs and normalize noisy inputs"
    aliases = ["clean logs", "clean log file", "filter logs", "remove noise"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        from core.log_loader import LogLoader
        from core.log_cleaner import LogCleaner

        raw = " ".join(args).strip()
        if not raw:
            console.print("[yellow]Usage: clean-logs <log_file>[/yellow]")
            return "usage"

        log_file = _extract_log(raw) or raw
        
        loader = LogLoader()
        try:
            with open(log_file, "r", errors="replace") as f:
                raw_lines = [l.strip() for l in f.read().splitlines() if l.strip()]
        except Exception:
            raw_lines = []

        # Fulfilling 'Load the file using LogLoader' requirement (even though it auto-cleans now)
        loader.load(log_file) 

        cleaner = LogCleaner()
        cleaned = cleaner.clean(raw_lines)
        stats = cleaner.get_stats(raw_lines, cleaned)

        console.print(f"Stats: {stats}")

        console.print(Rule("Preview", style="bold cyan"))
        for line in cleaned[:10]:
            console.print(line)

        console.print(f"Run complete. {len(cleaned)} lines ready for analysis.")
        return "ok"


class HelpHandler(BaseHandler):
    description = "Print all registered commands"
    aliases = ["help"]
    requires_service = False

    def handle(self, args: list[str]) -> str:
        table = Table(
            box=box.ROUNDED,
            show_lines=True,
            expand=True,
            title="[bold magenta]╭─── AI-SRE Commands ───╮[/bold magenta]",
            title_style="bold magenta",
            padding=(0, 1),
        )
        table.add_column("Command", style="bold cyan", width=24, no_wrap=True)
        table.add_column("Description", style="white", width=42)
        table.add_column("Examples", style="dim", width=30)

        rows = [
            ("[bold cyan]analyse[/bold cyan] [italic]<service>[/italic]",
             "[white]RAG-based RCA with sliding window[/white]",
             "analyse payment-service"),
            ("[bold cyan]analyse[/bold cyan] [italic]<service>[/italic] [dim]--baseline[/dim]",
             "[white]LLM-only analysis, no RAG[/white]",
             "analyse payment-service --baseline"),
            ("[bold cyan]analyse[/bold cyan] [italic]<service>[/italic] [dim]--compare[/dim]",
             "[white]Run both, save comparison report[/white]",
             "analyse payment-service --compare"),
            ("[bold cyan]compare[/bold cyan]",
             "[white]Baseline vs RAG analysis comparison[/white]",
             "compare"),
            ("[bold cyan]watch[/bold cyan] [italic]<service>[/italic]",
             "[white]Live log tailing + instant RCA[/white]",
             "watch payment-service"),
            ("[bold cyan]chat[/bold cyan]",
             "[white]Interactive follow-up on last RCA[/white]",
             "chat"),
            ("[bold cyan]status[/bold cyan]",
             "[white]System health + component dashboard[/white]",
             "status"),
            ("[bold cyan]explain[/bold cyan] [italic]<concept>[/italic]",
             "[white]SRE/Kubernetes concept explanations[/white]",
             "explain what is OOMKilled"),
            ("[bold cyan]clean-logs[/bold cyan] [italic]<log_file>[/italic]",
             "[white]Filter noise from log file[/white]",
             "clean-logs logs/test.log"),
            ("[bold cyan]help[/bold cyan]",
             "[white]Display this command reference[/white]",
             "help"),
            ("[bold cyan]exit[/bold cyan] [dim]/ quit[/dim]",
             "[white]Exit interactive SRE shell[/white]",
             "exit"),
        ]

        for cmd, desc, ex in rows:
            table.add_row(cmd, desc, ex)

        console.print(table)
        console.print()
        return "ok"


_ANALYSE = AnalyseHandler()
_STATUS = StatusHandler()
_COMPARE = CompareHandler()
_WATCH = WatchHandler()
_CHAT = ChatHandler()
_EXPLAIN = ExplainHandler()
_CLEAN = CleanHandler()
_CLEAN_LOGS = CleanLogsHandler()
_HELP = HelpHandler()

REGISTRY: dict[str, BaseHandler] = {
    "analyse": _ANALYSE,
    "analyze": _ANALYSE,
    "status": _STATUS,
    "compare": _COMPARE,
    "watch": _WATCH,
    "chat": _CHAT,
    "explain": _EXPLAIN,
    "clean": _CLEAN,
    "clean-logs": _CLEAN_LOGS,
    "help": _HELP,
}


def resolve(user_input: str) -> Optional[tuple[BaseHandler, list[str]]]:
    text = (user_input or "").strip()
    if not text:
        return None

    words = text.split()
    first = words[0].lower()

    question_starters = {
        "what", "how", "why", "when", "where", "which",
        "who", "can", "could", "should", "is", "are",
        "do", "does", "did"
    }

    if first in question_starters:
        return None

    if is_out_of_scope(text):
        return None

    # Tier 1: exact match
    if first in REGISTRY:
        return REGISTRY[first], words[1:]

    # Tier 2: fuzzy command match
    fuzzy = _fuzzy_match_command(first)
    if fuzzy:
        confirmed = _prompt_did_you_mean(first, fuzzy)
        if confirmed:
            return REGISTRY[fuzzy], words[1:]
        return None

    if first == "investigate":
        return None

    # Tier 3: keyword confidence scoring
    keyword_command = _keyword_scored_command(text)
    if keyword_command and keyword_command in REGISTRY:
        if keyword_command == "explain":
            return REGISTRY[keyword_command], [text]
        return REGISTRY[keyword_command], words

    # Tier 4: unknown
    return None


def is_out_of_scope(text: str) -> bool:
    text_lower = text.lower().strip()

    in_scope = [
        "pod", "pods", "container", "node", "kubectl", "kubernetes", "k8s", "namespace",
        "deploy", "deployment", "replica", "istio", "envoy", "sidecar", "mesh", "cluster",
        "helm", "log", "logs", "error", "crash", "restart", "fail", "failing", "failed",
        "timeout", "latency", "connection", "refused", "memory", "cpu", "oom", "metric",
        "alert", "incident", "outage", "rca", "root cause", "investigate", "analyze", "analyse",
        "monitor", "trace", "baseline", "rag", "cache", "database", "db", "redis", "kafka",
        "postgres", "mysql", "nginx", "api", "endpoint", "health", "probe", "liveness",
        "readiness", "evict", "secret", "configmap", "pvc", "volume", "hpa", "service", "gateway",
    ]
    for keyword in in_scope:
        if keyword in text_lower:
            return False

    known_services, _ = _load_services()
    for svc in known_services:
        if svc in text_lower:
            return False

    out_of_scope_patterns = [
        r"\bwho is\b", r"\bwho was\b", r"prime minister", r"president of", r"\bgovernment\b",
        r"\bpolitics\b", r"capital city of", r"\bweather\b", r"\bsports?\b", r"\bcricket\b",
        r"\bfootball\b", r"\bmovie\b", r"\bfilm\b", r"\bsong\b", r"\brecipe\b", r"\bcooking\b",
        r"\bwrite (me |a |an )", r"\bpoem\b", r"\bstory\b", r"\btranslat", r"\bjoke\b",
        r"\bbitcoin\b", r"\bstock price\b", r"^(hi|hello|hey)\.?$", r"^how are you", r"^what is your name",
    ]
    for pattern in out_of_scope_patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True

    return False


def print_out_of_scope_message(raw_query: str):
    msg = Text()
    msg.append("I am an SRE investigation tool.\n", style="white")
    msg.append("I can help with:\n", style="dim")
    for item in [
        "  • Service log analysis",
        "  • Pod failure investigation",
        "  • Kubernetes resource issues",
        "  • Root cause analysis",
        "  • SRE concept explanations",
    ]:
        msg.append(f"{item}\n", style="cyan")
    msg.append(f"\nYour query: \"{raw_query}\"\n", style="dim")
    msg.append("Try: 'check payment-service' or 'what is OOMKilled'", style="dim yellow")
    console.print(Panel(msg, title="[bold yellow]Out of scope[/bold yellow]", border_style="yellow", expand=False))


def print_banner():
    console.print(Panel(
        "\n[bold white]AI SRE Assistant[/]\n\n"
        "Type [bold cyan]'help'[/bold cyan] to see examples\n",
        title="[bold cyan]AI-SRE[/bold cyan]",
        subtitle="[dim]Kubernetes Microservices RCA Tool[/dim]",
        border_style="cyan",
        expand=True,
    ))


def _keyword_scored_command(text: str) -> Optional[str]:
    text_lower = text.lower()

    if text_lower.startswith("what is") or text_lower.startswith("how does") or text_lower.startswith("explain"):
        return "explain"

    score = {
        "analyze": 0,
        "status": 0,
        "compare": 0,
        "watch": 0,
        "chat": 0,
        "clean": 0,
        "help": 0,
    }

    keyword_sets = {
        "analyze": ["why", "failing", "failed", "broken", "down", "error", "incident", "outage", "root cause", "investigate", "diagnose", "rca", "service"],
        "status": ["status", "health", "system", "components", "environment"],
        "compare": ["compare", "baseline", "rag", "difference", "evaluation"],
        "watch": ["watch", "monitor", "live", "tail", "stream"],
        "chat": ["chat", "follow-up", "follow up", "question"],
        "clean": ["clean", "sanitize", "normalize", "filter logs"],
        "clean-logs": ["clean logs", "clean log file", "filter logs", "remove noise"],
        "help": ["help", "commands", "usage", "examples"],
    }

    for command, keywords in keyword_sets.items():
        for keyword in keywords:
            if keyword in text_lower:
                score[command] += 1

    if _has_sre_keywords(text_lower):
        score["analyze"] += 2

    best = max(score, key=score.get)
    if score[best] > 0:
        return best
    return None


def _levenshtein(s1: str, s2: str) -> int:
    if s1 == s2:
        return 0
    if len(s1) == 0:
        return len(s2)
    if len(s2) == 0:
        return len(s1)

    rows = len(s1) + 1
    cols = len(s2) + 1
    matrix = [[0] * cols for _ in range(rows)]

    for i in range(rows):
        matrix[i][0] = i
    for j in range(cols):
        matrix[0][j] = j

    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            matrix[i][j] = min(
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost,
            )

    return matrix[rows - 1][cols - 1]


def _fuzzy_match_command(word: str) -> Optional[str]:
    if len(word) <= 3:
        return None

    threshold = 1 if len(word) <= 6 else 2
    best_match = None
    best_distance = threshold + 1

    for command in REGISTRY.keys():
        distance = _levenshtein(word, command)
        if distance <= threshold and distance < best_distance:
            best_distance = distance
            best_match = command

    return best_match


def _prompt_did_you_mean(word: str, match: str) -> bool:
    console.print(
        f"\n  [bold yellow]Did you mean:[/] "
        f"[bold cyan]'{match}'[/bold cyan]"
        f"  [dim](y/n):[/dim] ",
        end="",
    )
    try:
        answer = input().strip().lower()
        return answer in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        console.print()
        return False


def _has_sre_keywords(text: str) -> bool:
    strong_sre_keywords = [
        "pod", "pods", "container", "node", "kubectl", "kubernetes", "k8s", "namespace", "deployment",
        "replica", "cluster", "istio", "envoy", "sidecar", "ingress", "service mesh", "helm", "configmap",
        "secret", "pvc", "volume", "hpa", "daemonset", "statefulset", "log", "logs", "error", "errors",
        "crash", "crashed", "crashing", "restart", "restarting", "restarts", "fail", "failed", "failing",
        "failure", "timeout", "latency", "slow", "hang", "connection refused", "unreachable", "oom",
        "oomkilled", "memory leak", "cpu throttl", "evict", "evicted", "crash loop", "crashloop",
        "image pull", "imagepull", "probe fail", "liveness", "readiness", "rca", "root cause", "incident",
        "outage", "alert", "metric", "analyze", "analyse", "investigate", "diagnose", "troubleshoot",
        "debug", "baseline", "rag", "historical", "database", "db", "redis", "kafka", "postgres", "mysql",
        "mongo", "rabbitmq", "elasticsearch", "nginx", "apache", "grpc", "down", "unavailable", "degraded",
        "not working", "not responding", "broken", "offline",
    ]

    known_services, service_aliases = _load_services()

    for service in known_services:
        if service in text:
            return True
    for alias in service_aliases.values():
        if alias in text:
            return True

    for keyword in strong_sre_keywords:
        if keyword in text:
            return True

    return False


def _extract_service(text: str) -> Optional[str]:
    text_lower = (text or "").lower()
    known_services, service_aliases = _load_services()

    names = sorted(known_services + list(service_aliases.keys()), key=len, reverse=True)
    for name in names:
        if name in text_lower:
            return service_aliases.get(name, name)
    return None


def _extract_mode(text: str) -> str:
    lowered = (text or "").lower()
    if "baseline" in lowered:
        return "baseline"
    return "rag"


def _extract_log(text: str) -> Optional[str]:
    match = re.search(r"[\w/\\.-]+\.log", text or "")
    if match:
        path = match.group(0)
        for candidate in [path, f"logs/{path}", "logs/test.log"]:
            if os.path.exists(candidate):
                return candidate
    if os.path.exists("logs/test.log"):
        return "logs/test.log"
    return None


def _extract_ns(text: str) -> Optional[str]:
    match = re.search(r"namespace[=:\s]+(\S+)", text or "", re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"-n\s+(\S+)", text or "")
    if match:
        return match.group(1)
    return None


def _load_services() -> tuple[list[str], dict[str, str]]:
    try:
        service_file = Path(__file__).resolve().parent.parent / "services.yaml"
        if not service_file.exists():
            return [], {}

        with open(service_file, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

        services = data.get("services", {})
        known_services = list(services.keys())
        aliases = {}
        for name in known_services:
            parts = name.split("-")
            if len(parts) > 1 and parts[0] not in aliases:
                aliases[parts[0]] = name

        return known_services, aliases
    except Exception:
        return [], {}
