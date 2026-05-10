"""
K8s Service Resolver - Single entry point for service name resolution.

Implements a 4-step resolution strategy:
1. Static config lookup (services.yaml)
2. Fuzzy name matching against snapshot
3. Interactive namespace + workload selection
4. User confirmation
"""

from typing import Optional, List
import yaml
from pathlib import Path
from dataclasses import dataclass
from rich.console import Console
from rich.table import Table
from rich import box

from core.logger import get_logger
from k8s.models import K8sClusterSnapshot, K8sWorkload
from k8s.namespace_guard import NamespaceGuard

log = get_logger("k8s_service_resolver")
console = Console()


class K8sServiceResolver:
    """
    Service name resolver with fuzzy matching and interactive fallback.
    
    Resolution order:
    1. Static config lookup
    2. Fuzzy name match in snapshot
    3. Interactive namespace/workload selection
    4. User confirmation
    """

    def __init__(
        self,
        snapshot: K8sClusterSnapshot,
        services_yaml_path: str = "services.yaml",
        guard: Optional[NamespaceGuard] = None,
    ):
        """
        Initialize resolver.
        
        Args:
            snapshot: K8sClusterSnapshot from collector
            services_yaml_path: Path to services.yaml
            guard: NamespaceGuard instance (created fresh if None)
        """
        self.snapshot = snapshot
        self.services_yaml_path = services_yaml_path
        self.guard = guard or NamespaceGuard()
        self._static_config: dict = {}
        self._cache: dict[str, K8sWorkload] = {}

        # Load static config
        self._load_static_config()

    def _load_static_config(self):
        """Load services.yaml into _static_config."""
        try:
            with open(self.services_yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                self._static_config = data.get("services", {})
                log.debug(f"Loaded {len(self._static_config)} services from {self.services_yaml_path}")
        except FileNotFoundError:
            log.warn(f"services.yaml not found at {self.services_yaml_path}")
            self._static_config = {}
        except Exception as e:
            log.warn(f"Failed to load services.yaml: {e}")
            self._static_config = {}

    def resolve(self, user_input: str, explicit_namespace: Optional[str] = None) -> Optional[K8sWorkload]:
        """
        Resolve service name through 4-step process.
        
        Args:
            user_input: Service name to resolve
            explicit_namespace: Optional namespace override
            
        Returns:
            K8sWorkload if found, None otherwise
        """
        if not user_input or not user_input.strip():
            return None

        user_input = user_input.strip().lower()

        # Check cache first
        if user_input in self._cache:
            return self._cache[user_input]

        # Step 1: Static config lookup
        result = self._step1_static_config(user_input, explicit_namespace)
        if result:
            self._cache[user_input] = result
            return result

        # Step 2: Fuzzy name match in snapshot
        result = self._step2_fuzzy_match(user_input)
        if result:
            result = self._step4_confirm(user_input, result)
            if result:
                self._cache[user_input] = result
            return result

        # Step 3: Interactive selection
        result = self._step3_interactive(explicit_namespace)
        if result:
            result = self._step4_confirm(user_input, result)
            if result:
                self._cache[user_input] = result
            return result

        return None

    def _step1_static_config(self, user_input: str, explicit_namespace: Optional[str]) -> Optional[K8sWorkload]:
        """
        Step 1: Check services.yaml for exact or close match.
        
        If found and has kubernetes.deployment: look up in snapshot.
        """
        # Try exact match
        if user_input in self._static_config:
            config = self._static_config[user_input]
            return self._lookup_from_config(config, explicit_namespace)

        # Try partial match
        for svc_name, config in self._static_config.items():
            if user_input in svc_name.lower() or svc_name.lower() in user_input:
                return self._lookup_from_config(config, explicit_namespace)

        return None

    def _lookup_from_config(self, config: dict, explicit_namespace: Optional[str]) -> Optional[K8sWorkload]:
        """Look up workload in snapshot from services.yaml config."""
        k8s_cfg = config.get("kubernetes", {})
        if not k8s_cfg:
            return None

        ns = explicit_namespace or k8s_cfg.get("namespace", "default")
        deployment_name = k8s_cfg.get("deployment")

        if not deployment_name:
            return None

        # Find workload in snapshot
        for workload in self.snapshot.pods:  # Note: workloads not pods
            if (
                workload.namespace == ns
                and (workload.name == deployment_name or workload.name.startswith(deployment_name))
            ):
                return workload

        return None

    def _step2_fuzzy_match(self, user_input: str) -> Optional[K8sWorkload]:
        """
        Step 2: Fuzzy name matching in snapshot.
        
        Score workloads by:
        - Partial ratio with workload name
        - Partial ratio with service object name
        - Pod label matching (boost by 20)
        """
        try:
            from thefuzz import fuzz
        except ImportError:
            log.warn("thefuzz not installed, skipping fuzzy matching")
            return None

        best_score = 0
        best_workload = None

        for workload in self.snapshot.pods:
            score = 0

            # Score workload name
            score = max(score, fuzz.partial_ratio(user_input, workload.name.lower()))

            # Score service object name
            if workload.namespace:
                score = max(score, fuzz.partial_ratio(user_input, workload.namespace.lower()))

            # Check pod labels for app=*
            for pod in workload.pods if hasattr(workload, 'pods') else []:
                # Pod labels would be in metadata, but we don't have direct access
                # For now, check pod name
                if user_input in pod.name.lower():
                    score += 20

            if score >= 70 and score > best_score:
                best_score = score
                best_workload = workload

        return best_workload if best_score >= 70 else None

    def _step3_interactive(self, explicit_namespace: Optional[str]) -> Optional[K8sWorkload]:
        """
        Step 3: Interactive namespace and workload selection.
        
        List non-protected namespaces, let user pick.
        Then list workloads in that namespace, let user pick.
        """
        # Get safe (non-protected) namespaces
        safe_ns = self.guard.get_safe_namespaces(self.snapshot.namespaces)

        if not safe_ns:
            console.print("[yellow]No accessible namespaces found.[/yellow]")
            return None

        # Auto-select if only one namespace
        if len(safe_ns) == 1:
            ns = safe_ns[0]
            console.print(f"[dim]Auto-selected namespace: {ns}[/dim]")
        else:
            # Show namespace table
            table = Table(title="Available Namespaces", box=box.ROUNDED)
            table.add_column("Namespace", style="bold cyan")
            table.add_column("Pod Count", justify="right")

            for n in safe_ns:
                pod_count = len([p for p in self.snapshot.pods if p.namespace == n])
                table.add_row(n, str(pod_count))

            console.print(table)

            # Prompt for selection
            try:
                selection = console.input("Select namespace (name or number): ").strip()
                if not selection:
                    return None
                if selection.isdigit():
                    idx = int(selection)
                    if 0 <= idx < len(safe_ns):
                        ns = safe_ns[idx]
                    else:
                        console.print("[red]Invalid selection.[/red]")
                        return None
                else:
                    # Match by name
                    matches = [n for n in safe_ns if selection.lower() in n.lower()]
                    if not matches:
                        console.print("[red]No matching namespace.[/red]")
                        return None
                    ns = matches[0]
            except KeyboardInterrupt:
                console.print()
                return None

        # List workloads in namespace
        workloads_in_ns = [p for p in self.snapshot.pods if p.namespace == ns]
        if not workloads_in_ns:
            console.print(f"[yellow]No workloads in namespace {ns}.[/yellow]")
            return None

        # Show workloads table
        table = Table(title=f"Workloads in {ns}", box=box.ROUNDED)
        table.add_column("#", justify="right", style="dim")
        table.add_column("Workload Name", style="bold cyan")
        table.add_column("Kind", style="magenta")
        table.add_column("Pods Ready", justify="right")

        for idx, wl in enumerate(workloads_in_ns):
            kind = getattr(wl, "kind", "Pod")
            ready_count = len([p for p in wl.pods if p.ready]) if hasattr(wl, 'pods') else "?"
            table.add_row(str(idx), wl.name, kind, str(ready_count))

        console.print(table)

        # Prompt for workload selection
        try:
            selection = console.input("Select workload (name or number): ").strip()
            if not selection:
                return None
            if selection.isdigit():
                idx = int(selection)
                if 0 <= idx < len(workloads_in_ns):
                    return workloads_in_ns[idx]
                else:
                    console.print("[red]Invalid selection.[/red]")
                    return None
            else:
                # Match by name
                matches = [wl for wl in workloads_in_ns if selection.lower() in wl.name.lower()]
                if not matches:
                    console.print("[red]No matching workload.[/red]")
                    return None
                return matches[0]
        except KeyboardInterrupt:
            console.print()
            return None

    def _step4_confirm(self, user_input: str, workload: K8sWorkload) -> Optional[K8sWorkload]:
        """
        Step 4: User confirmation.
        
        If user_input does not exactly match workload name, ask for confirmation.
        """
        if user_input == workload.name.lower():
            return workload

        # Ask for confirmation
        try:
            ans = console.input(
                f"[yellow]Did you mean '[bold]{workload.name}[/bold]' "
                f"in namespace '[bold]{workload.namespace}[/bold]'? [Y/n]: [/yellow]"
            ).strip().lower()
            if ans in ("n", "no"):
                console.print("[dim]Analysis cancelled.[/dim]")
                return None
            return workload
        except KeyboardInterrupt:
            console.print()
            return None

    def resolve_all(self) -> List[K8sWorkload]:
        """Get all workloads across non-protected namespaces."""
        safe_ns = self.guard.get_safe_namespaces(self.snapshot.namespaces)
        return [p for p in self.snapshot.pods if p.namespace in safe_ns]
