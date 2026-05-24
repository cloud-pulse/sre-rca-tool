## 2024-05-24 - Precompile Log Processing Regexes
**Learning:** Recompiling regexes inside of processing loops (especially across thousands of log lines) acts as a massive bottleneck in Python.
**Action:** When handling logs or frequent loop iterations, always initialize and precompile combined regex patterns (e.g., in `__init__`) rather than dynamically generating or searching with inline `re.search/sub`.
