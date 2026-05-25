## 2026-05-25 - Regex Compilation in LogProcessor
**Learning:** Compiling regex patterns repeatedly inside loops is a huge performance hit when processing large files.
**Action:** When a regex is used multiple times inside a loop, extract and pre-compile it into a class attribute or module-level variable to improve performance.
