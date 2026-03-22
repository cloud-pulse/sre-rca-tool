#!/bin/bash
# AI-SRE launcher
# Tries installed command first,
# falls back to python ai_sre.py

PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

# Try installed command first
if command -v ai-sre &> /dev/null; then
    ai-sre "$@"
else
    # Fallback to python
    python ai_sre.py "$@"
fi
