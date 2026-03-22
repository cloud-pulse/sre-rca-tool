#!/bin/bash
PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

echo "=== Task G Verification ==="
echo ""

echo "--- Test 1: Per-service logs exist ---"
for f in \
  logs/services/api-gateway.log \
  logs/services/payment-service.log \
  logs/services/database-service.log \
  logs/services/auth-service.log
do
  if [ -f "$f" ]; then
    count=$(wc -l < "$f")
    echo "  OK: $f ($count lines)"
  else
    echo "  MISSING: $f"
  fi
done

echo ""
echo "--- Test 2: Mock describe files ---"
for f in \
  mock/kubectl/describe/connection-pool-exhaustion.txt \
  mock/kubectl/describe/oom-killed.txt \
  mock/kubectl/describe/image-pull-backoff.txt \
  mock/kubectl/describe/secret-missing.txt \
  mock/kubectl/describe/pvc-not-bound.txt \
  mock/kubectl/describe/probe-failure.txt \
  mock/kubectl/describe/recent-deployment.txt \
  mock/kubectl/describe/node-pressure.txt \
  mock/kubectl/describe/istio-crash.txt
do
  if [ -f "$f" ]; then
    echo "  OK: $(basename $f)"
  else
    echo "  MISSING: $f"
  fi
done

echo ""
echo "--- Test 3: Mock events files ---"
for f in \
  mock/kubectl/events/connection-pool-exhaustion.txt \
  mock/kubectl/events/oom-killed.txt \
  mock/kubectl/events/image-pull-backoff.txt \
  mock/kubectl/events/secret-missing.txt \
  mock/kubectl/events/pvc-not-bound.txt \
  mock/kubectl/events/recent-deployment.txt \
  mock/kubectl/events/probe-failure.txt \
  mock/kubectl/events/node-pressure.txt \
  mock/kubectl/events/istio-crash.txt
do
  if [ -f "$f" ]; then
    echo "  OK: $(basename $f)"
  else
    echo "  MISSING: $f"
  fi
done

echo ""
echo "--- Test 4: Rollout history ---"
if [ -f "mock/kubectl/rollout/history.txt" ]; then
  echo "  OK: history.txt"
  cat mock/kubectl/rollout/history.txt
else
  echo "  MISSING: history.txt"
fi

echo ""
echo "--- Test 5: LogLoader per-service ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_loader import LogLoader
from core.service_graph import ServiceGraph

loader = LogLoader()
graph = ServiceGraph()
services = graph.get_all_service_names()

print(f'  Testing {len(services)} services:')
for svc in services:
    lines = loader.load_service_logs(svc)
    print(f'  {svc}: {len(lines)} lines loaded')

print()
print('  Testing fallback (nonexistent svc):')
lines = loader.load_service_logs(
    'nonexistent-service'
)
print(
    f'  nonexistent-service: '
    f'{len(lines)} lines (fallback)'
)
"

echo ""
echo "--- Test 6: load_all_service_logs ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_loader import LogLoader
from core.service_graph import ServiceGraph

loader = LogLoader()
graph = ServiceGraph()
services = graph.get_all_service_names()

all_logs = loader.load_all_service_logs(
    services
)
print(f'  Loaded logs for {len(all_logs)} '
      f'services:')
for svc, lines in all_logs.items():
    print(f'  {svc}: {len(lines)} lines')
"

echo ""
echo "--- Test 7: Mock kubectl loader ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_loader import LogLoader

loader = LogLoader()

scenarios = [
    ('describe', 'oom-killed'),
    ('describe', 'secret-missing'),
    ('events', 'connection-pool-exhaustion'),
    ('rollout', 'history'),
]
for rtype, scenario in scenarios:
    content = loader.load_mock_kubectl(
        rtype, scenario
    )
    preview = content[:60].replace(
        '\n', ' '
    )
    status = 'OK' if content else 'EMPTY'
    print(
        f'  [{status}] {rtype}/{scenario}: '
        f'{preview}...'
    )
"

echo ""
echo "=== Task G complete ==="
echo ""
echo "Mock files created:"
echo "  logs/services/     — per-service logs"
echo "  mock/kubectl/      — kubectl simulation"
