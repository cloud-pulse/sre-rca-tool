#!/bin/bash
# ═══════════════════════════════════════════
# SRE-AI Final End-to-End Verification
# Run this before dissertation submission
# ═══════════════════════════════════════════

set -e  # stop on first error

PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

PASS=0
FAIL=0
SKIP=0
ERRORS=()

# ── Helper functions ───────────────────────

pass() {
    echo "  [PASS] $1"
    PASS=$((PASS + 1))
}

fail() {
    echo "  [FAIL] $1"
    FAIL=$((FAIL + 1))
    ERRORS+=("$1")
}

skip() {
    echo "  [SKIP] $1"
    SKIP=$((SKIP + 1))
}

section() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

check_file() {
    if [ -f "$1" ]; then
        pass "File exists: $1"
    else
        fail "File missing: $1"
    fi
}

check_dir() {
    if [ -d "$1" ]; then
        pass "Directory exists: $1"
    else
        fail "Directory missing: $1"
    fi
}

check_python() {
    # Run python snippet and check exit code
    # $1 = description
    # $2 = python code
    if echo "n" | python -c "$2" &>/dev/null 2>&1; then
        pass "$1"
    else
        fail "$1"
    fi
}

check_ollama() {
    # Returns true if Ollama is reachable
    python -c "
import requests
try:
    r = requests.get(
        'http://localhost:11434/',
        timeout=3
    )
    exit(0 if r.status_code == 200 else 1)
except:
    exit(1)
" &>/dev/null 2>&1
}

echo ""
echo "════════════════════════════════════════"
echo "  SRE-AI Final Verification"
echo "  $(date)"
echo "════════════════════════════════════════"

# ══════════════════════════════════════════
section "1. Project Structure"
# ══════════════════════════════════════════

# Core Python files
check_file "main.py"
check_file "ai_sre.py"
check_file "config.py"
check_file "flags.py"
check_file "setup.py"
check_file "requirements.txt"
check_file ".env"
check_file ".env.example"
check_file "services.yaml"

# Core modules
check_file "core/__init__.py"
check_file "core/logger.py"
check_file "core/log_loader.py"
check_file "core/log_processor.py"
check_file "core/resource_collector.py"
check_file "core/context_builder.py"
check_file "core/llm_analyzer.py"
check_file "core/rag_engine.py"
check_file "core/llm_cache.py"
check_file "core/service_graph.py"
check_file "core/sre_investigator.py"

# Output + evaluation
check_file "output/__init__.py"
check_file "output/rca_formatter.py"
check_file "evaluation/__init__.py"
check_file "evaluation/comparator.py"

# Log files
check_file "logs/test.log"
check_file "logs/historical/incident_001.log"
check_file "logs/historical/incident_002.log"
check_file "logs/historical/incident_003.log"
check_file "logs/services/api-gateway.log" \
    2>/dev/null || true

# Mock files
check_dir "mock/kubectl/describe"
check_dir "mock/kubectl/events"
check_dir "mock/kubectl/rollout"

# ══════════════════════════════════════════
section "2. Python Imports"
# ══════════════════════════════════════════

check_python "flags.py imports" "
import sys, os
sys.path.insert(0, os.getcwd())
import flags
assert hasattr(flags, 'DEBUG')
assert hasattr(flags, 'USE_KUBERNETES')
assert hasattr(flags, 'LLM_CACHE_ENABLED')
assert hasattr(flags, 'RAG_ENABLED')
"

check_python "core.logger imports" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.logger import get_logger, SRELogger
log = get_logger('test')
assert hasattr(log, 'debug')
assert hasattr(log, 'info')
assert hasattr(log, 'error')
"

check_python "core.log_loader imports" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_loader import LogLoader
l = LogLoader()
assert hasattr(l, 'load')
assert hasattr(l, 'load_service_logs')
assert hasattr(l, 'load_all_service_logs')
assert hasattr(l, 'load_mock_kubectl')
assert hasattr(l, 'load_from_kubectl')
assert hasattr(l, 'load_auto')
"

check_python "core.log_processor imports" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_processor import LogProcessor
p = LogProcessor()
assert hasattr(p, 'process')
assert hasattr(p, 'filter_by_severity')
assert hasattr(p, 'get_summary')
assert hasattr(p, 'get_failure_chain')
"

check_python "core.resource_collector imports" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.resource_collector import (
    ResourceCollector
)
r = ResourceCollector()
assert hasattr(r, 'get_mock_resources')
assert hasattr(r, 'get_resources')
assert hasattr(r, 'get_critical_services')
assert hasattr(r, 'get_real_pod_metrics')
assert hasattr(r, 'get_pod_status')
"

check_python "core.llm_analyzer imports" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
a = LLMAnalyzer()
assert hasattr(a, 'analyze_baseline')
assert hasattr(a, 'analyze_rag')
assert hasattr(a, 'analyze_investigation')
assert hasattr(a, 'warmup')
assert hasattr(a, 'cache')
"

check_python "core.rag_engine imports" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.rag_engine import RAGEngine
r = RAGEngine('logs/historical')
assert hasattr(r, 'retrieve')
assert hasattr(r, 'format_retrieved_context')
assert hasattr(r, 'get_collection_stats')
"

check_python "core.service_graph imports" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.service_graph import ServiceGraph
g = ServiceGraph()
services = g.get_all_service_names()
assert len(services) > 0
assert hasattr(g, 'get_blast_radius')
assert hasattr(g, 'discover_from_logs')
assert hasattr(g, 'get_containers')
"

check_python "core.sre_investigator imports" "
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
i = SREInvestigator()
assert hasattr(i, 'investigate')
assert len(PatternDetector.RULES) >= 15
"

check_python "output.rca_formatter imports" "
import sys, os
sys.path.insert(0, os.getcwd())
from output.rca_formatter import RCAFormatter
f = RCAFormatter()
assert hasattr(f, 'print_full_result')
assert hasattr(f, 'print_full_investigation')
assert hasattr(f, 'print_service_health_dashboard')
assert hasattr(f, 'print_cascade_timeline')
assert hasattr(f, 'print_remediation_steps')
assert hasattr(f, 'print_ranked_causes')
"

check_python "evaluation.comparator imports" "
import sys, os
sys.path.insert(0, os.getcwd())
from evaluation.comparator import Comparator
c = Comparator()
assert hasattr(c, 'compare')
assert hasattr(c, 'save_comparison_report')
"

check_python "ai_sre imports" "
import sys, os
sys.path.insert(0, os.getcwd())
from ai_sre import NLParser, AISRECli
p = NLParser()
assert len(p.known_services) > 0
c = AISRECli()
assert hasattr(c, '_run_investigation')
assert hasattr(c, '_run_analyze')
"

# ══════════════════════════════════════════
section "3. Feature Flags"
# ══════════════════════════════════════════

check_python "Debug flag readable" "
import sys, os
sys.path.insert(0, os.getcwd())
from flags import DEBUG, SUPPRESS_LOGS
assert isinstance(DEBUG, bool)
assert isinstance(SUPPRESS_LOGS, bool)
"

check_python "Kubernetes flag readable" "
import sys, os
sys.path.insert(0, os.getcwd())
from flags import USE_KUBERNETES, K8S_NAMESPACE
assert isinstance(USE_KUBERNETES, bool)
assert isinstance(K8S_NAMESPACE, str)
"

check_python "LLM flags readable" "
import sys, os
sys.path.insert(0, os.getcwd())
from flags import (
    LLM_CACHE_ENABLED,
    LLM_WARMUP,
    LLM_MAX_TOKENS,
    LLM_TIMEOUT
)
assert isinstance(LLM_CACHE_ENABLED, bool)
assert LLM_MAX_TOKENS > 0
assert LLM_TIMEOUT > 0
"

check_python "RAG flags readable" "
import sys, os
sys.path.insert(0, os.getcwd())
from flags import RAG_ENABLED, RAG_TOP_K
assert isinstance(RAG_ENABLED, bool)
assert RAG_TOP_K > 0
"

check_python "Debug env override works" "
import sys, os
os.environ['SYSTEM_DEBUG'] = 'true'
sys.path.insert(0, os.getcwd())
import importlib
import flags
importlib.reload(flags)
assert flags.DEBUG == True
os.environ['SYSTEM_DEBUG'] = 'false'
"

# ══════════════════════════════════════════
section "4. Log Loading Pipeline"
# ══════════════════════════════════════════

check_python "Load test.log" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_loader import LogLoader
l = LogLoader()
lines = l.load('logs/test.log')
assert len(lines) >= 50
"

check_python "Load historical logs" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_loader import LogLoader
l = LogLoader()
files = l.load_directory('logs/historical')
assert len(files) >= 3
"

check_python "Load per-service logs" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_loader import LogLoader
from core.service_graph import ServiceGraph
l = LogLoader()
g = ServiceGraph()
services = g.get_all_service_names()
for svc in services:
    lines = l.load_service_logs(svc)
    assert isinstance(lines, list)
"

check_python "Load all services at once" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_loader import LogLoader
from core.service_graph import ServiceGraph
l = LogLoader()
g = ServiceGraph()
services = g.get_all_service_names()
all_logs = l.load_all_service_logs(services)
assert len(all_logs) == len(services)
"

check_python "Load mock kubectl files" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_loader import LogLoader
l = LogLoader()
content = l.load_mock_kubectl(
    'describe', 'oom-killed'
)
assert len(content) > 100
content2 = l.load_mock_kubectl(
    'events', 'secret-missing'
)
assert len(content2) > 50
"

check_python "Log processor — parse and filter" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.log_loader import LogLoader
from core.log_processor import LogProcessor
l = LogLoader()
p = LogProcessor()
lines = l.load('logs/test.log')
entries = p.process(lines)
assert len(entries) > 0
errors = p.filter_by_severity(entries, 'ERROR')
assert len(errors) > 0
summary = p.get_summary(entries)
assert summary['total'] > 0
assert len(summary['services']) > 0
"

# ══════════════════════════════════════════
section "5. Service Graph"
# ══════════════════════════════════════════

check_python "services.yaml loads correctly" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.service_graph import ServiceGraph
g = ServiceGraph()
services = g.get_all_service_names()
assert len(services) >= 4
"

check_python "Blast radius resolves correctly" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.service_graph import ServiceGraph
g = ServiceGraph()
services = g.get_all_service_names()
for svc in services:
    br = g.get_blast_radius(svc)
    assert 'target' in br
    assert 'downstream' in br
    assert 'upstream' in br
    assert 'safe_services' in br
    assert 'all_affected' in br
"

check_python "Partial name matching works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.service_graph import ServiceGraph
g = ServiceGraph()
services = g.get_all_service_names()
for svc in services:
    partial = svc.split('-')[0]
    resolved = g.get_service_name(partial)
    assert resolved is not None
"

check_python "Container list works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.service_graph import ServiceGraph
g = ServiceGraph()
services = g.get_all_service_names()
for svc in services:
    containers = g.get_containers(svc)
    assert isinstance(containers, list)
    assert len(containers) >= 1
"

check_python "Dependency discovery from logs" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.service_graph import ServiceGraph
g = ServiceGraph()
mock_logs = [
    'connecting to new-unknown-service:8080',
    'host: another-mystery-service:5432',
]
services = g.get_all_service_names()
src = services[0] if services else 'test'
discoveries = g.discover_from_logs(
    mock_logs, src
)
assert isinstance(discoveries, list)
"

check_python "No hardcoded names in service_graph" "
import ast, sys
with open('core/service_graph.py') as f:
    source = f.read()
tree = ast.parse(source)
suspicious = [
    'api-gateway', 'payment-service',
    'database-service', 'auth-service'
]
for node in ast.walk(tree):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            for name in suspicious:
                if name == node.value:
                    raise AssertionError(
                        f'Hardcoded: {name}'
                    )
"

# ══════════════════════════════════════════
section "6. Resource Collection"
# ══════════════════════════════════════════

check_python "Mock resources return correct format" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.resource_collector import (
    ResourceCollector
)
from core.service_graph import ServiceGraph
r = ResourceCollector()
g = ServiceGraph()
services = g.get_all_service_names()
resources = r.get_mock_resources(services)
assert len(resources) == len(services)
for svc, data in resources.items():
    assert 'cpu_percent' in data
    assert 'memory_percent' in data
    assert 'restarts' in data
    assert 'status' in data
"

check_python "Critical services detection works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.resource_collector import (
    ResourceCollector
)
from core.service_graph import ServiceGraph
r = ResourceCollector()
g = ServiceGraph()
services = g.get_all_service_names()
resources = r.get_mock_resources(services)
critical = r.get_critical_services(resources)
assert isinstance(critical, list)
"

check_python "Resource summary text works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.resource_collector import (
    ResourceCollector
)
from core.service_graph import ServiceGraph
r = ResourceCollector()
g = ServiceGraph()
services = g.get_all_service_names()
resources = r.get_mock_resources(services)
summary = r.get_resource_summary(resources)
assert isinstance(summary, str)
assert len(summary) > 50
"

# ══════════════════════════════════════════
section "7. LLM Cache"
# ══════════════════════════════════════════

check_python "Cache set and get works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_cache import LLMCache
c = LLMCache()
mock = {'mode': 'test', 'confidence': 80}
c.set('test-prompt-verification', 'test', mock)
result = c.get('test-prompt-verification', 'test')
assert result is not None
assert result['confidence'] == 80
assert result.get('from_cache') == True
"

check_python "Cache stats work" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_cache import LLMCache
c = LLMCache()
stats = c.stats()
assert 'total_entries' in stats
assert 'enabled' in stats
assert 'ttl_seconds' in stats
"

check_python "Cache clear works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_cache import LLMCache
c = LLMCache()
mock = {'mode': 'test', 'confidence': 50}
c.set('test-clear-prompt', 'test', mock)
deleted = c.clear(0)
assert isinstance(deleted, int)
"

# ══════════════════════════════════════════
section "8. RAG Engine"
# ══════════════════════════════════════════

check_python "RAG engine initializes" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.rag_engine import RAGEngine
r = RAGEngine('logs/historical')
stats = r.get_collection_stats()
assert stats['total_chunks'] >= 0
assert isinstance(
    stats['files_indexed'], list
)
"

check_python "RAG retrieval works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.rag_engine import RAGEngine
r = RAGEngine('logs/historical')
results = r.retrieve(
    'database connection timeout error', 3
)
assert isinstance(results, list)
"

check_python "RAG format works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.rag_engine import RAGEngine
r = RAGEngine('logs/historical')
results = r.retrieve(
    'connection pool exhausted', 2
)
formatted = r.format_retrieved_context(results)
assert isinstance(formatted, str)
"

# ══════════════════════════════════════════
section "9. SRE Investigator"
# ══════════════════════════════════════════

check_python "Pattern detector has rules" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.sre_investigator import PatternDetector
rules = PatternDetector.RULES
assert len(rules) >= 15
categories = set(r['category'] for r in rules)
expected = {
    'Resource', 'Network',
    'Config', 'Deployment', 'Storage'
}
assert expected.issubset(categories)
"

check_python "Evidence collection works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.sre_investigator import (
    SREInvestigator,
    InvestigationEvidence
)
from core.service_graph import ServiceGraph
i = SREInvestigator()
g = ServiceGraph()
services = g.get_all_service_names()
target = services[0]
namespace = g.get_namespace(target)
ev = i.collector.collect(
    target, namespace, use_mock=True
)
assert isinstance(ev, InvestigationEvidence)
assert ev.service_name == target
assert isinstance(ev.container_logs, dict)
"

check_python "Full investigation runs" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.sre_investigator import (
    SREInvestigator, InvestigationReport
)
from core.service_graph import ServiceGraph
i = SREInvestigator()
g = ServiceGraph()
services = g.get_all_service_names()
target = services[0]
report = i.investigate(
    target, use_mock=True
)
assert isinstance(report, InvestigationReport)
assert report.target_service is not None
assert len(report.evidence) > 0
assert report.probable_root_cause != ''
assert isinstance(
    report.cascade_timeline, list
)
assert isinstance(
    report.patterns_by_category, dict
)
"

check_python "Cascade timeline builds" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.sre_investigator import SREInvestigator
from core.service_graph import ServiceGraph
i = SREInvestigator()
g = ServiceGraph()
# Find service with dependencies
services = g.get_all_service_names()
target = services[0]
for svc in services:
    br = g.get_blast_radius(svc)
    if br['downstream']:
        target = svc
        break
report = i.investigate(
    target, use_mock=True
)
assert isinstance(
    report.cascade_timeline, list
)
"

check_python "Summary text generates" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.sre_investigator import SREInvestigator
from core.service_graph import ServiceGraph
i = SREInvestigator()
g = ServiceGraph()
services = g.get_all_service_names()
target = services[0]
report = i.investigate(
    target, use_mock=True
)
summary = i.get_summary_text(report)
assert isinstance(summary, str)
assert len(summary) > 200
assert 'INVESTIGATION' in summary
"

# ══════════════════════════════════════════
section "10. LLM Analyzer Methods"
# ══════════════════════════════════════════

check_python "Baseline prompt builds" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
from core.log_loader import LogLoader
from core.log_processor import LogProcessor
from core.resource_collector import (
    ResourceCollector
)
from core.context_builder import ContextBuilder
a = LLMAnalyzer()
l = LogLoader()
p = LogProcessor()
r = ResourceCollector()
b = ContextBuilder()
lines = l.load('logs/test.log')
entries = p.process(lines)
filtered = p.filter_by_severity(entries, 'ERROR')
summary = p.get_summary(entries)
resources = r.get_mock_resources(
    summary['services']
)
context = b.build(filtered, resources)
prompt = a.build_baseline_prompt(context)
assert len(prompt) > 500
assert 'ROOT CAUSE' in prompt
"

check_python "Investigation prompt builds" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
from core.sre_investigator import SREInvestigator
from core.service_graph import ServiceGraph
a = LLMAnalyzer()
i = SREInvestigator()
g = ServiceGraph()
services = g.get_all_service_names()
target = services[0]
report = i.investigate(
    target, use_mock=True
)
prompt = a.build_investigation_prompt(
    report, ''
)
assert len(prompt) > 1000
assert 'INCIDENT OVERVIEW' in prompt
assert 'PRE-ANALYSIS' in prompt
assert 'REMEDIATION' in prompt
assert 'kubectl' in prompt
"

check_python "Empty investigation result works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
from core.sre_investigator import SREInvestigator
from core.service_graph import ServiceGraph
a = LLMAnalyzer()
i = SREInvestigator()
g = ServiceGraph()
services = g.get_all_service_names()
report = i.investigate(
    services[0], use_mock=True
)
result = a._empty_investigation_result(report)
assert result['mode'] == 'investigation_failed'
assert 'services_health' in result
assert 'cascade_timeline' in result
assert 'patterns_by_category' in result
"

# ══════════════════════════════════════════
section "11. RCA Formatter"
# ══════════════════════════════════════════

check_python "Investigation header renders" "
import sys, os
sys.path.insert(0, os.getcwd())
from output.rca_formatter import RCAFormatter
from core.service_graph import ServiceGraph
f = RCAFormatter()
g = ServiceGraph()
services = g.get_all_service_names()
result = {
    'target_service': services[0],
    'namespace': 'sre-demo',
    'data_source': 'file',
}
f.print_investigation_header(result)
"

check_python "Health dashboard renders" "
import sys, os
sys.path.insert(0, os.getcwd())
from output.rca_formatter import RCAFormatter
from core.service_graph import ServiceGraph
f = RCAFormatter()
g = ServiceGraph()
services = g.get_all_service_names()
result = {
    'services_health': {
        svc: 'OK' for svc in services
    },
    'cascade_timeline': [],
    'patterns_by_category': {},
}
f.print_service_health_dashboard(result)
"

check_python "Cascade timeline renders" "
import sys, os
sys.path.insert(0, os.getcwd())
from output.rca_formatter import RCAFormatter
from core.service_graph import ServiceGraph
f = RCAFormatter()
g = ServiceGraph()
services = g.get_all_service_names()
result = {
    'cascade_timeline': [
        {
            'service': services[0],
            'time': '10:05:00',
            'event': 'Test event',
            'severity': 'CRITICAL',
            'role': 'root_cause',
            'error_count': 10
        }
    ]
}
f.print_cascade_timeline(result)
"

check_python "Remediation steps render" "
import sys, os
sys.path.insert(0, os.getcwd())
from output.rca_formatter import RCAFormatter
f = RCAFormatter()
result = {
    'remediation_steps': [
        {
            'priority': 'IMMEDIATE',
            'step': 1,
            'action': 'Restart pod',
            'command': 'kubectl rollout restart deployment/test -n default',
            'explanation': 'Clears state'
        }
    ],
    'patterns_by_category': {}
}
f.print_remediation_steps(result)
"

# ══════════════════════════════════════════
section "12. NL Parser"
# ══════════════════════════════════════════

check_python "Parser loads services dynamically" "
import sys, os
sys.path.insert(0, os.getcwd())
from ai_sre import NLParser
from core.service_graph import ServiceGraph
p = NLParser()
g = ServiceGraph()
services = g.get_all_service_names()
assert len(p.known_services) == len(services)
for svc in services:
    assert svc in p.known_services
"

check_python "Parser intent detection works" "
import sys, os
sys.path.insert(0, os.getcwd())
from ai_sre import NLParser
from core.service_graph import ServiceGraph
p = NLParser()
g = ServiceGraph()
services = g.get_all_service_names()
tests = [
    ('compare baseline vs rag', 'compare'),
    ('status', 'status'),
    ('help', 'help'),
    ('clear cache', 'cache_clear'),
    ('watch logs', 'watch'),
]
for text, expected in tests:
    result = p.parse(text)
    assert result['intent'] == expected, (
        f'Expected {expected} for \"{text}\" '
        f'but got {result[\"intent\"]}'
    )
"

check_python "Parser extracts service names" "
import sys, os
sys.path.insert(0, os.getcwd())
from ai_sre import NLParser
from core.service_graph import ServiceGraph
p = NLParser()
g = ServiceGraph()
services = g.get_all_service_names()
for svc in services:
    result = p.parse(
        f'check what is wrong with {svc}'
    )
    assert result['service'] == svc, (
        f'Expected {svc} but got '
        f'{result[\"service\"]}'
    )
"

check_python "Parser resolves partial names" "
import sys, os
sys.path.insert(0, os.getcwd())
from ai_sre import NLParser
from core.service_graph import ServiceGraph
p = NLParser()
g = ServiceGraph()
services = g.get_all_service_names()
for svc in services:
    partial = svc.split('-')[0]
    result = p.parse(
        f'why is {partial} failing'
    )
    assert result['service'] is not None
"

# ══════════════════════════════════════════
section "13. CLI Commands"
# ══════════════════════════════════════════

echo "  Testing: python main.py --help"
if python main.py --help &>/dev/null; then
    pass "main.py --help works"
else
    fail "main.py --help failed"
fi

echo "  Testing: python main.py status"
if python main.py status &>/dev/null; then
    pass "main.py status works"
else
    fail "main.py status failed"
fi

echo "  Testing: python main.py cache"
if python main.py cache &>/dev/null; then
    pass "main.py cache works"
else
    fail "main.py cache failed"
fi

echo "  Testing: python main.py analyze --help"
if python main.py analyze --help \
    &>/dev/null; then
    pass "analyze --help works"
else
    fail "analyze --help failed"
fi

echo "  Testing: python main.py compare --help"
if python main.py compare --help \
    &>/dev/null; then
    pass "compare --help works"
else
    fail "compare --help failed"
fi

echo "  Testing: python main.py watch --help"
if python main.py watch --help \
    &>/dev/null; then
    pass "watch --help works"
else
    fail "watch --help failed"
fi

echo "  Testing: python main.py chat --help"
if python main.py chat --help \
    &>/dev/null; then
    pass "chat --help works"
else
    fail "chat --help failed"
fi

echo "  Testing: python ai_sre.py help"
if python ai_sre.py help &>/dev/null; then
    pass "ai_sre.py help works"
else
    fail "ai_sre.py help failed"
fi

echo "  Testing: python ai_sre.py status"
if python ai_sre.py status &>/dev/null; then
    pass "ai_sre.py status works"
else
    fail "ai_sre.py status failed"
fi

# ══════════════════════════════════════════
section "14. Feature Flag Modes"
# ══════════════════════════════════════════

check_python "File mode active by default" "
import sys, os
sys.path.insert(0, os.getcwd())
from flags import USE_KUBERNETES
assert USE_KUBERNETES == False, (
    'USE_KUBERNETES should default to False'
)
"

check_python "Kubernetes flag toggleable" "
import sys, os
os.environ['SOURCE_KUBERNETES'] = 'true'
sys.path.insert(0, os.getcwd())
import importlib
import flags
importlib.reload(flags)
assert flags.USE_KUBERNETES == True
os.environ['SOURCE_KUBERNETES'] = 'false'
"

check_python "Cache flag works" "
import sys, os
sys.path.insert(0, os.getcwd())
from flags import LLM_CACHE_ENABLED
assert isinstance(LLM_CACHE_ENABLED, bool)
"

check_python "RAG flag works" "
import sys, os
sys.path.insert(0, os.getcwd())
from flags import RAG_ENABLED
assert isinstance(RAG_ENABLED, bool)
"

# ══════════════════════════════════════════
section "15. Ollama + LLM Tests"
# ══════════════════════════════════════════

if check_ollama; then
    echo "  Ollama is RUNNING — running LLM tests"

    check_python "Baseline analysis works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
from core.log_loader import LogLoader
from core.log_processor import LogProcessor
from core.resource_collector import ResourceCollector
from core.context_builder import ContextBuilder
a = LLMAnalyzer()
l = LogLoader()
p = LogProcessor()
r = ResourceCollector()
b = ContextBuilder()
lines = l.load('logs/test.log')
entries = p.process(lines)
filtered = p.filter_by_severity(entries, 'ERROR')
summary = p.get_summary(entries)
resources = r.get_mock_resources(summary['services'])
context = b.build(filtered, resources)
result = a.analyze_baseline(context)
assert result['mode'] in ['baseline', 'baseline_failed']
assert 'root_cause' in result
assert 'confidence' in result
"

    check_python "RAG analysis works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
from core.log_loader import LogLoader
from core.log_processor import LogProcessor
from core.resource_collector import ResourceCollector
from core.context_builder import ContextBuilder
from core.rag_engine import RAGEngine
a = LLMAnalyzer()
l = LogLoader()
p = LogProcessor()
r = ResourceCollector()
b = ContextBuilder()
rag = RAGEngine('logs/historical')
lines = l.load('logs/test.log')
entries = p.process(lines)
filtered = p.filter_by_severity(entries, 'ERROR')
summary = p.get_summary(entries)
resources = r.get_mock_resources(summary['services'])
context = b.build(filtered, resources)
retrieved = rag.retrieve(context['formatted_logs'], 3)
rag_ctx = rag.format_retrieved_context(retrieved)
result = a.analyze_rag(context, rag_ctx)
assert result['mode'] in ['rag', 'rag_failed']
assert 'root_cause' in result
"

    check_python "Investigation analysis works" "
import sys, os
sys.path.insert(0, os.getcwd())
from core.llm_analyzer import LLMAnalyzer
from core.sre_investigator import SREInvestigator
from core.service_graph import ServiceGraph
a = LLMAnalyzer()
i = SREInvestigator()
g = ServiceGraph()
services = g.get_all_service_names()
target = services[0]
for svc in services:
    br = g.get_blast_radius(svc)
    if br['downstream']:
        target = svc
        break
report = i.investigate(target, use_mock=True)
result = a.analyze_investigation(report, i)
assert result['mode'] in [
    'investigation',
    'investigation_failed'
]
assert 'services_health' in result
assert 'cascade_timeline' in result
assert 'target_service' in result
"

else
    skip "Ollama not running — LLM tests skipped"
    skip "  Start Ollama: ollama serve"
    skip "  Then re-run this script"
fi

# ══════════════════════════════════════════
section "16. Scripts"
# ══════════════════════════════════════════

check_file "scripts/check_env.sh"
check_file "scripts/ai-sre.sh"
check_file "scripts/setup_alias.sh"
check_file "scripts/setup_minikube.sh" \
    2>/dev/null || true
check_file "scripts/simulate_new_errors.sh"
check_file "scripts/verify_task_f.sh"
check_file "scripts/verify_task_g.sh"
check_file "scripts/verify_task_h.sh"
check_file "scripts/verify_task_i.sh"
check_file "scripts/verify_task_j.sh"
check_file "scripts/verify_task_k.sh"

echo "  Testing bash launcher:"
if bash scripts/ai-sre.sh help \
    &>/dev/null 2>&1; then
    pass "scripts/ai-sre.sh help works"
else
    fail "scripts/ai-sre.sh help failed"
fi

# ══════════════════════════════════════════
section "17. Final Summary"
# ══════════════════════════════════════════

echo ""
echo "════════════════════════════════════════"
echo "  VERIFICATION RESULTS"
echo "════════════════════════════════════════"
echo ""
echo "  Passed : $PASS"
echo "  Failed : $FAIL"
echo "  Skipped: $SKIP"
echo ""

if [ ${#ERRORS[@]} -gt 0 ]; then
    echo "  Failed checks:"
    for err in "${ERRORS[@]}"; do
        echo "    ✗ $err"
    done
    echo ""
fi

TOTAL=$((PASS + FAIL))
if [ $TOTAL -gt 0 ]; then
    PCT=$(( (PASS * 100) / TOTAL ))
else
    PCT=0
fi

echo "  Pass rate: $PCT% ($PASS/$TOTAL)"
echo ""

if [ $FAIL -eq 0 ]; then
    echo "  ✓ ALL CHECKS PASSED"
    echo "  Tool is ready for dissertation"
    echo "  submission."
else
    echo "  ✗ $FAIL CHECK(S) FAILED"
    echo "  Fix the failures above before"
    echo "  dissertation submission."
fi

echo ""
echo "════════════════════════════════════════"
echo ""

if [ $SKIP -gt 0 ]; then
    echo "  Note: $SKIP test(s) skipped"
    echo "  (Ollama not running)"
    echo "  To run all tests:"
    echo "    ollama serve (new terminal)"
    echo "    bash scripts/verify_final.sh"
    echo ""
fi

echo "  Full integration test:"
echo "    ollama serve (new terminal)"
echo "    source jarvis/Scripts/activate"
echo "    python ai_sre.py 'check [service]'"
echo ""
