from __future__ import annotations

from pathlib import Path
from typing import List
import yaml

from core.logger import get_logger
from rich.console import Console
from rich.panel import Panel

log = get_logger("k8s_namespace_guard")
console = Console()


class NamespaceGuard:
    def __init__(self, config_path: str = "protected_namespaces.yaml"):
        self._protected: List[str] = []
        self._config_path = Path(config_path)
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    protected = data.get("protected", []) if isinstance(data, dict) else []
                    self._protected = [p.lower() for p in protected if isinstance(p, str)]
                log.debug(f"Loaded {len(self._protected)} protected namespaces from {self._config_path}")
            except Exception as exc:
                log.warn(f"Failed to load protected namespaces from {self._config_path}: {exc}")
                self._protected = ["kube-system", "kube-public", "kube-node-lease"]
        else:
            log.warn(f"Protected namespaces config not found at {self._config_path}; using fallback list")
            self._protected = ["kube-system", "kube-public", "kube-node-lease"]

    def is_protected(self, namespace: str) -> bool:
        if not namespace:
            return False
        return namespace.lower() in set(self._protected)

    def assert_safe(self, namespace: str, explicit: bool = False) -> bool:
        if not self.is_protected(namespace):
            return True

        log.warn(f"Namespace '{namespace}' is protected. It will not be analysed automatically.")
        if not explicit:
            return False

        # explicit=True : ask for confirmation and only allow read-only analysis
        panel_text = (
            f"⚠️  Protected Namespace: {namespace}\n\n"
            "This namespace contains cluster control-plane components.\n"
            "Only READ-ONLY analysis will be performed. No changes will be made.\n\n"
            "Confirm to proceed with READ-ONLY analysis? [y/N]: "
        )
        console.print(Panel(panel_text, title="Protected Namespace", expand=False))
        try:
            resp = input().strip().lower()
            return resp in ("y", "yes")
        except Exception:
            return False

    def get_safe_namespaces(self, candidates: List[str]) -> List[str]:
        return [ns for ns in (candidates or []) if not self.is_protected(ns)]
