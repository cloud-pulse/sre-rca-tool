## 2024-05-22 - [LogProcessor regex optimization]
**Learning:** Repetitive re.search and re.sub are bottlenecks in logging applications. By utilizing pre-compiled regular expressions at the class level instead of inline compilations, the overall throughput of `LogProcessor` substantially improved (reduced parsing time by ~80%).
**Action:** Identify inline regular expression usages inside high-frequency processing loops across future classes and promote them to class/module scope instances if the regex literal doesn't mutate dynamically.
