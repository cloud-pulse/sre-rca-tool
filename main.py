import sys
import click
from core.log_loader import LogLoader
from core.log_processor import LogProcessor
from core.resource_collector import ResourceCollector
from core.context_builder import ContextBuilder
from core.llm_analyzer import LLMAnalyzer

def check_python_version():
    if sys.version_info < (3, 12):
        print(f"ERROR: Python 3.12+ required. You are on {sys.version}")
        print("Make sure Python 3.12 is accessible via 'python' command.")
        sys.exit(1)

check_python_version()

def run_pipeline(log_path: str,
                 severity: str = "ERROR",
                 mode: str = "rag",
                 use_mock: bool = True) -> dict:
    """
    Execute the full Phase 1 + 2 + 3 pipeline step by step.
    
    Args:
        log_path: Path to the log file
        severity: Severity level to filter by
        mode: Analysis mode ("baseline" or "rag")
        use_mock: Whether to use mock resources
        
    Returns:
        Full analysis result dictionary
    """
    # Step 1 — Load logs
    print(f"Step 1/5: Loading logs from {log_path}")
    loader = LogLoader()
    lines = loader.load(log_path)
    if not lines:
        print(f"ERROR: No logs found in {log_path}")
        sys.exit(1)
    
    # Step 2 — Process logs
    print("Step 2/5: Processing and parsing log lines")
    processor = LogProcessor()
    entries = processor.process(lines)
    filtered = processor.filter_by_severity(entries, severity)
    summary = processor.get_summary(entries)
    print(f"Found {summary['errors']} errors, {summary['warnings']} warnings across {len(summary['services'])} services")
    print(f"Services: {', '.join(summary['services'])}")
    
    # Step 3 — Collect resources
    print("Step 3/5: Collecting pod resource data")
    collector = ResourceCollector()
    if use_mock:
        resources = collector.get_mock_resources(summary["services"])
    else:
        resources = collector.get_resources()
    critical_services = collector.get_critical_services(resources)
    print(f"Critical pods: {', '.join(critical_services)}")
    
    # Step 4 — Build context
    print("Step 4/5: Building incident context")
    builder = ContextBuilder()
    context = builder.build(filtered, resources)
    incident_summary = builder.get_incident_summary(context)
    print(f"Incident summary: {incident_summary}")
    
    # Step 4.5 — RAG retrieval
    rag_context = ""
    retrieved = []
    if mode == "rag":
        from core.rag_engine import RAGEngine
        from config import HISTORICAL_LOGS_DIR
        print("Step 4.5/5: Retrieving similar historical "
              "incidents via RAG")
        rag = RAGEngine(HISTORICAL_LOGS_DIR)
        retrieved = rag.retrieve(
            context["formatted_logs"],
            top_k=3
        )
        rag_context = rag.format_retrieved_context(
            retrieved
        )
        best = rag.get_best_match(retrieved)
        is_known = rag.is_known_pattern(retrieved)
        if best:
            print(f"  Best match: {best['source_file']} "
                  f"({best['similarity_score']}%)")
        print(f"  Known pattern: {is_known}")
    
    # Step 5 — Analyze with LLM
    print(f"Step 5/5: Sending to LLM "
          f"(mode: {mode})")
    analyzer = LLMAnalyzer()
    if not analyzer.check_ollama_connection():
        print("ERROR: Ollama not running.")
        print("Start with: ollama serve")
        sys.exit(1)

    if mode == "rag":
        result = analyzer.analyze_rag(
            context, rag_context
        )
    else:
        result = analyzer.analyze_baseline(context)

    # Enrich result with pipeline metadata
    result["incident_summary"] = (
        builder.get_incident_summary(context)
    )
    result["services_found"] = summary["services"]
    result["critical_pods"] = (
        collector.get_critical_services(resources)
    )
    result["retrieved_incidents"] = retrieved
    result["rag_context_used"] = rag_context

    return result

def print_result(result: dict):
    """
    Print the RCA result in clean plain text.
    
    Args:
        result: Analysis result dictionary
    """
    print("\n" + "="*55)
    print(f"  SRE-AI ROOT CAUSE ANALYSIS")
    print(f"  Mode: {result['mode'].upper()}")
    print("="*55)

    print(f"\nROOT CAUSE:")
    print(f"  {result['root_cause']}")

    print(f"\nAFFECTED SERVICES:")
    print(f"  {result['affected_services']}")

    print(f"\nFAILURE CHAIN:")
    print(f"  {result['failure_chain']}")

    print(f"\nSUGGESTED FIXES:")
    for fix in result["suggested_fixes"]:
        print(f"  [{fix['priority']}] {fix['fix']}")

    print(f"\nCONFIDENCE: {result['confidence']}%")
    print(f"REASON    : {result['confidence_reason']}")

    # Show historical match only in RAG mode
    if result.get("historical_match"):
        print(f"\nHISTORICAL MATCH:")
        print(f"  {result['historical_match']}")

    # Show retrieved incidents if RAG mode
    if result.get("retrieved_incidents"):
        print(f"\nRAG RETRIEVED:")
        for r in result["retrieved_incidents"]:
            print(f"  {r['source_file']}: "
                  f"{r['similarity_score']}% — "
                  f"{r['incident_type']}")

    print(f"\nINCIDENT SUMMARY:")
    print(f"  {result['incident_summary']}")

    print(f"\nCRITICAL PODS : {result['critical_pods']}")
    print(f"SERVICES FOUND: {result['services_found']}")
    print("="*55)

@click.group()
def cli():
    """SRE-AI: AI-assisted Root Cause Analysis tool."""
    pass

@cli.command()
@click.argument("log_file",
                type=click.Path(exists=True),
                default="logs/test.log")
@click.option("--mode",
              type=click.Choice(["baseline", "rag"]),
              default="rag",
              help="Analysis mode")
@click.option("--severity",
              type=click.Choice(["ERROR","WARN","ALL"]),
              default="ERROR",
              help="Log severity filter")
def analyze(log_file, mode, severity):
    """Analyze a log file. Full CLI coming in Task 19."""
    result = run_pipeline(log_file, severity, mode)
    print_result(result)

@cli.command()
def status():
    """Check environment and Ollama status."""
    from core.llm_analyzer import LLMAnalyzer
    analyzer = LLMAnalyzer()
    ok = analyzer.check_ollama_connection()
    if ok:
        click.echo("All systems ready.")
    else:
        click.echo("Ollama not ready. Run: ollama serve")

if __name__ == "__main__":
    # If arguments look like click commands, let click handle them
    if len(sys.argv) > 1 and sys.argv[1] in ['analyze', 'status']:
        cli()
    else:
        # Direct pipeline run
        log_path = sys.argv[1] if len(sys.argv) > 1 \
                   else "logs/test.log"
        mode = sys.argv[2] if len(sys.argv) > 2 \
               else "rag"
        severity = sys.argv[3] if len(sys.argv) > 3 \
                   else "ERROR"

        print("SRE-AI Pipeline — Phase 3 Verification")
        print(f"Log file : {log_path}")
        print(f"Mode     : {mode}")
        print(f"Severity : {severity}")
        print("")

        result = run_pipeline(log_path, severity, mode)
        print_result(result)
