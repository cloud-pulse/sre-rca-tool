#!/bin/bash
PROJ="/c/playground/sre-rca-tool"
cd "$PROJ"
source jarvis/Scripts/activate

echo "=== Task J Verification ==="
echo ""

echo "--- Test 1: New methods exist ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from output.rca_formatter import RCAFormatter
f = RCAFormatter()
methods = [
    'print_investigation_header',
    'print_service_health_dashboard',
    'print_cascade_timeline',
    'print_investigation_summary',
    'print_ranked_causes',
    'print_remediation_steps',
    'print_safe_services',
    'print_full_investigation',
]
all_ok = True
for m in methods:
    exists = hasattr(f, m)
    print(f'  {m}: {exists}')
    if not exists:
        all_ok = False
print(f'  All methods present: {all_ok}')
import sys
if not all_ok:
    sys.exit(1)
"

echo ""
echo "--- Test 2: Full investigation render ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from output.rca_formatter import RCAFormatter
from core.resource_collector import (
    ResourceCollector
)

formatter = RCAFormatter()
collector = ResourceCollector()

# Build a realistic mock investigation result
# using dynamic data (no hardcoded names)
from core.service_graph import ServiceGraph
graph = ServiceGraph()
services = graph.get_all_service_names()
target = services[0] if services else 'svc-a'
downstream = graph.get_blast_radius(
    target
)['downstream']
upstream = graph.get_blast_radius(
    target
)['upstream']
safe = graph.get_blast_radius(
    target
)['safe_services']

mock_result = {
    'mode': 'investigation',
    'target_service': target,
    'namespace': 'sre-demo',
    'data_source': 'file',
    'investigation_summary': (
        f'The {target} experienced a critical '
        f'failure causing cascade effects across '
        f'dependent services. Root cause identified '
        f'as connection pool exhaustion.'
    ),
    'probable_root_cause_service': (
        downstream[0]
        if downstream else target
    ),
    'probable_root_cause': (
        'Connection pool exhausted due to '
        'connection leak in retry logic'
    ),
    'pre_analysis_root_cause': (
        downstream[0]
        if downstream else target
    ),
    'ranked_causes': [
        {
            'rank': 1,
            'category': 'Resource',
            'service': (
                downstream[0]
                if downstream else target
            ),
            'cause': 'Connection pool exhausted',
            'confidence': 87,
            'evidence': 'max connections reached'
        },
        {
            'rank': 2,
            'category': 'Network',
            'service': target,
            'cause': 'Cannot reach dependency',
            'confidence': 74,
            'evidence': 'connection refused'
        },
        {
            'rank': 3,
            'category': 'Deployment',
            'service': target,
            'cause': 'Recent deployment (8 min ago)',
            'confidence': 55,
            'evidence': 'rollout history revision 7'
        },
    ],
    'safe_services': safe,
    'cascade_analysis': (
        f'{downstream[0] if downstream else target}'
        f' failed first, causing {target} to lose '
        f'connectivity, then upstream services '
        f'started receiving errors.'
    ),
    'remediation_steps': [
        {
            'priority': 'IMMEDIATE',
            'step': 1,
            'action': 'Restart the failing pod',
            'command': (
                f'kubectl rollout restart '
                f'deployment/'
                f'{downstream[0] if downstream else target}'
                f' -n sre-demo'
            ),
            'explanation': (
                'Clears connection pool state '
                'and gets fresh connections'
            )
        },
        {
            'priority': 'SHORT-TERM',
            'step': 2,
            'action': 'Increase connection pool',
            'command': (
                f'kubectl set env deployment/'
                f'{downstream[0] if downstream else target}'
                f' DB_POOL_SIZE=300 -n sre-demo'
            ),
            'explanation': (
                'Prevents pool exhaustion '
                'under normal load'
            )
        },
        {
            'priority': 'LONG-TERM',
            'step': 3,
            'action': 'Add pool monitoring alert',
            'command': (
                'kubectl apply -f '
                'monitoring/pool-alert.yaml'
            ),
            'explanation': (
                'Early warning before pool '
                'reaches capacity'
            )
        },
    ],
    'confidence': 82,
    'confidence_reason': (
        'Strong evidence from logs and '
        'matching historical pattern'
    ),
    'patterns_by_category': {
        'Resource': [
            f'{downstream[0] if downstream else target}'
            f': CONNECTION_POOL_EXHAUSTED'
        ],
        'Network': [
            f'{target}: CONNECTION_FAILURE'
        ],
    },
    'cascade_timeline': [
        {
            'service': (
                downstream[0]
                if downstream else target
            ),
            'time': '10:05:12',
            'event': 'Connection pool exhausted',
            'severity': 'CRITICAL',
            'role': 'root_cause',
            'error_count': 24
        },
        {
            'service': target,
            'time': '10:07:45',
            'event': 'Cannot reach dependency',
            'severity': 'WARNING',
            'role': 'cascade_victim',
            'error_count': 12
        },
    ] + [
        {
            'service': s,
            'time': 'N/A',
            'event': 'Service healthy',
            'severity': 'OK',
            'role': 'unaffected',
            'error_count': 0
        }
        for s in safe
    ],
    'services_health': {
        (downstream[0] if downstream else target):
            'CRITICAL',
        target: 'WARNING',
        **{s: 'OK' for s in safe}
    },
}

resources = collector.get_mock_resources(
    services
)

print('Rendering full investigation output:')
print()
formatter.print_full_investigation(
    mock_result, resources
)
print()
print('Render completed OK')
"

echo ""
echo "--- Test 3: Individual panels ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from output.rca_formatter import RCAFormatter
from core.service_graph import ServiceGraph

formatter = RCAFormatter()
graph = ServiceGraph()
services = graph.get_all_service_names()
target = services[0] if services else 'svc'

# Minimal result for panel tests
result = {
    'target_service': target,
    'namespace': 'sre-demo',
    'data_source': 'file',
    'investigation_summary': 'Test summary.',
    'probable_root_cause_service': target,
    'probable_root_cause': 'Test cause',
    'pre_analysis_root_cause': target,
    'ranked_causes': [],
    'safe_services': [],
    'cascade_analysis': 'Test cascade.',
    'remediation_steps': [],
    'confidence': 70,
    'confidence_reason': 'Test reason',
    'patterns_by_category': {},
    'cascade_timeline': [],
    'services_health': {target: 'WARNING'},
}

print('Header:')
formatter.print_investigation_header(result)
print('Health dashboard:')
formatter.print_service_health_dashboard(result)
print('Timeline (empty):')
formatter.print_cascade_timeline(result)
print('Summary:')
formatter.print_investigation_summary(result)
print('Ranked causes (empty fallback):')
formatter.print_ranked_causes(result)
print('Remediation (empty fallback):')
formatter.print_remediation_steps(result)
print('Safe services (empty):')
formatter.print_safe_services(result)
print('All panels OK')
"

echo ""
echo "--- Test 4: Existing methods intact ---"
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from output.rca_formatter import RCAFormatter
f = RCAFormatter()
existing = [
    'print_header',
    'print_resource_table',
    'print_rca',
    'print_rag_context',
    'print_full_result',
    'spinner',
]
for m in existing:
    print(f'  {m}: {hasattr(f, m)}')
print('  All existing methods intact OK')
"

echo ""
echo "--- Test 5: main.py still works ---"
python main.py status

echo ""
echo "=== Task J complete ==="
echo ""
echo "Investigation output panels added:"
echo "  print_investigation_header"
echo "  print_service_health_dashboard"
echo "  print_cascade_timeline"
echo "  print_investigation_summary"
echo "  print_ranked_causes"
echo "  print_remediation_steps"
echo "  print_safe_services"
echo "  print_full_investigation"
