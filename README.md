# sre-rca-tool

AI-assisted SRE RCA tool with optional Kubernetes-native observability and RCA.

## Quick start

```bash
source jarvis/Scripts/activate
pip install -r requirements.txt
python main.py status
```

## Kubernetes mode

The existing source flag remains the switch:

```bash
export SOURCE_KUBERNETES=true
export SOURCE_NAMESPACE=default
export KUBE_NAMESPACES=default
```

Kubernetes commands:

```bash
python main.py k8s status
python main.py k8s pods --namespace default
python main.py k8s deployments --namespace default
python main.py k8s events --namespace default
python main.py k8s logs <pod-name> --namespace default --tail 50
python main.py k8s rca payment-service
python main.py k8s rca all
```

Interactive shell commands:

```bash
python ai_sre.py
/k8s status
/k8s rca all
```

Simulation (guarded):

```bash
export K8S_ENABLE_SIMULATION=true
python main.py k8s simulate crash_loop payment-service --namespace default
python main.py k8s rollback crash_loop
```