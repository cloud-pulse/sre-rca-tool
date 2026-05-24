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

import re
from datetime import datetime
from typing import Optional
from core.logger import get_logger

log = get_logger("log_processor")

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

    def __init__(self):
        # Precompile extraction regexes
        self.ISO_REGEX = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
        self.TIME_REGEX = re.compile(r'\d{1,2}:\d{2}(?::\d{2})?')
        self.BRACKET_LEVEL_REGEX = re.compile(r'\[([A-Z]+)\]')
        self.BRACKET_SERVICE_REGEX = re.compile(r'\[([a-z\-]+)\]')

        # Combine valid levels into a single regex pattern
        self.LEVELS_REGEX = re.compile(r'\b(?:' + '|'.join(self.VALID_LEVELS) + r')\b', re.IGNORECASE)
        self.ALIASES_REGEX = re.compile(r'\b(?:crit|warning)\b', re.IGNORECASE)

        # Combine known services into a single regex pattern
        services = [re.escape(svc) for svc in self.KNOWN_SERVICES]
        self.SERVICES_REGEX = re.compile(r'\b(?:' + '|'.join(services) + r')\b', re.IGNORECASE)

        # Precompile message cleanup regexes
        self.MSG_ISO_REGEX = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\s*')
        self.MSG_BRACKET_LEVEL = re.compile(r'\s*\[[A-Z]+\]\s*')
        self.MSG_BRACKET_SERVICE = re.compile(r'\s*\[[a-z\-]+\]\s*')
        self.MSG_TIME = re.compile(r'\d{1,2}:\d{2}(?::\d{2})?\s*')

        levels = ['ERROR', 'CRITICAL', 'CRIT', 'WARN', 'WARNING', 'INFO', 'DEBUG']
        self.MSG_LEVELS = re.compile(r'\b(?:' + '|'.join(levels) + r')\b\s*', re.IGNORECASE)

        self.MSG_SERVICES = re.compile(r'\b(?:' + '|'.join(services) + r')\b\s*', re.IGNORECASE)

        self.MSG_LEAD_PUNCT = re.compile(r'^[\s\-]+')

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
        iso_match = self.ISO_REGEX.search(line)
        if iso_match:
            return iso_match.group(0)

        time_match = self.TIME_REGEX.search(line)
        if time_match:
            return time_match.group(0)

        return "unknown"

    def _extract_level(self, line: str) -> str:
        """Extract log level from log line."""
        bracket_match = self.BRACKET_LEVEL_REGEX.search(line)
        if bracket_match:
            level = bracket_match.group(1)
            level = self.LEVEL_ALIASES.get(level, level)
            if level in self.VALID_LEVELS:
                return level

        level_match = self.LEVELS_REGEX.search(line)
        if level_match:
            return level_match.group(0).upper()

        alias_match = self.ALIASES_REGEX.search(line)
        if alias_match:
            alias = alias_match.group(0).upper()
            return self.LEVEL_ALIASES.get(alias, alias)

        return "UNKNOWN"

    def _extract_service(self, line: str) -> str:
        """Extract service name from log line."""
        bracket_match = self.BRACKET_SERVICE_REGEX.search(line)
        if bracket_match:
            potential_service = bracket_match.group(1)
            if '-' in potential_service or potential_service in self.KNOWN_SERVICES:
                return self._normalize_service(potential_service)

        service_match = self.SERVICES_REGEX.search(line)
        if service_match:
            return self._normalize_service(service_match.group(0))

        return "unknown"

    def _normalize_service(self, service: str) -> str:
        """Normalize service name using aliases."""
        service_lower = service.lower()
        return self.SERVICE_ALIASES.get(service_lower, service_lower)

    def _extract_message(self, line: str) -> str:
        """Extract message by removing timestamp, level, and service."""
        message = line
        message = self.MSG_ISO_REGEX.sub('', message)
        message = self.MSG_BRACKET_LEVEL.sub('', message)
        message = self.MSG_BRACKET_SERVICE.sub('', message)
        message = self.MSG_TIME.sub('', message)
        message = self.MSG_LEVELS.sub('', message)
        message = self.MSG_SERVICES.sub('', message)
        message = self.MSG_LEAD_PUNCT.sub('', message)
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
