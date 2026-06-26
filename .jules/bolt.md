## 2024-05-15 - [Pre-compiling Regex in Log Processor]
**Learning:** `core/log_processor.py` was using `re.search` and `re.sub` extensively within loops for processing log lines. Pre-compiling the regex patterns significantly improves log parsing performance.
**Action:** When a Python script uses regular expressions repeatedly (e.g., inside a loop), pre-compile the patterns in the `__init__` method of the class to avoid recompiling them on every function call.
