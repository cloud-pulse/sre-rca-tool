import sys
import os
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

import requests
import re
import time
from core.logger import get_logger
from core.llm_cache import LLMCache
from flags import (
    LLM_WARMUP,
    LLM_KEEP_ALIVE,
    LLM_MAX_TOKENS,
    LLM_TIMEOUT,
    LLM_CACHE_ENABLED,
)

from core.sre_investigator import (
    InvestigationReport
)

log = get_logger("llm_analyzer")

# Allow imports to work when running this file directly
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LLMAnalyzer:
    """
    Analyzes incident context using Ollama and phi3:mini model.
    Supports baseline and RAG modes.
    """

    def __init__(self):
        """Initialize LLMAnalyzer with configuration."""
        from config import OLLAMA_URL, OLLAMA_MODEL

        self.ollama_url = OLLAMA_URL
        self.model = OLLAMA_MODEL
        self.timeout = LLM_TIMEOUT
        self.max_retries = 2
        self.max_prompt_chars = 7000
        self._warmed_up = False
        self._connection_checked = False
        self.cache = LLMCache()

        log.step(f"LLMAnalyzer initialized — model: {self.model}")

    def check_ollama_connection(self) -> bool:
        """
        Verify Ollama is running and reachable.

        Returns:
            True if Ollama is reachable, False otherwise
        """
        if self._connection_checked:
            return True   # skip repeat check
        # Step 1: ping Ollama base URL
        try:
            response = requests.get(f"{self.ollama_url}/", timeout=5)
            if response.status_code != 200:
                log.error("Cannot reach Ollama at localhost:11434")
                log.error("Make sure Ollama is running: ollama serve")
                self._connection_checked = True
                return False
        except (requests.ConnectionError, requests.Timeout):
            log.error("Cannot reach Ollama at localhost:11434")
            log.error("Make sure Ollama is running: ollama serve")
            self._connection_checked = True
            return False
        except Exception:
            log.error("Cannot reach Ollama at localhost:11434")
            log.error("Make sure Ollama is running: ollama serve")
            self._connection_checked = True
            return False

        # Step 2: check if phi3:mini is pulled
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=10)
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                phi3_found = any(
                    "phi3" in model.get("name", "").lower() for model in models
                )
                if not phi3_found:
                    log.warn("phi3:mini not found locally")
                    log.warn("Run: ollama pull phi3:mini")
                    log.warn("This may take a few minutes...")
                    self._connection_checked = True
                    return False
            else:
                log.error("Cannot get model list from Ollama")
                self._connection_checked = True
                return False
        except Exception as e:
            log.error(f"Failed to check models: {e}")
            self._connection_checked = True
            return False

        # Step 3: do a quick warmup call with tiny prompt
        try:
            payload = {
                "model": self.model,
                "prompt": "Reply with one word: ready",
                "stream": False,
                "options": {"temperature": 0.2, "top_p": 0.9, "num_predict": 10},
            }
            response = requests.post(
                f"{self.ollama_url}/api/generate", json=payload, timeout=60
            )
            if response.status_code == 200:
                data = response.json()
                response_text = data.get("response", "").strip().lower()
                if "ready" in response_text:
                    log.debug("Ollama warmup OK")
                else:
                    log.warn("Warmup response unexpected, but proceeding")
            else:
                log.warn("Warmup call failed, but proceeding")
        except requests.Timeout:
            log.warn("Warmup timed out, model may be slow but proceeding")
        except Exception as e:
            log.warn(f"Warmup failed: {e}, but proceeding")

        log.success("Ollama connection OK")
        self._connection_checked = True
        return True

    def warmup(self) -> bool:
        if self._warmed_up:
            return True
        # Send a tiny prompt to pre-load model
        # Only if LLM_WARMUP flag is True
        # Only if Ollama is reachable
        # Use a very short prompt:
        #   "Reply with one word: ready"
        # Set short timeout: 90s
        # Print progress to user:
        #   "Warming up phi3:mini..."
        #   "Model ready." on success
        #   "Warmup skipped." if flag=false
        # Return True if successful
        if not LLM_WARMUP:
            log.debug("Warmup disabled by flag")
            self._warmed_up = True
            return True
        try:
            log.info("[dim]Warming up phi3:mini...[/dim]")
            payload = {
                "model": self.model,
                "prompt": "Reply: ready",
                "stream": False,
                "options": {"num_predict": 5, "keep_alive": "10m"},
            }
            response = requests.post(
                f"{self.ollama_url}/api/generate", json=payload, timeout=90
            )
            if response.status_code == 200:
                log.success("Model ready.")
                self._warmed_up = True
                return True
            else:
                log.debug("Warmup call failed, but proceeding")
                self._warmed_up = True
                return True
        except requests.Timeout:
            log.debug("Warmup timed out — model will load on first call")
            self._warmed_up = True
            return True
        except Exception as e:
            log.debug(f"Warmup failed: {e}")
            self._warmed_up = True
            return True

    def build_baseline_prompt(self, context: dict) -> str:
        """
        Build the full baseline prompt for LLM analysis.

        Args:
            context: Context dictionary from ContextBuilder.build()

        Returns:
            Full prompt string
        """
        prompt = f"""You are an expert SRE (Site Reliability Engineer)
with deep knowledge of Kubernetes and microservices.
Analyze the following incident data carefully.

{context["formatted_logs"]}

{context["formatted_resources"]}

=== INCIDENT CONTEXT ===
Services affected : {context["services_affected"]}
Failure chain     : {context["failure_chain"]}
Time window       : {context["log_window"]}
Total errors      : {context["error_count"]}

=== YOUR TASK ===
Based on the logs and resource data above, provide a
detailed root cause analysis.

You MUST respond in this EXACT format.
Do not add any text outside this format:

ROOT CAUSE: [one clear sentence identifying the root cause]

AFFECTED SERVICES: [comma separated list in order of impact]

FAILURE CHAIN:
[step 1 — what happened first]
[step 2 — what happened next]
[step 3 — how it cascaded]

SUGGESTED FIXES:
- [High] [specific actionable fix]
- [Medium] [specific actionable fix]
- [Low] [specific actionable fix]

CONFIDENCE: [number between 0-100]%

CONFIDENCE REASON: [one sentence explaining the score]
"""
        return self._trim_prompt(prompt)

    def _trim_prompt(self, prompt: str) -> str:
        """
        Trim prompt if it exceeds max_prompt_chars.

        Args:
            prompt: The full prompt string

        Returns:
            Trimmed prompt string
        """
        if len(prompt) <= self.max_prompt_chars:
            return prompt

        # Keep first 3500 chars (headers + most logs)
        prefix = prompt[:3500]

        # Keep last 1500 chars (instructions + format)
        suffix = prompt[-1500:]

        # Replace middle with trimming message
        trimmed_prompt = (
            prefix + "\n[...some log entries trimmed for length...]\n" + suffix
        )

        log.warn(f"Prompt trimmed from {len(prompt)} to {len(trimmed_prompt)} chars")

        return trimmed_prompt

    def _call_ollama(self, prompt: str) -> str:
        """
        Call Ollama API with the given prompt using streaming.

        Args:
            prompt: The prompt string to send to LLM

        Returns:
            Response text from LLM, or empty string on error
        """
        import json

        for attempt in range(self.max_retries + 1):
            try:
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {
                        "temperature": 0.2,
                        "top_p": 0.9,
                        "num_predict": LLM_MAX_TOKENS,
                        "keep_alive": ("10m" if LLM_KEEP_ALIVE else "0"),
                    },
                }

                response = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json=payload,
                    stream=True,
                    timeout=(10, self.timeout),
                )

                if response.status_code == 200:
                    full_response = ""
                    token_count = 0
                    log.debug("Receiving response")

                    for line in response.iter_lines():
                        if line:
                            line_str = line.decode("utf-8")
                            try:
                                data = json.loads(line_str)
                                if "response" in data:
                                    chunk = data["response"]
                                    full_response += chunk
                                    token_count += 1
                                    if token_count % 10 == 0:
                                        log.debug(".")
                                if data.get("done", False):
                                    break
                            except json.JSONDecodeError:
                                continue

                    print()  # Newline after dots
                    return full_response
                else:
                    print(f"ERROR: Ollama returned status {response.status_code}")

            except requests.ConnectionError:
                print("ERROR: Cannot connect to Ollama")
            except requests.Timeout:
                print(f"ERROR: Ollama request timed out after {self.timeout}s")
            except Exception as e:
                print(f"ERROR: Failed to call Ollama: {e}")

            if attempt < self.max_retries:
                print(
                    f"Retrying in 5 seconds... (attempt {attempt + 2}/{self.max_retries + 1})"
                )
                time.sleep(5)

        return ""

    def _parse_response(self, raw: str, debug: bool = False) -> dict:

        if debug:
            print("\n=== RAW LLM RESPONSE ===")
            print(raw)
            print("=== END RAW RESPONSE ===\n")

        # Step 1: Normalize the raw text
        # Remove markdown: **, *, #
        # Normalize multiple newlines to single newline
        text = raw
        text = re.sub(r"\*+", "", text)
        text = re.sub(r"#+\s*", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        # Step 2: Split into lines for easier parsing
        lines = text.split("\n")

        # Step 3: Extract each field using
        # MULTIPLE fallback patterns per field

        # ROOT CAUSE — try these patterns:
        root_cause = _extract_field(
            text,
            [
                r"root\s*cause\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
                r"root\s*cause\s*[:\-]\s*(.+)",
                r"cause\s*:\s*(.+)",
            ],
        )
        if not root_cause:
            root_cause = "Could not determine root cause"

        # AFFECTED SERVICES — try these patterns:
        affected_services = _extract_field(
            text,
            [
                r"affected\s*services?\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
                r"services?\s*affected\s*:\s*(.+)",
                r"impacted\s*services?\s*:\s*(.+)",
            ],
        )
        if not affected_services:
            affected_services = "Unknown"

        # FAILURE CHAIN — try these patterns:
        # (may span multiple lines)
        failure_chain = _extract_multiline_field(
            text,
            [
                r"failure\s*chain\s*:\s*(.+?)(?=\nSUGGESTED|\nCONFIDENCE|\Z)",
                r"chain\s*:\s*(.+?)(?=\nSUGGESTED|\nCONFIDENCE|\Z)",
            ],
        )
        if not failure_chain:
            failure_chain = "Could not determine failure chain"

        # SUGGESTED FIXES — parse "- [Priority] fix" lines
        # Try multiple formats:
        suggested_fixes = []

        # Format 1: - [High] fix text
        fixes_1 = re.findall(r"-\s*\[(high|medium|low)\]\s*(.+)", text, re.IGNORECASE)
        # Format 2: [High] fix text
        fixes_2 = re.findall(r"\[(high|medium|low)\]\s*(.+)", text, re.IGNORECASE)
        # Format 3: High: fix text
        fixes_3 = re.findall(
            r"(high|medium|low)\s*(?:priority)?\s*[:\-]\s*(.+)", text, re.IGNORECASE
        )
        # Format 4: numbered list with priority word
        fixes_4 = re.findall(
            r"\d+\.\s*(high|medium|low)[:\s]+(.+)", text, re.IGNORECASE
        )

        raw_fixes = fixes_1 or fixes_2 or fixes_3 or fixes_4
        for priority, fix_text in raw_fixes:
            suggested_fixes.append(
                {"priority": priority.capitalize(), "fix": fix_text.strip()}
            )

        # If still no fixes found — extract any numbered
        # or bulleted list items after SUGGESTED FIXES:
        if not suggested_fixes:
            section = _extract_multiline_field(
                text,
                [
                    r"suggested\s*fixes?\s*:\s*(.+?)(?=\nCONFIDENCE|\Z)",
                ],
            )
            if section:
                items = re.findall(r"[-\d\.]+\s*(.{10,})", section)
                for i, item in enumerate(items[:3]):
                    priorities = ["High", "Medium", "Low"]
                    suggested_fixes.append(
                        {"priority": priorities[i], "fix": item.strip()}
                    )

        # CONFIDENCE — try multiple patterns:
        confidence = 0
        conf_patterns = [
            r"confidence\s*(?:score)?\s*:\s*(\d+)\s*%",
            r"confidence\s*(?:score)?\s*:\s*(\d+)",
            r"(\d+)\s*%\s*confidence",
            r"(\d+)\s*/\s*100",
            r"confidence[^\d]+(\d+)",
        ]
        for pattern in conf_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                confidence = int(match.group(1))
                confidence = max(0, min(100, confidence))
                break
        if confidence == 0:
            confidence = 50

        # CONFIDENCE REASON — try these patterns:
        confidence_reason = _extract_field(
            text,
            [
                r"confidence\s*reason\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
                r"reason\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
                r"because\s+(.+?)(?=\n|\Z)",
            ],
        )
        if not confidence_reason:
            confidence_reason = "Confidence based on available log data"

        # HISTORICAL MATCH
        historical_match = _extract_field(
            text,
            [
                r"historical\s*match\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
                r"historical\s*pattern\s*:\s*(.+)",
                r"matches?\s+historical\s*:\s*(.+)",
            ],
        )
        if not historical_match:
            historical_match = "no"

        return {
            "root_cause": root_cause.strip(),
            "affected_services": affected_services.strip(),
            "failure_chain": failure_chain.strip(),
            "suggested_fixes": suggested_fixes,
            "confidence": confidence,
            "confidence_reason": confidence_reason.strip(),
            "historical_match": historical_match.strip(),
            "raw_response": raw,
        }

    def analyze_baseline(self,
                     context: dict,
                     query: str = "") -> dict:
        """
        Full baseline analysis pipeline.

        Args:
            context: Context dictionary from ContextBuilder.build()

        Returns:
            Analysis result dictionary
        """
        print("=== SRE-AI Baseline Analysis ===")
        print(f"Model    : {self.model}")
        print(f"Timeout  : {self.timeout}s")
        print()

        # Check Ollama connection
        if not self.check_ollama_connection():
            return {
                "mode": "baseline_failed",
                "root_cause": "Could not reach Ollama",
                "affected_services": "",
                "failure_chain": "",
                "suggested_fixes": [],
                "confidence": 0,
                "confidence_reason": "Ollama not running",
                "raw_response": "",
            }

        # Build prompt
        prompt = self.build_baseline_prompt(context)
        print(f"Prompt   : {len(prompt)} chars")
        print()

        # Check cache first
        cached = self.cache.get(
            prompt, "baseline", query=query
        )
        if cached:
            log.info("[bold green]Cache hit![/] Returning cached RCA result.")
            return cached

        # Call LLM
        print("Sending to Ollama...")
        raw_response = self._call_ollama(prompt)

        if not raw_response:
            return {
                "mode": "baseline_failed",
                "root_cause": "LLM analysis failed",
                "affected_services": "",
                "failure_chain": "",
                "suggested_fixes": [],
                "confidence": 0,
                "confidence_reason": "LLM returned empty response",
                "raw_response": "",
            }

        # Parse response
        print("Parsing response...")
        parsed = self._parse_response(raw_response, debug=True)

        print("Done.")

        # Build result
        result = {
            "mode": "baseline",
            "root_cause": parsed["root_cause"],
            "affected_services": parsed["affected_services"],
            "failure_chain": parsed["failure_chain"],
            "suggested_fixes": parsed["suggested_fixes"],
            "confidence": parsed["confidence"],
            "confidence_reason": parsed["confidence_reason"],
            "raw_response": raw_response,
        }

        # Cache the result
        self.cache.set(
            prompt, "baseline", result, query=query
        )

        return result

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TASK 14 HOOKS — leave these as stubs
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def build_rag_prompt(self, context: dict, rag_context: str) -> str:
        """
        Build the RAG-augmented prompt for LLM analysis.

        Args:
            context: Context dictionary from ContextBuilder.build()
            rag_context: Formatted historical incident context from RAG

        Returns:
            Full RAG-augmented prompt string
        """
        prompt = f"""You are an expert SRE (Site Reliability Engineer)
with deep knowledge of Kubernetes and microservices.
Analyze the following incident carefully.
You have been provided with similar historical
incidents that were previously resolved — use them
to improve the accuracy and specificity of your
root cause analysis.

{context["formatted_logs"]}

{context["formatted_resources"]}

=== INCIDENT CONTEXT ===
Services affected : {context["services_affected"]}
Failure chain     : {context["failure_chain"]}
Time window       : {context["log_window"]}
Total errors      : {context["error_count"]}

=== SIMILAR HISTORICAL INCIDENTS ===
{rag_context}

=== YOUR TASK ===
Using the current logs, resource data, AND the
historical incident patterns above, provide a
detailed root cause analysis.

If the current incident matches a historical pattern,
explicitly reference it and use the known resolution
to inform your suggested fixes.

You MUST respond in this EXACT format.
Do not add any text outside this format:

ROOT CAUSE: [one clear sentence identifying the
             root cause — reference historical
             pattern if applicable]

AFFECTED SERVICES: [comma separated list in order
                    of impact]

FAILURE CHAIN:
[step 1 — what happened first]
[step 2 — what happened next]
[step 3 — how it cascaded]

SUGGESTED FIXES:
- [High] [specific fix — reference historical
          resolution if applicable]
- [Medium] [specific actionable fix]
- [Low] [specific actionable fix]

CONFIDENCE: [number between 0-100]%

CONFIDENCE REASON: [one sentence — mention if
                    historical match boosted
                    confidence]

HISTORICAL MATCH: [yes/no — name of matched
                   incident if yes, e.g.
                   "yes — DB connection pool
                   exhaustion (incident_001.log)"]
"""
        return self._trim_prompt(prompt)

    def analyze_rag(self,
                context: dict,
                rag_context: str,
                query: str = "") -> dict:
        """
        Full RAG-augmented analysis pipeline.

        Args:
            context: Context dictionary from ContextBuilder.build()
            rag_context: Formatted historical incident context from RAG

        Returns:
            Analysis result dictionary
        """
        print("=== SRE-AI RAG-Augmented Analysis ===")
        print(f"Model    : {self.model}")
        print(f"Prompt   : {len(self.build_rag_prompt(context, rag_context))} chars")
        print(f"Timeout  : {self.timeout}s")
        print(f"RAG ctx  : {len(rag_context)} chars of historical context")
        print()

        # Check Ollama connection
        if not self.check_ollama_connection():
            return {
                "mode": "rag_failed",
                "root_cause": "Could not reach Ollama",
                "affected_services": "",
                "failure_chain": "",
                "suggested_fixes": [],
                "confidence": 0,
                "confidence_reason": "Ollama not running",
                "historical_match": "no",
                "raw_response": "",
            }

        # Build RAG prompt
        prompt = self.build_rag_prompt(context, rag_context)

        # Check cache first
        cached = self.cache.get(
            prompt, "rag", query=query
        )
        if cached:
            log.info("[bold green]Cache hit![/] Returning cached RAG result.")
            return cached

        # Call LLM
        print("Sending to Ollama...")
        raw_response = self._call_ollama(prompt)

        if not raw_response:
            return {
                "mode": "rag_failed",
                "root_cause": "LLM analysis failed",
                "affected_services": "",
                "failure_chain": "",
                "suggested_fixes": [],
                "confidence": 0,
                "confidence_reason": "LLM returned empty response",
                "historical_match": "no",
                "raw_response": "",
            }

        # Parse response
        print("Parsing response...")
        parsed = self._parse_response(raw_response, debug=True)

        print("Done.")

        # Build result
        result = {
            "mode": "rag",
            "root_cause": parsed["root_cause"],
            "affected_services": parsed["affected_services"],
            "failure_chain": parsed["failure_chain"],
            "suggested_fixes": parsed["suggested_fixes"],
            "confidence": parsed["confidence"],
            "confidence_reason": parsed["confidence_reason"],
            "historical_match": parsed["historical_match"],
            "raw_response": raw_response,
        }

        # Cache the result
        self.cache.set(
            prompt, "rag", result, query=query
        )

        return result

    def build_investigation_prompt(
            self,
            report: "InvestigationReport",
            summary_text: str) -> str:
        lines = []

        # Role
        lines.append(
            "You are a senior SRE engineer with "
            "10+ years of Kubernetes and "
            "microservices experience. "
            "You are investigating a production "
            "incident. Think step by step. "
            "Consider every possible cause before "
            "concluding. Do not guess \u2014 base your "
            "analysis strictly on the evidence."
        )
        lines.append("")

        # Incident overview
        lines.append("=== INCIDENT OVERVIEW ===")
        lines.append(
            f"Target service: "
            f"{report.target_service}"
        )
        lines.append(
            f"Namespace: {report.namespace}"
        )
        lines.append(
            f"Data source: {report.data_source}"
        )
        lines.append(
            f"Services investigated: "
            f"{list(report.evidence.keys())}"
        )
        lines.append(
            f"Blast radius \u2014 downstream: "
            f"{report.blast_radius.get('downstream', [])}"
        )
        lines.append(
            f"Blast radius \u2014 upstream: "
            f"{report.blast_radius.get('upstream', [])}"
        )
        lines.append(
            f"Safe services: "
            f"{report.blast_radius.get('safe_services', [])}"
        )
        lines.append(
            f"Pre-analysis root cause: "
            f"{report.probable_root_cause}"
        )
        lines.append("")

        # Service health summary
        lines.append(
            "=== SERVICE HEALTH SUMMARY ==="
        )
        for svc, ev in report.evidence.items():
            lines.append(
                f"{svc}: {ev.health_status} | "
                f"errors={ev.error_count} "
                f"warnings={ev.warning_count} | "
                f"role={ev.role_in_incident}"
            )
            if ev.exit_codes:
                lines.append(
                    f"  Exit codes: {ev.exit_codes}"
                    + (
                        " (137=OOMKill)"
                        if 137 in ev.exit_codes
                        else ""
                    )
                )
        lines.append("")

        # Pre-analysis detected patterns
        lines.append(
            "=== PRE-ANALYSIS DETECTED PATTERNS ==="
        )
        lines.append(
            "These were detected by rule-based "
            "analysis. Use as strong hints:"
        )
        if report.patterns_by_category:
            for cat, items in (
                report.patterns_by_category.items()
            ):
                lines.append(f"\nCategory: {cat}")
                for item in items:
                    p = item["pattern"]
                    lines.append(
                        f"  [{p.severity}] "
                        f"{item['service']}: "
                        f"{p.pattern_id}"
                    )
                    lines.append(
                        f"    Description: "
                        f"{p.description}"
                    )
                    lines.append(
                        f"    Evidence: "
                        f"{p.evidence[:100]}"
                    )
                    lines.append(
                        f"    Remediation hint: "
                        f"{p.remediation_hint}"
                    )
        else:
            lines.append(
                "No patterns detected by "
                "rule-based analysis."
            )
        lines.append("")

        # Resource metrics
        lines.append(
            "=== RESOURCE METRICS ==="
        )
        for svc, ev in report.evidence.items():
            if ev.resource_metrics:
                m = ev.resource_metrics
                lines.append(f"{svc}:")
                lines.append(
                    f"  CPU: "
                    f"{m.get('cpu_usage','?')} / "
                    f"{m.get('cpu_limit','?')} "
                    f"({m.get('cpu_percent','?')}%)"
                )
                lines.append(
                    f"  Memory: "
                    f"{m.get('memory_usage','?')} / "
                    f"{m.get('memory_limit','?')} "
                    f"({m.get('memory_percent','?')}%)"
                )
                lines.append(
                    f"  Restarts: "
                    f"{m.get('restarts','?')}"
                )
                lines.append(
                    f"  Status: "
                    f"{m.get('status','?')}"
                )
        lines.append("")

        # Service logs \u2014 errors only, last 5 per container
        lines.append(
            "=== SERVICE LOG ERRORS ==="
        )
        processor_ref = None
        try:
            from core.log_processor import (
                LogProcessor
            )
            processor_ref = LogProcessor()
        except Exception:
            pass

        for svc, ev in report.evidence.items():
            if not ev.container_logs:
                continue
            lines.append(f"\n--- {svc} ---")
            for container, c_lines in (
                ev.container_logs.items()
            ):
                if not c_lines:
                    continue
                if processor_ref:
                    entries = processor_ref.process(
                        c_lines
                    )
                    errors = (
                        processor_ref
                        .filter_by_severity(
                            entries, "ERROR"
                        )
                    )
                    if errors:
                        lines.append(
                            f"  [{container}] "
                            f"errors ({len(errors)}):"
                        )
                        for e in errors[-5:]:
                            lines.append(
                                f"    "
                                f"{e['raw'][:120]}"
                            )
                else:
                    error_lines = [
                        l for l in c_lines
                        if "error" in l.lower() or
                        "ERROR" in l
                    ]
                    for el in error_lines[-5:]:
                        lines.append(
                            f"  [{container}] "
                            f"{el[:120]}"
                        )
        lines.append("")

        # Kubernetes events
        lines.append(
            "=== KUBERNETES EVENTS ==="
        )
        for svc, ev in report.evidence.items():
            if ev.events_output:
                lines.append(f"\n--- {svc} ---")
                event_lines = (
                    ev.events_output
                    .split("\n")[:20]
                )
                for el in event_lines:
                    if el.strip():
                        lines.append(
                            f"  {el[:150]}"
                        )
        lines.append("")

        # Describe \u2014 key fields only
        lines.append(
            "=== POD DESCRIBE (KEY FIELDS) ==="
        )
        key_fields = [
            "Status:", "Conditions:",
            "Last State:", "Exit Code:",
            "Reason:", "Message:",
            "Events:", "Warning",
            "Liveness:", "Readiness:",
            "Limits:", "Requests:",
            "Ready:", "Restart Count:"
        ]
        for svc, ev in report.evidence.items():
            if not ev.describe_output:
                continue
            lines.append(f"\n--- {svc} ---")
            desc_lines = (
                ev.describe_output.split("\n")
            )
            for dl in desc_lines:
                if any(
                    kf in dl for kf in key_fields
                ):
                    lines.append(
                        f"  {dl.strip()[:150]}"
                    )
        lines.append("")

        # Deployment history
        lines.append(
            "=== DEPLOYMENT HISTORY ==="
        )
        shown_history = False
        for svc, ev in report.evidence.items():
            if ev.rollout_history:
                lines.append(f"\n--- {svc} ---")
                for rl in (
                    ev.rollout_history
                    .split("\n")[:10]
                ):
                    if rl.strip():
                        lines.append(
                            f"  {rl[:120]}"
                        )
                if ev.deployment_age_minutes is not (
                    None
                ):
                    age = ev.deployment_age_minutes
                    lines.append(
                        f"  Deployment age: "
                        f"{age} minutes"
                    )
                    if age < 15:
                        lines.append(
                            f"  \u26a0 RECENT DEPLOYMENT "
                            f"({age} min ago) \u2014 "
                            f"consider as possible "
                            f"cause of incident"
                        )
                shown_history = True
                break  # one history is enough
        if not shown_history:
            lines.append(
                "  No deployment history available"
            )
        lines.append("")

        # Instructions
        lines.append("=== YOUR TASK ===")
        lines.append(
            "Based on ALL evidence above, provide "
            "a thorough root cause analysis. "
            "Think like a senior SRE. Consider: "
            "application bugs, config errors, "
            "infrastructure issues, network/mesh "
            "problems, recent deployments, resource "
            "constraints, external dependencies, "
            "and cascade failures."
        )
        lines.append(
            "\nProvide kubectl commands for the "
            f"namespace: {report.namespace}"
        )
        lines.append("")

        # Output format
        lines.append(
            "Respond ONLY in this exact format. "
            "No text outside this format:\n"
        )
        lines.append(
            "INVESTIGATION SUMMARY:\n"
            "[2-3 sentences: what happened, "
            "why, and what was affected]\n"
        )
        lines.append(
            "PROBABLE ROOT CAUSE:\n"
            "Service: [service name]\n"
            "Cause: [specific technical cause]\n"
            "Confidence: [0-100]%\n"
        )
        lines.append(
            "RANKED CAUSES:\n"
            "Category: [Resource/Network/"
            "Config/Deployment/Storage]\n"
            "N. [Service]: [cause]\n"
            "   Confidence: N%\n"
            "   Evidence: [evidence]\n"
        )
        lines.append(
            "SAFE SERVICES:\n"
            "[services that are healthy]\n"
        )
        lines.append(
            "CASCADE ANALYSIS:\n"
            "[failure chain in order]\n"
        )
        lines.append(
            "REMEDIATION STEPS:\n"
            "\n"
            "Priority: IMMEDIATE\n"
            "Step 1: [what to do]\n"
            f"  Command: kubectl [cmd] "
            f"-n {report.namespace}\n"
            "  Explanation: [why]\n"
            "\n"
            "Priority: SHORT-TERM\n"
            "Step 2: [what to do]\n"
            "  Command: kubectl [cmd]\n"
            "  Explanation: [why]\n"
            "\n"
            "Priority: LONG-TERM\n"
            "Step 3: [what to do]\n"
            "  Command: [cmd or config change]\n"
            "  Explanation: [why]\n"
        )
        lines.append(
            "CONFIDENCE SCORE: [0-100]%\n"
            "CONFIDENCE REASON: [one sentence]\n"
        )

        prompt = "\n".join(lines)
        return self._trim_prompt(prompt)

    def analyze_investigation(
                          report,
                          investigator=None,
                          query: str = "") -> dict:
        summary_text = ""
        if investigator:
            try:
                summary_text = (
                    investigator.get_summary_text(
                        report
                    )
                )
            except Exception:
                pass

        prompt = self.build_investigation_prompt(
            report, summary_text
        )

        cache_key = (
            f"investigation:{report.target_service}"
            f":{report.namespace}"
        )
        cached = self.cache.get(
            prompt, "investigation", query=query
        )
        if cached:
            log.info(
                "[bold green]Cache hit![/] "
                "Returning cached investigation."
            )
            return cached

        if not self.check_ollama_connection():
            log.error(
                "Ollama not running. "
                "Start with: ollama serve"
            )
            return self._empty_investigation_result(
                report
            )

        log.info(
            f"\n[bold cyan]=== SRE-AI Deep "
            f"Investigation ===[/bold cyan]"
        )
        log.info(
            f"[dim]Target  : "
            f"{report.target_service}[/dim]"
        )
        log.info(
            f"[dim]Services: "
            f"{len(report.evidence)}[/dim]"
        )
        log.info(
            f"[dim]Patterns: "
            f"{sum(len(v) for v in report.patterns_by_category.values())}"
            f"[/dim]"
        )
        log.info(
            f"[dim]Prompt  : "
            f"{len(prompt)} chars[/dim]"
        )
        log.info(
            "[dim]Sending to Ollama...[/dim]"
        )

        raw = self._call_ollama(prompt)

        if not raw:
            log.error(
                "LLM returned empty response"
            )
            return self._empty_investigation_result(
                report
            )

        result = self._parse_investigation_response(
            raw, report
        )

        self.cache.set(prompt, "investigation",
        result, query=query)

        return result

    def _parse_investigation_response(
            self,
            raw: str,
            report: "InvestigationReport"
            ) -> dict:
        text = re.sub(r'\*+', '', raw)
        text = re.sub(r'#+\s*', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        def extract(pattern, default=""):
            m = re.search(
                pattern, text,
                re.IGNORECASE | re.DOTALL
            )
            if m:
                return m.group(1).strip()
            return default

        def extract_int(pattern, default=50):
            m = re.search(
                pattern, text, re.IGNORECASE
            )
            if m:
                try:
                    v = int(
                        re.search(
                            r'\d+', m.group(1)
                        ).group()
                    )
                    return max(0, min(100, v))
                except Exception:
                    pass
            return default

        inv_summary = extract(
            r"INVESTIGATION SUMMARY[:\s]*"
            r"\n(.+?)(?=\nPROBABLE ROOT CAUSE"
            r"|\nRANKED|\Z)"
        )

        prc_service = extract(
            r"PROBABLE ROOT CAUSE.*?Service[:\s]+"
            r"([^\n]+)"
        ) or report.probable_root_cause

        prc_desc = extract(
            r"PROBABLE ROOT CAUSE.*?Cause[:\s]+"
            r"([^\n]+)"
        )

        prc_conf = extract_int(
            r"PROBABLE ROOT CAUSE.*?"
            r"Confidence[:\s]+(\d+)"
        )

        ranked_causes = []
        cat_pattern = re.finditer(
            r"Category:\s*(\w+)\n"
            r"(\d+)\.\s*([^:]+):\s*([^\n]+)\n"
            r"\s*Confidence:\s*(\d+)%\n"
            r"\s*Evidence:\s*([^\n]+)",
            text,
            re.IGNORECASE
        )
        for m in cat_pattern:
            try:
                ranked_causes.append({
                    "rank": int(m.group(2)),
                    "category": m.group(1).strip(),
                    "service": m.group(3).strip(),
                    "cause": m.group(4).strip(),
                    "confidence": int(m.group(5)),
                    "evidence": m.group(6).strip()
                })
            except Exception:
                pass

        safe_text = extract(
            r"SAFE SERVICES[:\s]*\n"
            r"(.+?)(?=\nCASCADE|\nREMED|\Z)"
        )
        safe_services = [
            s.strip().strip("-").strip()
            for s in safe_text.split("\n")
            if s.strip() and
            len(s.strip()) > 2
        ] if safe_text else (
            report.blast_radius.get(
                "safe_services", []
            )
        )

        cascade = extract(
            r"CASCADE ANALYSIS[:\s]*\n"
            r"(.+?)(?=\nREMEDIATION|\Z)"
        )

        remediation_steps = []
        priority_blocks = re.finditer(
            r"Priority:\s*(IMMEDIATE|SHORT.TERM"
            r"|LONG.TERM)\s*\n"
            r"Step\s*(\d+):\s*([^\n]+)\n"
            r"\s*Command:\s*([^\n]+)\n"
            r"\s*Explanation:\s*([^\n]+)",
            text,
            re.IGNORECASE
        )
        for m in priority_blocks:
            remediation_steps.append({
                "priority": m.group(1).upper(),
                "step": int(m.group(2)),
                "action": m.group(3).strip(),
                "command": m.group(4).strip(),
                "explanation": m.group(5).strip()
            })

        if not remediation_steps:
            step_matches = re.finditer(
                r"Step\s*(\d+)[:\s]*([^\n]+)\n"
                r"(?:.*?Command:\s*([^\n]+)\n)?",
                text,
                re.IGNORECASE
            )
            priorities = [
                "IMMEDIATE", "SHORT-TERM",
                "LONG-TERM"
            ]
            for i, m in enumerate(step_matches):
                remediation_steps.append({
                    "priority": priorities[
                        min(i, len(priorities)-1)
                    ],
                    "step": int(m.group(1)),
                    "action": m.group(2).strip(),
                    "command": (
                        m.group(3).strip()
                        if m.group(3) else ""
                    ),
                    "explanation": ""
                })

        confidence = extract_int(
            r"CONFIDENCE SCORE[:\s]+(\d+)"
        )
        if confidence == 50:
            confidence = extract_int(
                r"CONFIDENCE[:\s]+(\d+)"
            )

        conf_reason = extract(
            r"CONFIDENCE REASON[:\s]+([^\n]+)"
        ) or "Based on available evidence"

        patterns_summary = {}
        for cat, items in (
            report.patterns_by_category.items()
        ):
            patterns_summary[cat] = [
                f"{item['service']}: "
                f"{item['pattern'].pattern_id}"
                for item in items
            ]

        return {
            "mode": "investigation",
            "target_service": report.target_service,
            "namespace": report.namespace,
            "data_source": report.data_source,
            "investigation_summary": (
                inv_summary or
                "Investigation complete. "
                "See ranked causes below."
            ),
            "probable_root_cause_service": (
                prc_service
            ),
            "probable_root_cause": (
                prc_desc or
                "See ranked causes below"
            ),
            "ranked_causes": ranked_causes,
            "safe_services": safe_services,
            "cascade_analysis": (
                cascade or
                "See cascade timeline below"
            ),
            "remediation_steps": remediation_steps,
            "confidence": confidence,
            "confidence_reason": conf_reason,
            "pre_analysis_root_cause": (
                report.probable_root_cause
            ),
            "patterns_by_category": (
                patterns_summary
            ),
            "cascade_timeline": (
                report.cascade_timeline
            ),
            "services_health": {
                svc: ev.health_status
                for svc, ev in
                report.evidence.items()
            },
            "raw_response": raw
        }

    def _empty_investigation_result(
            self,
            report: "InvestigationReport"
            ) -> dict:
        return {
            "mode": "investigation_failed",
            "target_service": report.target_service,
            "namespace": report.namespace,
            "data_source": report.data_source,
            "investigation_summary": (
                "LLM analysis failed. "
                "Rule-based pre-analysis results "
                "are shown below."
            ),
            "probable_root_cause_service": (
                report.probable_root_cause
            ),
            "probable_root_cause": (
                "Determined by rule-based analysis"
                " only (LLM unavailable)"
            ),
            "ranked_causes": [],
            "safe_services": report.blast_radius.get(
                "safe_services", []
            ),
            "cascade_analysis": "",
            "remediation_steps": [],
            "confidence": 0,
            "confidence_reason": (
                "LLM call failed"
            ),
            "pre_analysis_root_cause": (
                report.probable_root_cause
            ),
            "patterns_by_category": {
                cat: [
                    f"{item['service']}: "
                    f"{item['pattern'].pattern_id}"
                    for item in items
                ]
                for cat, items in
                report.patterns_by_category.items()
            },
            "cascade_timeline": (
                report.cascade_timeline
            ),
            "services_health": {
                svc: ev.health_status
                for svc, ev in
                report.evidence.items()
            },
            "raw_response": ""
        }


def _extract_field(text: str, patterns: list[str]) -> str:
    # Try each pattern, return first match found
    # All patterns use IGNORECASE + DOTALL
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1).strip()
            # Clean up: remove leading/trailing
            # punctuation and excess whitespace
            value = re.sub(r"\s+", " ", value)
            value = value.strip(":-").strip()
            if len(value) > 3:
                return value
    return ""


def _extract_multiline_field(text: str, patterns: list[str]) -> str:
    # Same as _extract_field but preserves newlines
    # in the extracted value
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1).strip()
            if len(value) > 3:
                return value
    return ""


if __name__ == "__main__":
    from core.log_loader import LogLoader
    from core.log_processor import LogProcessor
    from core.resource_collector import ResourceCollector
    from core.context_builder import ContextBuilder
    from core.rag_engine import RAGEngine
    from config import HISTORICAL_LOGS_DIR

    loader = LogLoader()
    processor = LogProcessor()
    collector = ResourceCollector()
    builder = ContextBuilder()
    analyzer = LLMAnalyzer()
    rag = RAGEngine(HISTORICAL_LOGS_DIR)

    print("--- Pre-flight: Ollama check ---")
    connected = analyzer.check_ollama_connection()
    if not connected:
        print("Fix Ollama first: ollama serve")
        exit(1)

    print("\n--- Building pipeline context ---")
    lines = loader.load("logs/test.log")
    entries = processor.process(lines)
    filtered = processor.filter_by_severity(entries, "ERROR")
    summary = processor.get_summary(entries)
    resources = collector.get_mock_resources(summary["services"])
    context = builder.build(filtered, resources)

    print("\n--- RAG retrieval ---")
    retrieved = rag.retrieve(context["formatted_logs"], top_k=3)
    rag_context = rag.format_retrieved_context(retrieved)
    print(f"RAG context length: {len(rag_context)} chars")

    print("\n--- Test 1: Baseline analysis ---")
    print("Running baseline mode...")
    baseline_result = analyzer.analyze_baseline(context)
    print(f"Mode      : {baseline_result['mode']}")
    print(f"Root cause: {baseline_result['root_cause']}")
    print(f"Confidence: {baseline_result['confidence']}%")

    print("\n--- Test 2: RAG analysis ---")
    print("Running RAG mode...")
    rag_result = analyzer.analyze_rag(context, rag_context)
    print(f"Mode            : {rag_result['mode']}")
    print(f"Root cause      : {rag_result['root_cause']}")
    print(f"Confidence      : {rag_result['confidence']}%")
    print(f"Historical match: {rag_result['historical_match']}")

    print("\n--- Test 3: Compare confidence ---")
    diff = rag_result["confidence"] - baseline_result["confidence"]
    print(f"Baseline confidence : {baseline_result['confidence']}%")
    print(f"RAG confidence      : {rag_result['confidence']}%")
    print(f"Difference          : {'+' if diff >= 0 else ''}{diff}%")
    if diff >= 0:
        print("RAG mode matched or improved confidence.")
    else:
        print("Note: RAG confidence lower this run —")
        print("  normal with small models + mock data.")
        print("  Will improve with real kubectl data.")

    print("\n--- Test 4: RAG prompt preview ---")
    rag_prompt = analyzer.build_rag_prompt(context, rag_context)
    print(f"RAG prompt length: {len(rag_prompt)} chars")
    print(f"Contains historical context: {'SIMILAR HISTORICAL' in rag_prompt}")

    print("\nTask 14 OK")
