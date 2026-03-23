import sys
import os
import json
import time
import subprocess

sys.path.insert(
    0,
    os.path.dirname(os.path.abspath(__file__))
)

from rich.console import Console
from rich.rule import Rule
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

import yaml
import re
from pathlib import Path

class NLParser:
    def __init__(self):
        self._load_services()

    def _load_services(self):
        try:
            with open('services.yaml', 'r') as f:
                data = yaml.safe_load(f)
                services = data.get('services', {})
            
            self.known_services = list(services.keys())
            self.service_aliases = {}
            for svc in self.known_services:
                if '-' in svc:
                    alias = svc.split('-')[0]
                    self.service_aliases[alias] = svc
            
            # EXACT priority order from spec
            self.intent_patterns = [
                # COMPARE (check before analyze)
                (["compare", "baseline"], "compare"),
                (["compare", "rag"],      "compare"),
                (["compare"],             "compare"),
                (["vs", "baseline"],      "compare"),
                (["difference"],          "compare"),
                
                # WATCH
                (["watch"],    "watch"),
                (["monitor"],  "watch"),
                (["live"],     "watch"),
                (["real-time"],"watch"),
                (["tail"],     "watch"),
                
                # CHAT
                (["chat"],        "chat"),
                (["follow up"],   "chat"),
                (["follow-up"],   "chat"),
                (["interactive"], "chat"),
                
                # STATUS
                (["status"],          "status"),
                (["health"],          "status"),
                (["ready"],           "status"),
                (["check", "system"], "status"),
                
                # CACHE
                (["cache", "clear"], "cache_clear"),
                (["clear", "cache"], "cache_clear"),
                (["cache"],          "cache_stats"),
                
                # HELP
                (["help"],      "help"),
                (["commands"],  "help"),
                (["what can"],  "help"),
                
                # EXPLAIN (before analyze)
                (["what is"],            "explain"),
                (["what are"],           "explain"),
                (["how does"],           "explain"),
                (["how do"],             "explain"),
                (["explain"],            "explain"),
                (["tell me about"],      "explain"),
                (["is it"],              "explain"),
                (["is there"],           "explain"),
                (["does this"],          "explain"),
                (["is this"],            "explain"),
                (["implemented"],        "explain"),
                (["difference between"], "explain"),
                (["what does"],          "explain"),
                (["how is"],             "explain"),
                
                # ANALYZE (catch-all — MUST BE LAST)
                (["check"],       "analyze"),
                (["analyze"],     "analyze"),
                (["analyse"],     "analyze"),
                (["why"],         "analyze"),
                (["what", "happened"], "analyze"),
                (["failing"],     "analyze"),
                (["error"],       "analyze"),
                (["issue"],       "analyze"),
                (["problem"],     "analyze"),
                (["incident"],    "analyze"),
                (["rca"],         "analyze"),
                (["logs"],        "analyze"),
                (["diagnose"],    "analyze"),
                (["investigate"], "analyze"),
            ]
        except Exception:
            self.known_services = []
            self.service_aliases = {}
            self.intent_patterns = []

    def extract_service(self, text):
        candidates = list(self.service_aliases.values()) + self.known_services
        candidates = sorted(set(candidates), key=len, reverse=True)
        text_lower = text.lower()
        for cand in candidates:
            if cand.lower() in text_lower:
                return cand
        return None

    def extract_mode(self, text):
        return "baseline" if "baseline" in text.lower() else "rag"

    def extract_log_file(self, text):
        match = re.search(r'(\S+\.log)', text, re.I)
        if match:
            log_file = match.group(1)
            if os.path.exists(log_file):
                return log_file
            log_file = f'logs/{log_file}'
            if os.path.exists(log_file):
                return log_file
        default = 'logs/test.log'
        if os.path.exists(default):
            return default
        return None

    def extract_namespace(self, text):
        patterns = [
            r'namespace[=:]\s*(\S+)',
            r'-n\s+(\S+)'
        ]
        for pat in patterns:
            match = re.search(pat, text, re.I)
            if match:
                return match.group(1)
        return None

    def is_out_of_scope(self, text):
        text_lower = text.lower().strip()
        
        # Step 1: ANY hard_in_scope → False
        hard_in_scope = [
            'pod', 'pods', 'container', 'node', 'kubectl',
            'kubernetes', 'k8s', 'namespace', 'deploy',
            'deployment', 'replica', 'replicaset',
            'daemonset', 'statefulset', 'ingress',
            'configmap', 'secret', 'pvc', 'volume',
            'hpa', 'vpa', 'crd', 'rbac', 'istio', 'envoy',
            'sidecar', 'mesh', 'cluster', 'kubeconfig',
            'helm', 'log', 'logs', 'error', 'crash',
            'restart', 'fail', 'failing', 'failed',
            'timeout', 'latency', 'slowdown',
            'connection', 'refused', 'unreachable',
            'memory', 'cpu', 'oom', 'throttl', 'metric',
            'alert', 'incident', 'outage', 'rca',
            'root cause', 'investigate', 'analyze',
            'analyse', 'diagnose', 'monitor', 'watch',
            'trace', 'baseline', 'rag', 'cache',
            'database', 'db', 'redis', 'kafka', 'rabbitmq',
            'postgres', 'mysql', 'nginx', 'apache',
            'grpc', 'http', 'api', 'endpoint', 'health',
            'probe', 'liveness', 'readiness', 'evict'
        ]
        if any(word in text_lower for word in hard_in_scope):
            return False

        # Step 2: known services/aliases → False
        all_services = set(self.service_aliases.values()) | set(self.known_services)
        if any(svc.lower() in text_lower for svc in all_services):
            return False

        # Step 3: hard_out_of_scope regex
        out_patterns = [
            r"\bwho is\b", r"\bwho was\b",
            r"prime minister", r"president of",
            r"\bgovernment\b", r"\bpolitics\b",
            r"capital (city )?of", r"\bweather\b",
            r"\bsports?\b", r"\bcricket\b",
            r"\bfootball\b", r"\bmovie\b", r"\bfilm\b",
            r"\bsong\b", r"\bmusic\b", r"\brecipe\b",
            r"\bcooking\b", r"\bwrite (me |a |an )",
            r"\bpoem\b", r"\bstory\b", r"\btranslat",
            r"\bjoke\b", r"\bstock price\b", r"\bbitcoin\b",
            r"^(hi|hello|hey)\.?$", r"^how are you",
            r"^what is your name"
        ]
        if any(re.search(pat, text_lower) for pat in out_patterns):
            return True

        # Step 4: default False (allow)
        return False

    def parse(self, text):
        text_lower = text.lower().strip()
        intent = "analyze"  # default
        for keywords, mapped in self.intent_patterns:
            if all(kw in text_lower for kw in keywords):
                intent = mapped
                break
        return {
            "intent": intent,
            "service": self.extract_service(text),
            "mode": self.extract_mode(text),
            "log_file": self.extract_log_file(text),
            "namespace": self.extract_namespace(text),
            "raw": text
        }

class SREShell:
    def __init__(self):
        self.parser = NLParser()
        self.discovery = None

    def _get_discovery(self):
        if not self.discovery:
            from core.service_discovery import ServiceDiscovery
            self.discovery = ServiceDiscovery()
        return self.discovery

    def _resolve_service(self, service: str, namespace: str = None) -> tuple[str, str]:
        from core.service_graph import ServiceGraph
        graph = ServiceGraph()
        canonical = graph.get_service_name(service)

        if canonical:
            ns = namespace or graph.get_namespace(canonical)
            return canonical, ns

        # Not in services.yaml — use ServiceDiscovery
        discovery = self._get_discovery()
        chosen_ns = discovery.prompt_for_namespace(service)

        if chosen_ns is None:
            return service, namespace or "default"

        # Ask to save
        save = discovery.prompt_save_to_yaml(service, chosen_ns)
        if save:
            graph.apply_discoveries(
                [{
                    "target": service,
                    "source": service, 
                    "confidence": "high",
                    "evidence": "user-confirmed namespace",
                    "already_in_graph": False
                }],
                service
            )
            console.print(
                f"[bold green]Saved {service} → {chosen_ns} to services.yaml[/bold green]"
            )

        return service, chosen_ns

    def _print_banner(self):
        console.print(Panel(
            "\n[bold white]AI SRE Assistant[/]\n\n"
            "Type [bold cyan]'help'[/bold cyan] to see examples\n",
            title="[bold cyan]AI-SRE[/bold cyan]",
            subtitle="[dim]Kubernetes Microservices RCA Tool[/dim]",
            border_style="cyan",
            expand=True
        ))

    def _print_help(self):
        console.print(Rule("AI-SRE Commands", style="bold cyan"))
        table = Table(box=box.ROUNDED, show_lines=True, expand=True)
        table.add_column("Command", style="bold cyan", width=30)
        table.add_column("What it does", style="white")
        table.add_column("Example", style="dim")
        rows = [
            ("analyze <service>", "Full SRE investigation", "analyze payment-service"),
            ("check <service>", "Same as analyze", "check database"),
            ("why is <service> failing", "Investigate failures", "why is payment failing"),
            ("compare", "Baseline vs RAG side-by-side", "compare"),
            ("watch <service>", "Live log monitoring", "watch payment-service"),
            ("chat", "Follow-up Q&A on last RCA", "chat"),
            ("status", "System health check", "status"),
            ("cache", "Show LLM cache stats", "cache"),
            ("cache clear", "Clear cached responses", "cache clear"),
            ("what is <concept>", "Explain SRE concepts", "what is istio"),
            ("how does <x> work", "Explain how something works", "how does RAG work"),
            ("help", "Show this help", "help"),
            ("exit / quit", "Exit the shell", "exit"),
        ]
        for cmd, desc, ex in rows:
            table.add_row(cmd, desc, ex)
        console.print(table)
        console.print()

    def execute(self, command: dict):
        # STEP 1: Guardrail — MUST BE FIRST
        if self.parser.is_out_of_scope(command["raw"]):
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
            msg.append(f"\nYour query: \"{command['raw']}\"\n", style="dim")
            msg.append("Try: 'check payment-service' or 'what is OOMKilled'", style="dim yellow")
            console.print(Panel(msg, title="[bold yellow]Out of scope[/bold yellow]", border_style="yellow", expand=False))
            return

        # STEP 2: Show understood
        intent = command["intent"]
        svc = command["service"]
        console.print(f"\n[dim]→ {intent}" + (f" | {svc}" if svc else "") + "[/dim]\n")

        # STEP 3: Route
        if intent == "analyze":
            self._cmd_analyze(command)
        elif intent == "compare":  
            self._cmd_compare(command)
        elif intent == "watch":
            self._cmd_watch(command)
        elif intent == "chat":
            self._cmd_chat()
        elif intent == "status":
            self._cmd_status()
        elif intent == "cache_clear":
            self._cmd_cache_clear()
        elif intent == "cache_stats":
            self._cmd_cache_stats()
        elif intent == "explain":
            self._cmd_explain(command["raw"])
        elif intent == "help":
            self._print_help()
        else:
            console.print("[yellow]Unknown command. Type 'help' for options.[/yellow]")

    def _cmd_status(self):
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

        # Python
        v = sys.version_info
        table.add_row("Python", "[bold green]OK[/bold green]", f"{v.major}.{v.minor}.{v.micro}")

        # Venv
        venv = os.environ.get("VIRTUAL_ENV", "")
        venv_name = os.path.basename(venv) if venv else "none"
        table.add_row("Virtual env", "[bold green]active[/bold green]" if venv else "[bold yellow]not active[/bold yellow]", venv_name)

        # Ollama
        analyzer = LLMAnalyzer()
        ollama_ok = analyzer.check_ollama_connection()
        table.add_row("Ollama", "[bold green]OK[/bold green]" if ollama_ok else "[bold red]NOT RUNNING[/bold red]", "phi3:mini" if ollama_ok else "run: ollama serve")

        # ChromaDB / RAG  
        try:
            rag = RAGEngine("logs/historical")
            stats = rag.get_collection_stats()
            chunks = stats["total_chunks"]
            files = len(stats["files_indexed"])
            table.add_row("ChromaDB", "[bold green]OK[/bold green]", f"{chunks} chunks, {files} files")
        except Exception as e:
            table.add_row("ChromaDB", "[bold red]ERROR[/bold red]", str(e)[:40])

        # Services
        try:
            graph = ServiceGraph()
            svcs = graph.get_all_service_names()
            table.add_row("services.yaml", "[bold green]OK[/bold green]", f"{len(svcs)} services defined")
        except Exception:
            table.add_row("services.yaml", "[bold red]MISSING[/bold red]", "")

        # Cache
        try:
            cache = LLMCache()
            cs = cache.stats()
            table.add_row("LLM Cache", "[bold green]enabled[/bold green]" if LLM_CACHE_ENABLED else "[dim]disabled[/dim]", f"{cs['total_entries']} entries, {cs['total_size_kb']} KB")
        except Exception:
            table.add_row("LLM Cache", "[dim]unavailable[/dim]", "")

        # Source mode
        table.add_row("Source mode", "[bold green]kubernetes[/bold green]" if USE_KUBERNETES else "[bold yellow]file[/bold yellow]", f"namespace: {K8S_NAMESPACE}" if USE_KUBERNETES else "logs/test.log")

        # Feature flags
        table.add_row("RAG", "[bold green]enabled[/bold green]" if RAG_ENABLED else "[dim]disabled[/dim]", "")
        table.add_row("Debug mode", "[bold yellow]ON[/bold yellow]" if DEBUG else "[dim]off[/dim]", "SYSTEM_DEBUG=true in .env" if DEBUG else "")

        # Last RCA
        try:
            with open(".last_rca.json") as f:
                last = json.load(f)
            table.add_row("Last RCA", "[bold green]available[/bold green]", f"mode: {last.get('mode','?')}, confidence: {last.get('confidence',0)}%")
        except Exception:
            table.add_row("Last RCA", "[dim]none yet[/dim]", "run: analyze <service>")

        console.print(table)
        console.print()

    def _cmd_analyze(self, command: dict):
        service = command["service"]
        mode = command["mode"]
        log_file = command["log_file"] 
        namespace = command["namespace"]

        if service:
            canonical, ns = self._resolve_service(service, namespace)
            self._run_investigation(canonical, ns, mode)
        else:
            from main import run_pipeline
            from output.rca_formatter import RCAFormatter
            formatter = RCAFormatter()
            result = run_pipeline(log_path=log_file or "logs/test.log", mode=mode, verbose=False)
            resources = result.get("resources", {})
            formatter.print_full_result(result, resources)

    def _run_investigation(self, service: str, namespace: str, mode: str):
        from core.service_graph import ServiceGraph
        from core.sre_investigator import SREInvestigator
        from core.llm_analyzer import LLMAnalyzer
        from core.resource_collector import ResourceCollector
        from output.rca_formatter import RCAFormatter
        from flags import USE_KUBERNETES

        graph = ServiceGraph()
        investigator = SREInvestigator()
        analyzer = LLMAnalyzer()
        collector = ResourceCollector()
        formatter = RCAFormatter()

        console.print(Rule(f"Investigating: {service}", style="bold cyan"))
        console.print(f"  [dim]Namespace: {namespace}[/dim]\n")

        if not analyzer.check_ollama_connection():
            console.print("[bold red]Ollama not running.\nStart: ollama serve[/bold red]")
            return

        analyzer.warmup()

        use_mock = not USE_KUBERNETES

        with formatter.spinner(f"Collecting evidence for {service}..."):
            report = investigator.investigate(service, namespace=namespace, use_mock=use_mock)

        all_svcs = list(report.evidence.keys())
        resources = collector.get_resources(all_svcs, namespace=namespace, use_mock=use_mock)

        with formatter.spinner("Running deep SRE analysis..."):
            result = analyzer.analyze_investigation(report, investigator, query=service)

        formatter.print_full_investigation(result, resources)

    def _cmd_compare(self, command: dict):
        from main import run_pipeline
        from evaluation.comparator import Comparator

        log_file = command["log_file"] or "logs/test.log"
        namespace = command["namespace"]

        console.print(Rule("Baseline vs RAG Comparison", style="bold magenta"))

        console.print("[dim]Running baseline analysis...[/dim]")
        baseline = run_pipeline(log_path=log_file, mode="baseline", namespace=namespace, query=log_file)

        console.print("[dim]Running RAG analysis...[/dim]")
        rag = run_pipeline(log_path=log_file, mode="rag", namespace=namespace, query=log_file)

        Comparator().compare(baseline, rag, rag.get("retrieved_incidents", []))

    def _cmd_watch(self, command: dict):
        from core.log_processor import LogProcessor
        from main import run_pipeline
        from output.rca_formatter import RCAFormatter

        log_file = command["log_file"] or "logs/test.log"
        service = command["service"]
        namespace = command["namespace"]

        if service and not namespace:
            _, namespace = self._resolve_service(service)

        console.print(Rule(f"Live Monitor: {log_file}", style="bold cyan"))
        console.print("[dim]Watching for new errors... Ctrl+C to stop[/dim]\n")

        processor = LogProcessor()
        formatter = RCAFormatter()
        seen = 0

        try:
            with open(log_file, "r", errors="replace") as f:
                seen = len(f.readlines())

            while True:
                time.sleep(2)
                with open(log_file, "r", errors="replace") as f:
                    lines = f.readlines()

                new_lines = [l.rstrip() for l in lines[seen:] if l.strip()]
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

    def _cmd_chat(self):
        from core.llm_analyzer import LLMAnalyzer

        console.print(Rule("Interactive Chat", style="bold cyan"))

        # Load last RCA
        last_result = None
        try:
            with open(".last_rca.json") as f:
                last_result = json.load(f)
        except Exception:
            pass

        if not last_result:
            console.print("[yellow]No previous RCA found.\nRun 'analyze <service>' first, then use 'chat'.[/yellow]")
            return

        analyzer = LLMAnalyzer()
        if not analyzer.check_ollama_connection():
            console.print("[bold red]Ollama not running: ollama serve[/bold red]")
            return

        context = (
            f"You are an SRE assistant.\n"
            f"Previous RCA:\n"
            f"Root cause: {last_result.get('root_cause')}\n"
            f"Services: {last_result.get('affected_services')}\n"
            f"Confidence: {last_result.get('confidence')}%\n"
            f"Answer follow-up questions about this incident concisely."
        )

        history = []
        console.print("[dim]Type 'exit' to leave chat[/dim]\n")

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

            history.append({"role": "user", "content": user_input})

            hist_text = "\n".join(
                f"{'User' if m['role']=='user' else 'Assistant'}: {m['content']}"
                for m in history[-6:]
            )

            prompt = f"{context}\n\nConversation:\n{hist_text}\n\nAnswer concisely:"

            with console.status("[dim]Thinking...[/dim]", spinner="dots"):
                response = analyzer._call_ollama(prompt)

            if response:
                console.print(f"[bold cyan]SRE-AI:[/] {response.strip()}\n")
                history.append({"role": "assistant", "content": response.strip()})

        console.print("[dim]Chat ended.[/dim]\n")

    def _cmd_cache_clear(self):
        from core.llm_cache import LLMCache
        count = LLMCache().clear(0)
        console.print(f"[bold green]Cache cleared: {count} entries removed.[/bold green]")

    def _cmd_cache_stats(self):
        from core.llm_cache import LLMCache
        from rich.table import Table
        from rich import box as rbox

        stats = LLMCache().stats()
        table = Table(title="LLM Cache", box=rbox.ROUNDED)
        table.add_column("Property", style="bold white")
        table.add_column("Value", style="cyan")
        table.add_row("Enabled", "[green]yes[/]" if stats["enabled"] else "[red]no[/]")
        table.add_row("Entries", str(stats["total_entries"]))
        table.add_row("Size", f"{stats['total_size_kb']} KB")
        table.add_row("TTL", f"{stats['ttl_seconds']}s")
        console.print(table)

    def _cmd_explain(self, question: str):
        from core.llm_analyzer import LLMAnalyzer
        from core.service_graph import ServiceGraph

        console.print(Rule("Explain", style="bold cyan"))

        analyzer = LLMAnalyzer()
        project_context = ""
        try:
            graph = ServiceGraph()
            services = graph.get_all_service_names()
            containers = {s: graph.get_containers(s) for s in services}
            project_context = f"\nProject context:\nServices: {services}\nContainers per service (includes sidecars): {containers}\n"
        except Exception:
            pass

        prompt = (
            f"You are an expert SRE engineer.\n"
            f"Answer in 3-5 sentences max.\n"
            f"Be specific and practical.\n"
            f"If asked whether something is implemented in this project, use the project context to answer."
            f"{project_context}\n"
            f"Question: {question}\n\n"
            f"Do NOT output RCA format.\n"
            f"Just answer directly."
        )

        if not analyzer.check_ollama_connection():
            console.print("[bold red]Ollama not running: ollama serve[/bold red]")
            return

        with console.status("[bold cyan]Thinking...[/bold cyan]", spinner="dots"):
            response = analyzer._call_ollama(prompt)

        if response and response.strip():
            console.print(Panel(response.strip(), title="[bold cyan]Answer[/]", border_style="cyan", expand=False))
        else:
            console.print("[yellow]No response from LLM. Is Ollama running?[/yellow]")

def main():
    shell = SREShell()

    if len(sys.argv) > 1:
        # Single command mode
        text = " ".join(sys.argv[1:])
        command = shell.parser.parse(text)
        shell.execute(command)
        return

    # Interactive shell mode
    shell._print_banner()

    while True:
        try:
            console.print("[bold cyan]ai-sre>[/bold cyan] ", end="")
            user_input = input().strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "bye", "q"):
            console.print("[dim]Goodbye.[/dim]")
            break

        command = shell.parser.parse(user_input)
        shell.execute(command)

if __name__ == "__main__":
    main()

