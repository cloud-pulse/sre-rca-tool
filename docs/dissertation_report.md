# AI-Assisted SRE Framework for Root Cause Analysis in Cloud-Native Microservices

**Student:** Veerapalli Gowtham (BITS ID: 2024MT03007)  
**Program:** M.Tech (Cloud Computing), BITS Pilani WILP  
**Project Repository:** `sre-rca-tool`

---

## 1. Abstract
Modern Kubernetes incidents require correlating logs, pod events, metrics, deployment history, endpoints, and service dependencies under strict time pressure. This project implements an AI-assisted SRE framework that automates this workflow for microservices using two operational modes: file-based analysis and live kubectl evidence analysis. The implementation combines staged evidence collection (`core/kubectl_rca_investigator.py`), rule-based pattern detection, LLM reasoning (`core/llm_provider.py`), and retrieval-augmented incident memory through ChromaDB (`core/rag_engine.py`, `core/incident_recorder.py`). A command-registry interactive shell (`ai_sre.py` + `core/command_registry.py`) provides analyst-friendly operations such as `analyse`, `--baseline`, `--compare`, and `chat`. The framework introduces confidence-aware sliding-window analysis (`core/window_analyzer.py`) and automatic incident recording with similarity gating to avoid duplicate historical entries. Current evaluation assets include mock kubectl scenarios and generated comparison reports under `reports/` and `logs/baseline/`. The implemented architecture demonstrates a practical path to reduce SRE toil and improve mean-time-to-resolution (MTTR) while preserving transparent, auditable RCA outputs for academic and operational contexts.

---

## 2. Introduction

### 2.1 Problem statement
Manual root cause analysis in Kubernetes microservices is slow because engineers must manually correlate distributed evidence from multiple control-plane and application sources.

### 2.2 Motivation
- Reduce repetitive SRE toil.
- Improve MTTR by automating evidence gathering and first-pass diagnosis.
- Preserve investigation consistency across repeated incidents.

### 2.3 Objectives
1. Build an end-to-end RCA assistant with interactive CLI UX.
2. Support both file-mode and live kubectl-mode analysis.
3. Integrate historical incident retrieval and similarity-based memory.
4. Provide explainable outputs (confidence, reason, ranked fixes, known/new incident decision).

---

## 3. Literature Review

### 3.1 Existing SRE tools
Platforms such as Dynatrace, Datadog, PagerDuty, and New Relic provide strong observability and alerting. However, practical RCA often still requires human correlation across metrics, logs, topology, and deployment context, especially in custom microservice environments.

### 3.2 RAG in operations
RAG provides contextual retrieval from historical operational records, enabling incident-specific reasoning rather than generic model output. In this project, historical incidents are vector-indexed and reused during triage.

### 3.3 LLM-assisted incident management
LLMs can synthesize narrative RCA, failure chains, and remediation plans from mixed evidence. The key challenge is controlling hallucination and confidence quality, addressed here via structured prompts, confidence extraction, and pattern-based grounding.

### 3.4 Gap addressed by this work
This repository contributes a code-level integration of:
- staged Kubernetes evidence collection,
- rule-based pattern detection,
- confidence-aware LLM RCA,
- incident-memory reuse and deduplication,
all in a single interactive SRE workflow.

---

## 4. System Design and Architecture

### 4.1 Real architecture from implementation
Primary interactive path:
1. `ai_sre.py` prompt loop
2. `core.command_registry.resolve()`
3. Command handler (`AnalyseHandler` etc.)
4. Pipeline execution (file or kubectl)
5. Output rendering and `.last_rca.json` persistence

### 4.2 Component diagram (textual)
- `flags.py`: environment/config flags
- `core/log_loader.py`, `core/log_processor.py`, `core/log_cleaner.py`: input normalization
- `core/service_graph.py`: service topology + blast radius
- `core/kubectl_client.py`, `core/kubectl_rca_investigator.py`: live evidence layer
- `core/llm_provider.py`, `core/llm_analyzer.py`: reasoning and prompt/parse layer
- `core/rag_engine.py`, `core/incident_recorder.py`: historical memory and similarity
- `output/rca_formatter.py`, `evaluation/comparator.py`: presentation/evaluation

### 4.3 Two operating modes
- **File mode:** uses local log files (`logs/services/*.log` or `logs/test.log`) and sliding-window analysis.
- **Kubectl mode:** uses live `kubectl` evidence collection and LLM narrative generation with optional baseline/compare execution.

### 4.4 RAG pipeline design
Current code path (`analyse` in file mode):
`WindowAnalyzer.analyse()` → confidence extraction → `IncidentRecorder.check_and_save()` → similarity query against ChromaDB → save/embed if new.

### 4.5 Kubectl RCA pipeline design (7 stages)
Implemented in `KubectlRCAInvestigator.investigate(...)`:
1. Pod Status
2. Pod Events
3. Pod Logs
4. Cluster Resource Pressure
5. Node Describe (stage 4b in code)
6. Service Endpoints
7. VirtualService (Istio, when present)

Then `collect_all_evidence(report)` assembles LLM prompt material.

### 4.6 Dependency analysis design
- Static source: `services.yaml` (`depends_on`, `exposes_to`).
- Runtime enrichment: `ServiceGraph.discover_from_logs(...)` attempts to discover new dependencies from log patterns.
- Impact model: `ServiceGraph.get_blast_radius(...)` provides downstream/upstream/safe service sets.

### 4.7 Incident recording and similarity detection
- Similarity computed in `IncidentRecorder._query_similarity(...)`.
- Thresholded known/new decision in `check_and_save(...)`.
- New incidents saved to `logs/historical/incident_*.log` and embedded into ChromaDB.

---

## 5. Implementation

### 5.1 Tech stack and rationale
- Python 3.12: consistent runtime for CLI + data processing.
- Rich/Click: robust terminal UX and command ergonomics.
- ChromaDB: lightweight local vector store with persistent path `.chromadb`.
- NVIDIA NIM / Ollama abstraction: provider flexibility via `LLMProvider`.
- YAML-driven topology (`services.yaml`): explicit service dependency model.

### 5.2 Key implementation decisions
- **Sliding window (`WindowAnalyzer`)**: avoids oversized prompts while allowing confidence-based expansion.
- **ChromaDB-based memory**: enables retrieval of prior incident context and duplicate suppression.
- **Pattern detection before LLM (`PATTERNS`)**: raises grounded confidence and triage speed.
- **Collect-all-evidence approach**: kubectl pipeline gathers broad context before LLM call, reducing premature conclusions.

### 5.3 Challenges and solutions
- **Embedding/vector dimension mismatch:** handled by `_is_dim_error()` and `_purge_and_reload()` in `IncidentRecorder`.
- **Embedding consistency:** incident query and write paths both use `provider.embed(...)`.
- **Design evolution:** moved toward evidence-complete collection before narrative generation in kubectl mode.

---

## 6. Evaluation

### 6.1 Demo scenarios
A `demo-scenarios.yaml` file is not present in the current repository snapshot. Operational scenarios are inferred from mock kubectl assets and `_detect_mock_scenario(...)` mapping in `core/sre_investigator.py`.

Core failure scenarios used in code/demo flow:
1. `oom-killed`
2. `secret-missing`
3. `image-pull-backoff`
4. `pvc-not-bound`
5. `probe-failure`
6. `node-pressure`
7. `istio-crash`

(Additional application-level fallback scenario: `connection-pool-exhaustion`.)

### 6.2 Expected RCA outputs per scenario
For each scenario, expected output structure includes:
- root cause statement,
- confidence score and reason,
- ranked remediation steps,
- known/new incident decision (`incident_record`).

### 6.3 RAG similarity improvement
- `analyse --compare` and `evaluation/comparator.py` are implemented to compare baseline vs RAG.
- Comparison artifacts are stored in `reports/compare_*.txt`.
- Baseline snapshots for kubectl mode are stored under `logs/baseline/`.

### 6.4 Confidence scoring methodology
- Confidence is extracted from LLM output block (`CONFIDENCE: <n>%`) using regex in `WindowAnalyzer` and command handlers.
- Sliding-window reanalysis is triggered when confidence is below threshold (default 60).

---

## 7. Results and Discussion

### 7.1 What works well
- Unified shell UX (`ai_sre.py`) for SRE workflows.
- Repeat-incident handling with similarity gating and automatic historical save for new incidents.
- Practical compare mode for dissertation demonstration (`--compare`).
- Kubernetes evidence stages implemented and auditable.

### 7.2 Current limitations
- No formal automated test suite directory yet.
- Some legacy paths in `main.py` coexist with the command-registry flow.
- Scenario definitions are file-driven and inferred; no centralized `demo-scenarios.yaml` contract in current snapshot.

### 7.3 File mode vs kubectl mode (accuracy discussion)
- File mode depends on available log completeness and parser quality.
- Kubectl mode has richer evidence breadth (events, endpoints, node info), usually yielding better contextual RCA potential.
- Comparative quality is measured through implemented confidence delta and report outputs, not yet a statistically complete benchmark in this snapshot.

---

## 8. Conclusion and Future Work

### 8.1 Contributions summary
This work delivers a functioning AI-assisted SRE RCA framework with command-driven UX, dual execution modes, historical incident memory, confidence-aware analysis, and explicit remediation output.

### 8.2 Future directions
1. Multi-cluster and multi-namespace federation support.
2. Incident workflow integration (Slack/PagerDuty/Jira) for operational handoff.
3. Guided auto-remediation and policy-controlled runbooks.
4. Domain-tuned SRE model strategies (fine-tuned or tool-augmented).

---

## 9. References

1. Google. *Site Reliability Engineering: How Google Runs Production Systems*. O’Reilly, 2016.
2. Kubernetes Documentation. https://kubernetes.io/docs/
3. ChromaDB Documentation. https://docs.trychroma.com/
4. Lewis et al. “Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.” NeurIPS, 2020.
5. OpenAI-compatible API and NVIDIA NIM documentation (as used by `LLMProvider`).