## 2024-05-24 - Pre-compiled Regexes in LogProcessor
**Learning:** The Python application parses logs heavily via regexes internally initialized per operation call. Using raw `re.search` and `re.sub` inline during looping drastically hurts parsing performance.
**Action:** When working on text parsing features in Python loops within this codebase, immediately extract regex calls to pre-compiled `re.Pattern` objects (`re.compile`) inside class constructors to bypass internal cache limitations and object re-creation overhead.
