#!/bin/bash
# Adds ai-sre alias to bash profile
# Run once: bash scripts/setup_alias.sh

PROJ="/c/playground/sre-rca-tool"
PROFILE="$HOME/.bashrc"

# Check if already added
if grep -q "ai-sre" "$PROFILE" 2>/dev/null; then
    echo "ai-sre alias already in $PROFILE"
else
    echo "" >> "$PROFILE"
    echo "# SRE-AI Tool" >> "$PROFILE"
    echo "alias ai-sre='cd $PROJ && source jarvis/Scripts/activate && python ai_sre.py'" >> "$PROFILE"
    echo "Added ai-sre alias to $PROFILE"
    echo "Run: source $PROFILE"
    echo "Then: ai-sre help"
fi
