## 2024-06-25 - Pre-compiling RegEx in LogProcessor
**Learning:** The `LogProcessor` class heavily relies on inline `re.search` and `re.sub` within loops (especially for log parsing line-by-line). This causes significant performance overhead for high-volume logs due to regex compilation during iteration.
**Action:** Pre-compile all regular expressions within the `__init__` method of the `LogProcessor` class.
