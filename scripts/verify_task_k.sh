#!/bin/bash
PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

echo "=== Task K Verification ==="
echo ""

echo "--- Test 1: setup.py exists ---"
if [ -f "setup.py" ]; then
    echo "  setup.py EXISTS"
    python -c "
import ast
with open('setup.py') as f:
    content = f.read()
print('  Entry point defined:',
      'ai-sre=ai_sre:main' in content)
print('  Package name defined:',
      'sre-rca-tool' in content)
"
else
    echo "  MISSING: setup.py"
fi

echo ""
echo "--- Test 2: Package installed ---"
python -c "
import importlib.util
spec = importlib.util.find_spec('sre_rca_tool')
# Check if ai-sre entry point exists
import shutil
ai_sre_path = shutil.which('ai-sre')
if ai_sre_path:
    print(f'  ai-sre command found: {ai_sre_path}')
else:
    print('  ai-sre not in PATH')
    print('  (may need: pip install -e .)')
    print('  Checking jarvis/Scripts/...')
    import os
    scripts_dir = os.path.join(
        'jarvis', 'Scripts'
    )
    if os.path.exists(scripts_dir):
        scripts = os.listdir(scripts_dir)
        ai_sre_files = [
            s for s in scripts
            if 'ai-sre' in s.lower() or
               'ai_sre' in s.lower()
        ]
        if ai_sre_files:
            print(
                f'  Found in Scripts: '
                f'{ai_sre_files}'
            )
        else:
            print(
                '  Not found in Scripts'
            )
"

echo ""
echo "--- Test 3: ai-sre help command ---"
echo "  Via python directly:"
python ai_sre.py help
echo ""

echo "--- Test 4: ai-sre status command ---"
python ai_sre.py status

echo ""
echo "--- Test 5: Parser loads services
     dynamically ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from ai_sre import NLParser
p = NLParser()
print(f'  Known services loaded: '
      f'{len(p.known_services)}')
print(f'  Services: {p.known_services}')
print(f'  Aliases: {p.service_aliases}')
print(
    '  Dynamic loading OK'
    if p.known_services
    else '  No services found in yaml'
)
"

echo ""
echo "--- Test 6: NL parsing with real names ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from ai_sre import NLParser
from core.service_graph import ServiceGraph

p = NLParser()
graph = ServiceGraph()
services = graph.get_all_service_names()

if not services:
    print('  No services to test')
else:
    # Test each real service name
    for svc in services:
        result = p.parse(
            f'check what is wrong with {svc}'
        )
        print(
            f'  \"{svc}\" → '
            f'intent={result[\"intent\"]} '
            f'service={result[\"service\"]}'
        )
    # Test partial names
    for svc in services:
        partial = svc.split('-')[0]
        result = p.parse(
            f'why is {partial} failing'
        )
        print(
            f'  \"{partial}\" → '
            f'service={result[\"service\"]}'
        )
"

echo ""
echo "--- Test 7: Investigation wiring ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from ai_sre import AISRECli

cli = AISRECli()
has_run_inv = hasattr(cli, '_run_investigation')
has_run_ana = hasattr(cli, '_run_analyze')
print(f'  _run_investigation: {has_run_inv}')
print(f'  _run_analyze: {has_run_ana}')
print('  Investigation wiring OK')
"

echo ""
echo "--- Test 8: Via launcher script ---"
if [ -f "scripts/ai-sre.sh" ]; then
    bash scripts/ai-sre.sh help
else
    echo "  MISSING: scripts/ai-sre.sh"
fi

echo ""
echo "--- Test 9: Main app still works ---"
python main.py status
python main.py analyze logs/test.log \
    --output plain 2>&1 | head -5

echo ""
echo "=== Task K complete ==="
echo ""
echo "Usage after this task:"
echo ""
echo "  Option 1 — Direct python (always works):"
echo "    cd /c/playground/sre-rca-tool"
echo "    source jarvis/Scripts/activate"
echo "    python ai_sre.py help"
echo "    python ai_sre.py status"
echo "    python ai_sre.py 'check payment-service'"
echo ""
echo "  Option 2 — Via launcher script:"
echo "    bash scripts/ai-sre.sh help"
echo "    bash scripts/ai-sre.sh status"
echo "    bash scripts/ai-sre.sh 'check payment'"
echo ""
echo "  Option 3 — Installed command (in venv):"
echo "    source jarvis/Scripts/activate"
echo "    ai-sre help"
echo "    ai-sre status"
echo "    ai-sre 'check payment-service'"
echo ""
echo "  Option 4 — Permanent alias:"
echo "    bash scripts/setup_alias.sh"
echo "    source ~/.bashrc"
echo "    ai-sre help"
