## 2026-06-04 - Pre-compile Regex Patterns
**Learning:** Compiling regular expressions inline in frequent string processing loops (like log processing) adds significant overhead.
**Action:** Pre-compile regular expressions in class `__init__` methods rather than using inline `re.search` or `re.sub` to optimize performance.
