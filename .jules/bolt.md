## 2024-05-29 - Pre-compiling combined regular expressions in log parsing
**Learning:** In highly repetitive operations like log parsing (`LogProcessor`), using inline `re.search` and `re.sub` for every line causes massive overhead. Combining multiple removal patterns into a single big regex using the OR operator `|` and compiling it in the class `__init__` yielded a ~75% speedup (from 0.68s down to 0.14s for 10k lines).
**Action:** When parsing thousands of log lines, always compile regexes in `__init__` and combine redundant replacement/matching steps into single patterns.
