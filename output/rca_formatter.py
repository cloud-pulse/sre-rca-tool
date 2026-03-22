from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich import box
from rich.progress import Progress, BarColumn
from rich.style import Style
import contextlib
import sys
import os

# Fix Unicode block characters on Windows
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _get_bar_char() -> tuple:
    """Get bar characters, with ASCII fallback for terminals without Unicode support."""
    try:
        "█░".encode(sys.stdout.encoding or "utf-8")
        return "█", "░"
    except (UnicodeEncodeError, AttributeError, TypeError):
        return "=", "-"


class RCAFormatter:
    """Format and display RCA results with rich terminal UI."""

    def __init__(self):
        self.console = Console()

    def print_header(self, mode: str):
        """Print a styled header panel with mode-specific colors."""
        # Determine color based on mode
        if mode.lower() == "rag":
            mode_color = "bold cyan"
            mode_display = "RAG-Augmented"
        elif mode.lower() == "baseline":
            mode_color = "bold yellow"
            mode_display = "Baseline"
        else:
            mode_color = "bold red"
            mode_display = "Failed"

        # Create content with two lines
        content = (
            "Root Cause Analysis Framework\n"
            f"Mode: [{mode_color}]{mode_display}[/]"
        )

        # Create and print the panel
        header_panel = Panel(
            content,
            title="[bold white]SRE-AI[/bold white]",
            border_style="bold blue",
            expand=True,
            padding=(1, 2),
        )
        self.console.print(header_panel)

    def print_resource_table(self, resources: dict):
        """Print a rich table showing pod resource data with color coding."""
        table = Table(
            title="Pod Resource Consumption",
            box=box.ROUNDED,
            show_lines=True,
        )

        # Add columns
        table.add_column("Service", style="bold white")
        table.add_column("Pod Name", style="dim white")
        table.add_column("CPU", justify="right")
        table.add_column("CPU %", justify="right")
        table.add_column("Memory", justify="right")
        table.add_column("Mem %", justify="right")
        table.add_column("Restarts", justify="right")
        table.add_column("Status", justify="center")

        # Process each service
        for service_name, pods in resources.items():
            if not isinstance(pods, list):
                continue

            for pod in pods:
                status = pod.get("status", "Unknown")
                cpu_percent = pod.get("cpu_percent", 0.0)
                mem_percent = pod.get("memory_percent", 0.0)
                restarts = pod.get("restarts", 0)

                # Determine row and cell styles based on status and metrics
                row_style = ""
                status_style = ""

                # Check for error states
                if status == "CrashLoopBackOff":
                    row_style = "red"
                    status_style = "bold red"
                elif status == "OOMKilled":
                    row_style = "red"
                    status_style = "bold red"
                elif status == "Error":
                    row_style = "red"
                    status_style = "bold red"
                elif status == "Running":
                    # Check if any metric is critical
                    if cpu_percent > 80 or mem_percent > 80 or restarts > 3:
                        row_style = "yellow"
                        status_style = "bold green"
                    else:
                        status_style = "bold green"

                # Format CPU % with color
                if cpu_percent > 80:
                    cpu_text = f"[bold red]{cpu_percent:.1f}%[/bold red]"
                elif cpu_percent > 60:
                    cpu_text = f"[bold yellow]{cpu_percent:.1f}%[/bold yellow]"
                else:
                    cpu_text = f"[bold green]{cpu_percent:.1f}%[/bold green]"

                # Format Memory % with color
                if mem_percent > 80:
                    mem_text = f"[bold red]{mem_percent:.1f}%[/bold red]"
                elif mem_percent > 60:
                    mem_text = f"[bold yellow]{mem_percent:.1f}%[/bold yellow]"
                else:
                    mem_text = f"[bold green]{mem_percent:.1f}%[/bold green]"

                # Format Restarts with color
                if restarts > 3:
                    restarts_text = f"[bold red]{restarts}[/bold red]"
                elif restarts > 0:
                    restarts_text = f"[bold yellow]{restarts}[/bold yellow]"
                else:
                    restarts_text = "[bold green]0[/bold green]"

                # Format status with correct style
                status_text = f"[{status_style}]{status}[/]"

                # Add row
                table.add_row(
                    service_name,
                    pod.get("name", "unknown"),
                    pod.get("cpu", "0m"),
                    cpu_text,
                    pod.get("memory", "0Mi"),
                    mem_text,
                    restarts_text,
                    status_text,
                    style=row_style,
                )

        self.console.print(table)
        self.console.print()

    def print_rca(self, result: dict):
        """Print the RCA result as a rich Panel with color-coded sections."""
        # Build the content text
        content = Text()

        # ROOT CAUSE
        content.append("ROOT CAUSE\n", style="bold red")
        content.append(f"{result.get('root_cause', 'N/A')}\n\n", style="white")

        # AFFECTED SERVICES
        content.append("AFFECTED SERVICES\n", style="bold yellow")
        content.append(
            f"{result.get('affected_services', 'N/A')}\n\n", style="white"
        )

        # FAILURE CHAIN
        content.append("FAILURE CHAIN\n", style="bold white")
        content.append(
            f"{result.get('failure_chain', 'N/A')}\n\n", style="dim white"
        )

        # SUGGESTED FIXES
        content.append("SUGGESTED FIXES\n", style="bold magenta")
        fixes = result.get("suggested_fixes", [])
        if isinstance(fixes, list):
            for fix in fixes:
                priority = fix.get("priority", "Low")
                fix_text = fix.get("fix", "")

                # Color by priority
                if priority == "High":
                    content.append("  [High]   ", style="bold red")
                elif priority == "Medium":
                    content.append("  [Medium] ", style="bold yellow")
                else:
                    content.append("  [Low]    ", style="bold green")

                content.append(f"{fix_text}\n", style="white")
        content.append("\n")

        # CONFIDENCE
        confidence = result.get("confidence", 0)
        content.append("CONFIDENCE: ", style="bold cyan")

        if confidence >= 80:
            content.append(f"{confidence}%\n", style="bold green")
        elif confidence >= 50:
            content.append(f"{confidence}%\n", style="bold yellow")
        else:
            content.append(f"{confidence}%\n", style="bold red")

        # CONFIDENCE REASON
        content.append("REASON: ", style="bold cyan")
        content.append(
            f"{result.get('confidence_reason', 'N/A')}\n\n", style="dim white"
        )

        # HISTORICAL MATCH (only if mode == "rag")
        mode = result.get("mode", "baseline")
        if mode.lower() == "rag":
            content.append("HISTORICAL MATCH: ", style="bold cyan")
            historical_match = result.get("historical_match", "no")
            if historical_match.lower().startswith("yes"):
                content.append(f"{historical_match}\n", style="bold green")
            else:
                content.append(f"no\n", style="dim white")

        # Determine panel border color based on confidence
        if confidence >= 70:
            border_style = "green"
        elif confidence >= 50:
            border_style = "yellow"
        else:
            border_style = "red"

        # Create and print the panel
        rca_panel = Panel(
            content,
            title="RCA Result",
            border_style=border_style,
            expand=True,
            padding=(1, 2),
        )
        self.console.print(rca_panel)

    def print_incident_summary(self, result: dict):
        """Print a simple summary rule and text."""
        self.console.print(Rule("Incident Summary", style="dim blue"))
        self.console.print(
            f"  {result.get('incident_summary', 'N/A')}\n", style="dim white"
        )

        critical_pods = result.get("critical_pods", [])
        services_found = result.get("services_found", [])

        critical_str = ", ".join(critical_pods) if critical_pods else "None"
        services_str = ", ".join(services_found) if services_found else "None"

        self.console.print(
            f"  Critical pods : [bold red]{critical_str}[/]\n"
            f"  Services found: [bold white]{services_str}[/]"
        )
        self.console.print()

    @contextlib.contextmanager
    def spinner(self, message: str):
        """Context manager for showing a spinner while processing."""
        with self.console.status(
            f"[bold green]{message}[/bold green]", spinner="dots"
        ) as status:
            yield status

    def _make_similarity_bar(self,
                              score: float,
                              width: int = 20) -> Text:
        """Create a visual similarity bar using rich Text."""
        filled = int((score / 100) * width)
        empty = width - filled
        filled_char, empty_char = _get_bar_char()
        bar = Text()
        
        if score >= 75:
            bar.append(filled_char * filled, style="bold green")
        elif score >= 50:
            bar.append(filled_char * filled, style="bold yellow")
        else:
            bar.append(filled_char * filled, style="bold red")
        
        bar.append(empty_char * empty, style="dim white")
        bar.append(f"  {score}%", style="bold white")
        return bar

    def print_rag_context(self, retrieved: list):
        """Print a panel showing retrieved historical incidents from RAG."""
        if not retrieved:
            empty_panel = Panel(
                "No similar historical incidents retrieved.",
                border_style="dim",
                expand=True,
            )
            self.console.print(empty_panel)
            return

        # Print title rule
        self.console.print(
            Rule(
                f"RAG Context - {len(retrieved)} historical incidents",
                style="bold cyan",
            )
        )

        # Print each incident card
        for incident in retrieved:
            source = incident.get("source_file", "unknown")
            incident_type = incident.get("incident_type", "Unknown")
            date = incident.get("date", "N/A")
            severity = incident.get("severity", "UNKNOWN")
            similarity = incident.get("similarity_score", 0.0)
            resolution = incident.get("resolution", "N/A")

            # Truncate resolution to 120 chars
            if len(resolution) > 120:
                resolution = resolution[:117] + "..."

            # Determine card border color by similarity
            if similarity >= 75:
                border_color = "green"
            elif similarity >= 50:
                border_color = "yellow"
            else:
                border_color = "dim"

            # Build content
            content = Text()
            content.append(f"Source file  : {source}\n", style="dim white")
            content.append(f"Incident     : {incident_type}\n", style="white")
            content.append(f"Date         : {date}\n", style="dim white")
            content.append(f"Severity     : ", style="dim white")

            # Severity color
            if severity == "CRITICAL":
                content.append(f"{severity}\n", style="bold red")
            elif severity == "HIGH":
                content.append(f"{severity}\n", style="bold red")
            elif severity == "MEDIUM":
                content.append(f"{severity}\n", style="bold yellow")
            else:
                content.append(f"{severity}\n", style="bold green")

            content.append("\n")
            content.append("Similarity   : ", style="dim white")
            content.append(self._make_similarity_bar(similarity))
            content.append("\n\n")
            content.append("Resolution   : ", style="dim white")
            content.append(f"{resolution}\n", style="white")

            # Create and print card
            card = Panel(
                content,
                border_style=border_color,
                expand=True,
                padding=(0, 1),
            )
            self.console.print(card)

        # Print closing line
        self.console.print()

    def print_investigation_header(self, result: dict):
        target = result.get("target_service", "Unknown")
        ns = result.get("namespace", "default")
        src = result.get("data_source", "unknown")
        
        src_color = "bold green" if src == "kubernetes" else "bold yellow"
        
        content = Text(justify="center")
        content.append("Target: ", style="white")
        content.append(f"{target}\n", style="bold cyan")
        content.append("Namespace: ", style="white")
        content.append(f"{ns}\n", style="bold white")
        content.append("Source: ", style="white")
        content.append(f"{src}", style=src_color)
        
        panel = Panel(
            content,
            title="[bold white]SRE-AI[/bold white]",
            border_style="bold blue",
            expand=True
        )
        self.console.print(panel)

    def print_service_health_dashboard(self, result: dict):
        self.console.print(Rule("Service Health Dashboard", style="bold cyan"))
        
        table = Table(
            box=box.ROUNDED,
            show_header=True,
            header_style="bold white"
        )
        table.add_column("Service")
        table.add_column("Health")
        table.add_column("Role")
        table.add_column("Errors")
        table.add_column("Warnings")
        table.add_column("Key Patterns")
        
        services_health = result.get("services_health", {})
        timeline = result.get("cascade_timeline", [])
        patterns = result.get("patterns_by_category", {})
        
        roles_map = {item.get("service"): item.get("role") for item in timeline if isinstance(item, dict) and "service" in item}
        
        counts = {"CRITICAL": 0, "WARNING": 0, "OK": 0}
        
        for svc, health in services_health.items():
            if health == "CRITICAL":
                row_style = "red"
                health_cell = "[bold red]● CRITICAL[/]"
                counts["CRITICAL"] += 1
            elif health == "WARNING":
                row_style = "yellow"
                health_cell = "[bold yellow]● WARNING[/]"
                counts["WARNING"] += 1
            elif health == "OK":
                row_style = "green"
                health_cell = "[bold green]✓ OK[/]"
                counts["OK"] += 1
            else:
                row_style = "dim"
                health_cell = "[dim]? UNKNOWN[/]"
            
            role_raw = roles_map.get(svc, "unknown")
            if role_raw == "root_cause":
                role_cell = "[bold red]ROOT CAUSE[/]"
            elif role_raw == "cascade_victim":
                role_cell = "[yellow]CASCADE[/]"
            elif role_raw == "unaffected":
                role_cell = "[green]SAFE[/]"
            else:
                role_cell = "[dim]UNKNOWN[/]"
                
            # Key patterns
            svc_patterns = []
            for cat, items in patterns.items():
                for item in items:
                    if isinstance(item, str) and item.startswith(f"{svc}:"):
                        pat_id = item.split(":", 1)[1].strip()
                        svc_patterns.append(pat_id)
            
            pat_str = ", ".join(svc_patterns[:2])
            if len(pat_str) > 40:
                pat_str = pat_str[:37] + "..."
            
            table.add_row(
                svc,
                health_cell,
                role_cell,
                str(next((item.get("error_count", 0) for item in timeline if isinstance(item, dict) and item.get("service") == svc), 0)),
                "0",
                pat_str,
                style=row_style
            )
            
        self.console.print(table)
        self.console.print(f"{counts['CRITICAL']} critical, {counts['WARNING']} warning, {counts['OK']} healthy services", style="white")

    def print_cascade_timeline(self, result: dict):
        self.console.print(Rule("Cascade Timeline", style="bold magenta"))
        timeline = result.get("cascade_timeline", [])
        
        if not timeline:
            self.console.print("No cascade data available", style="dim")
            return
            
        for i, entry in enumerate(timeline):
            if not isinstance(entry, dict):
                continue
            svc = entry.get("service", "unknown")
            sev = entry.get("severity", "UNKNOWN")
            event = entry.get("event", "Unknown event")
            role = entry.get("role", "unknown")
            
            if sev == "CRITICAL":
                border = "red"
                symbol = "●"
                title_style = "bold red"
            elif sev == "WARNING":
                border = "yellow"
                symbol = "▲"
                title_style = "bold yellow"
            elif sev == "OK":
                border = "green"
                symbol = "✓"
                title_style = "bold green"
            else:
                border = "dim"
                symbol = "?"
                title_style = "dim"
                
            role_display = role.replace("_", " ").upper()
            
            content = Text()
            content.append(f"{symbol} {svc}  [{sev}]\n", style=title_style)
            content.append(f"  {event}\n", style="white")
            content.append(f"  Role: {role_display}", style="dim white")
            
            panel = Panel(
                content,
                border_style=border,
                expand=False
            )
            self.console.print(panel)
            
            if i < len(timeline) - 1:
                self.console.print("     ↓", style="dim")

    def print_investigation_summary(self, result: dict):
        self.console.print(Rule("Investigation Summary", style="bold white"))
        
        summary = result.get("investigation_summary", "No summary available")
        panel = Panel(
            summary,
            style="white",
            border_style="dim",
            expand=True
        )
        self.console.print(panel)
        
        self.console.print("Probable Root Cause:")
        svc = result.get("probable_root_cause_service", "Unknown")
        cause = result.get("probable_root_cause", "Unknown")
        self.console.print(f"Service: [bold red]{svc}[/]")
        self.console.print(f"Cause:   [bold white]{cause}[/]")
        
        pre_analysis_svc = result.get("pre_analysis_root_cause", "")
        if svc == pre_analysis_svc:
            self.console.print("✓ Rule-based analysis agrees", style="bold green")
        else:
            self.console.print(f"Rule-based suggested: {pre_analysis_svc}", style="dim")

    def print_ranked_causes(self, result: dict):
        self.console.print(Rule("Ranked Causes by Category", style="bold yellow"))
        
        ranked = result.get("ranked_causes", [])
        if not ranked:
            patterns = result.get("patterns_by_category", {})
            for cat, items in patterns.items():
                self.console.print(Rule(cat, style="dim yellow"))
                for item in items:
                    self.console.print(f"[SEVERITY] {item}")
            return
            
        categories = {}
        for cause in ranked:
            c = cause.get("category", "Uncategorized")
            if c not in categories:
                categories[c] = []
            categories[c].append(cause)
            
        for cat, causes in categories.items():
            self.console.print(Rule(cat, style="dim yellow"))
            for cause in causes:
                rank = cause.get("rank", 0)
                svc = cause.get("service", "Unknown")
                desc = cause.get("cause", "")
                evidence = cause.get("evidence", "")
                conf = cause.get("confidence", 0)
                
                content = Text()
                content.append(f"#{rank} ", style="bold white")
                content.append(f"{svc}\n", style="bold cyan")
                content.append(f"{desc}\n", style="white")
                content.append(f"Evidence: {evidence}\n", style="dim")
                content.append(self._make_similarity_bar(conf))
                
                if conf >= 80:
                    border = "green"
                elif conf >= 60:
                    border = "yellow"
                else:
                    border = "red"
                    
                self.console.print(Panel(content, border_style=border, expand=True))

    def print_remediation_steps(self, result: dict):
        self.console.print(Rule("Remediation Steps", style="bold green"))
        
        steps = result.get("remediation_steps", [])
        if not steps:
            self.console.print("No remediation steps generated. Check LLM response.", style="dim")
            patterns = result.get("patterns_by_category", {})
            for cat, items in patterns.items():
                for item in items:
                    self.console.print(f"Hint for {item}: Check pattern documentation", style="dim")
            return
            
        priorities = {"IMMEDIATE": [], "SHORT-TERM": [], "LONG-TERM": []}
        for step in steps:
            p = step.get("priority", "LONG-TERM").upper()
            if p in priorities:
                priorities[p].append(step)
            else:
                priorities["LONG-TERM"].append(step)
                
        headers = {
            "IMMEDIATE": ("IMMEDIATE — Do this now", "bold red", "red"),
            "SHORT-TERM": ("SHORT-TERM — Within 1 hour", "bold yellow", "yellow"),
            "LONG-TERM": ("LONG-TERM — Prevent recurrence", "bold green", "green")
        }
        
        for p, p_steps in priorities.items():
            if not p_steps:
                continue
                
            htext, hstyle, border = headers[p]
            self.console.print(Rule(htext, style=hstyle))
            
            for step in p_steps:
                n = step.get("step", "?")
                action = step.get("action", "")
                cmd = step.get("command", "")
                why = step.get("explanation", "")
                
                content = Text()
                content.append(f"{action}\n\n", style="bold white")
                content.append("Command:\n", style="bold cyan")
                content.append(f"  $ {cmd}\n\n", style="dim cyan")
                content.append("Why:\n", style="dim white")
                content.append(f"{why}", style="white")
                
                self.console.print(Panel(content, title=f"Step {n}", border_style=border, expand=True))

    def print_safe_services(self, result: dict):
        safe = result.get("safe_services", [])
        if not safe:
            self.console.print("All services showing signs of impact", style="dim")
            return
            
        self.console.print(Rule("Safe Services", style="bold green"))
        for s in safe:
            self.console.print(f"  ✓ {s}", style="bold green")
            
        self.console.print(f"{len(safe)} service(s) confirmed healthy and not contributing to incident", style="dim green")

    def print_full_investigation(self, result: dict, resources: dict = None):
        self.print_investigation_header(result)
        self.print_service_health_dashboard(result)
        if resources:
            self.print_resource_table(resources)
        self.print_cascade_timeline(result)
        self.print_investigation_summary(result)
        self.print_ranked_causes(result)
        self.print_safe_services(result)
        self.print_remediation_steps(result)
        self.console.print(Rule("End of Investigation Report", style="dim"))

    def print_full_result(self, result: dict, resources: dict):
        """Convenience method that prints everything in the correct order."""
        mode = result.get("mode", "baseline")
        self.print_header(mode)
        self.print_resource_table(resources)
        
        # Include RAG context if in RAG mode with retrieved incidents
        if mode.lower() == "rag":
            retrieved = result.get("retrieved_incidents", [])
            if retrieved:
                self.print_rag_context(retrieved)
        
        self.print_rca(result)
        self.print_incident_summary(result)


if __name__ == "__main__":
    import sys
    import os
    import time
    
    # Add workspace root to path for imports
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    from core.resource_collector import ResourceCollector

    formatter = RCAFormatter()
    collector = ResourceCollector()

    resources = collector.get_mock_resources([
        "database-service",
        "payment-service",
        "api-gateway",
        "auth-service"
    ])

    mock_retrieved = [
        {
            "source_file": "incident_001.log",
            "incident_type": (
                "DB connection pool exhaustion"
            ),
            "resolution": (
                "Increased DB connection pool size "
                "from 100 to 300. Added "
                "connection_timeout=30s and "
                "idle_timeout=600s."
            ),
            "severity": "HIGH",
            "date": "2024-01-10",
            "similarity_score": 84.2,
            "chunk": "sample log chunk text..."
        },
        {
            "source_file": "incident_002.log",
            "incident_type": (
                "Payment service OOM killed"
            ),
            "resolution": (
                "Increased memory limit from "
                "512Mi to 1Gi. Fixed HTTP client "
                "session leak."
            ),
            "severity": "HIGH",
            "date": "2024-02-03",
            "similarity_score": 61.5,
            "chunk": "sample log chunk text..."
        },
        {
            "source_file": "incident_003.log",
            "incident_type": (
                "Network policy misconfiguration"
            ),
            "resolution": (
                "Rolled back NetworkPolicy to "
                "previous version. All traffic "
                "restored within 3 minutes."
            ),
            "severity": "CRITICAL",
            "date": "2024-02-20",
            "similarity_score": 43.1,
            "chunk": "sample log chunk text..."
        }
    ]

    mock_result = {
        "mode": "rag",
        "root_cause": (
            "Database connection pool exhausted "
            "due to connection leak in "
            "payment-service retry logic."
        ),
        "affected_services": (
            "database-service, payment-service, "
            "api-gateway"
        ),
        "failure_chain": (
            "1. database-service pool hit 100%\n"
            "2. payment-service lost DB access\n"
            "3. api-gateway circuit breaker opened"
        ),
        "suggested_fixes": [
            {
                "priority": "High",
                "fix": (
                    "Increase DB connection pool "
                    "size from 100 to 300"
                )
            },
            {
                "priority": "Medium",
                "fix": (
                    "Fix connection leak in "
                    "payment-service retry logic"
                )
            },
            {
                "priority": "Low",
                "fix": (
                    "Add pool monitoring alerts "
                    "at 70% threshold"
                )
            }
        ],
        "confidence": 82,
        "confidence_reason": (
            "Strong match with historical pattern "
            "from incident_001.log"
        ),
        "historical_match": (
            "yes - DB connection pool exhaustion "
            "(incident_001.log)"
        ),
        "incident_summary": (
            "Incident at 10:05:12 affecting 3 "
            "services over 17 minutes."
        ),
        "critical_pods": [
            "database-service",
            "payment-service"
        ],
        "services_found": [
            "api-gateway",
            "auth-service",
            "database-service",
            "payment-service"
        ],
        "retrieved_incidents": mock_retrieved
    }

    print("\n--- Test 1: RAG context panel ---")
    formatter.print_rag_context(mock_retrieved)

    print("\n--- Test 2: Similarity bars ---")
    for score in [84.2, 61.5, 43.1, 95.0, 30.0]:
        bar = formatter._make_similarity_bar(score)
        formatter.console.print(
            f"Score {score:5.1f}%: ", bar
        )

    print("\n--- Test 3: Empty retrieved ---")
    formatter.print_rag_context([])

    print("\n--- Test 4: Full result RAG mode ---")
    formatter.print_full_result(mock_result, resources)

    print("\n--- Test 5: Full result baseline mode ---")
    baseline_result = {
        **mock_result,
        "mode": "baseline",
        "historical_match": "no",
        "retrieved_incidents": []
    }
    formatter.print_full_result(
        baseline_result, resources
    )

    print("\n--- Test 6: Spinner ---")
    with formatter.spinner(
        "Analyzing with phi3:mini (RAG mode)..."
    ):
        time.sleep(2)
    print("Spinner done.")

    print("\nTask 17 OK")
