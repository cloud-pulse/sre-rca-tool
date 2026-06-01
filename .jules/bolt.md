
## 2024-05-18 - [Python Regex Compilation Overhead in Loops]
**Learning:** In Python, repeatedly calling `re.search` or `re.sub` inside tight loops (like log file processing per-line) incurs significant overhead due to regex recompilation and cache lookups, even with Python's internal regex caching.
**Action:** Always pre-compile regular expressions using `re.compile()` in class `__init__` methods for any parsing classes that handle large volumes of data line-by-line (e.g. `LogProcessor`).
