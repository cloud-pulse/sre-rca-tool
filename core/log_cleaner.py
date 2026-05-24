class LogCleaner:
    def __init__(self):
        self.health_patterns = [
            "health check: ok",
            "liveness",
            "readiness",
            "get /health",
            "get /metrics",
            "get /ping",
            "get /ready"
        ]

        self.debug_patterns = [
            "token validation successful",
            "forwarding request to",
            "routing paths updated",
            "connected to identity provider"
        ]

        self.keep_patterns = [
            "error", "warn", "crit", "critical",
            "oom", "oomkilled", "restart",
            "circuit breaker", "rollback", "timeout", "exhausted",
            "unreachable", "degraded", "failed"
        ]

    def clean(self, lines: list[str]) -> list[str]:
        cleaned = []
        prev_line_stripped = None
        consecutive_count = 0

        for line in lines:
            line_lower = line.lower()
            stripped = line.strip()

            # Track consecutive duplicates in raw stream
            if prev_line_stripped is not None and stripped == prev_line_stripped:
                consecutive_count += 1
            else:
                consecutive_count = 1
                prev_line_stripped = stripped

            # MUST KEEP (bypasses all dropping rules)
            must_keep = False
            for keep_pattern in self.keep_patterns:
                if keep_pattern in line_lower:
                    must_keep = True
                    break

            if must_keep:
                cleaned.append(line)
                continue

            # Rule 1: HEALTH PROBES
            is_health_probe = False
            for hp in self.health_patterns:
                if hp in line_lower:
                    is_health_probe = True
                    break
            if is_health_probe:
                continue

            # Rule 2: PURE METRICS LINES
            if "metrics" in line_lower:
                continue

            # Rule 4: DEBUG NOISE
            is_info = "[info]" in line_lower or " info " in line_lower
            if is_info:
                is_debug_noise = False
                for dp in self.debug_patterns:
                    if dp in line_lower:
                        is_debug_noise = True
                        break
                if is_debug_noise:
                    continue

            # Rule 3: REPEATED CONSECUTIVE DUPLICATES
            if consecutive_count > 3:
                continue

            cleaned.append(line)

        return cleaned

    def get_stats(self, original: list[str], cleaned: list[str]) -> dict:
        original_count = len(original)
        cleaned_count = len(cleaned)
        removed_count = original_count - cleaned_count
        removal_percent = round((removed_count / original_count * 100) if original_count else 0.0, 1)

        return {
            "original_count": original_count,
            "cleaned_count": cleaned_count,
            "removed_count": removed_count,
            "removal_percent": removal_percent
        }
