from __future__ import annotations

from typing import Dict
import yaml

from core.logger import get_logger
from .models import K8sClusterSnapshot, K8sPod

log = get_logger("k8s_service_mapper")


class K8sServiceMapper:
    """
    Maps Kubernetes cluster resources to services defined in services.yaml.
    
    Resolution order (strict — do not skip steps):
    1. Check self._config[service_name].get("kubernetes", {}) for explicit deployment name and namespace
    2. If step 1 fails: scan snapshot.deployments for name containing service_name (case-insensitive)
    3. If step 2 fails: return None and log a warning
    """

    def __init__(self, snapshot: K8sClusterSnapshot, services_yaml_path: str = "services.yaml"):
        self.snapshot = snapshot
        self.services_yaml_path = services_yaml_path
        self._config = {}
        self._load_config()

    def _load_config(self):
        """Load services.yaml into self._config"""
        try:
            with open(self.services_yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if data and 'services' in data:
                    self._config = data['services']
                else:
                    self._config = {}
            log.debug(f"Loaded {len(self._config)} services from {self.services_yaml_path}")
        except FileNotFoundError:
            log.debug(f"services.yaml not found at {self.services_yaml_path}")
            self._config = {}
        except Exception as exc:
            log.warn(f"Failed to load services.yaml: {exc}")
            self._config = {}

    def resolve(self, service_name: str) -> dict | None:
        """
        Resolve a service to its Kubernetes deployment and pods.
        
        Returns: {"deployment": str, "pods": List[K8sPod], "namespace": str} or None
        
        Resolution order (strict):
        1. Check self._config[service_name].get("kubernetes", {}) for explicit deployment name and namespace
        2. If step 1 fails: scan snapshot.deployments for name containing service_name (case-insensitive)
        3. If step 2 fails: return None and log a warning
        """
        # Step 1: Check for explicit deployment name and namespace in services.yaml kubernetes: section
        if service_name in self._config:
            service_config = self._config[service_name]
            k8s_config = service_config.get("kubernetes", {})

            if k8s_config:
                namespace = k8s_config.get("namespace")
                deployment_name = k8s_config.get("deployment")

                if namespace and deployment_name:
                    # Look up matching deployment and pods in snapshot
                    for deploy in self.snapshot.deployments:
                        if deploy.namespace == namespace and deploy.name == deployment_name:
                            # Find pods for this deployment
                            pods = [
                                p for p in self.snapshot.pods
                                if p.namespace == namespace and p.name.startswith(deployment_name)
                            ]
                            log.debug(f"Resolved {service_name} to deployment {deployment_name} ({len(pods)} pods)")
                            return {
                                "deployment": deployment_name,
                                "pods": pods,
                                "namespace": namespace,
                            }

        # Step 2: Scan cluster deployments for name containing service_name (case-insensitive)
        # Handle both hyphenated names (payment-service) and non-hyphenated (paymentservice)
        service_lower = service_name.lower()
        service_normalized = service_name.lower().replace("-", "")  # payment-service -> paymentservice
        
        for deploy in self.snapshot.deployments:
            deploy_lower = deploy.name.lower()
            deploy_normalized = deploy.name.lower().replace("-", "")  # redis-cart -> rediscart
            
            # Check for matches
            if (service_lower in deploy_lower or  # "frontend" in "frontend"
                deploy_lower in service_lower or  # "redis" in "redis-cart"
                service_normalized == deploy_normalized or  # "paymentservice" == "paymentservice"
                service_normalized in deploy_normalized):  # "payment" in "paymentservice"
                
                # Find pods for this deployment
                pods = [
                    p for p in self.snapshot.pods
                    if p.namespace == deploy.namespace and p.name.startswith(deploy.name)
                ]
                log.debug(f"Resolved {service_name} to deployment {deploy.name} (cluster scan) ({len(pods)} pods)")
                return {
                    "deployment": deploy.name,
                    "pods": pods,
                    "namespace": deploy.namespace,
                }

        # Step 3: Not found
        log.warn(f"Could not resolve service '{service_name}' to any deployment")
        return None

    def resolve_all(self) -> Dict[str, dict | None]:
        """
        Resolve all services in services.yaml to cluster resources.
        
        Returns: dict with service names as keys, resolved info (or None) as values
        """
        results = {}
        for service_name in self._config.keys():
            results[service_name] = self.resolve(service_name)
        resolved_count = len([v for v in results.values() if v is not None])
        log.debug(f"Resolved {resolved_count} out of {len(results)} services")
        return results
