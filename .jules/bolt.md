## 2024-06-07 - Pre-compiling Regexes in LogProcessor
**Learning:** `re.search` and `re.sub` inline usage inside `core/log_processor.py` was a significant performance bottleneck due to the sheer volume of log processing loops.
**Action:** Always pre-compile regular expressions in class `__init__` methods (such as in log processing classes) rather than using inline `re.search` or `re.sub` to optimize performance.
