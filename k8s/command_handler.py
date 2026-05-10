from __future__ import annotations

from core.logger import get_logger
from flags import K8S_ENABLE_SIMULATION
from .client import K8sClientManager
from .collector import K8sCollector
from .rca_engine import K8sRCAEngine

log = get_logger("k8s_command_handler")


class K8sCommandHandler:
    def __init__(self):
        self.client = K8sClientManager()
        self.collector = K8sCollector(self.client)

        # Wire engine dependencies (required by K8sRCAEngine.__init__)
        from k8s.event_analyzer import K8sEventAnalyzer
        from k8s.service_resolver import K8sServiceResolver
        from core.llm_analyzer import LLMAnalyzer

        snapshot = self.collector.collect_all(["default"])
        analyzer = K8sEventAnalyzer()
        resolver = K8sServiceResolver(snapshot)
        llm_analyzer = LLMAnalyzer()

        self.engine = K8sRCAEngine(
            analyzer=analyzer,
            resolver=resolver,
            llm_analyzer=llm_analyzer,
        )
        self.simulator = None
        if K8S_ENABLE_SIMULATION:
            from .simulator import K8sSimulator

            self.simulator = K8sSimulator(self.client)

    def status(self):
        info = self.client.get_cluster_info()
        if not info.get("available"):
            print("Kubernetes unavailable")
            if info.get("error"):
                print(f"Reason: {info['error']}")
            return

        namespaces = self.client.get_namespaces()
        snapshot = self.collector.collect_all(namespaces or ["default"])
        print(f"Cluster available: {info['available']}")
        print(f"Namespaces: {', '.join(snapshot.namespaces)}")
        print(f"Pods: {len(snapshot.pods)}")
        print(f"Deployments: {len(snapshot.deployments)}")
        print(f"Events: {len(snapshot.events)}")
        print(f"Nodes: {len(snapshot.nodes)}")
        print(f"PVCs: {len(snapshot.pvcs)}")
        print(f"Quotas: {len(snapshot.quotas)}")

    def pods(self, namespace: str):
        for pod in self.collector.collect_pods(namespace):
            print(f"{pod.name}\t{pod.phase}\tready={pod.ready}\trestarts={pod.restart_count}")

    def deployments(self, namespace: str):
        for dep in self.collector.collect_deployments(namespace):
            print(
                f"{dep.name}\tready={dep.replicas_ready}/{dep.replicas_desired}\t"
                f"updated={dep.replicas_updated}\tavailable={dep.replicas_available}"
            )

    def events(self, namespace: str):
        for evt in self.collector.collect_events(namespace):
            if evt.type == "Warning":
                print(f"[{evt.reason}] {evt.message}")

    def logs(self, pod: str, namespace: str, tail: int = 50):
        for line in self.collector.collect_pod_logs(pod, namespace, tail=tail):
            print(line)

    def rca(self, service: str, namespaces: list[str]):
        snapshot = self.collector.collect_all(namespaces)
        if service == "all":
            return self.engine.generate_rca_for_all(snapshot)
        return [self.engine.generate_rca(service, snapshot)]

    def simulate(self, scenario: str, namespace: str, service: str):
        if not K8S_ENABLE_SIMULATION:
            print("Simulation disabled. Set K8S_ENABLE_SIMULATION=true to enable.")
            return False

        if self.simulator is None:
            from .simulator import K8sSimulator

            self.simulator = K8sSimulator(self.client)

        if scenario == "crash_loop":
            return self.simulator.scale_deployment(namespace, service, 0, scenario="crash_loop")
        if scenario == "image_pull":
            return self.simulator.set_bad_image(namespace, service, "does-not-exist:broken", scenario="image_pull")
        print(f"Unsupported scenario: {scenario}")
        return False

    def rollback(self, scenario: str):
        if not K8S_ENABLE_SIMULATION:
            print("Simulation disabled. Set K8S_ENABLE_SIMULATION=true to enable.")
            return False
        if self.simulator is None:
            from .simulator import K8sSimulator

            self.simulator = K8sSimulator(self.client)
        return self.simulator.rollback(scenario)
