import os

PROJ = "c:/playground/sre-rca-tool"

def create_file(path, content):
    full_path = os.path.join(PROJ, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")

# PART 1: Per-service log files
# 30-40 lines each, ISO timestamps, mixed formats
log_api_gateway = """
2026-03-22T10:00:00Z [api-gateway] INFO  Request ID 101: Starting request routing to payment-service
2026-03-22T10:00:00Z [istio-proxy] [api-gateway] mTLS connection established with downstream client
2026-03-22T10:00:01Z [api-gateway] INFO  Request ID 102: Starting request routing to auth-service
{"timestamp": "2026-03-22T10:00:01Z", "level": "INFO", "service": "api-gateway", "message": "auth-service returns 200 OK"}
2026-03-22T10:00:05Z [api-gateway] WARN  High latency observed from payment-service (latency > 2s)
2026-03-22T10:00:10Z [api-gateway] ERROR Request ID 101: 500 Internal Server Error returned from payment-service
2026-03-22T10:00:12Z [api-gateway] WARN  Consecutive 500 errors detected from payment-service
2026-03-22T10:00:15Z [istio-proxy] [api-gateway] Upstream connection reset by peer
{"timestamp": "2026-03-22T10:00:16Z", "level": "ERROR", "service": "api-gateway", "message": "Circuit breaker OPEN for payment-service"}
2026-03-22T10:00:18Z [istio-proxy] [api-gateway] Returning 503 Service Unavailable to client
2026-03-22T10:00:20Z [api-gateway] INFO  Request ID 103: Returning 503 due to open circuit breaker
""" * 3

log_payment_service = """
2026-03-22T10:00:00Z [payment-service] INFO  Processing transaction TRX-001
2026-03-22T10:00:00Z [istio-proxy] [payment-service] Establishing outbound connection to database-service
{"timestamp": "2026-03-22T10:00:02Z", "level": "INFO", "service": "payment-service", "message": "Transaction TRX-001 validated"}
2026-03-22T10:00:05Z [payment-service] WARN  DB connection attempt failing, queue depth growing
2026-03-22T10:00:08Z [payment-service] ERROR Transaction TRX-001 rollbacked due to DB timeout
2026-03-22T10:00:10Z [istio-proxy] [payment-service] Upstream connect error or disconnect/reset before headers
{"timestamp": "2026-03-22T10:00:12Z", "level": "ERROR", "service": "payment-service", "message": "Service degraded state: 5 active DB connections failing"}
2026-03-22T10:00:15Z [payment-service] ERROR Queue depth growing beyond threshold (depth=150)
2026-03-22T10:00:20Z [payment-service] WARN  Dropping new requests to prevent completely crashing
""" * 4

log_database_service = """
2026-03-22T10:00:00Z [database-service] INFO  Normal query serving for user sessions
{"timestamp": "2026-03-22T10:00:01Z", "level": "INFO", "service": "database-service", "message": "Connection pool at 50% capacity"}
2026-03-22T10:00:03Z [database-service] WARN  Connection pool filling up quickly
2026-03-22T10:00:05Z [database-service] WARN  Slow queries under load detected (>1000ms execution)
2026-03-22T10:00:08Z [database-service] ERROR FATAL: Pool exhaustion errors - no free connections available
2026-03-22T10:00:10Z [database-service] ERROR rejecting new connections
{"timestamp": "2026-03-22T10:00:15Z", "level": "FATAL", "service": "database-service", "message": "Memory limit reached, impending OOM"}
2026-03-22T10:00:16Z [system] OOMKilled event triggered by node 
2026-03-22T10:00:25Z [system] Pod restart initiated 
2026-03-22T10:00:30Z [database-service] INFO  Recovery attempts starting, warming up buffer pool
""" * 4

log_auth_service = """
2026-03-22T10:00:00Z [auth-service] INFO  Mostly healthy operation, token validation OK
{"timestamp": "2026-03-22T10:00:01Z", "level": "INFO", "service": "auth-service", "message": "Health checks passing"}
2026-03-22T10:00:02Z [istio-proxy] [auth-service] Normal traffic flowing
2026-03-22T10:00:05Z [auth-service] INFO  Validating token for user 10293
2026-03-22T10:00:08Z [auth-service] WARN  One warning about increased load from api-gateway
2026-03-22T10:00:10Z [auth-service] INFO  Slightly elevated latency observed parsing JWTs (20ms)
{"timestamp": "2026-03-22T10:00:15Z", "level": "INFO", "service": "auth-service", "message": "Health checks passing"}
2026-03-22T10:00:18Z [auth-service] INFO  Continuing mostly healthy operation
2026-03-22T10:00:20Z [istio-proxy] [auth-service] Normal traffic flowing
""" * 4

# PART 2: Mock kubectl describe
desc_conn_pool = """
Name:             database-service-84d7fcb6f-pxkgp
Namespace:        default
Node:             ip-10-0-1-12/10.0.1.12
Labels:           app=database-service
Annotations:      kubernetes.io/psp: eks.privileged
Status:           Running
IP:               10.0.1.55
Containers:
  app:
    Container ID:   docker://abcdef123456
    Image:          myrepo/database-service:v1.0
    Image ID:       docker-pullable://myrepo/database-service@sha256:123
    Port:           5432/TCP
    State:          Waiting
      Reason:       CrashLoopBackOff
    Last State:     Terminated
      Reason:       Error
      Exit Code:    1
    Ready:          False
    Restart Count:  5
    Limits:
      cpu:          1000m
      memory:       512Mi
    Requests:
      cpu:          500m
      memory:       256Mi
    Environment:
      DB_URL:       <set to the key 'url' in secret 'db-secret'>  Optional: false
    Liveness:       httpGet http://:5432/health delay=30s timeout=1s period=10s #success=1 #failure=3
    Readiness:      httpGet http://:5432/health delay=5s timeout=1s period=10s #success=1 #failure=3
Conditions:
  Type              Status
  Ready             False
Events:
  Type     Reason     Age                From               Message
  ----     ------     ----               ----               -------
  Warning  Unhealthy  12s (x3 over 32s)  kubelet            Readiness probe failed: HTTP probe failed with statuscode: 503
  Warning  Unhealthy  12s (x3 over 32s)  kubelet            Liveness probe failed: HTTP probe failed with statuscode: 503
  Warning  BackOff    5s (x4 over 45s)   kubelet            Back-off restarting failed container
"""

desc_oom_killed = """
Name:             payment-service-5c68f6d899-xyz12
Namespace:        default
Status:           OOMKilled
Containers:
  app:
    Last State:     Terminated
      Reason:       OOMKilled
      Exit Code:    137
    Limits:
      memory:       512Mi
Events:
  Type     Reason      Message
  ----     ------      -------
  Warning  OOMKilling  Memory cgroup out of memory: Killed process 1234 (app) total-vm:700140kB, anon-rss:524288kB
  Warning  Killing     Killing container with id docker://abcdef:Need to kill Pod
"""

desc_image_pull = """
Status:           Pending
Containers:
  app:
    State:          Waiting
      Reason:       ImagePullBackOff
    Image:          myrepo/payment-service:v2.1.0-bad
Events:
  Type     Reason      Message
  ----     ------      -------
  Warning  Failed      Failed to pull image "myrepo/payment-service:v2.1.0-bad": rpc error: code = Unknown desc = Error response from daemon: manifest for myrepo/payment-service:v2.1.0-bad not found
  Warning  BackOff     Back-off pulling image "myrepo/payment-service:v2.1.0-bad"
"""

desc_secret_missing = """
Status:           CrashLoopBackOff
Containers:
  app:
    Environment:
      SECRET_KEY:  <set to the key 'key' in secret 'payment-secrets'>  Optional: false
    Mounts:
      /etc/secrets from my-secret-volume (ro)
Events:
  Type     Reason       Message
  ----     ------       -------
  Warning  FailedMount  MountVolume.SetUp failed for volume "my-secret-volume" : secret "payment-secrets" not found
"""

desc_pvc_not_bound = """
Status:           Pending
Volumes:
  my-data-pvc:
    Type:       PersistentVolumeClaim (a reference to a PersistentVolumeClaim in the same namespace)
    ClaimName:  my-data-pvc
    ReadOnly:   false
Events:
  Type     Reason       Message
  ----     ------       -------
  Warning  FailedMount  Unable to attach or mount volumes: unmounted volumes=[my-data-pvc], unattached volumes=[my-data-pvc]: timed out waiting for the condition
  Warning  FailedMount  persistentvolumeclaim "my-data-pvc" not found
"""

desc_probe_failure = """
Status:           Running
Conditions:
  Type              Status
  Ready             False
Containers:
  app:
    Liveness:       httpGet http://:8080/health delay=10s timeout=1s period=10s #success=1 #failure=3
    Readiness:      httpGet http://:8080/health delay=10s timeout=1s period=10s #success=1 #failure=3
Events:
  Type     Reason     Message
  ----     ------     -------
  Warning  Unhealthy  Liveness probe failed: HTTP probe failed with statuscode: 503
  Warning  Killing    Killing container with id docker://12345:Container failed liveness probe, will be restarted
"""

desc_recent_deploy = """
Annotations:      deployment.kubernetes.io/revision: "7"
Status:           Running
Containers:
  app:
    Image:          myrepo/payment-service:v2.1.0
    Restart Count:  2
Events:
  Type     Reason     Message
  ----     ------     -------
  Normal   Pulled     Successfully pulled image "myrepo/payment-service:v2.1.0"
  Normal   Created    Created container app
  Normal   Started    Started container app
  Warning  Unhealthy  Readiness probe failed: HTTP probe failed with statuscode: 500
"""

desc_node_pressure = """
Status:           Failed
Reason:           Evicted
Message:          The node was low on resource: memory. Threshold quantity: 100Mi, available: 45Mi
Events:
  Type     Reason   Message
  ----     ------   -------
  Warning  Evicting  Evicting pod due to node pressure
  Warning  Evicted   Pod evicted
"""

desc_istio_crash = """
Containers:
  app:
    State:          Running
  istio-proxy:
    State:          Waiting
      Reason:       CrashLoopBackOff
    Last State:     Terminated
      Reason:       Error
      Exit Code:    255
    Restart Count:  8
Events:
  Type     Reason     Message
  ----     ------     -------
  Warning  Unhealthy  Readiness probe failed: connection refused
  Warning  BackOff    Back-off restarting failed container istio-proxy
"""

event_conn_pool = """
LAST SEEN   TYPE      REASON        OBJECT
12s         Warning   BackOff       pod/database-service-84d7fcb6f-pxkgp
14s         Warning   Unhealthy     pod/database-service-84d7fcb6f-pxkgp
1min        Warning   FailedMount   pod/database-service-84d7fcb6f-pxkgp
2min        Normal    Pulling       pod/database-service-84d7fcb6f-pxkgp
2min        Normal    Pulled        pod/database-service-84d7fcb6f-pxkgp
"""

event_oom = """
LAST SEEN   TYPE      REASON        OBJECT
12s         Warning   OOMKilling    node/ip-10-0-1-12
12s         Warning   Killing       pod/payment-service-5c68f6
3min        Normal    Pulled        pod/payment-service-5c68f6
3min        Normal    Started       pod/payment-service-5c68f6
1min        Warning   BackOff       pod/payment-service-5c68f6
"""

event_image_pull = """
LAST SEEN   TYPE      REASON        OBJECT
12s         Warning   Failed        pod/payment-service-5c68f6
  Failed to pull image "myrepo/payment-service:v2.1.0-bad"
12s         Warning   Failed        pod/payment-service-5c68f6
  Error: ErrImagePull
14s         Warning   BackOff       pod/payment-service-5c68f6
  Back-off pulling image
"""

event_secret = """
LAST SEEN   TYPE      REASON        OBJECT
12s         Warning   FailedMount   pod/payment-service-5c68f6
  MountVolume.SetUp failed
  secret "payment-secrets" not found
14s         Warning   Failed        pod/payment-service-5c68f6
"""

event_pvc = """
LAST SEEN   TYPE      REASON              OBJECT
12s         Warning   FailedMount         pod/database-service-84
  Unable to attach or mount volumes
14s         Warning   FailedAttachVolume  pod/database-service-84
  AttachVolume.Attach failed
"""

event_recent = """
LAST SEEN   TYPE      REASON             OBJECT
3min        Normal    ScalingReplicaSet  deploy/payment-service
  Scaled up replica set to 1
2min        Normal    Pulled             pod/payment-service-5c68f6
2min        Normal    Created            pod/payment-service-5c68f6
2min        Normal    Started            pod/payment-service-5c68f6
12s         Warning   Unhealthy          pod/payment-service-5c68f6
"""

event_probe = """
LAST SEEN   TYPE      REASON        OBJECT
12s         Warning   Unhealthy     pod/api-gateway-84
  Liveness probe failed: HTTP probe
  failed with statuscode: 503
12s         Warning   Killing       pod/api-gateway-84
  Stopping container due to probe
"""

event_node = """
LAST SEEN   TYPE      REASON                  OBJECT
12s         Warning   Evicting                pod/payment-service-5c
12s         Warning   Evicted                 pod/payment-service-5c
12s         Warning   NodeHasDiskPressure     node/ip-10-0-1-12
12s         Warning   NodeHasMemoryPressure   node/ip-10-0-1-12
"""

event_istio = """
LAST SEEN   TYPE      REASON        OBJECT
12s         Warning   BackOff       pod/payment-service-5c
  Back-off restarting failed container
  istio-proxy
14s         Warning   Unhealthy     pod/payment-service-5c
  Liveness probe failed for istio-proxy
"""

rollout_history = """
REVISION  CHANGE-CAUSE
1         Initial deployment v1.0.0
2         Updated DB connection pool config
3         Added health endpoint /health
4         Performance optimizations v1.2.0
5         Security patches v1.3.0
6         Feature: async payment processing
7         Hotfix: connection timeout config
"""

files_to_write = {
    "logs/services/api-gateway.log": log_api_gateway,
    "logs/services/payment-service.log": log_payment_service,
    "logs/services/database-service.log": log_database_service,
    "logs/services/auth-service.log": log_auth_service,
    
    "mock/kubectl/describe/connection-pool-exhaustion.txt": desc_conn_pool,
    "mock/kubectl/describe/oom-killed.txt": desc_oom_killed,
    "mock/kubectl/describe/image-pull-backoff.txt": desc_image_pull,
    "mock/kubectl/describe/secret-missing.txt": desc_secret_missing,
    "mock/kubectl/describe/pvc-not-bound.txt": desc_pvc_not_bound,
    "mock/kubectl/describe/probe-failure.txt": desc_probe_failure,
    "mock/kubectl/describe/recent-deployment.txt": desc_recent_deploy,
    "mock/kubectl/describe/node-pressure.txt": desc_node_pressure,
    "mock/kubectl/describe/istio-crash.txt": desc_istio_crash,

    "mock/kubectl/events/connection-pool-exhaustion.txt": event_conn_pool,
    "mock/kubectl/events/oom-killed.txt": event_oom,
    "mock/kubectl/events/image-pull-backoff.txt": event_image_pull,
    "mock/kubectl/events/secret-missing.txt": event_secret,
    "mock/kubectl/events/pvc-not-bound.txt": event_pvc,
    "mock/kubectl/events/recent-deployment.txt": event_recent,
    "mock/kubectl/events/probe-failure.txt": event_probe,
    "mock/kubectl/events/node-pressure.txt": event_node,
    "mock/kubectl/events/istio-crash.txt": event_istio,
    
    "mock/kubectl/rollout/history.txt": rollout_history,
}

for path, content in files_to_write.items():
    create_file(path, content)

print("Files created.")
