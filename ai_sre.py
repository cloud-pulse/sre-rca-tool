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

    # Tier 1 hard command words.
    # If input starts with any of these
    # (case insensitive) → that is the intent.
    # Everything after = parameter.
    HARD_COMMANDS = {
        "explain":     "explain",
        "watch":       "watch",
        "monitor":     "watch",
        "status":      "status",
        "health":      "status",
        "help":        "help",
        "compare":     "compare",
        "cache":       "cache_stats",
        "chat":        "chat",
        "exit":        "exit",
        "quit":        "exit",
        "bye":         "exit",
        "q":           "exit",
        "analyze":     "analyze",
        "analyse":     "analyze",
        "check":       "analyze",
        "investigate": "analyze",
        "diagnose":    "analyze",
    }

    # Special sub-commands for cache.
    # If first word is "cache" and second
    # word is one of these → override intent.
    CACHE_SUBCOMMANDS = {
        "clear": "cache_clear",
        "clean": "cache_clear",
        "reset": "cache_clear",
        "stats": "cache_stats",
        "show":  "cache_stats",
    }

    def __init__(self):
        self._load_services()

    def _load_services(self):
        # Load known_services and
        # service_aliases from services.yaml.
        # No hardcoded service names.
        try:
            import yaml
            from pathlib import Path
            f = (
                Path(__file__).parent
                / "services.yaml"
            )
            if f.exists():
                with open(f) as fh:
                    data = (
                        yaml.safe_load(fh) or {}
                    )
                svcs = data.get("services", {})
                self.known_services = list(
                    svcs.keys()
                )
                self.service_aliases = {}
                for name in self.known_services:
                    parts = name.split("-")
                    if len(parts) > 1:
                        alias = parts[0]
                        if alias not in (
                            self.service_aliases
                        ):
                            self.service_aliases[
                                alias
                            ] = name
            else:
                self.known_services = []
                self.service_aliases = {}
        except Exception:
            self.known_services = []
            self.service_aliases = {}

    def parse(self, text: str) -> dict:
        text = text.strip()
        if not text:
            return self._make_result(
                "unknown", text
            )

        text_lower = text.lower()
        words = text_lower.split()
        first_word = words[0] if words else ""

        # ── Tier 1: Exact hard command ─────────
        if first_word in self.HARD_COMMANDS:
            intent = self.HARD_COMMANDS[first_word]
            parameter = text[
                len(first_word):
            ].strip()

            # Cache sub-command check
            if intent in (
                "cache_stats", "cache_clear"
            ):
                second = (
                    words[1]
                    if len(words) > 1
                    else ""
                )
                if second in self.CACHE_SUBCOMMANDS:
                    intent = (
                        self.CACHE_SUBCOMMANDS[
                            second
                        ]
                    )

            return self._make_result(
                intent, text, parameter
            )

        # ── Tier 2: Fuzzy match on first word ──
        fuzzy = self._fuzzy_match_command(
            first_word
        )
        if fuzzy:
            confirmed = self._prompt_did_you_mean(
                first_word, fuzzy
            )
            if confirmed:
                intent = self.HARD_COMMANDS[fuzzy]
                parameter = text[
                    len(first_word):
                ].strip()
                # Re-check cache sub-command
                if intent in (
                    "cache_stats", "cache_clear"
                ):
                    second = (
                        words[1]
                        if len(words) > 1
                        else ""
                    )
                    if second in (
                        self.CACHE_SUBCOMMANDS
                    ):
                        intent = (
                            self.CACHE_SUBCOMMANDS[
                                second
                            ]
                        )
                return self._make_result(
                    intent, text, parameter
                )
            else:
                # User said no → unknown
                return self._make_result(
                    "unknown", text
                )

        # ── Tier 3: NLP with SRE keyword check ─
        if self._has_sre_keywords(text_lower):
            # Has real SRE context → analyze
            return self._make_result(
                "analyze", text, text
            )

        # ── Tier 4: Nothing matched ─────────────
        # Do NOT run any pipeline.
        # Return unknown intent.
        return self._make_result(
            "unknown", text
        )

    def _nlp_intent(self,
                    text_lower: str) -> str:
        # Fallback NLP for sentences that
        # don't start with a command word.
        # Used for natural language like:
        #   "why is payment failing"
        #   "what happened to database"
        #   "payment-service is down"
        #
        # Check out-of-scope first
        if self.is_out_of_scope(text_lower):
            return "out_of_scope"

        # SRE analyze triggers
        analyze_keywords = [
            "why", "failing", "failed",
            "broken", "down", "crash",
            "error", "issue", "problem",
            "incident", "outage", "rca",
            "root cause", "not working",
            "what happened", "what is wrong",
            "whats wrong", "investigate",
        ]
        for kw in analyze_keywords:
            if kw in text_lower:
                return "analyze"

        # If a known service name is mentioned
        # treat it as analyze
        for svc in self.known_services:
            if svc in text_lower:
                return "analyze"
        for alias in self.service_aliases:
            if alias in text_lower:
                return "analyze"

        # Default fallback
        return "analyze"

    def _extract_service(self,
                          text: str
                          ) -> str | None:
        text_lower = text.lower()
        # Sort longest first to avoid
        # "pay" matching before "payment-service"
        all_names = sorted(
            list(self.known_services) +
            list(self.service_aliases.keys()),
            key=len,
            reverse=True
        )
        for name in all_names:
            if name in text_lower:
                return self.service_aliases.get(
                    name, name
                )
        return None

    def _extract_mode(self,
                       text: str) -> str:
        if "baseline" in text:
            return "baseline"
        return "rag"

    def _extract_log(self,
                      text: str
                      ) -> str | None:
        import re
        import os
        m = re.search(
            r'[\w/\\.-]+\.log', text
        )
        if m:
            path = m.group(0)
            for candidate in [
                path,
                f"logs/{path}",
                "logs/test.log"
            ]:
                if os.path.exists(candidate):
                    return candidate
        if os.path.exists("logs/test.log"):
            return "logs/test.log"
        return None

    def _extract_ns(self,
                     text: str
                     ) -> str | None:
        import re
        m = re.search(
            r'namespace[=:\s]+(\S+)',
            text, re.IGNORECASE
        )
        if m:
            return m.group(1)
        m = re.search(r'-n\s+(\S+)', text)
        if m:
            return m.group(1)
        return None

    def is_out_of_scope(self,
                         text: str) -> bool:
        import re
        text_lower = text.lower().strip()

        # Always in scope if SRE keywords
        in_scope = [
            "pod", "pods", "container",
            "node", "kubectl", "kubernetes",
            "k8s", "namespace", "deploy",
            "deployment", "replica", "istio",
            "envoy", "sidecar", "mesh",
            "cluster", "helm", "log", "logs",
            "error", "crash", "restart",
            "fail", "failing", "failed",
            "timeout", "latency", "connection",
            "refused", "memory", "cpu", "oom",
            "metric", "alert", "incident",
            "outage", "rca", "root cause",
            "investigate", "analyze", "analyse",
            "monitor", "trace", "baseline",
            "rag", "cache", "database", "db",
            "redis", "kafka", "postgres",
            "mysql", "nginx", "api", "endpoint",
            "health", "probe", "liveness",
            "readiness", "evict", "secret",
            "configmap", "pvc", "volume",
            "hpa", "service", "gateway",
        ]
        for kw in in_scope:
            if kw in text_lower:
                return False

        for svc in self.known_services:
            if svc in text_lower:
                return False

        out_of_scope = [
            r"\bwho is\b",
            r"\bwho was\b",
            r"prime minister",
            r"president of",
            r"\bgovernment\b",
            r"\bpolitics\b",
            r"capital city of",
            r"\bweather\b",
            r"\bsports?\b",
            r"\bcricket\b",
            r"\bfootball\b",
            r"\bmovie\b",
            r"\bfilm\b",
            r"\bsong\b",
            r"\brecipe\b",
            r"\bcooking\b",
            r"\bwrite (me |a |an )",
            r"\bpoem\b",
            r"\bstory\b",
            r"\btranslat",
            r"\bjoke\b",
            r"\bbitcoin\b",
            r"\bstock price\b",
            r"^(hi|hello|hey)\.?$",
            r"^how are you",
            r"^what is your name",
        ]
        for pattern in out_of_scope:
            if re.search(
                pattern, text_lower,
                re.IGNORECASE
            ):
                return True

        return False

    def _levenshtein(self,
                  s1: str,
                  s2: str) -> int:
        # Standard dynamic programming
        # implementation.
        # Returns minimum edit distance
        # between s1 and s2.
        # Insertions, deletions, substitutions
        # each cost 1.
        if s1 == s2:
            return 0
        if len(s1) == 0:
            return len(s2)
        if len(s2) == 0:
            return len(s1)

        rows = len(s1) + 1
        cols = len(s2) + 1
        matrix = [
            [0] * cols for _ in range(rows)
        ]

        for i in range(rows):
            matrix[i][0] = i
        for j in range(cols):
            matrix[0][j] = j

        for i in range(1, rows):
            for j in range(1, cols):
                cost = (
                    0
                    if s1[i-1] == s2[j-1]
                    else 1
                )
                matrix[i][j] = min(
                    matrix[i-1][j] + 1,
                    matrix[i][j-1] + 1,
                    matrix[i-1][j-1] + cost
                )

        return matrix[rows-1][cols-1]

    def _fuzzy_match_command(self,
                          word: str
                          ) -> str | None:
        # Check if word is a typo of any known
        # command in HARD_COMMANDS keys.
        #
        # Threshold rules:
        #   word length 1-3:  no fuzzy match
        #     (too short, too many false positives)
        #   word length 4-6:  distance <= 1
        #   word length 7+:   distance <= 2
        #
        # Return the closest matching command
        # key (not the intent, the command word)
        # or None if no match within threshold.
        #
        # Example:
        #   "explan"    → "explain"   (dist 1)
        #   "investgate"→ "investigate" (dist 2)
        #   "chck"      → "check"     (dist 1)
        #   "hlp"       → None (too short)
        #   "xyz"       → None (no match)

        if len(word) <= 3:
            return None

        threshold = 1 if len(word) <= 6 else 2

        best_match = None
        best_dist = threshold + 1

        for cmd in self.HARD_COMMANDS.keys():
            dist = self._levenshtein(word, cmd)
            if dist <= threshold and (
                dist < best_dist
            ):
                best_dist = dist
                best_match = cmd

        return best_match

    def _has_sre_keywords(self,
                       text: str) -> bool:
        # Return True if text contains at least
        # ONE strong SRE keyword.
        # These are specific enough that their
        # presence means the user is asking
        # about infrastructure/operations.
        #
        # Do NOT include generic words like
        # "is", "the", "what" etc.

        strong_sre_keywords = [
            # Infrastructure
            "pod", "pods", "container", "node",
            "kubectl", "kubernetes", "k8s",
            "namespace", "deployment", "replica",
            "cluster", "istio", "envoy", "sidecar",
            "ingress", "service mesh", "helm",
            "configmap", "secret", "pvc", "volume",
            "hpa", "daemonset", "statefulset",
            # SRE operations
            "log", "logs", "error", "errors",
            "crash", "crashed", "crashing",
            "restart", "restarting", "restarts",
            "fail", "failed", "failing", "failure",
            "timeout", "latency", "slow", "hang",
            "connection refused", "unreachable",
            "oom", "oomkilled", "memory leak",
            "cpu throttl", "evict", "evicted",
            "crash loop", "crashloop",
            "image pull", "imagepull",
            "probe fail", "liveness", "readiness",
            # Analysis terms
            "rca", "root cause", "incident",
            "outage", "alert", "metric",
            "analyze", "analyse", "investigate",
            "diagnose", "troubleshoot", "debug",
            "baseline", "rag", "historical",
            # Databases and services
            "database", "db", "redis", "kafka",
            "postgres", "mysql", "mongo",
            "rabbitmq", "elasticsearch",
            "nginx", "apache", "grpc",
            # Status words with SRE context
            "down", "unavailable", "degraded",
            "not working", "not responding",
            "broken", "offline",
        ]

        text_lower = text.lower()

        # Also treat any known service name
        # as a strong SRE keyword
        for svc in self.known_services:
            if svc in text_lower:
                return True
        for alias in self.service_aliases.values():
            if alias in text_lower:
                return True

        for kw in strong_sre_keywords:
            if kw in text_lower:
                return True

        return False

    def _prompt_did_you_mean(self,
                          word: str,
                          match: str) -> bool:
        # Ask user if they meant a command.
        # Return True if user confirms.
        # Return False if user declines.
        #
        # Display:
        #   Did you mean: 'explain'? (y/n):
        #
        # Accept: y, yes → True
        # Accept: n, no, empty, anything else → False
        # Handle Ctrl+C → False

        from rich.console import Console
        c = Console()
        c.print(
            f"\n  [bold yellow]Did you mean:[/] "
            f"[bold cyan]'{match}'[/bold cyan]"
            f"  [dim](y/n):[/dim] ",
            end=""
        )
        try:
            answer = input().strip().lower()
            return answer in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            c.print()
            return False

    def _make_result(self,
                  intent: str,
                  text: str,
                  parameter: str = ""
                  ) -> dict:
        # Build the standard result dict
        return {
            "intent":    intent,
            "service":   self._extract_service(
                             parameter or text
                         ),
            "mode":      self._extract_mode(
                             text.lower()
                         ),
            "log_file":  self._extract_log(
                             parameter or text
                         ),
            "namespace": self._extract_ns(
                             parameter or text
                         ),
            "parameter": parameter,
            "raw":       text,
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
            # padding=(1, 2)
        ))

    def _print_help(self):
        # console.print(Rule("AI-SRE Commands", style="bold cyan"))
        table = Table(
            box=box.ROUNDED, 
            show_lines=True, 
            expand=True,
            title="[bold magenta]╭─── AI-SRE Commands ───╮[/bold magenta]",
            title_style="bold magenta",
            padding=(0, 1)
        )
        table.add_column("Command", style="bold cyan", width=24, no_wrap=True)
        table.add_column("Description", style="white", width=42)
        table.add_column("Examples", style="dim", width=30)
        
        rows = [
            ('[bold cyan]analyze[/bold cyan] [italic]<service>[/italic]', 
             '[white]Full SRE investigation (RCA, logs, metrics, K8s)[/white]',
             'analyze payment-service'),
            ('[bold cyan]check[/bold cyan] [italic]<service>[/italic]', 
             '[white]Alias for analyze (shorthand)[/white]',
             'check database'),
            ('[bold cyan]why is[/bold cyan] [italic]<service>[/italic] [bold cyan]failing[/bold cyan]', 
             '[white]Natural language failure diagnosis[/white]',
             'why is payment failing?'),
            ('[bold cyan]compare[/bold cyan]', 
             '[white]Baseline vs RAG analysis comparison[/white]',
             'compare'),
            ('[bold cyan]watch[/bold cyan] [italic]<service>[/italic]', 
             '[white]Live log tailing + instant RCA[/white]',
             'watch payment-service'),
            ('[bold cyan]chat[/bold cyan]', 
             '[white]Interactive follow-up on last RCA[/white]',
             'chat'),
            ('[bold cyan]status[/bold cyan]', 
             '[white]System health + component dashboard[/white]',
             'status'),
            ('[bold cyan]cache[/bold cyan] {stats|clear}', 
             '[white]LLM cache statistics and management[/white]',
             'cache stats\ncache clear'),
            ('[bold cyan]what is[/bold cyan] [italic]<concept>[/italic]', 
             '[white]SRE/Kubernetes concept explanations[/white]',
             'what is Istio?'),
            ('[bold cyan]how does[/bold cyan] [italic]<x>[/italic] [bold cyan]work[/bold cyan]', 
             '[white]Deep-dive technical explanations[/white]',
             'how does RAG work?'),
            ('[bold cyan]help[/bold cyan]', 
             '[white]Display this command reference[/white]',
             'help'),
            ('[bold cyan]exit[/bold cyan] [dim]/ quit[/dim]', 
             '[white]Exit interactive SRE shell[/white]',
             'exit')
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

        # STEP 3: Route — WRAPPED FOR Ctrl+C
        try:
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
                self._cmd_explain(command["parameter"] or command["raw"])
            elif intent == "help":
                self._print_help()
            else:
                console.print(
                    "[yellow]Unknown command. "
                    "Type 'help'.[/yellow]"
                )
        except KeyboardInterrupt:
            console.print(
                "\n[dim]Interrupted.[/dim]\n"
            )
        except Exception as e:
            console.print(
                f"\n[bold red]Error: {e}[/bold red]"
                f"\n[dim]Type 'help' for commands."
                f"[/dim]\n"
            )

    def _cmd_status(self):
        try:
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
        except KeyboardInterrupt:
            console.print("\n[dim]Status check interrupted.[/dim]\n")
            return
        except KeyboardInterrupt:
            console.print(
                "\n[dim]Status check interrupted."
                "[/dim]\n"
            )
            return

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

