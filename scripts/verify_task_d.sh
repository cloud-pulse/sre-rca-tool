#!/bin/bash
set -e

PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

echo "=== Task D Verification ==="
echo ""

echo "--- Test 1: log_loader ---"
python core/log_loader.py
echo ""

echo "--- Test 2: resource_collector ---"
python core/resource_collector.py
echo ""

echo "--- Test 3: llm_cache ---"
python core/llm_cache.py
echo ""

echo "--- Test 4: logger ---"
python core/logger.py
echo ""

echo "--- Test 5: main analyze ---"
python main.py analyze logs/test.log \
  --output plain
echo ""

echo "--- Test 6: main status ---"
python main.py status
echo ""

echo "=== All Task D checks passed ==="
