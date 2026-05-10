from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.table import Table
from rich.console import Console

from core.logger import get_logger
from .models import K8sClusterSnapshot

log = get_logger("k8s_graph_updater")
console = Console()


class K8sGraphUpdater:
    """
    Updates ServiceGraph based on Kubernetes cluster topology.
    Proposes changes and waits for user approval via interactive prompt.
    """

    def __init__(self, service_graph, snapshot: K8sClusterSnapshot):
        """
        Initialize with existing ServiceGraph and K8sClusterSnapshot.
        
        Args:
            service_graph: Existing ServiceGraph object
            snapshot: K8sClusterSnapshot from cluster
        """
        self.service_graph = service_graph
        self.snapshot = snapshot
        self.proposal_log = Path("logs/k8s_graph_proposals.log")

    def compute_proposed_changes(self) -> list[dict]:
        """
        Analyse snapshot to find new services and dependencies.
        
        Returns: List of change dicts:
            - {"type": "add_service", "details": str}
            - {"type": "add_dependency", "details": str}
        """
        changes = []
        existing_services = set(self.service_graph.get_all_service_names())

        # Find new services discovered in cluster
        discovered_deployment_names = {d.name for d in self.snapshot.deployments}
        for deploy_name in discovered_deployment_names:
            # Check if this deployment is already in the service graph
            found = False
            for svc_name in existing_services:
                k8s_cfg = self.service_graph.services.get(svc_name, {}).get("kubernetes", {})
                if k8s_cfg.get("deployment") == deploy_name:
                    found = True
                    break
            
            if not found:
                changes.append({
                    "type": "add_service",
                    "details": f"New deployment discovered: {deploy_name}"
                })

        # Find new pod↔deployment relationships (would be captured by add_service)
        # and cross-namespace dependencies
        namespaces_in_snapshot = set(d.namespace for d in self.snapshot.deployments)
        
        # Check for services that reference deployments in different namespaces
        for svc_name, svc_cfg in self.service_graph.services.items():
            k8s_cfg = svc_cfg.get("kubernetes", {})
            if k8s_cfg:
                svc_namespace = k8s_cfg.get("namespace")
                svc_deployment = k8s_cfg.get("deployment")
                
                # Find pods for this service in the snapshot
                svc_pods = [
                    p for p in self.snapshot.pods
                    if svc_namespace == p.namespace and svc_deployment in p.name
                ]
                
                # Check dependencies for cross-namespace refs
                for dep_svc in svc_cfg.get("depends_on", []):
                    dep_k8s_cfg = self.service_graph.services.get(dep_svc, {}).get("kubernetes", {})
                    if dep_k8s_cfg:
                        dep_namespace = dep_k8s_cfg.get("namespace")
                        if dep_namespace and dep_namespace != svc_namespace:
                            changes.append({
                                "type": "cross_namespace_dependency",
                                "details": f"{svc_name} ({svc_namespace}) → {dep_svc} ({dep_namespace})"
                            })

        return changes

    def prompt_and_apply(self) -> bool:
        """
        Show proposed changes and wait for user approval.
        
        Flow:
        1. Call compute_proposed_changes()
        2. If no changes: log "Service graph is up to date" and return True
        3. Print Rich Table showing changes
        4. Print: "Apply these N changes to the service graph? [y/N]: "
        5. Read input from stdin
        6. If "y"/"yes": Apply changes and return True
        7. Else: Save to logs/k8s_graph_proposals.log and return False
        
        Returns: bool - True if changes applied, False otherwise
        """
        changes = self.compute_proposed_changes()

        if not changes:
            log.info("Service graph is up to date")
            return True

        # Print Rich table
        table = Table(title=f"Kubernetes Topology Change Proposals ({len(changes)})")
        table.add_column("Change Type", style="cyan")
        table.add_column("Details", style="white")

        for change in changes:
            change_type = change.get("type", "unknown")
            details = change.get("details", "")
            table.add_row(change_type, details)

        console.print(table)

        # Prompt user
        try:
            response = console.input(f"\nApply these {len(changes)} changes to the service graph? [y/N]: ")
            answer = response.strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer in ["y", "yes"]:
            # Apply changes
            for change in changes:
                if change["type"] == "add_service":
                    # Extract deployment name from details
                    details = change["details"]
                    if ":" in details:
                        deploy_name = details.split(":")[-1].strip()
                        # Add to service graph
                        namespace = "default"
                        for d in self.snapshot.deployments:
                            if d.name == deploy_name:
                                namespace = d.namespace
                                break
                        
                        if deploy_name not in self.service_graph.services:
                            self.service_graph.services[deploy_name] = {
                                "description": f"Auto-discovered from Kubernetes cluster",
                                "namespace": namespace,
                                "port": 8080,
                                "depends_on": [],
                                "exposes_to": [],
                                "containers": [{"name": deploy_name}],
                                "kubernetes": {
                                    "namespace": namespace,
                                    "deployment": deploy_name,
                                    "selector": {"app": deploy_name},
                                    "container_name": deploy_name,
                                    "expected_replicas": 1,
                                },
                                "dependency_confidence": "discovered_k8s",
                            }

            self.service_graph._save()
            log.info(f"Service graph updated with {len(changes)} changes")
            return True
        else:
            # Save proposals to log
            self._save_proposals(changes)
            log.info(f"Service graph update declined. Changes saved to {self.proposal_log}")
            return False

    def _save_proposals(self, proposals: list[dict]):
        """Save proposed changes to log file for future reference"""
        self.proposal_log.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.proposal_log.open("a", encoding="utf-8") as f:
                timestamp = datetime.utcnow().isoformat()
                entry = {
                    "timestamp": timestamp,
                    "proposals": proposals
                }
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            log.error(f"Failed to save proposals: {exc}")

