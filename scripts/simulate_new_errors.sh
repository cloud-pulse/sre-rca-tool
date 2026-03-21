#!/bin/bash
# Simulates new errors appearing in the log file
# Run this in a SECOND terminal while watch runs

LOG_FILE="${1:-logs/test.log}"
echo "Appending test errors to $LOG_FILE..."
sleep 5

echo "2024-03-15T10:25:00Z [ERROR] \
[database-service] NEW: connection pool \
exhausted again" >> "$LOG_FILE"

echo "2024-03-15T10:25:01Z [ERROR] \
[payment-service] NEW: failed to process \
transaction txn_99999" >> "$LOG_FILE"

echo "2024-03-15T10:25:02Z [ERROR] \
[api-gateway] NEW: circuit breaker \
triggered again" >> "$LOG_FILE"

echo "Done. Watch should detect these errors."