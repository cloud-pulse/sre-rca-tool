import re
import sys
import os
from datetime import datetime
from typing import Optional

# Allow imports to work when running this file directly
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LogProcessor:
    """
    Processes raw log lines into structured, searchable entries.
    Handles multiple log format styles and extracts key information.
    """

    # Known service names and their canonical forms
    SERVICE_ALIASES = {
        'payment-svc': 'payment-service',
        'database-svc': 'database-service',
        'api-gw': 'api-gateway',
    }

    KNOWN_SERVICES = [
        'api-gateway', 'payment-service', 'database-service',
        'auth-service', 'payment-svc', 'database-svc', 'api-gw'
    ]

    LEVEL_ALIASES = {
        'CRIT': 'CRITICAL',
        'WARNING': 'WARN',
    }

    VALID_LEVELS = ['ERROR', 'CRITICAL', 'WARN', 'INFO', 'DEBUG', 'UNKNOWN']

    def process(self, raw_lines: list[str]) -> list[dict]:
        """
        Parse raw log lines into structured dictionaries.
        
        Args:
            raw_lines: List of raw log lines
            
        Returns:
            List of parsed log entry dictionaries (excludes comment lines)
        """
        entries = []

        for line in raw_lines:
            # Skip comment lines (metadata headers)
            if line.startswith('#'):
                continue

            entry = {
                "timestamp": self._extract_timestamp(line),
                "level": self._extract_level(line),
                "service": self._extract_service(line),
                "message": self._extract_message(line),
                "raw": line
            }

            entries.append(entry)

        return entries

    def _extract_timestamp(self, line: str) -> str:
        """Extract timestamp from log line."""
        # Try ISO format first: 2024-03-15T10:00:01Z
        iso_match = re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', line)
        if iso_match:
            return iso_match.group(0)

        # Try time only: HH:MM:SS or HH:MM
        time_match = re.search(r'\d{1,2}:\d{2}(?::\d{2})?', line)
        if time_match:
            return time_match.group(0)

        return "unknown"

    def _extract_level(self, line: str) -> str:
        """Extract log level from log line."""
        # Try bracketed format: [INFO], [ERROR], etc.
        bracket_match = re.search(r'\[([A-Z]+)\]', line)
        if bracket_match:
            level = bracket_match.group(1)
            # Normalize if needed
            level = self.LEVEL_ALIASES.get(level, level)
            if level in self.VALID_LEVELS:
                return level

        # Try plain word format at word boundaries
        for valid_level in self.VALID_LEVELS:
            if re.search(r'\b' + valid_level + r'\b', line, re.IGNORECASE):
                return valid_level

        # Check for aliases
        for alias_lower in ['crit', 'warning']:
            if re.search(r'\b' + alias_lower + r'\b', line, re.IGNORECASE):
                normalized = self.LEVEL_ALIASES.get(alias_lower.upper(), alias_lower.upper())
                return normalized

        return "UNKNOWN"

    def _extract_service(self, line: str) -> str:
        """Extract service name from log line."""
        # Try bracketed format: [api-gateway], [payment-service]
        bracket_match = re.search(r'\[([a-z\-]+)\]', line)
        if bracket_match:
            potential_service = bracket_match.group(1)
            # Check if it looks like a service name (contains hyphens or is known)
            if '-' in potential_service or potential_service in self.KNOWN_SERVICES:
                return self._normalize_service(potential_service)

        # Try to find known service names anywhere in line
        for service in self.KNOWN_SERVICES:
            if re.search(r'\b' + re.escape(service) + r'\b', line, re.IGNORECASE):
                return self._normalize_service(service)

        return "unknown"

    def _normalize_service(self, service: str) -> str:
        """Normalize service name using aliases."""
        service_lower = service.lower()
        return self.SERVICE_ALIASES.get(service_lower, service_lower)

    def _extract_message(self, line: str) -> str:
        """Extract message by removing timestamp, level, and service."""
        message = line

        # Remove ISO timestamp if present
        message = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\s*', '', message)

        # Remove bracketed level
        message = re.sub(r'\s*\[[A-Z]+\]\s*', '', message)

        # Remove bracketed service
        message = re.sub(r'\s*\[[a-z\-]+\]\s*', '', message)

        # Remove time-only patterns
        message = re.sub(r'\d{1,2}:\d{2}(?::\d{2})?\s*', '', message)

        # Remove level keywords (plain word format)
        for level in ['ERROR', 'CRITICAL', 'CRIT', 'WARN', 'WARNING', 'INFO', 'DEBUG']:
            message = re.sub(r'\b' + level + r'\b\s*', '', message, flags=re.IGNORECASE)

        # Remove service names
        for service in self.KNOWN_SERVICES:
            message = re.sub(r'\b' + re.escape(service) + r'\b\s*', '', message, flags=re.IGNORECASE)

        # Remove leading punctuation and dashes
        message = re.sub(r'^[\s\-]+', '', message)

        return message.strip()

    def filter_by_severity(self, entries: list[dict], severity: str) -> list[dict]:
        """
        Filter entries by severity level.
        
        Args:
            entries: List of parsed log entries
            severity: "ERROR", "WARN", or "ALL"
            
        Returns:
            Filtered list of entries
        """
        severity = severity.upper()

        if severity == "ALL":
            return entries

        if severity == "ERROR":
            return [e for e in entries if e['level'] in ['ERROR', 'CRITICAL']]

        if severity == "WARN":
            return [e for e in entries if e['level'] in ['ERROR', 'CRITICAL', 'WARN']]

        return entries

    def filter_by_service(self, entries: list[dict], service: str) -> list[dict]:
        """
        Filter entries by service name.
        
        Args:
            entries: List of parsed log entries
            service: Service name to filter by (case insensitive)
            
        Returns:
            Filtered list of entries
        """
        if not service or service.strip() == "":
            return entries

        service_normalized = self._normalize_service(service)
        return [e for e in entries if e['service'].lower() == service_normalized.lower()]

    def get_summary(self, entries: list[dict]) -> dict:
        """
        Generate summary statistics from parsed entries.
        
        Args:
            entries: List of parsed log entries
            
        Returns:
            Dictionary with summary statistics
        """
        summary = {
            "total": len(entries),
            "errors": sum(1 for e in entries if e['level'] in ['ERROR', 'CRITICAL']),
            "warnings": sum(1 for e in entries if e['level'] == 'WARN'),
            "info": sum(1 for e in entries if e['level'] == 'INFO'),
            "unknown": sum(1 for e in entries if e['level'] == 'UNKNOWN'),
            "services": [],
            "time_range": {"start": "unknown", "end": "unknown"}
        }

        # Get unique services (excluding "unknown")
        services = set()
        for entry in entries:
            if entry['service'] != 'unknown':
                services.add(entry['service'])
        summary["services"] = sorted(list(services))

        # Get time range
        timestamps = [e['timestamp'] for e in entries if e['timestamp'] != 'unknown']
        if timestamps:
            summary["time_range"]["start"] = timestamps[0]
            summary["time_range"]["end"] = timestamps[-1]

        return summary

    def get_failure_chain(self, entries: list[dict]) -> list[str]:
        """
        Identify the order in which services first failed.
        
        Args:
            entries: List of parsed log entries
            
        Returns:
            Ordered list of services with their first failure timestamp
        """
        # Track first error timestamp for each service
        first_errors = {}

        for entry in entries:
            if entry['level'] in ['ERROR', 'CRITICAL']:
                service = entry['service']
                if service != 'unknown' and service not in first_errors:
                    first_errors[service] = entry['timestamp']

        # Sort by timestamp (simple string sort works for ISO and HH:MM formats)
        sorted_services = sorted(
            first_errors.items(),
            key=lambda x: x[1] if x[1] != 'unknown' else 'zzz'
        )

        result = []
        for service, timestamp in sorted_services:
            result.append(f"{service} (first failure: {timestamp})")

        return result


if __name__ == "__main__":
    from core.log_loader import LogLoader

    loader = LogLoader()
    processor = LogProcessor()

    print("--- Test 1: Process test.log ---")
    lines = loader.load("logs/test.log")
    entries = processor.process(lines)
    print(f"Total entries parsed: {len(entries)}")
    print(f"Sample entry: {entries[0]}")

    print("\n--- Test 2: Summary ---")
    summary = processor.get_summary(entries)
    print(f"  Total:    {summary['total']}")
    print(f"  Errors:   {summary['errors']}")
    print(f"  Warnings: {summary['warnings']}")
    print(f"  Services: {summary['services']}")
    print(f"  Range:    {summary['time_range']}")

    print("\n--- Test 3: Filter ERROR only ---")
    errors = processor.filter_by_severity(entries, "ERROR")
    print(f"  Error entries: {len(errors)}")
    if errors:
        print(f"  Sample: {errors[0]['message']}")

    print("\n--- Test 4: Filter by service ---")
    db_entries = processor.filter_by_service(entries, "database-service")
    print(f"  database-service entries: {len(db_entries)}")

    print("\n--- Test 5: Failure chain ---")
    chain = processor.get_failure_chain(entries)
    for step in chain:
        print(f"  {step}")

    print("\n--- Test 6: Process historical log ---")
    hist_lines = loader.load("logs/historical/incident_001.log")
    hist_entries = processor.process(hist_lines)
    hist_summary = processor.get_summary(hist_entries)
    print(f"  incident_001: {hist_summary['total']} entries, "
          f"services: {hist_summary['services']}")

    print("\nTask 7 OK")
