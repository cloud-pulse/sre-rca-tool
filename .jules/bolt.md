## 2026-06-14 - Pre-compile Regex in LogProcessor
**Learning:** Parsing and compiling regular expressions inline on every method call incurs significant overhead in highly iterated methods, such as those processing logs line-by-line.
**Action:** Pre-compile regular expressions in the class `__init__` method using `re.compile()` and reference them to avoid redundant parsing and compilation.
