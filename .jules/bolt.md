## 2026-07-03 - Pre-compiled Regexes in LogProcessor
**Learning:** In python, doing multiple independent regex compilations via `re.sub` inline over every item in a loop scales poorly. Trying to combine them all into a single giant `|` separated regex breaks formatting requirements.
**Action:** The fastest pattern that retains backwards compatibility is simply to pre-compile the individual regex patterns sequentially within `__init__` via `re.compile()`, and reuse them iteratively.
