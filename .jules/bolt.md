## 2024-06-06 - [Pre-compiling regexes for faster log processing]
**Learning:** Inline `re.search` and `re.sub` calls inside hot loops (like parsing thousands of log lines) add significant overhead.
**Action:** Always pre-compile regexes in the `__init__` method for classes that process large volumes of text.
