import sys
import os
sys.path.insert(0, os.path.dirname(
    os.path.abspath(__file__)
))
from rich.console import Console
from rich.rule import Rule
from rich.panel import Panel
console = Console()

import yaml
import re
import subprocess
from pathlib import Path

class NLParser:
    def __init__(self):
        self._load_services()

    def _load_services(self):
        with open('services.yaml', 'r') as f:
            data = yaml.safe_load(f)
            services = data['services']
        
        self.known_services = list(services.keys())
        self.service_aliases = {}
        for svc in self.known_services:
            if '-' in svc:
                alias = svc.split('-')[0]
                self.service_aliases[alias] = svc
        
        self.intent_patterns = [
            # EXPLAIN PATTERNS (14 exact)
            (["what is"], "explain"),
            (["what are"], "explain"), 
            (["how does"], "explain"),
            (["how do"], "explain"),
            (["explain"], "explain"),
            (["tell me about"], "explain"),
            (["is it"], "explain"),
            (["is there"], "explain"),
            (["does this"], "explain"),
            (["is this"], "explain"),
            (["implemented"], "explain"),
            (["difference between"], "explain"),
            (["what does"], "explain"),
            (["how is"], "explain"),
            # ANALYZE (catch-all LAST)
            (["check"], "analyze"),
            (["analyze"], "analyze"),
            (["analyse"], "analyze"),
            (["why"], "analyze"),
            (["what", "happened"], "analyze"),
            (["failing"], "analyze"),
            (["error"], "analyze"),
            (["issue"], "analyze"),
            (["problem"], "analyze"),
            (["incident"], "analyze"),
            (["rca"], "analyze"),
            (["logs"], "analyze"),
            (["diagnose"], "analyze"),
            (["investigate"], "analyze"),
        ]

    def extract_service(self, text: str) -> str | None:
        candidates = list(self.service_aliases.values()) + self.known_services
        candidates = sorted(set(candidates), key=len, reverse=True)
        
        text_lower = text.lower()
        for cand in candidates:
            if cand.lower() in text_lower:
                return cand
        return None

    def extract_mode(self, text: str) -> str:
        return "baseline" if "baseline" in text.lower() else "rag"

    def extract_log_file(self, text: str) -> str | None:
        match = re.search(r'logs?/([^.\s]+?\.log)', text, re.I)
        if match:
            log_file = match.group(1)
            if os.path.exists(log_file):
                return log_file
            log_file = f'logs/{log_file}'
            if os.path.exists(log_file):
                return log_file
        if os.path.exists('logs/test.log'):
            return 'logs/test.log'
        return None

    def extract_namespace(self, text: str) -> str | None:
        patterns = [
            r'namespace[=:]\s*(\S+)',
            r'-n\s+(\S+)'
        ]
        text_lower = text.lower()
        for pat in patterns:
            match = re.search(pat, text_lower)
            if match:
                return match.group(1)
        return None

    def is_out_of_scope(self, text: str) -> bool:
        text_lower = text.lower()
        
        # Step 1: hard_in_scope keywords
        hard_in_scope = [
            'pod', 'pods', 'container', 'node', 'kubectl', 'kubernetes', 'k8s',
            'namespace', 'deploy', 'deployment', 'replica', 'replicaset',
            'daemonset', 'statefulset', 'ingress', 'service', 'configmap',
            'secret', 'pvc', 'volume', 'hpa', 'vpa', 'crd', 'rbac', 'istio',
            'envoy', 'sidecar', 'mesh', 'cluster', 'kubeconfig', 'helm', 'log',
            'logs', 'error', 'crash', 'restart', 'fail', 'failing', 'failed',
            'timeout', 'latency', 'slowdown', 'connection', 'refused',
            'unreachable', 'memory', 'cpu', 'oom', 'throttl', 'metric', 'alert',
            'incident', 'outage', 'rca', 'root cause', 'investigate', 'analyze',
            'analyse', 'diagnose', 'monitor', 'watch', 'trace', 'baseline', 'rag',
            'cache', 'database', 'db', 'redis', 'kafka', 'rabbitmq', 'postgres',
            'mysql', 'nginx', 'apache', 'grpc', 'http', 'api', 'endpoint',
            'health', 'probe', 'liveness', 'readiness', 'evict'
        ]
        if any(word in text_lower for word in hard_in_scope):
            return False
        
        # Step 2: known service or alias
        all_services = set(self.service_aliases.values()) | set(self.known_services)
        if any(svc.lower() in text_lower for svc in all_services):
            return False
        
        # Step 3: hard_out_of_scope patterns
        out_patterns = [
            r"\bwho is\b", r"\bwho was\b", r"\bwho are\b", r"prime minister",
            r"president of", r"\bminister\b", r"\bgovernment\b", r"\bpolitics\b",
            r"\belection\b", r"capital (city )?of", r"\bpopulation of\b",
            r"currency of", r"\bcountry\b", r"\bcity\b", r"\bcontinent\b",
            r"\bweather\b", r"\btemperature\b", r"\bsports?\b", r"\bcricket\b",
            r"\bfootball\b", r"\bmovie\b", r"\bfilm\b", r"\bsong\b", r"\bmusic\b",
            r"\bactor\b", r"\bactress\b", r"\bcelebrit", r"\brecipe\b",
            r"\bcooking\b", r"\bfood\b", r"\brestaurant\b", r"\bwrite (me |a |an )",
            r"\bpoem\b", r"\bstory\b", r"\bessay\b", r"\btranslat", r"\bjoke\b",
            r"\bstock price\b", r"\bshare price\b", r"\bcryptocurrenc", r"\bbitcoin\b",
            r"\bexchange rate\b", r"^(hi|hello|hey|howdy|greetings)\.?$", r"^how are you",
            r"^what is your name", r"^tell me about yourself"
        ]
        if any(re.search(pat, text_lower) for pat in out_patterns):
            return True
        
        # Step 4: sre_intent_words
        sre_intents = [
            'check', 'why', 'what happened', 'what is wrong', 'whats wrong',
            'broken', 'down', 'not working', 'issue', 'problem', 'investigate',
            'fix', 'debug', 'troubleshoot', 'compare', 'status', 'report',
            'incident', 'failure', 'alert'
        ]
        if any(phrase in text_lower for phrase in sre_intents):
            return False
        
        # Step 5: default False
        return False

    def get_out_of_scope_message(self, text: str) -> str:
        return Panel(
            "🤖 SRE-AI focuses on Kubernetes microservices troubleshooting\n\n"
            "Supported:\n"
            "• Log analysis & RCA\n" 
            "• Service health & investigation\n"
            "• Live log monitoring\n"
            "• Historical incident matching\n\n"
            f"[dim]'{text}'[/dim] is outside scope\n\n"
            "Try:\n"
            "• 'analyze payment-service'\n"
            "• 'check logs/test.log'\n"
            "• 'what is istio?'\n"
            "• 'help'",
            title="Scope Check",
            border_style="yellow",
            padding=(1,1)
        )

    def parse(self, text: str) -> dict:
        text_lower = text.lower()
        for words, intent in self.intent_patterns:
            if all(w in text_lower for w in words):
                return {
                    'intent': intent,
                    'service': self.extract_service(text),
                    'mode': self.extract_mode(text),
                    'log_file': self.extract_log_file(text),
                    'namespace': self.extract_namespace(text),
                    'raw': text
                }
        return {'intent': 'help', **{k: None for k in ['service','mode','log_file','namespace']}, 'raw': text}

class AISRECli:
    def __init__(self):
        self.parser = NLParser()

    def _print_banner(self):
        console.print(Panel(
            "AI SRE Assistant\n\nType [bold cyan]'help'[/bold cyan] to see examples",
            title="🤖 AI-SRE",
            subtitle="Kubernetes Microservices RCA Tool",
            border_style="cyan",
            padding=(2,2)
        ))

    def _print_help(self):
        console.print(Rule("Usage Examples", style="bold cyan"))
        examples = [
            "analyze logs/test.log",
            "check payment-service -n sre-demo", 
            "compare baseline vs rag",
            "watch logs/live.log",
            "what is istio sidecar?",
            "status",
            "cache_stats",
            "help"
        ]
        console.print("\n".join(f"• [cyan]{ex}[/cyan]" for ex in examples))

    def execute(self, command: dict):
        text = command['raw']
        
        if self.parser.is_out_of_scope(text):
            console.print(self.parser.get_out_of_scope_message(text))
            return
            
        intent = command['intent']
        console.print(f"[bold green]Understood:[/bold green] {intent}", 
                     f"service=[dim]{command.get('service') or 'all'}[/dim]", 
                     f"mode=[dim]{command.get('mode')}[/dim]", sep="\n  ")

        if intent == 'analyze':
            self._run_analyze(command['log_file'], command['service'], 
                            command['mode'], command['namespace'])
        elif intent == 'compare':
            self._run_compare(command['log_file'], command['namespace'])
        elif intent == 'watch':
            self._run_watch(command['log_file'], command['service'], command['namespace'])
        elif intent == 'chat':
            self._run_chat()
        elif intent == 'status':
            self._run_status()
        elif intent == 'cache_clear':
            self._run_cache_clear()
        elif intent == 'cache_stats':
            self._run_cache_stats()
        elif intent == 'explain':
            self._run_explain(command['raw'])
        elif intent == 'help':
            self._print_help()
        else:
            console.print(Panel("Unknown command. Type 'help'", 
                              border_style="yellow"))

    def _run_explain(self, question: str):
        from core.llm_analyzer import LLMAnalyzer
        from core.service_graph import ServiceGraph
        import yaml
        
        analyzer = LLMAnalyzer()
        graph = ServiceGraph()
        
        with open('services.yaml', 'r') as f:
            services = yaml.safe_load(f)['services']
        
        project_context = {
            'services': list(services.keys()),
            'containers': {svc: s.get('containers', []) for svc,s in services.items()}
        }
        
        prompt = f"""Answer this question about the SRE project in 3-5 sentences:

Question: {question}

Project context:
Services: {', '.join(project_context['services'])}
Containers per service: {project_context['containers']}

Do NOT output RCA format. Do NOT analyze logs. Answer directly and concisely."""

        if not analyzer.check_ollama_connection():
            console.print("[bold red]Ollama not available[/bold red]")
            return
            
        with console.status("🤔 Thinking..."):
            answer = analyzer._call_ollama(prompt)
        
        console.print(Panel(answer, title="Answer", style="cyan", padding=(1,1)))

    def _run_analyze(self, log_file, service, mode, namespace):
        if service:
            self._run_investigation(service, namespace, mode)
        else:
            from main import run_pipeline
            result = run_pipeline(
                log_path=log_file,
                mode=mode,
                service_filter=service,
                namespace=namespace
            )
            from output.rca_formatter import RCAFormatter
            formatter = RCAFormatter()
            formatter.print_full_result(result, {})

    def _run_investigation(self, service, namespace, mode):
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
        
        canonical = graph.resolve_service(service) or service
        namespace = graph.resolve_namespace(canonical) or namespace or 'sre-demo'
        
        console.print(Rule(f"🔍 Investigating: {canonical}", style="bold blue"))
        console.print(f"Namespace: [cyan]{namespace}[/cyan]")
        console.print(f"Mode: [cyan]{mode}[/cyan]")
        console.print(f"Source: [{'green'if USE_KUBERNETES else'yellow'}]{'kubectl' if USE_KUBERNETES else 'mock'}[/]")
        
        if not analyzer.check_ollama_connection():
            console.print("[bold red]Ollama unavailable - cannot investigate[/bold red]")
            return
            
        analyzer.warmup()
        
        with console.status("📊 Collecting evidence..."):
            evidence = investigator.investigate(canonical, namespace)
            
        services_list = graph.get_dependencies(canonical) + [canonical]
        with console.status("⚙️  Gathering resources..."):
            resources = collector.get_resources(services_list, namespace)
            
        with console.status("🧠 LLM analysis..."):
            analysis = analyzer.analyze_investigation(evidence)
            
        formatter.print_full_investigation(analysis, resources)

    def _run_compare(self, log_file, namespace):
        from main import run_pipeline
        from evaluation.comparator import Comparator
        
        baseline = run_pipeline(log_path=log_file, mode='baseline', namespace=namespace)
        rag = run_pipeline(log_path=log_file, mode='rag', namespace=namespace)
        
        comparator = Comparator()
        comparator.compare(baseline, rag)

    def _run_watch(self, log_file, service, namespace):
        if not log_file:
            if os.path.exists('logs/test.log'):
                log_file = 'logs/test.log'
            else:
                console.print("[red]No log file specified and logs/test.log missing[/red]")
                return
                
        import time
        from core.log_processor import LogProcessor
        
        processor = LogProcessor()
        rca_count = 0
        
        console.print(f"[bold green]👀 Watching {log_file}[/bold green]")
        console.print("Press Ctrl+C to stop")
        
        last_size = os.path.getsize(log_file)
        
        try:
            while True:
                time.sleep(2)
                
                if not os.path.exists(log_file):
                    continue
                    
                curr_size = os.path.getsize(log_file)
                if curr_size <= last_size:
                    continue
                    
                with open(log_file, 'r') as f:
                    f.seek(last_size)
                    new_lines = f.read().strip().split('\n')
                    
                last_size = curr_size
                
                if not new_lines:
                    continue
                    
                entries = processor.process(new_lines)
                errors = processor.filter_by_severity(entries, 'ERROR')
                
                if errors:
                    rca_count += 1
                    from main import run_pipeline
                    result = run_pipeline(log_file, mode='rag')
                    
                    # Compact RCA panel (as specified in main.py style)
                    from rich.panel import Panel
                    conf = result.get('confidence', 0)
                    cause = result.get('root_cause', 'N/A')[:150]
                    
                    border = 'green' if conf >=70 else 'yellow' if conf >=50 else 'red'
                    content = f"Root Cause: {cause}\nConfidence: {conf}%\nTop Fix: {result.get('suggested_fixes', [{}])[0].get('fix', 'N/A')[:100]}"
                    
                    console.print(Panel(content, title=f"Quick RCA #{rca_count}", border_style=border))
                    console.print(Rule(style='dim'))
        
        except KeyboardInterrupt:
            console.print("\n[dim]Watch stopped[/dim]")

    def _run_chat(self):
        subprocess.run([sys.executable, "main.py", "chat"])

    def _run_status(self):
        subprocess.run([sys.executable, "main.py", "status"])

    def _run_cache_clear(self):
        from core.llm_cache import LLMCache
        cache = LLMCache()
        count = cache.clear(0)
        console.print(f"[green]✅ Cleared {count} cache entries[/green]")

    def _run_cache_stats(self):
        subprocess.run([sys.executable, "main.py", "cache"])

def main():
    cli = AISRECli()
    
    if len(sys.argv) > 1:
        command_text = ' '.join(sys.argv[1:])
        command = cli.parser.parse(command_text)
        cli.execute(command)
        return
    
    cli._print_banner()
    
    try:
        while True:
            try:
                user_input = console.input("\n[bold cyan]ai-sre> [/bold cyan]")
                if not user_input.strip():
                    continue
                    
                if user_input.lower() in ['exit', 'quit', 'bye']:
                    console.print("[dim]Goodbye! 👋[/dim]")
                    break
                
                command = cli.parser.parse(user_input)
                cli.execute(command)
                
            except KeyboardInterrupt:
                console.print("\n[bold red]^C[/bold red] Use 'exit' to quit")
                
    except KeyboardInterrupt:
        console.print("\n[dim]ai-sre stopped[/dim]")

if __name__ == "__main__":
    main()

