## 2026-06-17 - [Log Processing Performance]
**Learning:** Compiling regular expressions repeatedly in loop-heavy log processing methods is a significant performance bottleneck.
**Action:** Pre-compile regular expressions in the class `__init__` method using `re.compile()` and reuse these pattern objects, which can cut parsing time in half.
