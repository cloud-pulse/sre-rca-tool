import os
import sys

sys.path.insert(
    0,
    os.path.dirname(os.path.abspath(__file__))
)

from rich.console import Console

from core.command_registry import (
    is_out_of_scope,
    print_banner,
    print_out_of_scope_message,
    resolve,
)

console = Console()

# ── K8s Default Mode Startup ──────────────────────────────────────
_K8S_MGR = None
_STARTUP_MODE = "file"

from flags import ENABLE_KUBERNETES_MODE, KUBE_CONFIG_PATH, KUBE_CONTEXT, KUBE_NAMESPACES

# Check if --log-file was passed on CLI
if "--log-file" in sys.argv:
    try:
        idx = sys.argv.index("--log-file")
        log_path = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if log_path:
            os.environ["ENABLE_KUBERNETES_MODE"] = "false"
            _STARTUP_MODE = "file"
            console.print(f"[dim]File mode: analysing {log_path}. K8s mode disabled for this run.[/dim]")
    except Exception:
        pass
elif ENABLE_KUBERNETES_MODE:
    try:
        from k8s.client import K8sClientManager
        _K8S_MGR = K8sClientManager(KUBE_NAMESPACES, KUBE_CONFIG_PATH, KUBE_CONTEXT)
        if _K8S_MGR.is_available():
            _STARTUP_MODE = "k8s"
            cluster_info = _K8S_MGR.get_cluster_info()
            context = cluster_info.get("context", "unknown")
            console.print(f"[dim]Connected to cluster. Context: {context}[/dim]")
        else:
            _STARTUP_MODE = "file"
            console.print(
                "[bold yellow]⚠️  K8s mode is ON but cluster is unreachable. "
                "Falling back to file mode. Pass --log-file <path> to analyse a log file.[/bold yellow]"
            )
    except Exception as e:
        _STARTUP_MODE = "file"
        console.print(f"[bold yellow]⚠️  K8s init failed ({e}). Falling back to file mode.[/bold yellow]")
else:
    _STARTUP_MODE = "file"


def _answer_sre_question(question: str):
    from core.llm_provider import provider
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.console import Console
    c = Console()

    prompt = (
        "You are an expert Site Reliability Engineer and DevOps practitioner.\n"
        "Answer the following question clearly and practically.\n"
        "Topics you cover: SRE, DevOps, Kubernetes, microservices, "
        "cloud infrastructure, observability, incident management, "
        "CI/CD, service mesh, containerisation, monitoring, alerting, "
        "chaos engineering, and all related tools and methodologies.\n"
        "If the question is completely unrelated to these topics, "
        "say so politely and suggest an SRE-related topic instead.\n"
        "Keep the answer focused — 3 to 8 sentences with practical detail.\n\n"
        f"Question: {question}"
    )

    with c.status("[dim]Thinking...[/dim]", spinner="dots"):
        try:
            response = provider.generate(prompt)
        except Exception as e:
            c.print(f"[bold red]LLM error: {e}[/bold red]")
            return

    if response and response.strip():
        c.print(Panel(
            Markdown(response.strip()),
            title="[bold cyan]SRE Knowledge[/bold cyan]",
            border_style="cyan",
            expand=False,
            padding=(1, 2),
        ))


def _run_input(user_input: str):
    # Handle /save command
    if user_input.lower() == "/save":
        try:
            from core.service_graph import ServiceGraph
            graph = ServiceGraph()
            # Try to get K8s snapshot for drift detection
            try:
                # This would need to be passed in context, for now just apply
                if hasattr(graph, '_pending_changes') and graph._pending_changes:
                    graph.prompt_and_apply(save_to_disk=True)
                else:
                    console.print("[dim]No pending changes to apply.[/dim]")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not detect drift: {e}[/yellow]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
        return

    result = resolve(user_input)

    if not result:
        if is_out_of_scope(user_input):
            print_out_of_scope_message(user_input)
            return
        # Fallback: treat as SRE knowledge question
        _answer_sre_question(user_input)
        return

    handler, args = result

    try:
        handler.handle(args)
    except KeyboardInterrupt:
        console.print(
            "\n[dim]Interrupted.[/dim]\n"
        )
    except Exception as exc:
        console.print(
            f"\n[bold red]Error: {exc}[/bold red]"
            f"\n[dim]Type 'help' for commands.[/dim]\n"
        )


def main():
    # Check for --save flag
    if "--save" in sys.argv:
        try:
            from core.service_graph import ServiceGraph
            graph = ServiceGraph()
            if hasattr(graph, '_pending_changes') and graph._pending_changes:
                graph.prompt_and_apply(save_to_disk=True)
            else:
                console.print("[dim]No pending changes to apply.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
        return

    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:]).strip()
        if text:
            _run_input(text)
        return

    print_banner()

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

        _run_input(user_input)


if __name__ == "__main__":
    main()
