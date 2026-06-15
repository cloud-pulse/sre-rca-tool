## 2024-05-18 - Pre-compile Regex in LogProcessor
**Learning:** Inline regex compilation in tight loops like log processing causes significant overhead. Pre-compiling regexes in the class __init__ speeds up processing by >50%.
**Action:** Always pre-compile regexes in class constructors when they will be applied to many lines iteratively.
