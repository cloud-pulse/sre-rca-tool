from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class K8sContainerState:
    name: str
    state: str
    state_reason: str
    restart_count: int
    ready: bool


@dataclass
class K8sPod:
    name: str
    namespace: str
    node_name: str
    image: str
    restart_count: int
    ready: bool
    phase: str
    cpu_usage: str = "N/A"                                         # e.g., "100m", "N/A"
    memory_usage: str = "N/A"                                      # e.g., "512Mi", "N/A"
    cpu_limit: str = "N/A"                                         # e.g., "500m"
    memory_limit: str = "N/A"                                      # e.g., "512Mi"
    container_states: List[K8sContainerState] = field(default_factory=list)
    events: List["K8sEvent"] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    previous_logs: List[str] = field(default_factory=list)


@dataclass
class K8sCondition:
    type: str
    status: str
    reason: str
    message: str
    last_transition_time: str


@dataclass
class K8sDeployment:
    name: str
    namespace: str
    replicas_desired: int
    replicas_ready: int
    replicas_updated: int
    replicas_available: int
    conditions: List[K8sCondition] = field(default_factory=list)


@dataclass
class K8sEvent:
    name: str
    namespace: str
    type: str
    reason: str
    message: str
    first_timestamp: str
    last_timestamp: str
    count: int
    involved_object: Dict


@dataclass
class K8sNode:
    name: str
    ready: bool
    cpu_capacity: str
    memory_capacity: str
    cpu_usage: str = "N/A"                                         # e.g., "1200m", "N/A"
    memory_usage: str = "N/A"                                      # e.g., "2048Mi", "N/A"
    conditions: List[K8sCondition] = field(default_factory=list)
    taints: List[str] = field(default_factory=list)


@dataclass
class K8sPVC:
    name: str
    namespace: str
    status: str
    storage_class: str
    capacity: str
    access_modes: List[str] = field(default_factory=list)


@dataclass
class K8sResourceQuota:
    name: str
    namespace: str
    hard: Dict[str, str] = field(default_factory=dict)
    used: Dict[str, str] = field(default_factory=dict)


@dataclass
class K8sNetworkPolicy:
    name: str
    namespace: str
    pod_selector: Dict
    ingress_rules: List[Dict] = field(default_factory=list)
    egress_rules: List[Dict] = field(default_factory=list)


@dataclass
class K8sServiceObject:
    """Represents a Kubernetes Service (ClusterIP/NodePort/LoadBalancer)"""
    name: str
    namespace: str
    type: str          # ClusterIP | NodePort | LoadBalancer
    cluster_ip: str
    ports: List[Dict] = field(default_factory=list)
    selector: Dict = field(default_factory=dict)


@dataclass
class K8sWorkload:
    """Represents a Deployment or StatefulSet with linked Service and Pods"""
    name: str
    namespace: str
    kind: str                                          # "Deployment" | "StatefulSet"
    replicas_desired: int
    replicas_ready: int
    service_object: "K8sServiceObject | None" = None
    pods: List[K8sPod] = field(default_factory=list)
    conditions: List[K8sCondition] = field(default_factory=list)


@dataclass
class K8sConfigMap:
    name: str
    namespace: str
    keys: List[str] = field(default_factory=list)


@dataclass
class K8sSecretMeta:
    name: str
    namespace: str
    type: str
    keys: List[str] = field(default_factory=list)


@dataclass
class K8sClusterSnapshot:
    timestamp: str
    namespaces: List[str]
    pods: List[K8sPod]
    deployments: List[K8sDeployment]
    events: List[K8sEvent]
    nodes: List[K8sNode]
    pvcs: List[K8sPVC]
    quotas: List[K8sResourceQuota]
    network_policies: List[K8sNetworkPolicy]
    configmaps: List[K8sConfigMap]
    secret_metadata: List[K8sSecretMeta]


@dataclass
class K8sRCAFinding:
    service: str
    namespace: str
    status: str
    severity: str
    root_cause: str
    supporting_causes: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    affected_resources: List[str] = field(default_factory=list)
    kubectl_commands: List[str] = field(default_factory=list)     # Suggested kubectl commands
    llm_narrative: str = ""                                        # LLM-generated RCA narrative
    detected_at: str = ""
