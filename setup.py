from setuptools import setup, find_packages

setup(
    name="sre-rca-tool",
    version="1.0.0",
    description=(
        "AI-assisted SRE Root Cause Analysis"
        " tool for Kubernetes microservices"
    ),
    author="Veerapalli Gowtham",
    packages=find_packages(),
    py_modules=["ai_sre", "main", "flags"],
    python_requires=">=3.12",
    install_requires=[
        "click>=8.1.0",
        "rich>=13.0.0",
        "requests>=2.31.0",
        "ollama>=0.1.0",
        "sentence-transformers>=2.2.0",
        "chromadb>=0.4.0",
        "numpy>=1.24.0",
        "pyyaml>=6.0.0",
    ],
    entry_points={
        "console_scripts": [
            "ai-sre=ai_sre:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Systems Administration",
    ],
)
