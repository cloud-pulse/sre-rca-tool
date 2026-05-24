# LLM call chain + prompts (baseline, RAG, live RCA)

This report documents **exact code locations, function/class names, prompt strings, and response parsing** used to generate RCA narratives.

---

## 1) `core/llm_provider.py`

### Full class: `LLMProvider`

```python
class LLMProvider:
    def __init__(self):
        provider = (LLM_PROVIDER or "ollama").strip().lower()
        self.provider = "nvidia" if provider == "nvidia" else "ollama"

        self.reasoning_model = LLM_REASONING_MODEL
        self.reasoning_fallback = LLM_REASONING_FALLBACK
        self.embedding_model = LLM_EMBEDDING_MODEL
        self.embedding_fallback = LLM_EMBEDDING_FALLBACK

        self._client = None
        self._embedding_model_local = None

        if self.provider == "nvidia":
            from openai import OpenAI

            self._client = OpenAI(
                base_url=LLM_BASE_URL,
                api_key=NVIDIA_API_KEY,
            )

    def _is_429(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return True

        response = getattr(exc, "response", None)
        if response is not None and getattr(response, "status_code", None) == 429:
            return True

        return "429" in str(exc)

    def _generate_nvidia(
        self,
        prompt: str,
        system_prompt: Optional[str],
        stream: bool,
        model: str,
    ) -> str:
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            top_p=0.7,
            max_tokens=flags.LLM_MAX_TOKENS,
            stream=stream,
        )

        if not stream:
            return (response.choices[0].message.content or "").strip()

        chunks: List[str] = []
        for chunk in response:
            token = ""
            if chunk.choices and chunk.choices[0].delta:
                token = chunk.choices[0].delta.content or ""
            if token:
                print(token, end="", flush=True)
                chunks.append(token)
        print()
        return "".join(chunks).strip()

    def _generate_ollama(self, prompt: str, stream: bool) -> str:
        for attempt in range(3):
            try:
                payload = {
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": stream,
                    "options": {
                        "temperature": 0.2,
                        "top_p": 0.9,
                        "num_predict": LLM_MAX_TOKENS,
                        "keep_alive": ("10m" if LLM_KEEP_ALIVE else "0"),
                    },
                }

                response = requests.post(
                    OLLAMA_URL,
                    json=payload,
                    stream=stream,
                    timeout=(10, flags.LLM_TIMEOUT),
                )

                if response.status_code == 200:
                    if not stream:
                        data = response.json()
                        return (data.get("response") or "").strip()

                    full_response = ""
                    for line in response.iter_lines():
                        if not line:
                            continue
                        line_str = line.decode("utf-8")
                        try:
                            data = json.loads(line_str)
                            token = data.get("response", "")
                            if token:
                                print(token, end="", flush=True)
                                full_response += token
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
                    print()
                    return full_response

                print(f"ERROR: Ollama returned status {response.status_code}")
            except requests.ConnectionError:
                print("ERROR: Cannot connect to Ollama")
            except requests.Timeout:
                print(f"ERROR: Ollama request timed out after {LLM_TIMEOUT}s")
            except Exception as exc:
                print(f"ERROR: Failed to call Ollama: {exc}")

            if attempt < 2:
                print(f"Retrying in 5 seconds... (attempt {attempt + 2}/3)")
                time.sleep(5)

        return ""

    def generate(self, prompt: str, system_prompt: Optional[str] = None, stream: bool = False) -> str:
        if self.provider == "nvidia":
            try:
                return self._generate_nvidia(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    stream=stream,
                    model=self.reasoning_model,
                )
            except Exception as exc:
                if self._is_429(exc):
                    print("[INFO] Primary model busy, switching to fallback model...")
                    try:
                        return self._generate_nvidia(
                            prompt=prompt,
                            system_prompt=system_prompt,
                            stream=stream,
                            model=self.reasoning_fallback,
                        )
                    except Exception as fallback_exc:
                        raise RuntimeError(
                            "NVIDIA generation failed after fallback. "
                            f"Tried models: {self.reasoning_model}, {self.reasoning_fallback}"
                        ) from fallback_exc
                raise

        merged_prompt = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"
        return self._generate_ollama(merged_prompt, stream=stream)

    def _embed_nvidia(self, texts: List[str], model: str) -> List[List[float]]:
        response = self._client.embeddings.create(
            model=model,
            input=texts,
            encoding_format="float",
        )
        return [item.embedding for item in response.data]

    def _embed_ollama_local(self, texts: List[str]) -> List[List[float]]:
        if self._embedding_model_local is None:
            from sentence_transformers import SentenceTransformer

        self._embedding_model_local = SentenceTransformer(EMBEDDING_MODEL)

        vectors = self._embedding_model_local.encode(texts, convert_to_numpy=True)
        return [vector.tolist() for vector in vectors]

    def embed(self, texts: List[str]) -> List[List[float]]:
        if self.provider == "nvidia":
            try:
                return self._embed_nvidia(texts, self.embedding_model)
            except Exception as exc:
                if self._is_429(exc):
                    print("[INFO] Embedding model busy, switching to fallback...")
                    try:
                        return self._embed_nvidia(texts, self.embedding_fallback)
                    except Exception as fallback_exc:
                        raise RuntimeError(
                            "NVIDIA embedding failed after fallback. "
                            f"Tried models: {self.embedding_model}, {self.embedding_fallback}"
                        ) from fallback_exc
                raise

        return self._embed_ollama_local(texts)

    def __repr__(self):
        return (
            f"LLMProvider({self.provider} | "
            f"reasoning={self.reasoning_model} | "
            f"embedding={self.embedding_model})"
        )
```

### What does `provider.generate(prompt)` return?

- **Exact return type:** `str`
- The method returns the model output **as a string**, stripped.

Evidence:

```python
def generate(...) -> str:
    ...
    return self._generate_ollama(...)
```

And both backend generators return `str`:

```python
def _generate_nvidia(...) -> str:
    ...
    return (response.choices[0].message.content or "").strip()

def _generate_ollama(...) -> str:
    ...
    return (data.get("response") or "").strip()
```

### Other methods besides `generate()`

Yes. Full set of methods in the class (by name):

- `__init__(self)`
- `_is_429(self, exc: Exception) -> bool`
- `_generate_nvidia(self, prompt: str, system_prompt: Optional[str], stream: bool, model: str) -> str`
- `_generate_ollama(self, prompt: str, stream: bool) -> str`
- `generate(self, prompt: str, system_prompt: Optional[str] = None, stream: bool = False) -> str`
- `_embed_nvidia(self, texts: List[str], model: str) -> List[List[float]]`
- `_embed_ollama_local(self, texts: List[str]) -> List[List[float]]`
- `embed(self, texts: List[str]) -> List[List[float]]`
- `__repr__(self)`

### How is the provider instantiated / exported?

At the bottom of `core/llm_provider.py`:

```python
provider = LLMProvider()
```

So other modules import it as:

```python
from core.llm_provider import provider
```

---

## 2) `core/window_analyzer.py`

### `WindowAnalyzer.analyse()` signature and return value

```python
def analyse(self, lines: list[str], service: str = "unknown") -> dict:
```

It returns a `dict` called `result`.

### Exact dict structure returned by `analyse()`

Two “success” shapes (windows used = 1 or 2):

**When window-1 is sufficient** (`confidence_1 >= CONFIDENCE_THRESHOLD` OR `len(lines) <= WINDOW_1_SIZE`):

```python
result = {
    "service": service,
    "windows_used": 1,
    "confidence": confidence_1,
    "analysis": response_1,
    "window_1_confidence": confidence_1,
    "window_1_analysis": response_1,
    "low_confidence_warning": confidence_1 < self.CONFIDENCE_THRESHOLD
}
```

**When merged re-analysis is used**:

```python
result = {
    "service": service,
    "windows_used": 2,
    "confidence": confidence_merged,
    "analysis": response_merged,
    "window_1_confidence": confidence_1,
    "window_1_analysis": response_1,
    "low_confidence_warning": confidence_1 < self.CONFIDENCE_THRESHOLD
}
```

**On exception:**

```python
result = {
    "service": service,
    "windows_used": 0,
    "confidence": 0,
    "analysis": "LLM unavailable",
    "window_1_confidence": 0,
    "window_1_analysis": "",
    "low_confidence_warning": True
}
```

Then, regardless of success/failure, it appends an additional key:

```python
record = recorder.check_and_save(result["analysis"], service, lines)
result["incident_record"] = record
return result
```

So the final return dict always contains:

- `service`
- `windows_used`
- `confidence`
- `analysis`
- `window_1_confidence`
- `window_1_analysis`
- `low_confidence_warning`
- `incident_record` (whatever `check_and_save()` returns)

### Does it call `provider.generate()` internally?

Yes. It calls via `_run_window()`:

```python
def _run_window(...):
    prompt = self._build_prompt(...)
    response_text = provider.generate(prompt)
    confidence_int = self._extract_confidence(response_text)
    ...
    return response_text, confidence_int
```

---

## 3) How `_print_analysis_result()` gets its data

### Full function from `command_registry.py`

```python
def _print_analysis_result(result, mode):
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich import box

    c = Console()

    low_conf = result.get('low_confidence_warning', False)
    record = result.get('incident_record', {})

    c.print(Rule(f"Analysis Complete — {mode} mode", style="bold green"))

    meta = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    meta.add_column("Key", style="bold cyan", width=14)
    meta.add_column("Value", style="white")

    meta.add_row("Service", str(result.get('service', 'unknown')))
    meta.add_row("Windows used", str(result.get('windows_used', 1)))
    meta.add_row("Confidence", f"{result.get('confidence', 0)}%")
    meta.add_row("Warning",
                 "[bold yellow]Low confidence — extended window used[/bold yellow]"
                 if low_conf else "[dim]None[/dim]")

    meta.add_row("Incident saved",
                 "[bold green]Yes[/bold green]"
                 if record.get('saved') else "[dim]No[/dim]")

    meta.add_row("Reason", str(record.get('reason', 'N/A')))
    meta.add_row("Similarity", f"{record.get('similarity_score', 0.0):.1%}")

    c.print(meta)

    from rich.markdown import Markdown
    analysis_text = result.get('analysis', 'No analysis returned.')

    # Strip the CONFIDENCE/REASON block from display — already shown in meta table
    import re
    clean_text = re.sub(r'\nCONFIDENCE:.*', '', analysis_text, flags=re.DOTALL).strip()

    c.print(Panel(
        Markdown(clean_text),
        title="[bold white]Root Cause Analysis[/bold white]",
        border_style="green",
        padding=(1, 2),
    ))
    c.print()
```

### What keys does it read from the result dict?

Every `.get()` / `record.get()` used:

From `result`:
- `result.get('low_confidence_warning', False)`
- `result.get('incident_record', {})`
- `result.get('service', 'unknown')`
- `result.get('windows_used', 1)`
- `result.get('confidence', 0)`
- `result.get('analysis', 'No analysis returned.')`

From `incident_record` (`record = result.get('incident_record', {})`):
- `record.get('saved')`
- `record.get('reason', 'N/A')`
- `record.get('similarity_score', 0.0)`

### Where does the `'analysis'` text come from?

In window-based RCA mode:
- `WindowAnalyzer.analyse()` sets `result["analysis"]` to the raw LLM string returned by `provider.generate(prompt)`.
- It is then displayed after cleaning.

Evidence:

```python
response_text = provider.generate(prompt)
...
return response_text, confidence_int
```

Then:

```python
result = { ..., "analysis": response_1, ... }
```

And `_print_analysis_result()` does:

```python
analysis_text = result.get('analysis', 'No analysis returned.')
clean_text = re.sub(r'\nCONFIDENCE:.*', '', analysis_text, flags=re.DOTALL).strip()
```

**Markdown vs plain text?**

- It is treated as **markdown** in display:

```python
Markdown(clean_text)
```

So LLM output is expected to contain markdown-ish formatting (or at least compatible with markdown rendering).

---

## 4) The prompt that generates the RCA narrative

There are multiple LLM call sites that produce narrative RCA.

### 4.1 Baseline mode prompt (string passed to `provider.generate(prompt)`) in `core/command_registry.py`

This is in `AnalyseHandler.handle()` under `if baseline_mode:`.

```python
prompt = (
    f"You are an expert Site Reliability Engineer.\n"
    f"Service: {service}\n"
    f"Analyse the following logs and provide RCA.\n\n"
    f"--- LOGS START ---\n"
    f"{chr(10).join(lines[:500])}\n"
    f"--- LOGS END ---"
)
raw_response = provider.generate(prompt)
```

So in **baseline mode**, the prompt is exactly that f-string.

### 4.2 Prompt used inside `WindowAnalyzer.analyse()` for RAG-like window mode

`WindowAnalyzer` does not do RAG retrieval; it does windowed LLM analysis.

Prompt builder:

```python
def _build_prompt(self, lines: list[str], service: str, window_label: str) -> str:
    logs_str = "\n".join(lines)
    return f"""You are an expert Site Reliability Engineer performing root cause analysis.

Service: {service}
Window: {window_label}
Log lines: {len(lines)}

--- LOGS START ---
{logs_str}
--- LOGS END ---

Analyse these logs and identify:
1. Root cause of any failures or anomalies
2. Sequence of events leading to failure
3. Affected services and impact
4. Recommended remediation steps

At the end of your analysis, you MUST include this block exactly:
CONFIDENCE: <number>%
REASON: <one sentence explaining your confidence level>

Confidence should reflect how complete the picture is:
- 80-100%: clear root cause, full failure sequence visible
- 60-79%: likely root cause but some gaps in evidence
- 40-59%: partial picture, more log context needed
- below 40%: insufficient data, cannot determine root cause"""
```

LLM call:

```python
response_text = provider.generate(prompt)
```

### 4.3 “System prompt” / instruction controlling the numbered format

The numbered format is induced by the instruction in `_build_prompt()`:

```text
Analyse these logs and identify:
1. Root cause of any failures or anomalies
2. Sequence of events leading to failure
3. Affected services and impact
4. Recommended remediation steps

At the end of your analysis, you MUST include this block exactly:
CONFIDENCE: <number>%
REASON: <one sentence explaining your confidence level>
```

This is part of the **user prompt string** passed to `provider.generate(prompt)`.

There is no separate `system_prompt=` parameter used for `WindowAnalyzer` calls; `provider.generate(prompt)` is invoked with default `system_prompt=None`.

---

## 5) LLM response parsing / cleaning between LLM call and display

### 5.1 Between `provider.generate()` and `_print_analysis_result()` (window mode)

For window mode, **no parsing of content into fields** happens between provider output and `_print_analysis_result()`.

Instead:
- `WindowAnalyzer._extract_confidence()` extracts `CONFIDENCE: <number>%` from the raw string

```python
def _extract_confidence(self, llm_response: str) -> int:
    match = re.search(r"CONFIDENCE:\s*(\d+)%", llm_response, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 50
```

- `_print_analysis_result()` then strips everything from the first newline before `CONFIDENCE:` onward (for display), because the confidence/reason are displayed in the meta table.

```python
clean_text = re.sub(r'\nCONFIDENCE:.*', '', analysis_text, flags=re.DOTALL).strip()
```

So the raw LLM output is displayed as-is (markdown-rendered) except for that truncation.

### 5.2 Baseline vs RAG (core/llm_analyzer.py “baseline/rag” mode) parsing

The alternative pipeline in `core/llm_analyzer.py` **does** parse/structure the LLM output.

LLM call sites:
- `raw_response = provider.generate(prompt)`

Then immediately:
- `parsed = self._parse_response(raw_response, debug=True)`

and the resulting structured dict uses:

```python
result = {
  "root_cause": parsed["root_cause"],
  "affected_services": parsed["affected_services"],
  "failure_chain": parsed["failure_chain"],
  "suggested_fixes": parsed["suggested_fixes"],
  "confidence": parsed["confidence"],
  "confidence_reason": parsed["confidence_reason"],
  ...
}
```

The parsing removes markdown markers (`*`, `#`) and normalizes whitespace:

```python
text = re.sub(r"\*+", "", text)
text = re.sub(r"#+\s*", "", text)
text = re.sub(r"\n{3,}", "\n\n", text)
text = text.strip()
```

---

## 6) Existing system prompts / instruction strings

### 6.1 Confirmed instruction strings in code that shape RCA behavior

From `core/window_analyzer.py`:

```text
You are an expert Site Reliability Engineer performing root cause analysis.
...
Analyse these logs and identify:
1. Root cause of any failures or anomalies
2. Sequence of events leading to failure
3. Affected services and impact
4. Recommended remediation steps

At the end of your analysis, you MUST include this block exactly:
CONFIDENCE: <number>%
REASON: <one sentence explaining your confidence level>
```

From `core/llm_analyzer.py`:

Baseline prompt has this explicit instruction on exact output sections:

```text
You are an expert SRE (Site Reliability Engineer)
with deep knowledge of Kubernetes and microservices.
...
You MUST respond in this EXACT format.
Do not add any text outside this format:

ROOT CAUSE: ...
...
CONFIDENCE: [number between 0-100]%
...
CONFIDENCE REASON: ...
```

RAG prompt includes historical incident context and requires exact format too.

From `core/command_registry.py`:

Baseline + compare mode uses a shorter prompt:

```text
You are an expert Site Reliability Engineer.
Service: {service}
Analyse the following logs and provide RCA.
--- LOGS START ---
...
--- LOGS END ---
```

And live watch (file tail) triggers `run_pipeline(..., mode="rag")`, which uses `LLMAnalyzer.analyze_rag()`.

### 6.2 `.github/prompts/*` files

I was not able to read `.github/prompts/prompts.md` / `implem.md` using the available file-read tool due to path resolution mismatches (tool reports file not found for the expected filesystem paths).

So the report above only includes prompts/instructions that were actually readable from the Python code.

If you want the exact system prompt strings stored under `.github/prompts/`, I need the on-disk path that the tool can access (or you can paste the contents).

