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
