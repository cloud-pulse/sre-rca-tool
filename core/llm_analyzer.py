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

import re
import flags
from core.logger import get_logger
from core.llm_cache import LLMCache
from flags import (
    LLM_TIMEOUT,
    LLM_MAX_TOKENS,
)
from core.llm_provider import provider

log = get_logger("llm_analyzer")


class LLMAnalyzer:
    """Analyzes incident context using the configured LLM provider.

    This file contains baseline + RAG pipelines plus an investigation prompt.
    Phase 5 adds Kubernetes context injection helper used by k8s/rca_engine.py.
    """

    def __init__(self):
        self.model = getattr(flags, "LLM_REASONING_MODEL", "phi3:mini")
        self.timeout = LLM_TIMEOUT
        self.max_prompt_chars = 7000
        self.cache = LLMCache()

        log.step(f"LLMAnalyzer initialized — model: {self.model}")

    def check_ollama_connection(self) -> bool:
        return True

    def warmup(self) -> bool:
        return True

    def _trim_prompt(self, prompt: str) -> str:
        if len(prompt) <= self.max_prompt_chars:
            return prompt
        prefix = prompt[:3500]
        suffix = prompt[-1500:]
        return prefix + "\n[...some log entries trimmed for length...]\n" + suffix

    def _parse_response(self, raw: str, debug: bool = False) -> dict:
        if debug:
            print("\n=== RAW LLM RESPONSE ===")
            print(raw)
            print("=== END RAW RESPONSE ===\n")

        text = raw
        text = re.sub(r"\*+", "", text)
        text = re.sub(r"#+\s*", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        def extract(patterns, default=""):
            for p in patterns:
                m = re.search(p, text, re.IGNORECASE | re.DOTALL)
                if m:
                    v = m.group(1).strip()
                    v = re.sub(r"\s+", " ", v).strip("-: ")
                    if v:
                        return v
            return default

        root_cause = extract(
            [
                r"root\s*cause\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
                r"root\s*cause\s*[:\-]\s*(.+)",
                r"cause\s*:\s*(.+)",
            ],
            "Could not determine root cause",
        )

        affected_services = extract(
            [
                r"affected\s*services?\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
                r"services?\s*affected\s*:\s*(.+)",
                r"impacted\s*services?\s*:\s*(.+)",
            ],
            "Unknown",
        )

        failure_chain = extract(
            [
                r"failure\s*chain\s*:\s*(.+?)(?=\nSUGGESTED|\nCONFIDENCE|\Z)",
                r"chain\s*:\s*(.+?)(?=\nSUGGESTED|\nCONFIDENCE|\Z)",
            ],
            "Could not determine failure chain",
        )

        suggested_fixes = []
        raw_fixes = re.findall(r"-\s*\[(high|medium|low)\]\s*(.+)", text, re.IGNORECASE)
        if not raw_fixes:
            raw_fixes = re.findall(r"\[(high|medium|low)\]\s*(.+)", text, re.IGNORECASE)
        if not raw_fixes:
            raw_fixes = re.findall(r"(high|medium|low)\s*(?:priority)?\s*[:\-]\s*(.+)", text, re.IGNORECASE)

        for pr, fix_text in raw_fixes:
            suggested_fixes.append({"priority": pr.capitalize(), "fix": fix_text.strip()})

        confidence = 0
        m = re.search(r"confidence[^\d]+(\d+)", text, re.IGNORECASE)
        if m:
            confidence = int(m.group(1))
            confidence = max(0, min(100, confidence))
        if confidence == 0:
            confidence = 50

        confidence_reason = extract(
            [
                r"confidence\s*reason\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
                r"reason\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
            ],
            "Confidence based on available log data",
        )

        historical_match = extract(
            [
                r"historical\s*match\s*:\s*(.+?)(?=\n[A-Z]|\Z)",
                r"historical\s*pattern\s*:\s*(.+)",
                r"matches?\s+historical\s*:\s*(.+)",
            ],
            "no",
        )

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

    def build_baseline_prompt(self, context: dict) -> str:
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
Based on the logs and resource data above, provide a detailed root cause analysis.

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

    def analyze_baseline(self, context: dict, query: str = "") -> dict:
        prompt = self.build_baseline_prompt(context)
        cached = self.cache.get(prompt, "baseline", query=query)
        if cached:
            return cached

        raw_response = provider.generate(prompt)
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

        parsed = self._parse_response(raw_response, debug=True)
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
        self.cache.set(prompt, "baseline", result, query=query)
        return result

    def build_rag_prompt(self, context: dict, rag_context: str) -> str:
        prompt = f"""You are an expert SRE (Site Reliability Engineer)
with deep knowledge of Kubernetes and microservices.
Analyze the following incident carefully.
You have been provided with similar historical incidents that were previously resolved.
Use them to improve the accuracy and specificity of your root cause analysis.

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
Using the current logs, resource data, AND the historical incident patterns above,
provide a detailed root cause analysis.

You MUST respond in this EXACT format.
Do not add any text outside this format:

ROOT CAUSE: [one clear sentence identifying the root cause]

AFFECTED SERVICES: [comma separated list in order of impact]

FAILURE CHAIN:
[step 1 — what happened first]
[step 2 — what happened next]
[step 3 — how it cascaded]

SUGGESTED FIXES:
- [High] [specific fix — reference historical resolution if applicable]
- [Medium] [specific actionable fix]
- [Low] [specific actionable fix]

CONFIDENCE: [number between 0-100]%

CONFIDENCE REASON: [one sentence]

HISTORICAL MATCH: [yes/no]
"""
        return self._trim_prompt(prompt)

    def analyze_rag(self, context: dict, rag_context: str, query: str = "") -> dict:
        prompt = self.build_rag_prompt(context, rag_context)
        cached = self.cache.get(prompt, "rag", query=query)
        if cached:
            return cached

        raw_response = provider.generate(prompt)
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

        parsed = self._parse_response(raw_response, debug=True)
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
        self.cache.set(prompt, "rag", result, query=query)
        return result

    # ──────────────────────────────
    # Investigation prompt (used by Phase 4)
    # ──────────────────────────────

    def build_investigation_prompt(self, report, summary_text: str) -> str:
        # Minimal compatibility implementation: existing Phase 4 relies on its own
        # formatting; k8s RCA only needs K8s context injection.
        # Keep it simple but valid.
        return self._trim_prompt(
            f"Investigation for {report.target_service} in {report.namespace}.\n"
            f"Summary: {summary_text}\n"
        )

    def analyze_investigation(self, report, investigator=None, query: str = "") -> dict:
        prompt = self.build_investigation_prompt(report, "")
        raw = provider.generate(prompt)
        if not raw:
            return {"mode": "investigation_failed"}
        # Phase 4 parsing is handled elsewhere; keep compatibility.
        return {"mode": "investigation", "raw_response": raw}

    # ──────────────────────────────
    # Phase 5: K8s context injection helper
    # ──────────────────────────────

    def build_k8s_context_block(self, workload, patterns: list, snapshot) -> str:
        """Build the structured K8s context block for k8s/rca_engine.py."""
        lines = [
            f"## Kubernetes Context — {workload.name} ({workload.namespace})",
            f"Kind: {workload.kind} | Replicas: {workload.replicas_ready}/{workload.replicas_desired}",
            f"Detected patterns: {', '.join(patterns) if patterns else 'None'}",
            "",
            "### Pod Status",
        ]

        for pod in getattr(workload, "pods", []) or []:
            lines.append(
                f"  - {pod.name}: phase={getattr(pod,'phase', '')} ready={getattr(pod,'ready', None)} "
                f"restarts={getattr(pod,'restart_count', None)} cpu={getattr(pod,'cpu_usage', None)} mem={getattr(pod,'memory_usage', None)}"
            )
            for cs in getattr(pod, "container_states", []) or []:
                state_reason = getattr(cs, "state_reason", "")
                if state_reason:
                    lines.append(
                        f"    Container {getattr(cs,'name','')}: {getattr(cs,'state','')} ({state_reason})"
                    )

        lines.append("")
        lines.append("### Node Health")
        for node in getattr(snapshot, "nodes", []) or []:
            lines.append(
                f"  - {getattr(node,'name','')}: ready={getattr(node,'ready', None)} "
                f"cpu={getattr(node,'cpu_usage', None)} mem={getattr(node,'memory_usage', None)}"
            )

        return "\n".join(lines)

