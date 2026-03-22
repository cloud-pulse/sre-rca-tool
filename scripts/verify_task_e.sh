#!/bin/bash
set -e

PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

echo "=== Task E Verification ==="
echo ""

echo "--- Test 1: Parser unit tests ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from ai_sre import NLParser
p = NLParser()

tests = [
    ('check logs in payment-service',
     'analyze', 'payment-service'),
    ('why is database failing',
     'analyze', 'database-service'),
    ('compare baseline vs rag',
     'compare', None),
    ('watch payment-service',
     'watch', 'payment-service'),
    ('status',
     'status', None),
    ('clear cache',
     'cache_clear', None),
    ('help',
     'help', None),
    ('what happened',
     'analyze', None),
    ('monitor the logs',
     'watch', None),
    ('why is auth-service down',
     'analyze', 'auth-service'),
]

passed = 0
failed = 0
for text, exp_intent, exp_service in tests:
    result = p.parse(text)
    intent_ok = result['intent'] == exp_intent
    service_ok = (
        exp_service is None or
        result['service'] == exp_service
    )
    status = (
        'PASS' if intent_ok and service_ok
        else 'FAIL'
    )
    if status == 'PASS':
        passed += 1
    else:
        failed += 1
    print(f'  [{status}] \"{text}\"')
    if status == 'FAIL':
        print(f'    Expected: '
              f'intent={exp_intent} '
              f'service={exp_service}')
        print(f'    Got:      '
              f'intent={result[\"intent\"]} '
              f'service={result[\"service\"]}')

print(f'')
print(f'Results: {passed} passed, '
      f'{failed} failed')
"
echo ""

echo "--- Test 2: Single command mode ---"
echo "(help command — no Ollama needed)"
python ai_sre.py help
echo ""

echo "--- Test 3: Status command ---"
python ai_sre.py status
echo ""

echo "--- Test 4: Cache stats command ---"
python ai_sre.py cache
echo ""

echo "--- Test 5: Bash launcher exists ---"
if [ -f "scripts/ai-sre.sh" ]; then
    echo "  scripts/ai-sre.sh EXISTS"
    bash scripts/ai-sre.sh help
else
    echo "  MISSING: scripts/ai-sre.sh"
fi
echo ""

echo "=== Task E verification complete ==="
echo ""
echo "To use the natural language CLI:"
echo "  bash scripts/ai-sre.sh"
echo "  bash scripts/ai-sre.sh check payment"
echo "  bash scripts/ai-sre.sh why is db down"
echo "  bash scripts/ai-sre.sh compare"
echo "  bash scripts/ai-sre.sh status"
