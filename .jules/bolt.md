## 2024-06-21 - [Pre-compiling Regex in Log Processor]
**Learning:** Initializing and executing regular expressions via inline `re.search` and `re.sub` functions directly within log extraction methods introduces significant performance bottlenecks, especially when processing large batches of logs.
**Action:** Always pre-compile regular expressions using `re.compile()` within class `__init__` methods for any class tasked with iterative or batch log processing.
