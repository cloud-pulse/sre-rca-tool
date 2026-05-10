from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.logger import get_logger

log = get_logger("k8s_client")


class K8sClientManager:
    _instance: "K8sClientManager | None" = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "K8sClientManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, namespaces: list[str] | None = None, kubeconfig_path: str | None = None, context: str | None = None):
        if self._initialized:
            return

        self._initialized = True
        self._available = False
        self._config_error = ""
        self._namespaces = namespaces or []
        self._kubeconfig_path = kubeconfig_path or os.getenv("KUBECONFIG")
        self._context = context or os.getenv("KUBE_CONTEXT")

        self._core_v1 = None
        self._apps_v1 = None
        self._networking_v1 = None

        try:
            from kubernetes import client, config
            from kubernetes.config.config_exception import ConfigException

            if self._kubeconfig_path:
                config.load_kube_config(
                    config_file=self._kubeconfig_path,
                    context=self._context,
                )
            else:
                default_path = Path.home() / ".kube" / "config"
                if default_path.exists():
                    config.load_kube_config(
                        config_file=str(default_path),
                        context=self._context,
                    )
                    self._kubeconfig_path = str(default_path)
                else:
                    config.load_kube_config(context=self._context)

            self._core_v1 = client.CoreV1Api()
            self._apps_v1 = client.AppsV1Api()
            self._networking_v1 = client.NetworkingV1Api()

            self._core_v1.get_api_resources(_request_timeout=10)
            self._available = True
            log.info("[dim]Kubernetes SDK client initialized[/dim]")
        except Exception as exc:  # broad for robust fallback
            self._available = False
            self._config_error = str(exc)
            if "ConfigException" in type(exc).__name__:
                log.warn(f"Kubernetes config unavailable: {exc}")
            else:
                log.warn(f"Kubernetes client unavailable: {exc}")

    def is_available(self) -> bool:
        return self._available

    def get_core_v1(self):
        if not self.is_available():
            return None
        return self._core_v1

    def get_apps_v1(self):
        if not self.is_available():
            return None
        return self._apps_v1

    def get_networking_v1(self):
        if not self.is_available():
            return None
        return self._networking_v1

    def get_namespaces(self) -> list[str]:
        if not self._available:
            return []
        try:
            response = self._core_v1.list_namespace(_request_timeout=30)
            return [item.metadata.name for item in response.items]
        except Exception as exc:
            log.warn(f"Failed to list namespaces: {exc}")
            return []

    def get_cluster_info(self) -> dict:
        if not self.is_available():
            return {}
        return {
            "context": self._context,
            "kubeconfig_path": self._kubeconfig_path,
            "namespaces": self._namespaces,
        }
