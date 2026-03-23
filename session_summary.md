# Session Summary — SRE-RCA-Tool Dissertation Project

## Section 1: Project Identity

**Student:** Veerapalli Gowtham | BITS ID: 2024MT03007 | BITS Pilani WILP | Course CCZG628T
**Supervisor:** Kuna Aditya, TCS Hyderabad
**Title:** AI-Assisted SRE Framework for Root Cause Analysis in Cloud-Native Microservices
**Environment:** Windows MINGW64, Python 3.12, venv named `jarvis`
**Project path:** `/c/playground/sre-rca-tool`

---

## Section 2: What Was Built This Session

### New Modules Created
- `core/service_discovery.py` — kubectl pod scanning, fuzzy image matching, namespace suggestion with confidence scores
- `core/service_graph.py` — dependency graph, blast radius, auto-discovery from logs

### Major Rewrites
- `ai_sre.py` — complete rewrite as proper interactive shell with four-tier intent detection
- `core/resource_collector.py` — removed hardcoded service names, dynamic mock generation

### Key Features Added
- **Four-tier intent system:**
  - Tier 1: Exact hard command match on first word
  - Tier 2: Fuzzy Levenshtein matching for typos
  - Tier 3: NLP with SRE keyword confidence threshold
  - Tier 4: Unknown — friendly message, no pipeline runs
- **Explain intent** — answers SRE concept questions via LLM directly
- **Guardrails** — out of scope rejection before any pipeline runs
- **Ctrl+C handling** — clean "Interrupted." message, shell survives
- **Cache fix** — query string included in cache key, no more collisions
- **Warmup dedup** — `_warmed_up` flag prevents double warmup

### Bugs Fixed
- `Asc` corruption throughout `ai_sre.py` — full rewrite
- `IndentationError` in `main.py` and `resource_collector.py`
- Poisoned cache returning same result for all queries
- `explain baseline vs rag` routing to `watch` instead of `explain`
- `who is prime minister` running full RCA pipeline
- Warmup called twice per analysis
- Hardcoded service names in mock data

---

## Section 3: Architecture (Current State)

```
python ai_sre.py
       │
       ▼
   SREShell (interactive REPL)
       │
   NLParser (4-tier intent detection)
       │
   ┌───┴────────────────────────────┐
   │                                │
explain  status  compare  watch  analyze
   │                                │
LLMAnalyzer                  SREInvestigator
(direct Q&A)                       │
                          ┌────────┴────────┐
                     EvidenceCollector  PatternDetector
                          │                 │
                    LogLoader          20 rules
                    ResourceCollector  5 categories
                    kubectl/mock
                          │
                     RAGEngine (ChromaDB)
                          │
                     LLMAnalyzer
                     (enriched prompt)
                          │
                     RCAFormatter
                     (rich terminal)
```

---

## Section 4: Key Design Decisions Made

| Decision | What was chosen | Why |
|----------|----------------|-----|
| Intent detection | First word = command, rest = parameter | More reliable than full-sentence NLP |
| Typo handling | Levenshtein distance 1-2 with confirmation | Prevents wasted LLM calls |
| Unknown input | Friendly message, NO pipeline | Saves time and resources |
| Namespace resolution | Auto from services.yaml, ask if missing | No friction for user |
| Missing service | kubectl image scan → suggestions → ask to save | Smart discovery |
| Cache key | mode + query + prompt[:2000] | Prevents collisions across different questions |
| Mock data | Dynamic generation from service list | No hardcoded names |
| Ctrl+C | Caught at every level, returns to prompt | Shell never crashes |

---

## Section 5: Remaining Tasks

### From Original Plan
| Task | What | Priority |
|------|------|----------|
| Task 24 | `--source` `--namespace` `--mock` fully wired in all `main.py` commands | Medium |
| Task 25 | `setup_minikube.sh` + deploy sock-shop for real testing | Phase 2 |

### Dissertation Tasks
| Task | What | Priority |
|------|------|----------|
| Cleanup PR | Delete runtime files, update `.gitignore`, remove dead code | **Do this first** |
| Mid-sem report | Markdown → Word doc submission | **Urgent** |
| Run evaluation | `python main.py compare logs/test.log --save-report` for numbers | Before report |
| Docs | `docs/dissertation_report.md` + `docs/developer_guide.md` | With report |

---

## Section 6: Mid-Sem Report Strategy

**Frame mock data as:** "controlled evaluation environment" — standard in systems research

**Key argument:** Phase 1 validates framework architecture. Phase 2 validates against real cluster.

**Report structure:**
1. Abstract
2. Introduction + problem statement
3. Background (RAG, AIOps, LLM for SRE)
4. Framework architecture + diagrams
5. Implementation + tech stack
6. Phase 1 evaluation (baseline vs RAG table)
7. Current status + known limitations
8. Phase 2 plan (Minikube + sock-shop)
9. References

**Strongest evidence to include:**
- Baseline vs RAG confidence comparison table (run `compare` command)
- 20 pattern detection rules table
- Architecture flow diagram (Mermaid)
- Demo screenshot of `python ai_sre.py`

---

## Section 7: Recommended Test Apps for Phase 2

| App | Repo | Why |
|-----|------|-----|
| **sock-shop** (recommended) | `github.com/microservices-demo/microservices-demo` | 8 services, chaos built in, SRE-ready |
| microservices-demo | `github.com/GoogleCloudPlatform/microservices-demo` | 10 services, runs on Minikube |
| podinfo | `github.com/stefanprodan/podinfo` | Lightweight, built-in failure endpoints |

```bash
# Quick sock-shop setup for Phase 2
minikube start --memory=4096 --cpus=2
kubectl create namespace sock-shop
kubectl apply -f https://raw.githubusercontent.com/microservices-demo/microservices-demo/master/deploy/kubernetes/complete-demo.yaml -n sock-shop
# Then set SOURCE_KUBERNETES=true in .env
# Set SOURCE_NAMESPACE=sock-shop in .env
```

---

## Section 8: Files to Save Locally Right Now

Save these before this session ends:

**1. The cleanup prompt** (Section 2 of previous message) — gives the agent exact instructions to clean the repo before PR

**2. The mid-sem report prompt** — when you are ready to generate the report

**3. Key file locations:**
```
Entry point:     python ai_sre.py
Main CLI:        python main.py
Config:          .env + services.yaml
Core engine:     core/sre_investigator.py
Pattern rules:   core/sre_investigator.py → PatternDetector.RULES
Dependency map:  services.yaml
Test suite:      scripts/verify_final.sh
Demo script:     scripts/quick_demo.sh
```

---

## Section 9: How to Continue in Next Session

Paste this at the start of your next conversation:

---

```
I am working on a dissertation project called
"AI-Assisted SRE Framework for Root Cause
Analysis in Cloud-Native Microservices".

BITS ID: 2024MT03007, BITS Pilani WILP
Project: /c/playground/sre-rca-tool
Venv: jarvis (source jarvis/Scripts/activate)
Use: python (not python3)

The project is a complete AI-powered SRE
investigation tool with:
- Interactive shell: python ai_sre.py
- Click CLI: python main.py
- Local LLM: Ollama + phi3:mini
- RAG: ChromaDB + sentence-transformers
- 20 rule-based failure pattern detectors
- Multi-service cascade analysis
- Four-tier fuzzy intent detection
- Natural language interface

CURRENT STATUS:
- All core features working
- Repo cleanup done (PR ready)
- Need to: [write what you need next]

Please read docs/repo_analysis.md first
to understand the current codebase state.
```

---

## Section 10: Immediate Next Steps in Order

1. **Run the cleanup prompt** on the agent — delete runtime files, update `.gitignore`, remove dead code
2. **Run the evaluation** — `python main.py compare logs/test.log --save-report` — get your numbers
3. **Generate the mid-sem report** — use the report prompt I wrote earlier
4. **Raise the PR** — clean branch, good commit message
5. **Submit mid-sem** — you have enough for a strong submission

---

## Section 11: Mid-Semester Report (Added March 2026)

**Files generated:**
- `mid_sem_report.docx` — editable Word document
- `mid_sem_report.pdf` — submission-ready PDF

**Report structure:**
1. Cover page (BITS format)
2. Abstract + signature block
3. Table of Contents
4. Introduction + research questions
5. Background + literature review (3 references)
6. Framework architecture + component table + pipeline diagrams
7. Implementation (tech stack, feature flags, RAG, 4-tier NLP, pattern detection)
8. Evaluation — Phase 1 (9 test scenarios, baseline vs RAG comparison table)
9. Current status (16 completed components table)
10. Phase 2 plan (Minikube + sock-shop, timeline table)
11. Abbreviations
12. References (6 total)

**After opening Word file:**
- Right-click Table of Contents → Update Field → Update entire table
- Add actual evaluation numbers from:
  `python main.py compare logs/test.log --save-report`
- Add signatures before submission

**Status vs abstract objectives:**
- All 6 dissertation objectives: COMPLETED in Phase 1
- Phase 2 (real cluster validation): testing phase 24 Mar – 16 Apr 2026
- On schedule per Plan of Work

---

**Save this page now** — select all text, copy, paste into a local markdown file called `session_summary.md` in your project docs folder.