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
        """Initialize log processor configuration."""
        self.re_iso_time = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
        self.re_time = re.compile(r'\d{1,2}:\d{2}(?::\d{2})?')
        self.re_bracket_level = re.compile(r'\[([A-Z]+)\]')

        valid_level_pattern = r'\b(' + '|'.join(self.VALID_LEVELS) + r')\b'
        self.re_valid_levels = re.compile(valid_level_pattern, re.IGNORECASE)
        self.re_alias_levels = re.compile(r'\b(crit|warning)\b', re.IGNORECASE)

        self.re_bracket_service = re.compile(r'\[([a-z\-]+)\]')

        known_service_pattern = r'\b(' + '|'.join(map(re.escape, self.KNOWN_SERVICES)) + r')\b'
        self.re_known_services = re.compile(known_service_pattern, re.IGNORECASE)

        self.re_msg_cleanups = [
            re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\s*'),
            re.compile(r'\s*\[[A-Z]+\]\s*'),
            re.compile(r'\s*\[[a-z\-]+\]\s*'),
            re.compile(r'\d{1,2}:\d{2}(?::\d{2})?\s*'),
            re.compile(r'\b(?:' + '|'.join(['ERROR', 'CRITICAL', 'CRIT', 'WARN', 'WARNING', 'INFO', 'DEBUG']) + r')\b\s*', re.IGNORECASE),
            re.compile(r'\b(?:' + '|'.join(map(re.escape, self.KNOWN_SERVICES)) + r')\b\s*', re.IGNORECASE),
            re.compile(r'^[\s\-]+')
        ]

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
        m = self.re_iso_time.search(line)
        if m: return m.group(0)
        m = self.re_time.search(line)
        if m: return m.group(0)
        return "unknown"

    def _extract_level(self, line: str) -> str:
        """Extract log level from log line."""
        m = self.re_bracket_level.search(line)
        if m:
            level = m.group(1)
            level = self.LEVEL_ALIASES.get(level, level)
            if level in self.VALID_LEVELS:
                return level

        m = self.re_valid_levels.search(line)
        if m:
            return m.group(1).upper()

        m = self.re_alias_levels.search(line)
        if m:
            alias_lower = m.group(1).lower()
            return self.LEVEL_ALIASES.get(alias_lower.upper(), alias_lower.upper())

        return "UNKNOWN"

    def _extract_service(self, line: str) -> str:
        """Extract service name from log line."""
        m = self.re_bracket_service.search(line)
        if m:
            potential = m.group(1)
            if '-' in potential or potential in self.KNOWN_SERVICES:
                return self._normalize_service(potential)

        m = self.re_known_services.search(line)
        if m:
            return self._normalize_service(m.group(1))

        return "unknown"

    def _normalize_service(self, service: str) -> str:
        """Normalize service name using aliases."""
        service_lower = service.lower()
        return self.SERVICE_ALIASES.get(service_lower, service_lower)

    def _extract_message(self, line: str) -> str:
        """Extract message by removing timestamp, level, and service."""
        message = line
        for regex in self.re_msg_cleanups:
            message = regex.sub('', message)
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
        total = len(entries)
        errors = 0
        warnings = 0
        info = 0
        unknown = 0
        services = set()
        start_time = "unknown"
        end_time = "unknown"

        for e in entries:
            lvl = e['level']
            if lvl in ('ERROR', 'CRITICAL'): errors += 1
            elif lvl == 'WARN': warnings += 1
            elif lvl == 'INFO': info += 1
            elif lvl == 'UNKNOWN': unknown += 1

            svc = e['service']
            if svc != 'unknown':
                services.add(svc)

            ts = e['timestamp']
            if ts != 'unknown':
                if start_time == "unknown":
                    start_time = ts
                end_time = ts

        summary = {
            "total": total,
            "errors": errors,
            "warnings": warnings,
            "info": info,
            "unknown": unknown,
            "services": sorted(list(services)),
            "time_range": {"start": start_time, "end": end_time}
        }
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
