#!/bin/bash
# Quick demo script for dissertation viva
# Shows key features of the SRE-AI tool
# Entry point: python ai_sre.py

PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

echo "══════════════════════════════════════"
echo "  SRE-AI Tool — Dissertation Demo"
echo "══════════════════════════════════════"
echo ""

echo "Demo 1: System status"
echo "──────────────────────"
python ai_sre.py status
echo ""
read -p "Press Enter for Demo 2..."

echo ""
echo "Demo 2: RAG-based RCA (default mode)"
echo "─────────────────────────────────────"
python ai_sre.py analyse payment-service
echo ""
read -p "Press Enter for Demo 3..."

echo ""
echo "Demo 3: Baseline analysis (no RAG)"
echo "────────────────────────────────────"
python ai_sre.py analyse payment-service --baseline
echo ""
read -p "Press Enter for Demo 4..."

echo ""
echo "Demo 4: Side-by-side comparison + report"
echo "─────────────────────────────────────────"
python ai_sre.py analyse payment-service --compare
echo ""
read -p "Press Enter for Demo 5..."

echo ""
echo "Demo 5: Log cleaning"
echo "─────────────────────"
python ai_sre.py clean-logs logs/test.log
echo ""

echo "══════════════════════════════════════"
echo "  Demo complete."
echo "══════════════════════════════════════"
