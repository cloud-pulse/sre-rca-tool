import sys
import os
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

from core.logger import get_logger

log = get_logger("context_builder")


class ContextBuilder:
    """
    Assembles structured log entries and resource data into a context
    object ready for LLM prompt generation.
    """

    def build(self, filtered_entries: list[dict], resources: dict) -> dict:
        """
        Assemble full context dictionary for LLM analysis.
        
        Args:
            filtered_entries: List of parsed log entries (already filtered)
            resources: Dictionary of resource data per service
            
        Returns:
            Context dictionary with all analysis data
        """
        from core.log_processor import LogProcessor
        from core.resource_collector import ResourceCollector
        
        # Extract error and warning counts
        error_count = sum(1 for e in filtered_entries 
                         if e['level'] in ['ERROR', 'CRITICAL'])
        warning_count = sum(1 for e in filtered_entries 
                           if e['level'] == 'WARN')
        
        # Get unique services affected
        services_affected = sorted(set(
            e['service'] for e in filtered_entries 
            if e['service'] != 'unknown'
        ))
        
        # Get failure chain
        processor = LogProcessor()
        failure_chain = processor.get_failure_chain(filtered_entries)
        
        # Get time window of errors
        timestamps = [e['timestamp'] for e in filtered_entries 
                     if e['timestamp'] != 'unknown']
        earliest_error = timestamps[0] if timestamps else "unknown"
        latest_error = timestamps[-1] if timestamps else "unknown"
        
        if earliest_error == "unknown" or latest_error == "unknown":
            log_window = "unknown"
        else:
            log_window = f"{earliest_error} to {latest_error}"
        
        # Get critical resources
        collector = ResourceCollector()
        critical_resources = {}
        for service, data in resources.items():
            if (data.get('cpu_percent', 0) > 80 or 
                data.get('memory_percent', 0) > 80 or
                data.get('restarts', 0) > 3 or
                data.get('status', '') in ['CrashLoopBackOff', 'OOMKilled', 'Error']):
                critical_resources[service] = data
        
        # Format logs and resources
        formatted_logs = self.format_logs_for_prompt(filtered_entries)
        formatted_resources = self.format_resources_for_prompt(resources)
        
        return {
            "error_count": error_count,
            "warning_count": warning_count,
            "services_affected": services_affected,
            "failure_chain": failure_chain,
            "earliest_error": earliest_error,
            "latest_error": latest_error,
            "log_window": log_window,
            "critical_resources": critical_resources,
            "formatted_logs": formatted_logs,
            "formatted_resources": formatted_resources
        }

    def format_logs_for_prompt(self, entries: list[dict]) -> str:
        """
        Format log entries as clean readable text for LLM.
        
        Args:
            entries: List of parsed log entries
            
        Returns:
            Formatted string for LLM consumption
        """
        # Sort entries by timestamp
        sorted_entries = sorted(
            entries,
            key=lambda e: e['timestamp'] if e['timestamp'] != 'unknown' else 'zzz'
        )
        
        # Filter out UNKNOWN level entries if we have many structured ones
        if len(sorted_entries) > 10:
            filtered = [e for e in sorted_entries if e['level'] != 'UNKNOWN']
            if filtered:  # Use filtered if we have any, otherwise use all
                sorted_entries = filtered
        
        # Format each entry
        formatted_lines = []
        formatted_lines.append(f"=== LOG ENTRIES ({len(sorted_entries)} total) ===")
        
        for entry in sorted_entries:
            timestamp = entry['timestamp']
            level = entry['level']
            service = entry['service']
            message = entry['message']
            
            # Truncate message to 200 chars
            if len(message) > 200:
                message = message[:197] + "..."
            
            formatted_lines.append(
                f"[{timestamp}] [{level}] [{service}] {message}"
            )
        
        formatted_lines.append("=== END OF LOGS ===")
        
        return "\n".join(formatted_lines)

    def format_resources_for_prompt(self, resources: dict) -> str:
        """
        Format resource data as clean readable text for LLM.
        
        Args:
            resources: Dictionary of resource data per service
            
        Returns:
            Formatted string for LLM consumption
        """
        from core.resource_collector import ResourceCollector
        
        # Get critical services
        collector = ResourceCollector()
        critical_services = collector.get_critical_services(resources)
        
        # Create critical summary line
        if critical_services:
            critical_line = f"CRITICAL PODS: {', '.join(critical_services)}"
        else:
            critical_line = "NO CRITICAL PODS DETECTED"
        
        # Get resource summary from collector
        summary = collector.get_resource_summary(resources)
        
        # Assemble formatted output
        lines = [
            critical_line,
            "",
            "=== POD RESOURCE DATA ===",
            summary,
            "=== END OF RESOURCE DATA ==="
        ]
        
        return "\n".join(lines)

    def get_incident_summary(self, context: dict) -> str:
        """
        Generate a one-paragraph human-readable incident summary.
        
        Args:
            context: Context dictionary from build()
            
        Returns:
            Human-readable summary string
        """
        error_count = context['error_count']
        warning_count = context['warning_count']
        services_affected = len(context['services_affected'])
        failure_chain = context['failure_chain']
        earliest_error = context['earliest_error']
        critical_count = len(context['critical_resources'])
        
        # Build failure chain text
        if failure_chain:
            # Extract service names from failure chain entries
            chain_services = [fc.split(" (")[0] for fc in failure_chain]
            chain_text = " → ".join(chain_services)
            chain_desc = f"Failure chain: {chain_text}."
        else:
            chain_desc = "No clear failure chain detected."
        
        # Build summary
        summary = (
            f"Incident detected at {earliest_error} affecting {services_affected} services. "
            f"{chain_desc} "
            f"{error_count} errors and {warning_count} warnings recorded over the incident window. "
            f"{critical_count} critical pod{'s' if critical_count != 1 else ''} identified."
        )
        
        return summary


if __name__ == "__main__":
    from core.log_loader import LogLoader
    from core.log_processor import LogProcessor
    from core.resource_collector import ResourceCollector

    loader = LogLoader()
    processor = LogProcessor()
    collector = ResourceCollector()
    builder = ContextBuilder()

    print("--- Test 1: Build full context ---")
    lines = loader.load("logs/test.log")
    entries = processor.process(lines)
    filtered = processor.filter_by_severity(entries, "ERROR")
    summary = processor.get_summary(entries)
    resources = collector.get_mock_resources(summary["services"])
    context = builder.build(filtered, resources)

    print(f"Error count:        {context['error_count']}")
    print(f"Services affected:  {context['services_affected']}")
    print(f"Failure chain:      {context['failure_chain']}")
    print(f"Log window:         {context['log_window']}")
    print(f"Critical resources: "
          f"{list(context['critical_resources'].keys())}")

    print("\n--- Test 2: Formatted logs ---")
    print(context["formatted_logs"][:500])
    print("...")

    print("\n--- Test 3: Formatted resources ---")
    print(context["formatted_resources"])

    print("\n--- Test 4: Incident summary ---")
    print(builder.get_incident_summary(context))

    print("\n--- Test 5: Build context with WARN severity ---")
    filtered_warn = processor.filter_by_severity(
        entries, "WARN"
    )
    context_warn = builder.build(filtered_warn, resources)
    print(f"Warn+Error count: {context_warn['error_count']}")

    print("\nTask 9 OK")
