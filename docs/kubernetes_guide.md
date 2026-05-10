# Kubernetes Guide

## Prerequisites

```bash
source jarvis/Scripts/activate
pip install -r requirements.txt
minikube status
kubectl get nodes
```

## Enable Kubernetes source mode

```bash
export SOURCE_KUBERNETES=true
export SOURCE_NAMESPACE=default
export KUBE_NAMESPACES=default
```

Optional collection toggles:

```bash
export K8S_COLLECT_PODS=true
export K8S_COLLECT_DEPLOYMENTS=true
export K8S_COLLECT_EVENTS=true
export K8S_COLLECT_LOGS=true
export K8S_COLLECT_NODES=true
export K8S_COLLECT_PVC=true
export K8S_COLLECT_QUOTAS=true
export K8S_COLLECT_NETWORK_POLICIES=true
export K8S_COLLECT_CONFIGMAPS=true
export K8S_COLLECT_SECRETS_META=true
```

## CLI commands

```bash
python main.py k8s status
python main.py k8s pods --namespace default
python main.py k8s deployments --namespace default
python main.py k8s events --namespace default
python main.py k8s logs <pod-name> --namespace default --tail 50
python main.py k8s rca payment-service
python main.py k8s rca all
python main.py k8s rca all --json
```

## Interactive shell

```bash
python ai_sre.py
/k8s status
/k8s pods default
/k8s rca payment-service
/k8s rca all
```

## Simulation for demo

```bash
export K8S_ENABLE_SIMULATION=true
python main.py k8s simulate crash_loop payment-service --namespace default
python main.py k8s rollback crash_loop
```

All simulation operations ask for explicit terminal confirmation.

## Expected RCA shape

```text
SERVICE: paymentservice
STATUS: Failed

ROOT CAUSE:
Pod entered CrashLoopBackOff

EVIDENCE:
* Restart count exceeded threshold
* Readiness probe failed
* Kubernetes event detected

RECOMMENDATION:
Check container startup configuration and dependency connectivity
```

## Troubleshooting

- If Kubernetes is unavailable, verify kubeconfig and context: `kubectl config current-context`
- If no findings are produced, check namespace values in `KUBE_NAMESPACES`
- If simulation is blocked, ensure `K8S_ENABLE_SIMULATION=true`
