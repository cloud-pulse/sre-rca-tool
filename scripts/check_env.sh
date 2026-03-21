#!/bin/bash
echo "=== Checking Python version ==="
if python -c "import sys; assert sys.version_info >= (3,12)"; then
    echo "Python 3.12+ OK — $(python --version)"
else
    echo "ERROR: Python 3.12+ required."
    echo "Make sure Python 3.12 is installed and accessible via 'python'"
    exit 1
fi

if [ -d "jarvis" ]; then
    echo "Virtual environment 'jarvis' exists"
else
    echo "Virtual environment 'jarvis' not found. Creating..."
    python -m venv jarvis

    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment"
        exit 1
    fi

    echo "'jarvis' virtual environment created"
fi

echo ""
echo "=== Activating jarvis and installing dependencies ==="
source jarvis/Scripts/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "=== Verifying installed packages ==="
python -c "import click; print('click: OK')"
python -c "import rich; print('rich: OK')"
python -c "import requests; print('requests: OK')"
python -c "import chromadb; print('chromadb: OK')"
python -c "from sentence_transformers import SentenceTransformer; print('sentence-transformers: OK')"

echo ""
echo "=== Checking Ollama ==="
if command -v ollama &> /dev/null; then
    echo "Ollama: installed"
    ollama list
else
    echo "WARNING: Ollama not found."
    echo "Install from: https://ollama.com/download"
    echo "Then run: ollama pull phi3:mini"
fi

echo ""
echo "=== Task 1 Setup Complete ==="
echo "IMPORTANT: Every new terminal session, activate venv with:"
echo "  source jarvis/bin/activate"
echo "Then use: python main.py"
