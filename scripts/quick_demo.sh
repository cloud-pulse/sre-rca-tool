#!/bin/bash
# Quick demo script for dissertation viva
# Shows key features of the tool
# Requires: ollama serve running

PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

echo "══════════════════════════════════════"
echo "  SRE-AI Tool — Dissertation Demo"
echo "══════════════════════════════════════"
echo ""

# Get first service with dependencies
TARGET=$(python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.service_graph import ServiceGraph
g = ServiceGraph()
services = g.get_all_service_names()
for svc in services:
    br = g.get_blast_radius(svc)
    if br['downstream']:
        print(svc)
        break
if not services:
    print('test-service')
" 2>/dev/null)

echo "Demo 1: System status"
echo "──────────────────────"
python main.py status
echo ""
read -p "Press Enter for Demo 2..."

echo ""
echo "Demo 2: Standard log analysis (RAG mode)"
echo "─────────────────────────────────────────"
python main.py analyze logs/test.log \
    --mode rag --output rich
echo ""
read -p "Press Enter for Demo 3..."

echo ""
echo "Demo 3: Baseline vs RAG comparison"
echo "────────────────────────────────────"
python main.py compare logs/test.log
echo ""
read -p "Press Enter for Demo 4..."

echo ""
echo "Demo 4: Natural language investigation"
echo "───────────────────────────────────────"
echo "Command: ai-sre 'check $TARGET'"
python ai_sre.py "check $TARGET"
echo ""
read -p "Press Enter for Demo 5..."

echo ""
echo "Demo 5: Service graph"
echo "──────────────────────"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from core.service_graph import ServiceGraph
g = ServiceGraph()
g.print_graph()
"
echo ""
echo "══════════════════════════════════════"
echo "  Demo complete."
echo "══════════════════════════════════════"
