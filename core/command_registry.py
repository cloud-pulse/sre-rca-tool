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
from flags import USE_KUBERNETES, K8S_NAMESPACE


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
    # meta.add_row("Windows used", str(result.get('windows_used', 1)))
    meta.add_row("Confidence", f"{result.get('confidence', 0)}%")
    meta.add_row("Warning", "[bold yellow]Low confidence — extended window used[/bold yellow]"
                 if low_conf else "[dim]None[/dim]")
    meta.add_row("Incident saved", "[bold green]Yes[/bold green]"
                 if record.get('saved') else "[dim]No[/dim]")
    # meta.add_row("Reason", str(record.get('reason', 'N/A')))
    meta.add_row("Similarity", f"{record.get('similarity_score', 0.0):.1%}")
    c.print(meta)

    from rich.markdown import Markdown
    analysis_text = result.get('analysis', 'No analysis returned.')
    
    import re
    clean_text = re.sub(r'\nCONFIDENCE:.*', '', analysis_text, flags=re.DOTALL).strip()
    
    c.print(Panel(
        Markdown(clean_text),
        title="[bold white]Root Cause Analysis[/bold white]",
        border_style="green",
        padding=(1, 2),
    ))
    c.print()

def _print_baseline_result(response, service, confidence=0):
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    import re

    c = Console()
    clean = re.sub(r'\nCONFIDENCE:.*', '', response, flags=re.DOTALL).strip()

    meta = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    meta.add_column("Key", style="bold cyan", width=14)
    meta.add_column("Value", style="white")
    meta.add_row("Service", service)
    meta.add_row("Source", "Live Kubernetes cluster (kubectl)")
    meta.add_row("Mode", "LLM-only — no vector retrieval")
    meta.add_row("Confidence", f"{confidence}%")
    c.print(meta)

    c.print(Panel(
        Markdown(clean),
        title="[bold white]Baseline Analysis — no RAG[/bold white]",
        border_style="blue",
        padding=(1, 2),
    ))

def _save_compare_report(service, kubectl_result, baseline_response, baseline_confidence=0) -> str:
    import datetime
    import os
    os.makedirs("reports", exist_ok=True)
    report_path = f"reports/compare_{service}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    record = kubectl_result.get('incident_record', {})
    sim = record.get('similarity_score', 0.0)
    kubectl_conf = kubectl_result.get('confidence', 0)
    delta = kubectl_conf - baseline_confidence
    better = "RAG" if delta >= 0 else "Baseline"

    content = f"""# Comparison Report
# Service: {service}
# Generated: {datetime.datetime.now().isoformat()}

## kubectl / RAG Mode
Confidence   : {kubectl_conf}%
Source       : Live Kubernetes cluster
Incident saved: {record.get('saved', False)}
Similarity   : {sim:.1%}

{kubectl_result.get('analysis', '')}

## Baseline Mode (no RAG, no history)
Confidence   : {baseline_confidence}%

{baseline_response}

## Summary
RAG confidence         : {kubectl_conf}%
Baseline confidence    : {baseline_confidence}%
Delta                  : {abs(delta)}% — {better} is more confident
Incident saved         : {record.get('saved', False)}
Historical similarity  : {sim:.1%}
"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)

    return report_path

def _save_last_rca(result: dict) -> None:
    """Persist the last RCA result so ChatHandler can load it."""
    try:
        with open(".last_rca.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
    except Exception as exc:
        console.print(f"[dim yellow]Warning: could not save .last_rca.json — {exc}[/dim yellow]")


class AnalyseHandler(BaseHandler):
    description = "Full SRE investigation (RCA, logs, metrics, K8s)"
    aliases = ["analyze", "analyse"]

    def handle(self, args: list[str]) -> str:

        # ── Parse args ────────────────────────────────────────────────────
        args_str = " ".join(args)
        parts = args_str.strip().split()
        baseline_mode = "--baseline" in parts
        compare_mode  = "--compare"  in parts
        service_parts = [p for p in parts if not p.startswith("--")]
        service = "-".join(service_parts) if service_parts else None

        if not service:
            console.print("[bold red]Usage: analyze <service-name>[/bold red]")
            return "no_service"

        # ── Branch: kubectl live mode ─────────────────────────────────────
        if USE_KUBERNETES:
            return self._handle_kubectl(service, baseline_mode=baseline_mode, compare_mode=compare_mode)

        # ── Branch: file mode (unchanged) ────────────────────────────────
        from core.log_loader import LogLoader
        loader = LogLoader()
        lines = loader.load_service_logs(service)

        if not lines:
            console.print(f"[bold red]No logs found for service: {service}[/bold red]")
            return "no_logs"

        if compare_mode:
            from core.window_analyzer import WindowAnalyzer
            from core.llm_provider import provider
            analyzer = WindowAnalyzer()
            rag_result = analyzer.analyse(lines, service=service)
            prompt = (
                f"You are an expert Site Reliability Engineer.\n"
                f"Service: {service}\n"
                f"Analyse the following logs and provide RCA.\n\n"
                f"--- LOGS START ---\n"
                f"{chr(10).join(lines[:500])}\n"
                f"--- LOGS END ---"
            )
            baseline_response = provider.generate(prompt)
            report_path = _save_compare_report(service, rag_result, baseline_response)
            console.print(f"\nComparison report saved to: {report_path}")
            _print_analysis_result(rag_result, mode="RAG")
            _save_last_rca(rag_result)
            return "ok"

        if baseline_mode:
            from core.llm_provider import provider
            prompt = (
                f"You are an expert Site Reliability Engineer.\n"
                f"Service: {service}\n"
                f"Analyse the following logs and provide RCA.\n\n"
                f"--- LOGS START ---\n"
                f"{chr(10).join(lines[:500])}\n"
                f"--- LOGS END ---"
            )
            raw_response = provider.generate(prompt)
            _print_baseline_result(raw_response, service)
            return "ok"

        from core.window_analyzer import WindowAnalyzer
        analyzer = WindowAnalyzer()
        result = analyzer.analyse(lines, service=service)
        _save_last_rca(result)
        _print_analysis_result(result, mode="RAG")
        return "ok"

    # ─────────────────────────────────────────────────────────────────────
    # kubectl live mode
    # ─────────────────────────────────────────────────────────────────────

    def _handle_kubectl(self, service: str, baseline_mode: bool = False, compare_mode: bool = False) -> str:
        from core.service_graph import ServiceGraph
        from core.kubectl_rca_investigator import (
            run_kubectl_rca, collect_all_evidence
        )
        from core.incident_recorder import IncidentRecorder
        from core.llm_provider import provider
        import re

        namespace = K8S_NAMESPACE or "default"
        sg = ServiceGraph()

        # ── Step 1: Resolve service name ─────────────────────────────────
        console.print(f"\n[dim]Resolving service '{service}'...[/dim]")
        resolved, found = self._resolve_service(service, sg, namespace)

        if not found:
            console.print(Panel(
                f"[bold red]Service '[white]{service}[/white]' not found.[/bold red]\n\n"
                f"[white]Not in [cyan]services.yaml[/cyan] or namespace "
                f"'[cyan]{namespace}[/cyan]'.[/white]\n\n"
                f"[dim]Run [bold]list-services[/bold] to see available services.[/dim]",
                title="[bold red]Service Not Found[/bold red]",
                border_style="red",
                padding=(1, 2),
            ))
            return "not_found"

        console.print(
            f"[dim]Running kubectl RCA for [bold]{resolved}[/bold] "
            f"in namespace [bold]{namespace}[/bold]...[/dim]\n"
        )

        # ── Step 2: Run evidence collection (always needed) ───────────────
        report = run_kubectl_rca(resolved, namespace, service_graph=sg)
        evidence_text = collect_all_evidence(report)

        # ── BASELINE MODE ─────────────────────────────────────────────────
        # Pure LLM call — same kubectl evidence, no RAG/incident history
        if baseline_mode:
            console.print("[dim]Running baseline analysis (no RAG)...[/dim]\n")
            baseline_prompt = self._build_kubectl_prompt(resolved, evidence_text, mode="baseline")
            baseline_narrative = provider.generate(baseline_prompt)

            conf_match = re.search(r"CONFIDENCE:\s*(\d+)%", baseline_narrative, re.IGNORECASE)
            baseline_confidence = int(conf_match.group(1)) if conf_match else 0

            # Save baseline report
            import datetime
            os.makedirs("logs/baseline", exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            baseline_path = f"logs/baseline/baseline_{resolved}_{ts}.json"
            try:
                with open(baseline_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "service": resolved,
                        "timestamp": datetime.datetime.now().isoformat(),
                        "analysis": baseline_narrative,
                        "confidence": baseline_confidence,
                        "mode": "baseline_kubectl",
                        "provider": "nvidia",
                    }, f, indent=2)
                console.print(f"[dim]Baseline saved → {baseline_path}[/dim]\n")
            except Exception as e:
                console.print(f"[dim yellow]Warning: could not save baseline file — {e}[/dim yellow]")

            self._print_kubectl_context(report, resolved, namespace)
            _print_baseline_result(baseline_narrative, resolved, baseline_confidence)
            return "ok"

        # ── COMPARE MODE ──────────────────────────────────────────────────
        # Run RAG analysis + baseline side-by-side
        if compare_mode:
            console.print("[dim]Running RAG analysis...[/dim]")
            kubectl_prompt = self._build_kubectl_prompt(resolved, evidence_text, mode="rag")
            kubectl_narrative = provider.generate(kubectl_prompt)

            conf_match = re.search(r"CONFIDENCE:\s*(\d+)%", kubectl_narrative, re.IGNORECASE)
            kubectl_confidence = int(conf_match.group(1)) if conf_match else 0

            console.print("[dim]Running baseline analysis (no RAG)...[/dim]")
            baseline_prompt = self._build_kubectl_prompt(resolved, evidence_text, mode="baseline")
            baseline_narrative = provider.generate(baseline_prompt)

            base_conf_match = re.search(r"CONFIDENCE:\s*(\d+)%", baseline_narrative, re.IGNORECASE)
            baseline_confidence = int(base_conf_match.group(1)) if base_conf_match else 0

            # Incident recording for the RAG result
            # Use confidence threshold only — keyword matching is too fragile
            # (LLM often says "healthy" even in a mixed narrative with real issues)
            record = {"saved": False, "reason": "kubectl_compare", "similarity_score": 0.0}
            if kubectl_confidence >= 50:
                recorder = IncidentRecorder()
                record = recorder.check_and_save(kubectl_narrative, resolved, evidence_text.splitlines())

            kubectl_result = {
                "service":                resolved,
                "windows_used":           "Live (kubectl)",
                "confidence":             kubectl_confidence,
                "analysis":               kubectl_narrative,
                "low_confidence_warning": kubectl_confidence < 70,
                "incident_record":        record,
            }

            # Save comparison report
            report_path = _save_compare_report(resolved, kubectl_result, baseline_narrative, baseline_confidence)

            # Save to .last_rca.json (use the RAG result as primary)
            _save_last_rca({**kubectl_result, "mode": "compare_kubectl"})

            # Display
            self._print_kubectl_context(report, resolved, namespace)
            _print_analysis_result(kubectl_result, mode="RAG")

            # Show baseline summary inline
            console.print(Rule("Baseline Analysis (no RAG)", style="bold blue"))
            _print_baseline_result(baseline_narrative, resolved, baseline_confidence)

            # Show comparison summary
            delta = kubectl_confidence - baseline_confidence
            better = " RAG" if delta >= 0 else "Baseline"
            console.print(Panel(
                f"[bold]RAG confidence:        [/bold]  {kubectl_confidence}%\n"
                f"[bold]Baseline confidence:   [/bold]  {baseline_confidence}%\n"
                f"[bold]Delta:                 [/bold]  {abs(delta)}% — [bold cyan]{better}[/bold cyan] is more confident\n"
                f"[bold]Incident saved:        [/bold]  {'Yes' if record.get('saved') else 'No'}\n"
                f"[bold]Similarity:            [/bold]  {record.get('similarity_score', 0.0):.1%}\n\n"
                f"[dim]Full report → {report_path}[/dim]",
                title="[bold magenta]Comparison Summary[/bold magenta]",
                border_style="magenta",
                padding=(1, 2),
            ))
            return "ok"

        # ── STANDARD KUBECTL RCA (no flags) ──────────────────────────────
        prompt = self._build_kubectl_prompt(resolved, evidence_text)
        console.print("[dim]Generating narrative RCA...[/dim]\n")
        narrative = provider.generate(prompt)

        conf_match = re.search(r"CONFIDENCE:\s*(\d+)%", narrative, re.IGNORECASE)
        confidence = int(conf_match.group(1)) if conf_match else 0

        # Use confidence threshold only for incident recording decision.
        # Keyword matching ("healthy", "no issue") is unreliable — the LLM often
        # includes those words even when describing a real failure scenario.
        # A confidence >= 50% means the LLM had enough evidence to form a view;
        # let IncidentRecorder decide via similarity whether it's truly new.
        record = {"saved": False, "reason": "kubectl_live", "similarity_score": 0.0}
        if confidence >= 50:
            evidence_lines = evidence_text.splitlines()
            recorder = IncidentRecorder()
            record = recorder.check_and_save(narrative, resolved, evidence_lines)

        result = {
            "service":                resolved,
            "windows_used":           "Live (kubectl)",
            "confidence":             confidence,
            "analysis":               narrative,
            "low_confidence_warning": confidence < 70,
            "incident_record":        record,
            "mode":                   "kubectl",
        }

        # FIX 1 — save so chat works
        _save_last_rca(result)

        self._print_kubectl_context(report, resolved, namespace)
        _print_analysis_result(result, mode="kubectl")
        return "ok"

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    def _resolve_service(self, service_name: str, sg, namespace: str) -> tuple[str, bool]:
        from core.kubectl_client import get_deployment_list

        if service_name in sg.services:
            return service_name, True

        fuzzy = [
            n for n in sg.services
            if service_name.lower() in n.lower() or n.lower() in service_name.lower()
        ]
        if fuzzy:
            console.print(f"[dim]Matched '{service_name}' → '{fuzzy[0]}' from services.yaml[/dim]")
            return fuzzy[0], True

        console.print(f"[dim]'{service_name}' not in services.yaml — scanning cluster...[/dim]")
        deployments = get_deployment_list(namespace)
        matches = [d for d in deployments if service_name.lower() in d.lower()]
        if matches:
            console.print(
                f"[dim]Found '[bold]{matches[0]}[/bold]' in cluster. "
                f"Adding to services.yaml...[/dim]"
            )
            if hasattr(sg, "add_discovered_service"):
                sg.add_discovered_service(matches[0], namespace)
            return matches[0], True

        # Not found anywhere
        return service_name, False

    def _build_kubectl_prompt(self, service: str, evidence_text: str, mode: str = "rag") -> str:
        """
        mode="rag"      — standard RCA (default, same as before)
        mode="baseline" — explicitly tells LLM NOT to use historical patterns,
                          pure analysis of what it sees in front of it
        """
        if mode == "baseline":
            extra = (
                "IMPORTANT: This is a BASELINE analysis. "
                "Do NOT reference any historical incidents or patterns. "
                "Analyse only the evidence provided below.\n\n"
            )
        else:
            extra = ""

        return f"""You are an expert Site Reliability Engineer performing root cause analysis.

{extra}Service: {service}
Source: Live Kubernetes cluster (kubectl)

--- KUBECTL EVIDENCE START ---
{evidence_text}
--- KUBECTL EVIDENCE END ---

Analyse this evidence and identify:
1. Root cause of any failures or anomalies
2. Sequence of events leading to failure
3. Affected services and impact
4. Recommended remediation steps

If everything appears healthy, clearly state there are no issues found
and provide any recommendations to improve reliability.

At the end of your analysis, you MUST include this block exactly:
CONFIDENCE: <number>%
REASON: <one sentence explaining your confidence level>

Confidence should reflect how complete the picture is:
- 80-100%: clear root cause, full evidence visible
- 60-79%: likely root cause but some gaps
- 40-59%: partial picture, more context needed
- below 40%: insufficient data or no issues found"""

    def _print_kubectl_context(self, report, service: str, namespace: str) -> None:
        ev = report.all_evidence
        ctx = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        ctx.add_column(style="bold cyan", width=18)
        ctx.add_column(style="white")

        ctx.add_row("Namespace", namespace)

        pod_line = ev.get("pod_status", "")
        pod_name = "N/A"
        if pod_line and "status=" in pod_line:
            pod_name = pod_line.strip().splitlines()[0].split(":")[0].strip()
        ctx.add_row("Analysed Pod", pod_name)

        if ev.get("pod_node"):
            ctx.add_row("Node", ev["pod_node"])

        endpoints = ev.get("service_endpoints", "")
        if "<none>" in endpoints or "notfound" in endpoints.lower():
            ctx.add_row("Endpoints", "[bold red]None — no ready pods[/bold red]")
        elif endpoints and "no endpoints" not in endpoints.lower():
            ctx.add_row("Endpoints", "[bold green]Healthy[/bold green]")

        if ev.get("virtual_service"):
            ctx.add_row("Istio", "[bold green]VirtualService present[/bold green]")

        if report.dependency_reports:
            dep_summary = []
            for dep in report.dependency_reports:
                dep_status = dep.all_evidence.get("pod_status", "")
                has_issue = any(
                    s in dep_status for s in [
                        "CrashLoop", "Error", "OOMKilled",
                        "Pending", "ImagePull", "no pods found"
                    ]
                )
                icon = "⚠" if has_issue else "✓"
                dep_summary.append(f"{icon} {dep.target_service}")
            ctx.add_row("Dependencies", "  ".join(dep_summary))

        # console.print(ctx)


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

        last_result = None
        try:
            with open(".last_rca.json") as f:
                last_result = json.load(f)
        except Exception:
            pass

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
        mode = last_result.get("mode", "kubectl")

        context = (
            "You are an SRE assistant helping with incident follow-up.\n"
            "You ONLY answer questions about the current incident described below.\n"
            "If asked anything unrelated to this incident or SRE topics, "
            "reply: 'I can only help with questions about this incident or SRE topics.'\n\n"
            f"Incident summary:\n"
            f"Service: {service}\n"
            f"Mode: {mode}\n"
            f"Confidence: {confidence}%\n"
            f"Analysis:\n{analysis[:1500]}\n\n"
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
            f"[dim]Chatting about: [bold]{service}[/bold] "
            f"(mode: {mode}, confidence: {confidence}%)[/dim]"
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
             "analyse paymentservice"),
            ("[bold cyan]analyse[/bold cyan] [italic]<service>[/italic] [dim]--baseline[/dim]",
             "[white]LLM-only kubectl analysis, no RAG[/white]",
             "analyse paymentservice --baseline"),
            ("[bold cyan]analyse[/bold cyan] [italic]<service>[/italic] [dim]--compare[/dim]",
             "[white]Run both, save comparison report[/white]",
             "analyse paymentservice --compare"),
            ("[bold cyan]chat[/bold cyan]",
             "[white]Interactive follow-up on last RCA[/white]",
             "chat"),
            ("[bold cyan]status[/bold cyan]",
             "[white]System health + component dashboard[/white]",
             "status"),
            ("[bold cyan]explain[/bold cyan] [italic]<concept>[/italic]",
             "[white]SRE/Kubernetes concept explanations[/white]",
             "explain what is OOMKilled"),
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
    msg.append("Try: 'analyse paymentservice' or 'explain OOMKilled'", style="dim yellow")
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