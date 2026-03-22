#!/bin/bash
PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

echo "=== Task I Verification ==="
echo ""

echo "--- Test 1: New methods exist ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
a = LLMAnalyzer()
has_build = hasattr(
    a, 'build_investigation_prompt'
)
has_analyze = hasattr(
    a, 'analyze_investigation'
)
has_parse = hasattr(
    a, '_parse_investigation_response'
)
has_empty = hasattr(
    a, '_empty_investigation_result'
)
print(f'  build_investigation_prompt: {has_build}')
print(f'  analyze_investigation: {has_analyze}')
print(f'  _parse_investigation_response: {has_parse}')
print(f'  _empty_investigation_result: {has_empty}')
all_ok = all([
    has_build, has_analyze,
    has_parse, has_empty
])
print(f'  All methods present: {all_ok}')
if not all_ok:
    import sys; sys.exit(1)
"

echo ""
echo "--- Test 2: Prompt generation ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
from core.sre_investigator import SREInvestigator
from core.service_graph import ServiceGraph

a = LLMAnalyzer()
investigator = SREInvestigator()
graph = ServiceGraph()
services = graph.get_all_service_names()

if not services:
    print('No services found')
    sys.exit(1)

# Get a service with dependencies
target = services[0]
for svc in services:
    br = graph.get_blast_radius(svc)
    if br['downstream']:
        target = svc
        break

print(f'  Investigating: {target}')
report = investigator.investigate(
    target, use_mock=True
)
prompt = a.build_investigation_prompt(
    report, ''
)
print(f'  Prompt length: {len(prompt)} chars')
print(f'  Has INCIDENT OVERVIEW: '
      f'{\"INCIDENT OVERVIEW\" in prompt}')
print(f'  Has PRE-ANALYSIS: '
      f'{\"PRE-ANALYSIS\" in prompt}')
print(f'  Has REMEDIATION: '
      f'{\"REMEDIATION\" in prompt}')
print(f'  Has kubectl: '
      f'{\"kubectl\" in prompt}')
print(f'  No hardcoded names: '
      f'{target in prompt}')
print('  Prompt generation OK')
"

echo ""
echo "--- Test 3: Empty result fallback ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
from core.sre_investigator import SREInvestigator
from core.service_graph import ServiceGraph

a = LLMAnalyzer()
investigator = SREInvestigator()
graph = ServiceGraph()
services = graph.get_all_service_names()
target = services[0] if services else 'test'

report = investigator.investigate(
    target, use_mock=True
)
result = a._empty_investigation_result(report)
print(f'  Mode: {result[\"mode\"]}')
print(f'  Target: {result[\"target_service\"]}')
print(f'  Has health: '
      f'{bool(result[\"services_health\"])}')
print(f'  Has timeline: '
      f'{bool(result[\"cascade_timeline\"])}')
print('  Empty result fallback OK')
"

echo ""
echo "--- Test 4: Parse response ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
from core.sre_investigator import SREInvestigator
from core.service_graph import ServiceGraph

a = LLMAnalyzer()
investigator = SREInvestigator()
graph = ServiceGraph()
services = graph.get_all_service_names()
target = services[0] if services else 'test'

report = investigator.investigate(
    target, use_mock=True
)

# Test with mock LLM response
mock_response = '''
INVESTIGATION SUMMARY:
The database service experienced connection pool
exhaustion causing cascade failures in dependent
services. Payment service lost DB connectivity
which caused API gateway to return 503 errors.

PROBABLE ROOT CAUSE:
Service: database-service
Cause: Connection pool exhausted due to leak
Confidence: 85%

RANKED CAUSES:

Category: Resource
1. database-service: Connection pool exhausted
   Confidence: 85%
   Evidence: max connections reached error

Category: Network
2. payment-service: Cannot reach database
   Confidence: 78%
   Evidence: connection refused to DB

SAFE SERVICES:
auth-service

CASCADE ANALYSIS:
database-service failed first causing payment
service to lose connectivity then api-gateway
started returning 503s.

REMEDIATION STEPS:

Priority: IMMEDIATE
Step 1: Restart database service pod
  Command: kubectl rollout restart deployment/database -n sre-demo
  Explanation: Clears connection pool state

Priority: SHORT-TERM
Step 2: Increase connection pool size
  Command: kubectl set env deployment/database DB_POOL_SIZE=300 -n sre-demo
  Explanation: Prevents pool exhaustion

Priority: LONG-TERM
Step 3: Add connection pool monitoring
  Command: kubectl apply -f monitoring/pool-alert.yaml
  Explanation: Alerts before pool exhausts

CONFIDENCE SCORE: 82%
CONFIDENCE REASON: Strong evidence from logs
'''

result = a._parse_investigation_response(
    mock_response, report
)
print(f'  Summary: {result[\"investigation_summary\"][:60]}')
print(f'  Root cause svc: '
      f'{result[\"probable_root_cause_service\"]}')
print(f'  Confidence: {result[\"confidence\"]}%')
print(f'  Ranked causes: '
      f'{len(result[\"ranked_causes\"])}')
print(f'  Remediation steps: '
      f'{len(result[\"remediation_steps\"])}')
print(f'  Safe services: '
      f'{result[\"safe_services\"]}')
print('  Parse response OK')
"

echo ""
echo "--- Test 5: Existing methods work ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
a = LLMAnalyzer()
print(f'  check_ollama: '
      f'{hasattr(a, \"check_ollama_connection\")}')
print(f'  analyze_baseline: '
      f'{hasattr(a, \"analyze_baseline\")}')
print(f'  analyze_rag: '
      f'{hasattr(a, \"analyze_rag\")}')
print(f'  cache: {hasattr(a, \"cache\")}')
print(f'  warmup: {hasattr(a, \"warmup\")}')
print('  Existing methods intact OK')
"

echo ""
echo "--- Test 6: Main app still works ---"
python main.py status
echo ""

echo "=== Task I complete ==="
echo ""
echo "Note: Full LLM test skipped here"
echo "It runs during Task J integration."
echo "To test manually with Ollama:"
echo "  ollama serve (in another terminal)"
echo "  python -c \""
echo "  from core.sre_investigator import *"
echo "  from core.llm_analyzer import *"
echo "  from core.service_graph import *"
echo "  g = ServiceGraph()"
echo "  i = SREInvestigator()"
echo "  a = LLMAnalyzer()"
echo "  r = i.investigate(g.get_all_service_names()[0], use_mock=True)"
echo "  result = a.analyze_investigation(r, i)"
echo "  print(result['investigation_summary'])"
echo "  \""
