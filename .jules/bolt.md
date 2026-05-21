## 2026-05-21 - Regex Performance in Parsing Logs
**Learning:** Repetitive regex matching in log files inside loops with inline compilation via `re.search` and `re.sub` is highly inefficient and caused O(n) bottleneck scaling with lines processed.
**Action:** When a method executes regex checks per log line, pre-compile regular expressions as class-level constants using `re.compile()` and replace `re.search` and `re.sub` with `self._PATTERN.search` and `self._PATTERN.sub` for significant performance gains (up to 7x speedup).
