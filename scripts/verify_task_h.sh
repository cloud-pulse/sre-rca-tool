#!/bin/bash
PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

echo "=== Task H Verification ==="
echo ""

echo "--- Test 1: Module imports ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.sre_investigator import (
    SREInvestigator,
    InvestigationEvidence,
    InvestigationReport,
    DetectedPattern,
    PatternDetector,
    EvidenceCollector
)
print('  All classes import OK')
print(f'  PatternDetector rules: '
      f'{len(PatternDetector.RULES)}')
"

echo ""
echo "--- Test 2: Full investigation ---"
python core/sre_investigator.py

echo ""
echo "--- Test 3: No hardcoded names ---"
python -c "
import ast, sys
with open('core/sre_investigator.py') as f:
    source = f.read()
tree = ast.parse(source)
# Check: no service names in string literals
# (they should only come from services.yaml)
# We can't check specific names since we
# don't know what's in services.yaml
# Instead check for suspicious patterns
suspicious = [
    'payment-service',
    'database-service',
    'api-gateway',
    'auth-service',
]
violations = []
for node in ast.walk(tree):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            for name in suspicious:
                if name == node.value:
                    violations.append(
                        f'Line {node.lineno}: '
                        f'\"{name}\"'
                    )
if violations:
    for v in violations:
        print(f'  FAIL: {v}')
    sys.exit(1)
else:
    print('  PASS: No hardcoded service names')
"

echo ""
echo "--- Test 4: Main app still works ---"
python main.py status
python main.py analyze logs/test.log \
  --output plain 2>&1 | head -20

echo ""
echo "=== Task H complete ==="
