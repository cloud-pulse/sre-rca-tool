# ─────────────────────────────────────────────────────────────────────────────
# PATCH: core/command_registry.py
# Replace AnalyseHandler._handle_kubectl(), _resolve_service()
# Remove _print_kubectl_result() entirely — no longer needed
# Add _build_kubectl_prompt() and _collect_kubectl_evidence()
# ─────────────────────────────────────────────────────────────────────────────
#
# HOW IT WORKS:
#   1. Resolve service name (yaml → fuzzy → kubectl fallback)
#   2. If not found anywhere → print clean error, return early
#   3. Run kubectl RCA pipeline to get structured finding + raw evidence
#   4. Build a prompt from that evidence (same style as WindowAnalyzer)
#   5. Call provider.generate(prompt) → get narrative string
#   6. Extract confidence from narrative (same regex as WindowAnalyzer)
#   7. Shape result dict to match _print_analysis_result() exactly
#   8. Call _print_analysis_result(result, mode="kubectl") — done
#
# ─────────────────────────────────────────────────────────────────────────────


class AnalyseHandler(BaseHandler):
    description = "Full SRE investigation (RCA, logs, metrics, K8s)"
    aliases = ["analyze", "analyse"]

    def handle(self, args: list[str]) -> str:

        # ── Parse args (unchanged) ────────────────────────────────────────
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
            return self._handle_kubectl(service)

        # ── Branch: file mode (completely unchanged) ──────────────────────
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
        _print_analysis_result(result, mode="RAG")
        return "ok"

    # ─────────────────────────────────────────────────────────────────────
    # kubectl live mode — main entry
    # ─────────────────────────────────────────────────────────────────────

    def _handle_kubectl(self, service: str) -> str:
        from core.service_graph import ServiceGraph
        from core.kubectl_rca_investigator import run_kubectl_rca
        from core.llm_provider import provider
        import re

        namespace = K8S_NAMESPACE or "default"
        sg = ServiceGraph()

        # ── Step 1: Resolve service name ──────────────────────────────────
        console.print(f"\n[dim]Resolving service '{service}'...[/dim]")
        resolved, found = self._resolve_service(service, sg, namespace)

        # ── Step 2: Early exit if not found anywhere ──────────────────────
        if not found:
            from rich.panel import Panel
            console.print(Panel(
                f"[bold red]Service '[white]{service}[/white]' not found.[/bold red]\n\n"
                f"[white]It does not exist in [cyan]services.yaml[/cyan] "
                f"or in the cluster namespace '[cyan]{namespace}[/cyan]'.[/white]\n\n"
                f"[dim]Run [bold]list-services[/bold] to see all available services.[/dim]",
                title="[bold red]Service Not Found[/bold red]",
                border_style="red",
                padding=(1, 2),
            ))
            return "not_found"

        console.print(
            f"[dim]Running kubectl RCA for [bold]{resolved}[/bold] "
            f"in namespace [bold]{namespace}[/bold]...[/dim]\n"
        )

        # ── Step 3: Run sequential RCA pipeline ───────────────────────────
        rca = run_kubectl_rca(resolved, namespace, service_graph=sg)

        # ── Step 4: Collect evidence into readable text ───────────────────
        evidence_text = self._collect_kubectl_evidence(rca)

        # ── Step 5: Build prompt + call LLM ──────────────────────────────
        prompt = self._build_kubectl_prompt(resolved, rca, evidence_text)
        console.print("[dim]Generating narrative RCA...[/dim]\n")
        narrative = provider.generate(prompt)

        # ── Step 6: Extract confidence (reuse WindowAnalyzer approach) ────
        confidence_match = re.search(r"CONFIDENCE:\s*(\d+)%", narrative, re.IGNORECASE)
        confidence = int(confidence_match.group(1)) if confidence_match else rca.get("confidence", 0)

        # ── Step 7: Shape result dict to match _print_analysis_result() ───
        result = {
            "service":               resolved,
            "windows_used":          "Live (kubectl)",
            "confidence":            confidence,
            "analysis":              narrative,
            "low_confidence_warning": confidence < 70,
            "incident_record": {
                "saved":            False,
                "reason":           rca.get("evidence_stage") or "kubectl_live",
                "similarity_score": 0.0,
            },
        }

        # ── Step 8: Print using EXISTING _print_analysis_result() ─────────
        # Swap "Windows used" label for kubectl-specific fields by printing
        # kubectl context BEFORE calling the standard renderer
        self._print_kubectl_context(rca, resolved, namespace)
        _print_analysis_result(result, mode="kubectl")
        return "ok"

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    def _resolve_service(self, service_name: str, sg, namespace: str) -> tuple[str, bool]:
        """
        Returns (resolved_name, found: bool).
        found=False means not in yaml AND not in cluster → caller should exit early.
        """
        from core.kubectl_client import get_deployment_list

        # Exact match in services.yaml
        if service_name in sg.services:
            return service_name, True

        # Fuzzy match in services.yaml
        fuzzy = [
            n for n in sg.services
            if service_name.lower() in n.lower() or n.lower() in service_name.lower()
        ]
        if fuzzy:
            console.print(f"[dim]Matched '{service_name}' → '{fuzzy[0]}' from services.yaml[/dim]")
            return fuzzy[0], True

        # kubectl cluster fallback
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

    def _collect_kubectl_evidence(self, rca: dict) -> str:
        """
        Flatten all kubectl evidence stages into a readable text block
        to use as the 'logs' context in the LLM prompt.
        """
        all_evidence = rca.get("all_evidence", {})
        sections = []

        if all_evidence.get("pod_status"):
            sections.append("=== POD STATUS ===\n" + all_evidence["pod_status"])

        if all_evidence.get("pod_events"):
            sections.append("=== POD EVENTS ===\n" + all_evidence["pod_events"][:2000])

        if all_evidence.get("pod_logs"):
            sections.append("=== POD LOGS ===\n" + all_evidence["pod_logs"][:3000])

        if all_evidence.get("resource_pressure"):
            sections.append("=== RESOURCE PRESSURE ===\n" + all_evidence["resource_pressure"])

        # Dependency evidence
        for dep_report in rca.get("dependency_reports", []):
            dep_svc = dep_report.get("target_service", "unknown")
            dep_evidence = dep_report.get("all_evidence", {})
            dep_lines = []
            if dep_evidence.get("pod_status"):
                dep_lines.append(dep_evidence["pod_status"])
            if dep_evidence.get("pod_logs"):
                dep_lines.append(dep_evidence["pod_logs"][:1000])
            if dep_lines:
                sections.append(f"=== DEPENDENCY: {dep_svc} ===\n" + "\n".join(dep_lines))

        return "\n\n".join(sections) if sections else "No evidence collected."

    def _build_kubectl_prompt(self, service: str, rca: dict, evidence_text: str) -> str:
        """
        Build the LLM prompt using the same style as WindowAnalyzer._build_prompt().
        Injects the structured RCA finding as additional context so the LLM
        produces a richer, more accurate narrative.
        """
        dep_chain = rca.get("dependency_chain", [])
        dep_chain_str = " → ".join(dep_chain) if dep_chain else "none"
        preliminary_cause = rca.get("root_cause", "unknown")
        preliminary_conf  = rca.get("confidence", 0)

        return f"""You are an expert Site Reliability Engineer performing root cause analysis.

Service: {service}
Source: Live Kubernetes cluster (kubectl)

Preliminary finding from automated rule-based analysis:
- Root cause candidate: {preliminary_cause}
- Confidence: {preliminary_conf}%
- Dependency chain: {dep_chain_str}

--- KUBECTL EVIDENCE START ---
{evidence_text}
--- KUBECTL EVIDENCE END ---

Using the evidence above, analyse this incident and identify:
1. Root cause of any failures or anomalies
2. Sequence of events leading to failure
3. Affected services and impact
4. Recommended remediation steps

If the preliminary finding is supported by the evidence, expand on it with detail.
If the evidence contradicts it, override it with your own conclusion.

At the end of your analysis, you MUST include this block exactly:
CONFIDENCE: <number>%
REASON: <one sentence explaining your confidence level>

Confidence should reflect how complete the picture is:
- 80-100%: clear root cause, full evidence visible
- 60-79%: likely root cause but some gaps
- 40-59%: partial picture, more context needed
- below 40%: insufficient data"""

    def _print_kubectl_context(self, rca: dict, service: str, namespace: str) -> None:
        """
        Print a small kubectl-specific context block BEFORE the standard
        _print_analysis_result() renders. Shows pod name, evidence stage,
        dependency chain — the fields file mode doesn't have.
        """
        from rich.table import Table
        from rich import box

        ctx = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        ctx.add_column(style="bold cyan", width=18)
        ctx.add_column(style="white")

        ctx.add_row("Namespace",      namespace)
        ctx.add_row("Affected Pod",   rca.get("affected_pod") or "N/A")
        ctx.add_row("Evidence Stage", rca.get("evidence_stage") or "N/A")

        dep_chain = rca.get("dependency_chain", [])
        if dep_chain:
            ctx.add_row("Root Chain", " → ".join(dep_chain))

        dep_reports = rca.get("dependency_reports", [])
        if dep_reports:
            dep_summary = []
            for dep in dep_reports:
                dep_svc  = dep.get("target_service", "?")
                dep_conf = dep.get("confidence", 0)
                status   = "⚠" if dep_conf >= 60 else "✓"
                dep_summary.append(f"{status} {dep_svc} ({dep_conf}%)")
            ctx.add_row("Dependencies", "  ".join(dep_summary))

        console.print(ctx)