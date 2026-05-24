# Kubectl live-mode integration report (codebase extraction)

This report extracted *real* code blocks (with function names / identifiers and exact snippets) from the repository.

---

## 1) `ai_sre.py` — REPL / dispatch loop

### 1.1 Exact code block where user input is read (prompt loop)

In `ai_sre.py`, inside `main()`:

```py
def main():
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:]).strip()
        if text:
            _run_input(text)
        return

    print_banner()

    while True:
        try:
            console.print("[bold cyan]ai-sre>[/bold cyan] ", end="")
            user_input = input().strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "bye", "q"):
            console.print("[dim]Goodbye.[/dim]")
            break

        _run_input(user_input)
```

### 1.2 How commands are parsed and dispatched

User input is passed into `_run_input()`; that calls `resolve(user_input)` from `core.command_registry`.

In `ai_sre.py`:

```py
def _run_input(user_input: str):
    result = resolve(user_input)

    if not result:
        if is_out_of_scope(user_input):
            print_out_of_scope_message(user_input)
            return
        # Fallback: treat as SRE knowledge question
        _answer_sre_question(user_input)
        return

    handler, args = result

    try:
        handler.handle(args)
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]\n")
    except Exception as exc:
        console.print(
            f"\n[bold red]Error: {exc}[/bold red]"
            f"\n[dim]Type 'help' for commands.[/dim]\n"
        )
```

### 1.3 If it uses `core.command_registry`, show how that registry works

`core/command_registry.py` defines:

- `REGISTRY: dict[str, BaseHandler]` (Tier 1 exact dispatch)
- `resolve(user_input: str)` (Tiered parsing: question detection, exact match, fuzzy match, keyword scoring)
- `BaseHandler` abstraction

Key objects/snippets:

```py
class BaseHandler(ABC):
    description: str = ""
    aliases: list[str] = []
    requires_service: bool = False

    @abstractmethod
    def handle(self, args: list[str]) -> str:
        raise NotImplementedError
```

Registry:

```py
REGISTRY: dict[str, BaseHandler] = {
    "analyse": _ANALYSE,
    "analyze": _ANALYSE,
    "status": _STATUS,
    "compare": _COMPARE,
    "watch": _WATCH,
    "chat": _CHAT,
    "explain": _EXPLAIN,
    "clean": _CLEAN,
    "clean-logs": _CLEAN_LOGS,
    "help": _HELP,
}
```

Dispatch/parse logic:

```py
def resolve(user_input: str) -> Optional[tuple[BaseHandler, list[str]]]:
    text = (user_input or "").strip()
    if not text:
        return None

    words = text.split()
    first = words[0].lower()

    question_starters = {...}
    if first in question_starters:
        return None

    if is_out_of_scope(text):
        return None

    # Tier 1: exact match
    if first in REGISTRY:
        return REGISTRY[first], words[1:]

    # Tier 2: fuzzy command match
    fuzzy = _fuzzy_match_command(first)
    if fuzzy:
        confirmed = _prompt_did_you_mean(first, fuzzy)
        if confirmed:
            return REGISTRY[fuzzy], words[1:]
        return None

    if first == "investigate":
        return None

    # Tier 3: keyword confidence scoring
    keyword_command = _keyword_scored_command(text)
    if keyword_command and keyword_command in REGISTRY:
        if keyword_command == "explain":
            return REGISTRY[keyword_command], [text]
        return REGISTRY[keyword_command], words

    return None
```

---

## 2) The `analyze` / `analyse` command — full flow

Note: the registry key is `analyse`/`analyze` mapped to `AnalyseHandler`.

### 2.1 Exact handler that runs when user types `analyze <service>`

In `core/command_registry.py`:

```py
class AnalyseHandler(BaseHandler):
    description = "Full SRE investigation (RCA, logs, metrics, K8s)"
    aliases = ["analyze", "analyse"]

    def handle(self, args: list[str]) -> str:
        ...
```

And in `REGISTRY`:

```py
"analyse": _ANALYSE,
"analyze": _ANALYSE,
```

### 2.2 What arguments it receives

- `resolve()` returns `(handler, words[1:])`
- Therefore `AnalyseHandler.handle(self, args)` receives `args = words[1:]`

Inside handler it parses args like this:

```py
args_str = " ".join(args)
parts = args_str.strip().split()
baseline_mode = "--baseline" in parts
compare_mode = "--compare" in parts
service_parts = [p for p in parts if not p.startswith("--")]
service = "-".join(service_parts) if service_parts else None
```

So supported syntaxes:
- `analyze <service>` → `service` is `<service>` with dashes preserved; no flags
- `analyze <service> --baseline` → `baseline_mode=True`
- `analyze <service> --compare` → `compare_mode=True`

### 2.3 What it calls next (full call chain until output is printed)

#### 2.3.1 Common initial steps

```py
from core.log_loader import LogLoader
loader = LogLoader()
lines = loader.load_service_logs(service)
```

If no logs:

```py
if not lines:
    print(f"No logs found for service: {service}")
    return "no_logs"
```

#### 2.3.2 compare mode (`--compare`)

Call chain:

```py
from core.window_analyzer import WindowAnalyzer
from core.llm_provider import provider
analyzer = WindowAnalyzer()
rag_result = analyzer.analyse(lines, service=service)
```

Then baseline LLM call:

```py
prompt = (
    f"You are an expert Site Reliability Engineer.\n"
    f"Service: {service}\n"
    f"Analyse ...\n\n"
    f"--- LOGS START ---\n"
    f"{chr(10).join(lines[:500])}\n"
    f"--- LOGS END ---"
)
baseline_response = provider.generate(prompt)
```

Then save compare report:

```py
report_path = _save_compare_report(service, rag_result, baseline_response)
print(f"\nComparison report saved to: {report_path}")
```

Then output formatting:

```py
_print_analysis_result(rag_result, mode="RAG")
```

#### 2.3.3 baseline-only mode (`--baseline`)

```py
from core.llm_provider import provider
raw_response = provider.generate(prompt)
_print_baseline_result(raw_response, service)
```

#### 2.3.4 default mode (RAG via WindowAnalyzer)

```py
from core.window_analyzer import WindowAnalyzer
analyzer = WindowAnalyzer()
result = analyzer.analyse(lines, service=service)
_print_analysis_result(result, mode="RAG")
```

#### 2.3.5 Where output fields are printed in this command

`_print_analysis_result()` prints a summary table and a Rich panel.
The relevant parts:

```py
meta.add_row("Service", str(result.get('service', 'unknown')))
meta.add_row("Confidence", f"{result.get('confidence', 0)}%")
meta.add_row("Reason", str(record.get('reason', 'N/A')))
meta.add_row("Similarity", f"{record.get('similarity_score', 0.0):.1%}")
...
analysis_text = result.get('analysis', 'No analysis returned.')
clean_text = re.sub(r'\nCONFIDENCE:.*', '', analysis_text, flags=re.DOTALL).strip()

c.print(Panel(
    Markdown(clean_text),
    title="[bold white]Root Cause Analysis[/bold white]",
    border_style="green",
    padding=(1, 2),
))
```

So in this command, the “Root Cause Analysis block” corresponds to the content rendered inside the `Panel(... title="Root Cause Analysis")`.

---

## 3) Output / display layer (final terminal printing + field renderers)

### 3.1 Exact function(s) that print the final result to terminal

For `analyse/analyze` command output, printing is handled by:

- `core.command_registry._print_analysis_result(result, mode)`
- `core.command_registry._print_baseline_result(response, service)`

#### 3.1.1 `_print_analysis_result` (RAG mode)

Exact printing section includes:

```py
c.print(Rule(f"Analysis Complete — {mode} mode", style="bold green"))
...
c.print(meta)
...
c.print(Panel(
    Markdown(clean_text),
    title="[bold white]Root Cause Analysis[/bold white]",
    border_style="green",
    padding=(1, 2),
))
```

### 3.2 Which function renders: Service, Confidence, Reason, Similarity, Root Cause Analysis

All five are rendered inside `_print_analysis_result()`:

- **Service**:
  ```py
  meta.add_row("Service", str(result.get('service', 'unknown')))
  ```
- **Confidence**:
  ```py
  meta.add_row("Confidence", f"{result.get('confidence', 0)}%")
  ```
- **Reason**:
  ```py
  meta.add_row("Reason", str(record.get('reason', 'N/A')))
  ```
- **Similarity**:
  ```py
  meta.add_row("Similarity", f"{record.get('similarity_score', 0.0):.1%}")
  ```
- **Root Cause Analysis block**:
  rendered by the `Panel` titled `"Root Cause Analysis"`:
  ```py
  c.print(Panel(
      Markdown(clean_text),
      title="[bold white]Root Cause Analysis[/bold white]",
      border_style="green",
      padding=(1, 2),
  ))
  ```

### 3.3 Is there a formatter/display module?

Yes, there is also a separate formatter used by `main.py` (click-based CLI), not by `ai_sre.py`’s `analyse` command.

File: `output/rca_formatter.py`

Class: `RCAFormatter`

Key entry points:
- `RCAFormatter.print_full_result(result, resources)`
- `RCAFormatter.print_rca(result)`

Example “RCA” rendering:

```py
# in RCAFormatter.print_rca
content.append("ROOT CAUSE\n", style="bold red")
content.append(f"{result.get('root_cause', 'N/A')}\n\n", style="white")
...
content.append("CONFIDENCE: ", style="bold cyan")
...
rca_panel = Panel(
    content,
    title="RCA Result",
    border_style=border_style,
    expand=True,
    padding=(1, 2),
)
self.console.print(rca_panel)
```

---

## 4) How `USE_KUBERNETES` / source mode is currently handled

### 4.1 Is there already a flags/config with `USE_KUBERNETES` / `SOURCE_KUBERNETES`?

Yes: `flags.py` contains:

```py
USE_KUBERNETES     = _parse_bool(_get("SOURCE_KUBERNETES", "false"), False)
K8S_NAMESPACE      = _get("SOURCE_NAMESPACE", "default")
```

So the env var name is `SOURCE_KUBERNETES`; code uses `USE_KUBERNETES`.

### 4.2 Is this flag checked in `ai_sre.py` or call chain?

In `ai_sre.py` specifically, no direct check exists.

However, in the command-dispatch call chain it is checked in `core.command_registry.StatusHandler`:

```py
from flags import USE_KUBERNETES, LLM_CACHE_ENABLED, RAG_ENABLED, DEBUG, K8S_NAMESPACE
...
table.add_row(
    "Source mode",
    "[bold green]kubernetes[/bold green]" if USE_KUBERNETES else "[bold yellow]file[/bold yellow]",
    f"namespace: {K8S_NAMESPACE}" if USE_KUBERNETES else "logs/test.log"
)
```

Also, in `main.py analyze` CLI, it is validated as part of log input requirements:

```py
from flags import USE_KUBERNETES
if not log_file and not USE_KUBERNETES:
    console.print("[bold red]ERROR: Provide a log file path, or set SOURCE_KUBERNETES=true in .env[/bold red]")
    return
```

### 4.3 If yes, show exactly where/how it branches

Branch 1 (status UI):

```py
"[bold green]kubernetes[/bold green]" if USE_KUBERNETES else "[bold yellow]file[/bold yellow]"
...
"namespace: {K8S_NAMESPACE}" if USE_KUBERNETES else "logs/test.log"
```

Branch 2 (click analyze requires log file unless USE_KUBERNETES):

```py
if not log_file and not USE_KUBERNETES:
    console.print(...)
    return
```

Branch 3 (click pipeline error message indicates source):

In `run_pipeline()` when no logs:

```py
source = (
    f"kubectl (namespace={active_namespace})"
    if USE_KUBERNETES
    else f"file ({log_path})"
)
console.print(f"[bold red]ERROR: No log lines loaded from {source}[/]")
```

---

## 5) ServiceGraph usage

### 5.1 Is ServiceGraph already instantiated in `ai_sre.py` or dependencies?

`ai_sre.py` itself does not instantiate `ServiceGraph`.

But the interactive command handlers in `core.command_registry.py` do instantiate it.

### 5.2 If yes, variable name and where created

In `core.command_registry.StatusHandler.handle()`:

```py
graph = ServiceGraph()
svcs = graph.get_all_service_names()
```

In `core.command_registry.WatchHandler.handle()`:

```py
graph = ServiceGraph()
canonical = graph.get_service_name(service) or service
namespace = graph.get_namespace(canonical)
```

In `core.command_registry.CommandRegistry` itself, there are helper calls to `_load_services()` for known services; that is based on `services.yaml`.

### 5.3 What namespace value is used

- In `StatusHandler`, namespace displayed is `K8S_NAMESPACE` from `flags.py`.

```py
table.add_row(
    "Source mode",
    ...,
    f"namespace: {K8S_NAMESPACE}" if USE_KUBERNETES else ...
)
```

- In `WatchHandler`, namespace is determined via service graph:

```py
namespace = graph.get_namespace(canonical)
```

If user does provide `namespace`, that value is used instead (`_extract_ns(raw)` in `WatchHandler`).

---

## 6) Existing kubectl calls in the codebase

### 6.1 List every file that already calls subprocess with `kubectl`

From code inspection of the files returned by search:

1. `core/kubectl_client.py`
   - Uses `subprocess.run()` and executes `cmd` arrays beginning with `"kubectl"`.

2. `main.py` (indirect)
   - `run_pipeline()` calls `LogLoader.load_auto(...)`, which includes kubectl fetching logic (not shown in the snippet extracted here). However, kubectl invocation appears to be implemented inside `core/log_loader.py` or other core modules.

3. `core/service_discovery.py` etc.
   - Search results indicate kubectl usage strings, but the concrete `subprocess` call sites are inside `core/kubectl_client.py` based on the available extracts.

### 6.2 Show function name and what kubectl command it runs

In `core/kubectl_client.py`, kubectl is executed via `_run(cmd)`:

```py
def _run(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        ...
```

Key kubectl-issuing functions with exact command arrays:

#### 6.2.1 `get_pods(namespace, service_name)`

Label selector approach:

```py
ok, out = _run([
    "kubectl", "get", "pods",
    "-n", namespace,
    "--selector", f"app={service_name}",
    "--no-headers",
    "-o", "wide",
])
```

Fallback:

```py
ok, out = _run([
    "kubectl", "get", "pods",
    "-n", namespace,
    "--no-headers",
])
```

#### 6.2.2 `get_pod_events(pod_name, namespace)`

Events:

```py
ok, out = _run([
    "kubectl", "get", "events",
    "-n", namespace,
    "--field-selector", f"involvedObject.name={pod_name}",
    "--sort-by=.lastTimestamp",
])
```

Fallback describe pod:

```py
ok2, out2 = _run([
    "kubectl", "describe", "pod", pod_name,
    "-n", namespace,
])
```

#### 6.2.3 `get_pod_logs(...)`

```py
cmd = [
    "kubectl", "logs", pod_name,
    "-n", namespace,
    f"--tail={tail}",
    "--timestamps=true",
]
...
ok, out = _run(cmd, timeout=60)
...
ok2, out2 = _run(cmd + ["--previous"], timeout=60)
```

#### 6.2.4 `get_node_resources()`

```py
ok, out = _run(["kubectl", "top", "nodes", "--no-headers"])
```

#### 6.2.5 `get_cluster_resource_pressure(namespace=None)`

```py
cmd = ["kubectl", "top", "pods", "--no-headers"]
if namespace:
    cmd += ["-n", namespace]
else:
    cmd.append("-A")
```

#### 6.2.6 `get_deployment_list(namespace)`

```py
ok, out = _run([
    "kubectl", "get", "deployments",
    "-n", namespace,
    "--no-headers",
])
```

#### 6.2.7 `get_containers_for_pod(pod_name, namespace)`

```py
ok, out = _run([
    "kubectl", "get", "pod", pod_name,
    "-n", namespace,
    "-o", "jsonpath={.spec.containers[*].name}",
])
```

---

## Notes relevant to integrating kubectl live mode into `ai_sre.py`

- There is already a click-based kubectl entrypoint in `main.py`:
  - command: `kubectl_analyze(service, namespace, output, verbose)`
  - calls:
    - `run_kubectl_rca(resolved, active_namespace, service_graph=sg)`
  - uses:
    - `ServiceGraph("services.yaml")`
    - `core.kubectl_rca_investigator.run_kubectl_rca(...)`

- `ai_sre.py` interactive shell currently supports:
  - `analyse/analyze`, `status`, `compare`, `watch`, `chat`, `explain`, `clean`, `clean-logs`, `help`
  - There is **no** interactive `kubectl` or `kubectl-live` command handler in `REGISTRY`.

- Adding kubectl live mode can be done surgically by:
  - extending `core.command_registry.REGISTRY` with a new handler key (e.g. `kubectl-live`)
  - ensuring printing uses the existing terminal rendering functions (`_print_analysis_result` or `output/rca_formatter.RCAFormatter`) depending on desired schema.

