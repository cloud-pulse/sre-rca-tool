## 2024-06-10 - Pre-compiling Regex in Python
**Learning:** In Python, repeatedly compiling regular expressions using inline `re.search` or `re.sub` within tight loops (like log processing where millions of lines might be parsed) introduces significant overhead.
**Action:** Always pre-compile regular expressions using `re.compile()` in the class `__init__` method and reuse the compiled regex objects.
