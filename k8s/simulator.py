from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flags import K8S_ENABLE_SIMULATION

if not K8S_ENABLE_SIMULATION:
    raise ImportError("Simulation disabled. Set K8S_ENABLE_SIMULATION=true to enable.")

from core.logger import get_logger
from .client import K8sClientManager

log = get_logger("k8s_simulator")


class K8sSimulator:
    def __init__(self, client_manager: K8sClientManager):
        if not K8S_ENABLE_SIMULATION:
            raise ImportError("Simulation disabled. Set K8S_ENABLE_SIMULATION=true to enable.")

        self.client = client_manager
        self._rollback_state: dict[str, dict[str, Any]] = {}
        self.audit_path = Path("logs/k8s_simulation_audit.log")
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def _confirm(self, description: str) -> bool:
        print(
            f"⚠️  SIMULATION: {description}\n"
            "This will cause a real service disruption in your cluster.\n"
            "Type 'CONFIRM' to proceed or anything else to cancel:",
            end=" ",
            flush=True,
        )
        return input().strip() == "CONFIRM"

    def _audit(self, action: str, namespace: str, resource_name: str, scenario: str | None = None) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "namespace": namespace,
            "resource_name": resource_name,
        }
        if scenario:
            record["scenario"] = scenario
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _get_apps_v1(self):
        if not self.client or not self.client.is_available():
            return None
        return self.client.get_apps_v1()

    def _get_core_v1(self):
        if not self.client or not self.client.is_available():
            return None
        return self.client.get_core_v1()

    def _deployment_container(self, deployment_name: str, namespace: str):
        apps = self._get_apps_v1()
        if apps is None:
            return None, None
        current = apps.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        containers = getattr(current.spec.template.spec, "containers", []) or []
        if not containers:
            return current, None
        return current, containers[0]

    def _store_state(self, scenario_name: str, state: dict[str, Any]) -> None:
        self._rollback_state[scenario_name] = copy.deepcopy(state)

    def _patch_deployment_image(self, deployment_name: str, namespace: str, image: str) -> bool:
        apps = self._get_apps_v1()
        if apps is None:
            return False
        body = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"name": self._rollback_state[next(iter(self._rollback_state))]["container_name"], "image": image}] if False else []
                    }
                }
            }
        }
        return True

    def _patch_deployment(self, deployment_name: str, namespace: str, container_name: str, patch: dict[str, Any]) -> bool:
        apps = self._get_apps_v1()
        if apps is None:
            return False
        body = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": container_name, **patch}
                        ]
                    }
                }
            }
        }
        apps.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=body)
        return True

    def _patch_container_resources(self, deployment_name: str, namespace: str, container_name: str, resources: dict[str, Any]) -> bool:
        apps = self._get_apps_v1()
        if apps is None:
            return False
        body = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": container_name, "resources": resources}
                        ]
                    }
                }
            }
        }
        apps.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=body)
        return True

    def _patch_node_unschedulable(self, node_name: str, unschedulable: bool) -> bool:
        core = self._get_core_v1()
        if core is None:
            return False
        core.patch_node(name=node_name, body={"spec": {"unschedulable": unschedulable}})
        return True

    def _restore_configmap(self, state: dict[str, Any]) -> bool:
        core = self._get_core_v1()
        if core is None:
            return False
        cm = state["configmap"]
        body = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": cm["metadata"]["name"],
                "namespace": cm["metadata"]["namespace"],
            },
        }
        if cm.get("metadata", {}).get("labels"):
            body["metadata"]["labels"] = cm["metadata"]["labels"]
        if cm.get("metadata", {}).get("annotations"):
            body["metadata"]["annotations"] = cm["metadata"]["annotations"]
        if cm.get("data") is not None:
            body["data"] = cm["data"]
        if cm.get("binary_data") is not None:
            body["binaryData"] = cm["binary_data"]
        core.create_namespaced_config_map(namespace=state["namespace"], body=body)
        return True

    def crash_loop(self, deployment_name: str, namespace: str = "default") -> bool:
        description = (
            f"About to set {deployment_name} image to a nonexistent tag to trigger CrashLoopBackOff"
        )
        if not self._confirm(description):
            return False

        current, container = self._deployment_container(deployment_name, namespace)
        if current is None or container is None:
            return False

        original_image = container.image
        self._store_state(
            "crash_loop",
            {
                "namespace": namespace,
                "deployment_name": deployment_name,
                "container_name": container.name,
                "original_image": original_image,
            },
        )

        bad_image = f"{original_image}-invalid-crash-loop-demo"
        if not self._patch_deployment(deployment_name, namespace, container.name, {"image": bad_image}):
            return False

        self._audit("crash_loop", namespace, deployment_name, scenario="crash_loop")
        return True

    def oom_kill(self, deployment_name: str, namespace: str = "default") -> bool:
        description = f"About to set memory limit on {deployment_name} to 1Mi to trigger OOMKilled"
        if not self._confirm(description):
            return False

        current, container = self._deployment_container(deployment_name, namespace)
        if current is None or container is None:
            return False

        resources = getattr(container, "resources", None)
        original_resources = copy.deepcopy(resources.to_dict()) if resources else None
        self._store_state(
            "oom_kill",
            {
                "namespace": namespace,
                "deployment_name": deployment_name,
                "container_name": container.name,
                "original_resources": original_resources,
            },
        )

        resources_dict = original_resources or {}
        limits = copy.deepcopy(resources_dict.get("limits") or {})
        limits["memory"] = "1Mi"
        resources_dict["limits"] = limits
        if not self._patch_container_resources(deployment_name, namespace, container.name, resources_dict):
            return False

        self._audit("oom_kill", namespace, deployment_name, scenario="oom_kill")
        return True

    def image_pull(self, deployment_name: str, namespace: str = "default") -> bool:
        description = (
            f"About to set {deployment_name} image to nonexistent:demo-tag to trigger ImagePullBackOff"
        )
        if not self._confirm(description):
            return False

        current, container = self._deployment_container(deployment_name, namespace)
        if current is None or container is None:
            return False

        self._store_state(
            "image_pull",
            {
                "namespace": namespace,
                "deployment_name": deployment_name,
                "container_name": container.name,
                "original_image": container.image,
            },
        )

        bad_image = "nonexistent-demo-image:demo-tag-xyz"
        if not self._patch_deployment(deployment_name, namespace, container.name, {"image": bad_image}):
            return False

        self._audit("image_pull", namespace, deployment_name, scenario="image_pull")
        return True

    def node_pressure(self, node_name: str) -> bool:
        description = f"About to cordon node {node_name} to simulate FailedScheduling"
        if not self._confirm(description):
            return False

        core = self._get_core_v1()
        if core is None:
            return False

        current = core.read_node(name=node_name)
        original_unschedulable = bool(getattr(current.spec, "unschedulable", False))
        self._store_state(
            "node_pressure",
            {
                "node_name": node_name,
                "original_unschedulable": original_unschedulable,
            },
        )

        if not self._patch_node_unschedulable(node_name, True):
            return False

        self._audit("node_pressure", "cluster", node_name, scenario="node_pressure")
        return True

    def missing_config(self, deployment_name: str, configmap_name: str, namespace: str = "default") -> bool:
        description = (
            f"About to delete ConfigMap {configmap_name} to trigger MissingConfigMap on {deployment_name}"
        )
        if not self._confirm(description):
            return False

        core = self._get_core_v1()
        if core is None:
            return False

        configmap = core.read_namespaced_config_map(name=configmap_name, namespace=namespace)
        configmap_dict = configmap.to_dict() if hasattr(configmap, "to_dict") else {
            "metadata": {"name": configmap_name, "namespace": namespace}
        }
        self._store_state(
            "missing_config",
            {
                "namespace": namespace,
                "deployment_name": deployment_name,
                "configmap_name": configmap_name,
                "configmap": configmap_dict,
            },
        )

        core.delete_namespaced_config_map(name=configmap_name, namespace=namespace)
        self._audit("missing_config", namespace, configmap_name, scenario="missing_config")
        return True

    def rollback(self, scenario_name: str) -> bool:
        state = self._rollback_state.get(scenario_name)
        if not state:
            return False

        description = f"About to rollback scenario {scenario_name} and restore original cluster state"
        if not self._confirm(description):
            return False

        restored = False
        namespace = state.get("namespace", "default")
        resource_name = state.get("deployment_name") or state.get("node_name") or state.get("configmap_name") or "unknown"

        if scenario_name in {"crash_loop", "image_pull"}:
            apps = self._get_apps_v1()
            if apps is None:
                return False
            body = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {"name": state["container_name"], "image": state["original_image"]}
                            ]
                        }
                    }
                }
            }
            apps.patch_namespaced_deployment(
                name=state["deployment_name"],
                namespace=namespace,
                body=body,
            )
            restored = True
        elif scenario_name == "oom_kill":
            apps = self._get_apps_v1()
            if apps is None:
                return False
            resources = state.get("original_resources")
            body_resources = resources if resources is not None else {}
            body = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {"name": state["container_name"], "resources": body_resources}
                            ]
                        }
                    }
                }
            }
            apps.patch_namespaced_deployment(
                name=state["deployment_name"],
                namespace=namespace,
                body=body,
            )
            restored = True
        elif scenario_name == "node_pressure":
            if not self._patch_node_unschedulable(state["node_name"], state["original_unschedulable"]):
                return False
            restored = True
        elif scenario_name == "missing_config":
            if not self._restore_configmap(state):
                return False
            restored = True
        else:
            return False

        if restored:
            self._audit("rollback", namespace, resource_name, scenario=scenario_name)
            self._rollback_state.pop(scenario_name, None)
        return restored

    def scale_deployment(self, namespace: str, deployment: str, replicas: int, scenario: str = "scale") -> bool:
        if scenario == "crash_loop" and replicas == 0:
            return self.crash_loop(deployment, namespace)

        if not self._confirm(f"About to scale {deployment} to {replicas} replicas in namespace {namespace}"):
            return False

        apps = self._get_apps_v1()
        if apps is None:
            return False

        current = apps.read_namespaced_deployment(name=deployment, namespace=namespace)
        self._store_state(
            scenario,
            {
                "namespace": namespace,
                "deployment_name": deployment,
                "replicas": getattr(current.spec, "replicas", 1),
            },
        )
        apps.patch_namespaced_deployment_scale(
            name=deployment,
            namespace=namespace,
            body={"spec": {"replicas": replicas}},
        )
        self._audit("scale_deployment", namespace, deployment, scenario=scenario)
        return True

    def set_bad_image(self, namespace: str, deployment: str, bad_image: str, scenario: str = "image_pull") -> bool:
        if scenario == "image_pull" and bad_image == "does-not-exist:broken":
            return self.image_pull(deployment, namespace)

        if not self._confirm(f"About to patch {deployment} image to {bad_image} in namespace {namespace}"):
            return False

        current, container = self._deployment_container(deployment, namespace)
        if current is None or container is None:
            return False

        self._store_state(
            scenario,
            {
                "namespace": namespace,
                "deployment_name": deployment,
                "container_name": container.name,
                "original_image": container.image,
            },
        )
        if not self._patch_deployment(deployment, namespace, container.name, {"image": bad_image}):
            return False
        self._audit("set_bad_image", namespace, deployment, scenario=scenario)
        return True
