# Next steps: Integrate Kubernetes into this SRE-AI RCA project

This file lists a practical sequence of tasks to move the project from **mock resource data** to **real kubectl/Kubernetes evidence** end-to-end.

> Assumption: your current RCA pipeline already supports plugging in “resources” and richer kubectl outputs via `core/resource_collector.py`, `core/context_builder.py`, and `core/llm_analyzer.py`.

---

## 0) Baseline: confirm what’s currently mock vs real
- Identify which code paths are controlled by flags/env vars (ex: `USE_KUBERNETES`, `SOURCE_KUBERNETES`, `--mock`).
- Trace how `main.py run_pipeline()` passes `use_mock` into `ResourceCollector.get_resources(...)`.
- Confirm which parts of the context are expected by the LLM prompts (formatted logs, formatted resources, incident_summary, etc.).

Deliverable: a short “mock→real mapping” doc or checklist in this repo.

---

## 1) Implement kubectl command runner (single place to execute kubectl)
- Add a small utility module (or extend an existing one) that:
  - Executes `kubectl` with `subprocess.run(..., capture_output=True, text=True, timeout=...)`
  - Sanitizes output (truncate very large outputs)
  - Returns structured output (raw text + exit status)
- Support “dry-run” and “debug” modes.

Deliverable: `core/kubectl_runner.py` (or similar) with methods like:
- `kubectl_get(namespace, kind, ...)`
- `kubectl_describe(namespace, kind, name)`
- `kubectl_logs(...)`
- `kubectl_events(...)`

---

## 2) Discover the Kubernetes “surface area” needed by the LLM prompts/UI
From the existing codebase, ensure you collect evidence for these categories:
- Pod/container lifecycle & status
- Exit codes / OOMKill / CrashLoopBackOff
- Events (`kubectl get events`, or describe events section)
- Pod describe key fields
- Resource usage (CPU/memory, restarts)
- Rollout / deployment history

Deliverable: a table mapping **(evidence type → kubectl command → where it goes in `resources`/`context`)**.

---

## 3) Extend `ResourceCollector` to support real kubectl collection
- Update `core/resource_collector.py` so that when `use_mock=False` it:
  - Determines affected services (from log summary)
  - Resolves them to K8s resources (deployment/statefulset/pods) using labels/naming convention
  - Collects:
    - Pod status + restart count
    - Metrics snapshot if available (optional): via `kubectl top` or metrics-server
    - `kubectl describe` (key fields)
    - Events for relevant pods/deployments
    - Rollout history (deployment revisions / rollout history)

Important:
- Make collection resilient: partial failures should not crash the whole pipeline.
- Cache kubectl outputs for a short TTL to reduce repeated calls.

Deliverable: Real `get_resources()` output that matches what `RCAFormatter.print_resource_table(...)` expects.

---

## 4) Add service discovery / mapping from “service names” → k8s objects
Right now the logs use service-like names such as:
- `api-gateway`, `payment-service`, `database-service`, etc.

You need a deterministic mapping to kubernetes object names:
- Option A: label-based lookup (recommended)
  - Use label selectors per service (e.g., `app=<service>`)
- Option B: naming convention fallback
  - Deployment name equals service name

Deliverable: a function like:
- `resolve_service_to_pods(namespace, service_name) -> list[pod specs]`
- `resolve_service_to_deployment(namespace, service_name) -> deployment info`

---

## 5) Extend `ContextBuilder` to format new kubectl evidence cleanly
- Ensure the context fed into LLM includes:
  - `formatted_resources` in a compact, readable way
  - Any additional “incident summary” data derived from resources
- Keep prompt size under control (apply truncation rules).

Deliverable:
- A stable context schema: same keys across runs.
- Unit tests for formatting output size and presence.

---

## 6) Validate with real cluster simulation fixtures first
You already have mock fixtures under:
- `logs/mock/kubectl/...`

Use those as golden files to validate parsing:
- Implement parsers that turn raw `kubectl` outputs into structured data.
- Compare your structured output shape against what the formatter/LLM expects.

Deliverable:
- Parser tests using fixture files.

---

## 7) Wire a new CLI mode/flags for kubectl integration
- Add CLI options (or env vars) to control:
  - kubeconfig path
  - kubectl binary path
  - namespace default
  - evidence collection “level” (light/medium/full)
  - log tail duration

Deliverable:
- Example commands:
  - `python main.py analyze <log_file> --mode rag --namespace <ns> --mock=false`
  - `python main.py watch <log_file> --namespace <ns>`

---

## 8) Improve correctness: failure chain ordering using timestamps
Currently failure chain is simplistic.
Upgrade it using collected evidence:
- Pod start times / first error times from log timestamps
- Restart timestamps / event timestamps

Deliverable:
- Better `failure_chain` generation that aligns with evidence.

---

## 9) Add integration smoke tests
- A lightweight test that:
  - Runs kubectl collection against a mocked namespace or fixture
  - Verifies `analyze` produces a parseable RCA response

Deliverable:
- `scripts/verify_final.sh` updated to run kubectl-integration checks.

---

## 10) Performance & reliability hardening
- Add caching for:
  - pod lists
  - describe outputs
  - events
- Add concurrency if you collect multiple pods/services.
- Add timeouts and fallbacks (e.g., if events fail, continue).

Deliverable:
- Reduced kubectl calls per analysis.

---

## Suggested milestone order (fastest path)
1. Kubectl runner utility (Step 1)
2. ResourceCollector real mode skeleton (Step 3)
3. Service name → k8s object mapping (Step 4)
4. ContextBuilder formatting (Step 5)
5. Parsing/fixture tests (Step 6)
6. CLI flags + smoke tests (Steps 7–9)
7. Quality/performance improvements (Steps 8–10)

---

## Done criteria
- Running `python main.py analyze logs/test.log --mode rag --namespace <ns>` produces:
  - resource table populated from real kubectl
  - LLM prompt includes kubectl evidence
  - response still matches the parser’s expected format

---

