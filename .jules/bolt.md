
## 2024-05-30 - [Pre-compile Regular Expressions]
**Learning:** Pre-compiling regular expressions in python is necessary when calling regex processing methods in a tight loop across many iterations, avoiding compilation overhead on every row.
**Action:** Always pre-compile regexes in `__init__` when iterating across data lines.
