#!/bin/bash
PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

echo "=== Task F Verification ==="
echo ""

echo "--- Test 1: pyyaml installed ---"
python -c "import yaml; print('pyyaml OK')"

echo ""
echo "--- Test 2: services.yaml exists ---"
if [ -f "services.yaml" ]; then
    echo "  services.yaml EXISTS"
    python -c "
import yaml
with open('services.yaml') as f:
    data = yaml.safe_load(f)
svcs = data.get('services', {})
print(f'  {len(svcs)} services defined:')
for svc in svcs:
    deps = svcs[svc].get('depends_on', [])
    print(f'    - {svc} (depends_on: {deps})')
"
else
    echo "  MISSING: services.yaml"
fi

echo ""
echo "--- Test 3: service_graph.py ---"
python core/service_graph.py

echo ""
echo "--- Test 4: No hardcoded names ---"
echo "  Checking for hardcoded service names..."
python -c "
import ast, sys

with open('core/service_graph.py') as f:
    source = f.read()

# These names should NOT appear as
# string literals in the Python code
# (they can appear in comments)
forbidden = [
    'api-gateway',
    'payment-service',
    'database-service',
    'auth-service'
]

# Parse AST to find string literals only
tree = ast.parse(source)
violations = []
for node in ast.walk(tree):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            for name in forbidden:
                if name in node.value:
                    violations.append(
                        f'Found hardcoded: '
                        f'\"{name}\" '
                        f'at line {node.lineno}'
                    )

if violations:
    for v in violations:
        print(f'  FAIL: {v}')
    sys.exit(1)
else:
    print('  PASS: No hardcoded service'
          ' names found in Python code')
"

echo ""
echo "=== Task F complete ==="
echo ""
echo "To add your own services:"
echo "  Edit services.yaml"
echo "  Add entries under 'services:'"
echo "  Re-run: python core/service_graph.py"
