# Final M.Tech Demo Presentation Script

## Opening (2 min)

### How to introduce yourself and project
"Good [morning/afternoon], I am Veerapalli Gowtham, BITS ID 2024MT03007 from BITS Pilani WILP, M.Tech Cloud Computing. My dissertation project is an AI-Assisted SRE framework for root cause analysis in Kubernetes microservices."

### Hook sentence
"This tool turns a multi-hour, manual Kubernetes incident investigation into a structured RCA in minutes, with confidence scoring and historical incident memory."

### Problem + why now
"Microservice systems fail in complex chains: logs, pod events, metrics, and dependency impact are scattered. SRE teams are under pressure to reduce MTTR while deployments increase. This project addresses that exact operational gap with an AI-guided and evidence-driven RCA workflow."

---

## Demo flow (15 min)

> Use the interactive shell (`python ai_sre.py`).

### 1) Start tool
**WHAT TO TYPE**
```bash
python ai_sre.py
```
**AUDIENCE WILL SEE**
- AI-SRE banner from `print_banner()`.
- Prompt `ai-sre>`.
**WHAT TO SAY**
"This is the single entry point for investigation. Commands are resolved by a registry pattern, not hardcoded if-else routing."

### 2) Check health
**WHAT TO TYPE**
```text
status
```
**AUDIENCE WILL SEE**
- Rich table from `StatusHandler` showing Python, venv, provider, ChromaDB, source mode, cache, and last RCA status.
**WHAT TO SAY**
"Before RCA, I verify runtime readiness: model provider, vector DB, service graph, and operating mode."

### 3) Healthy service case
**WHAT TO TYPE**
```text
analyse currencyservice
```
**AUDIENCE WILL SEE**
- RCA output panel from `_print_analysis_result`.
- Confidence and incident save decision.
**WHAT TO SAY**
"This is a positive/healthy baseline. It demonstrates the tool does not force a failure claim when evidence is weak or healthy."

### 4) Payment service RCA
**WHAT TO TYPE**
```text
analyse paymentservice
```
**AUDIENCE WILL SEE**
- Detailed RCA text + confidence.
- Incident metadata: `Incident saved`, `Similarity`.
**WHAT TO SAY**
"Payment service shows memory/config symptoms such as OOMKilled or container config failures depending on evidence. The analysis includes confidence and remediation guidance."

### 5) Crash loop case
**WHAT TO TYPE**
```text
analyse cartservice
```
**AUDIENCE WILL SEE**
- RCA for repeated crash behavior (CrashLoopBackOff-like patterning).
**WHAT TO SAY**
"Now we see a crash loop style failure, demonstrating category coverage beyond memory-only incidents."

### 6) Init/config failure case
**WHAT TO TYPE**
```text
analyse emailservice
```
**AUDIENCE WILL SEE**
- RCA output highlighting startup/config or dependency initialization signals.
**WHAT TO SAY**
"This case represents early container startup/config faults, which often surface as init-related failures."

### 7) Re-run payment service (RAG memory behavior)
**WHAT TO TYPE**
```text
analyse paymentservice
```
**AUDIENCE WILL SEE**
- `Similarity` increases vs prior incident.
- `Incident saved: No` when treated as known incident.
**WHAT TO SAY**
"This is the MTTR story: repeated incidents are recognized via similarity in ChromaDB, so we avoid duplicate triage and preserve historical learning."

### 8) Baseline vs RAG comparison
**WHAT TO TYPE**
```text
analyse paymentservice --compare
```
**AUDIENCE WILL SEE**
- RAG result + baseline result.
- Confidence delta summary panel.
- Report path like `reports/compare_<service>_<timestamp>.txt`.
**WHAT TO SAY**
"This demonstrates measurable difference between context-free baseline and memory-augmented RCA. It is useful for dissertation evaluation and reproducibility."

### 9) Follow-up Q&A mode
**WHAT TO TYPE**
```text
chat
```
**AUDIENCE WILL SEE**
- Interactive incident-grounded Q&A.
- Guardrails for out-of-scope prompts.
**WHAT TO SAY**
"After automated RCA, SREs usually ask follow-up questions. Chat reuses last RCA context and keeps discussion incident-focused."

---

## Key talking points per feature

### Why RAG instead of only LLM
- LLM-only answers can be generic and forget past operational context.
- RAG adds historical incident memory from `logs/historical` indexed in ChromaDB.
- Incident similarity helps decision speed on repeat patterns.

### Why kubectl live mode over log files
- File mode may miss control-plane evidence.
- Kubectl mode adds pod status/events, node details, endpoints, and virtual service checks.
- Better evidence breadth generally improves RCA reliability.

### 7-stage evidence pipeline (collect first, decide later)
- Pod status → events → logs → cluster resources → node describe → endpoints → virtual service.
- This avoids premature root-cause decisions from one noisy signal.

### Dependency analysis value
- Blast radius from `services.yaml` clarifies affected, upstream, and safe services.
- Helps committee see this is not single-pod troubleshooting only.

### Incident recording value (MTTR reduction)
- Known incidents are detected via similarity and not re-saved.
- New incidents are auto-stored and embedded for future retrieval.

---

## Expected committee questions and suggested answers

### Q1) What is novel vs Dynatrace/PagerDuty?
**Answer:** "This work is a code-level RCA framework combining staged kubectl evidence, pattern detection, LLM reasoning, and retrieval memory in one transparent pipeline. It emphasizes explainability and academic reproducibility over black-box SaaS behavior."

### Q2) How does RAG improve accuracy?
**Answer:** "RAG injects prior resolved incidents into analysis context, so recommendations are grounded in historically successful fixes. Compare mode (`--compare`) demonstrates confidence and output differences."

### Q3) What are the limitations?
**Answer:** "Current version uses mock-heavy evaluation paths and does not yet include a full automated benchmark suite. Also, production integrations (alerts/ticketing) are future work."

### Q4) How does it scale to production clusters?
**Answer:** "The architecture is modular: kubectl collection is already isolated in dedicated clients/investigator modules. Next step is multi-cluster orchestration and asynchronous evidence collection workers."

### Q5) Confidence score is based on what?
**Answer:** "Confidence is generated by the model in strict output format and parsed by the pipeline; low confidence triggers window expansion and can trigger additional evidence usage."

### Q6) Why not fine-tune instead of RAG?
**Answer:** "RAG is faster to operationalize, easier to update continuously, and avoids expensive retraining cycles for every new incident pattern."

### Q7) How would you productionize this?
**Answer:** "Add robust auth/RBAC, asynchronous collectors, centralized vector store, observability, and integration with Slack/PagerDuty/Jira workflows."

### Q8) Hardest technical challenge?
**Answer:** "Embedding consistency and ChromaDB dimension mismatch handling. This was solved with provider-consistent embedding calls and auto-heal purge/reload logic in `IncidentRecorder`."

---

## Closing (2 min)

### Summary statement
"In this demo, I showed an end-to-end AI-assisted SRE workflow: system readiness, RCA generation, repeat-incident memory, baseline-vs-RAG evaluation, and follow-up chat."

### Future work (3 bullets)
- Multi-cluster and multi-namespace orchestration.
- Slack/PagerDuty/ticketing integrations.
- Controlled auto-remediation with approval gates.

### Strong closing line
"The core contribution is not only AI-generated diagnosis, but a practical incident operating model that learns from every failure and reduces MTTR over time."