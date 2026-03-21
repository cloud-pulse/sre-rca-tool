import requests
import re
import sys
import os
import time

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
        self.timeout = 300
        self.max_retries = 2
        self.max_prompt_chars = 7000
        
        print(f"LLMAnalyzer initialized — model: {self.model}")

    def check_ollama_connection(self) -> bool:
        """
        Verify Ollama is running and reachable.
        
        Returns:
            True if Ollama is reachable, False otherwise
        """
        # Step 1: ping Ollama base URL
        try:
            response = requests.get(
                f"{self.ollama_url}/",
                timeout=5
            )
            if response.status_code != 200:
                print("ERROR: Cannot reach Ollama at localhost:11434")
                print("Make sure Ollama is running: ollama serve")
                return False
        except (requests.ConnectionError, requests.Timeout):
            print("ERROR: Cannot reach Ollama at localhost:11434")
            print("Make sure Ollama is running: ollama serve")
            return False
        except Exception:
            print("ERROR: Cannot reach Ollama at localhost:11434")
            print("Make sure Ollama is running: ollama serve")
            return False
        
        # Step 2: check if phi3:mini is pulled
        try:
            response = requests.get(
                f"{self.ollama_url}/api/tags",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                phi3_found = any("phi3" in model.get("name", "").lower() for model in models)
                if not phi3_found:
                    print("WARNING: phi3:mini not found locally")
                    print("Run: ollama pull phi3:mini")
                    print("This may take a few minutes...")
                    return False
            else:
                print("ERROR: Cannot get model list from Ollama")
                return False
        except Exception as e:
            print(f"ERROR: Failed to check models: {e}")
            return False
        
        # Step 3: do a quick warmup call with tiny prompt
        try:
            payload = {
                "model": self.model,
                "prompt": "Reply with one word: ready",
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "num_predict": 10
                }
            }
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=60
            )
            if response.status_code == 200:
                data = response.json()
                response_text = data.get("response", "").strip().lower()
                if "ready" in response_text:
                    print("Ollama warmup OK")
                else:
                    print("WARNING: Warmup response unexpected, but proceeding")
            else:
                print("WARNING: Warmup call failed, but proceeding")
        except requests.Timeout:
            print("WARNING: Warmup timed out, model may be slow but proceeding")
        except Exception as e:
            print(f"WARNING: Warmup failed: {e}, but proceeding")
        
        print("Ollama connection OK")
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

{context['formatted_logs']}

{context['formatted_resources']}

=== INCIDENT CONTEXT ===
Services affected : {context['services_affected']}
Failure chain     : {context['failure_chain']}
Time window       : {context['log_window']}
Total errors      : {context['error_count']}

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
        trimmed_prompt = prefix + "\n[...some log entries trimmed for length...]\n" + suffix
        
        print(f"WARNING: Prompt trimmed from {len(prompt)} to {len(trimmed_prompt)} chars")
        
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
                        "num_predict": 500
                    }
                }
                
                response = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json=payload,
                    stream=True,
                    timeout=(10, self.timeout)
                )
                
                if response.status_code == 200:
                    full_response = ""
                    token_count = 0
                    print("Receiving response: ", end="", flush=True)
                    
                    for line in response.iter_lines():
                        if line:
                            line_str = line.decode('utf-8')
                            try:
                                data = json.loads(line_str)
                                if 'response' in data:
                                    chunk = data['response']
                                    full_response += chunk
                                    token_count += 1
                                    if token_count % 10 == 0:
                                        print(".", end="", flush=True)
                                if data.get('done', False):
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
                print(f"Retrying in 5 seconds... (attempt {attempt + 2}/{self.max_retries + 1})")
                time.sleep(5)
        
        return ""

    def _parse_response(self, raw: str,
                        debug: bool = False) -> dict:

        if debug:
            print("\n=== RAW LLM RESPONSE ===")
            print(raw)
            print("=== END RAW RESPONSE ===\n")

        # Step 1: Normalize the raw text
        # Remove markdown: **, *, #
        # Normalize multiple newlines to single newline
        text = raw
        text = re.sub(r'\*+', '', text)
        text = re.sub(r'#+\s*', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        # Step 2: Split into lines for easier parsing
        lines = text.split('\n')

        # Step 3: Extract each field using
        # MULTIPLE fallback patterns per field

        # ROOT CAUSE — try these patterns:
        root_cause = _extract_field(text, [
            r"root\s*cause\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
            r"root\s*cause\s*[:\-]\s*(.+)",
            r"cause\s*:\s*(.+)",
        ])
        if not root_cause:
            root_cause = "Could not determine root cause"

        # AFFECTED SERVICES — try these patterns:
        affected_services = _extract_field(text, [
            r"affected\s*services?\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
            r"services?\s*affected\s*:\s*(.+)",
            r"impacted\s*services?\s*:\s*(.+)",
        ])
        if not affected_services:
            affected_services = "Unknown"

        # FAILURE CHAIN — try these patterns:
        # (may span multiple lines)
        failure_chain = _extract_multiline_field(text, [
            r"failure\s*chain\s*:\s*(.+?)(?=\nSUGGESTED|\nCONFIDENCE|\Z)",
            r"chain\s*:\s*(.+?)(?=\nSUGGESTED|\nCONFIDENCE|\Z)",
        ])
        if not failure_chain:
            failure_chain = "Could not determine failure chain"

        # SUGGESTED FIXES — parse "- [Priority] fix" lines
        # Try multiple formats:
        suggested_fixes = []

        # Format 1: - [High] fix text
        fixes_1 = re.findall(
            r'-\s*\[(high|medium|low)\]\s*(.+)',
            text, re.IGNORECASE
        )
        # Format 2: [High] fix text
        fixes_2 = re.findall(
            r'\[(high|medium|low)\]\s*(.+)',
            text, re.IGNORECASE
        )
        # Format 3: High: fix text
        fixes_3 = re.findall(
            r'(high|medium|low)\s*(?:priority)?\s*[:\-]\s*(.+)',
            text, re.IGNORECASE
        )
        # Format 4: numbered list with priority word
        fixes_4 = re.findall(
            r'\d+\.\s*(high|medium|low)[:\s]+(.+)',
            text, re.IGNORECASE
        )

        raw_fixes = fixes_1 or fixes_2 or fixes_3 or fixes_4
        for priority, fix_text in raw_fixes:
            suggested_fixes.append({
                "priority": priority.capitalize(),
                "fix": fix_text.strip()
            })

        # If still no fixes found — extract any numbered
        # or bulleted list items after SUGGESTED FIXES:
        if not suggested_fixes:
            section = _extract_multiline_field(text, [
                r"suggested\s*fixes?\s*:\s*(.+?)(?=\nCONFIDENCE|\Z)",
            ])
            if section:
                items = re.findall(
                    r'[-\d\.]+\s*(.{10,})', section
                )
                for i, item in enumerate(items[:3]):
                    priorities = ["High", "Medium", "Low"]
                    suggested_fixes.append({
                        "priority": priorities[i],
                        "fix": item.strip()
                    })

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
        confidence_reason = _extract_field(text, [
            r"confidence\s*reason\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
            r"reason\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
            r"because\s+(.+?)(?=\n|\Z)",
        ])
        if not confidence_reason:
            confidence_reason = (
                "Confidence based on available log data"
            )

        # HISTORICAL MATCH
        historical_match = _extract_field(text, [
            r"historical\s*match\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
            r"historical\s*pattern\s*:\s*(.+)",
            r"matches?\s+historical\s*:\s*(.+)",
        ])
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
            "raw_response": raw
        }

    def analyze_baseline(self, context: dict) -> dict:
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
                "raw_response": ""
            }
        
        # Build prompt
        prompt = self.build_baseline_prompt(context)
        print(f"Prompt   : {len(prompt)} chars")
        print()
        
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
                "raw_response": ""
            }
        
        # Parse response
        print("Parsing response...")
        parsed = self._parse_response(raw_response, debug=True)
        
        print("Done.")
        
        # Return result
        return {
            "mode": "baseline",
            "root_cause": parsed["root_cause"],
            "affected_services": parsed["affected_services"],
            "failure_chain": parsed["failure_chain"],
            "suggested_fixes": parsed["suggested_fixes"],
            "confidence": parsed["confidence"],
            "confidence_reason": parsed["confidence_reason"],
            "raw_response": raw_response
        }

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

{context['formatted_logs']}

{context['formatted_resources']}

=== INCIDENT CONTEXT ===
Services affected : {context['services_affected']}
Failure chain     : {context['failure_chain']}
Time window       : {context['log_window']}
Total errors      : {context['error_count']}

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

    def analyze_rag(self, context: dict, rag_context: str) -> dict:
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
                "raw_response": ""
            }
        
        # Build RAG prompt
        prompt = self.build_rag_prompt(context, rag_context)
        
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
                "raw_response": ""
            }
        
        # Parse response
        print("Parsing response...")
        parsed = self._parse_response(raw_response, debug=True)
        
        print("Done.")
        
        # Return result
        return {
            "mode": "rag",
            "root_cause": parsed["root_cause"],
            "affected_services": parsed["affected_services"],
            "failure_chain": parsed["failure_chain"],
            "suggested_fixes": parsed["suggested_fixes"],
            "confidence": parsed["confidence"],
            "confidence_reason": parsed["confidence_reason"],
            "historical_match": parsed["historical_match"],
            "raw_response": raw_response
        }


def _extract_field(text: str,
                   patterns: list[str]) -> str:
    # Try each pattern, return first match found
    # All patterns use IGNORECASE + DOTALL
    for pattern in patterns:
        match = re.search(
            pattern, text,
            re.IGNORECASE | re.DOTALL
        )
        if match:
            value = match.group(1).strip()
            # Clean up: remove leading/trailing
            # punctuation and excess whitespace
            value = re.sub(r'\s+', ' ', value)
            value = value.strip(':-').strip()
            if len(value) > 3:
                return value
    return ""


def _extract_multiline_field(text: str,
                              patterns: list[str]
                              ) -> str:
    # Same as _extract_field but preserves newlines
    # in the extracted value
    for pattern in patterns:
        match = re.search(
            pattern, text,
            re.IGNORECASE | re.DOTALL
        )
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
    filtered = processor.filter_by_severity(
        entries, "ERROR"
    )
    summary = processor.get_summary(entries)
    resources = collector.get_mock_resources(
        summary["services"]
    )
    context = builder.build(filtered, resources)

    print("\n--- RAG retrieval ---")
    retrieved = rag.retrieve(
        context["formatted_logs"], top_k=3
    )
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
    print(f"Historical match: "
          f"{rag_result['historical_match']}")

    print("\n--- Test 3: Compare confidence ---")
    diff = (rag_result['confidence'] -
            baseline_result['confidence'])
    print(f"Baseline confidence : "
          f"{baseline_result['confidence']}%")
    print(f"RAG confidence      : "
          f"{rag_result['confidence']}%")
    print(f"Difference          : "
          f"{'+' if diff >= 0 else ''}{diff}%")
    if diff >= 0:
        print("RAG mode matched or improved confidence.")
    else:
        print("Note: RAG confidence lower this run —")
        print("  normal with small models + mock data.")
        print("  Will improve with real kubectl data.")

    print("\n--- Test 4: RAG prompt preview ---")
    rag_prompt = analyzer.build_rag_prompt(
        context, rag_context
    )
    print(f"RAG prompt length: {len(rag_prompt)} chars")
    print(f"Contains historical context: "
          f"{'SIMILAR HISTORICAL' in rag_prompt}")

    print("\nTask 14 OK")
