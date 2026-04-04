import re
from core.llm_provider import provider
from core.logger import get_logger

log = get_logger("window_analyzer")

class WindowAnalyzer:
    WINDOW_1_SIZE = 500      # lines
    WINDOW_2_START = 500     # start index for window 2
    WINDOW_2_END = 1000      # end index for window 2
    CONFIDENCE_THRESHOLD = 60  # percent

    def analyse(self, lines: list[str], service: str = "unknown") -> dict:
        try:
            window_1_lines = lines[:self.WINDOW_1_SIZE]
            response_1, confidence_1 = self._run_window(window_1_lines, service, "Window 1")

            if confidence_1 >= self.CONFIDENCE_THRESHOLD or len(lines) <= self.WINDOW_1_SIZE:
                result = {
                    "service": service,
                    "windows_used": 1,
                    "confidence": confidence_1,
                    "analysis": response_1,
                    "window_1_confidence": confidence_1,
                    "window_1_analysis": response_1,
                    "low_confidence_warning": confidence_1 < self.CONFIDENCE_THRESHOLD
                }
            else:
                # merge and re-analyse
                merged_lines = lines[:self.WINDOW_2_END]
                response_merged, confidence_merged = self._run_window(merged_lines, service, "Window 1+2 merged")
                result = {
                    "service": service,
                    "windows_used": 2,
                    "confidence": confidence_merged,
                    "analysis": response_merged,
                    "window_1_confidence": confidence_1,
                    "window_1_analysis": response_1,
                    "low_confidence_warning": confidence_1 < self.CONFIDENCE_THRESHOLD
                }
        except Exception as e:
            if hasattr(log, "error"):
                log.error(f"Error in WindowAnalyzer: {e}")
            else:
                log.info(f"Error in WindowAnalyzer: {e}")
            result = {
                "service": service,
                "windows_used": 0,
                "confidence": 0,
                "analysis": "LLM unavailable",
                "window_1_confidence": 0,
                "window_1_analysis": "",
                "low_confidence_warning": True
            }

        from core.incident_recorder import IncidentRecorder
        recorder = IncidentRecorder()
        record = recorder.check_and_save(result["analysis"], service, lines)
        result["incident_record"] = record
        return result

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

    def _extract_confidence(self, llm_response: str) -> int:
        match = re.search(r"CONFIDENCE:\s*(\d+)%", llm_response, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 50

    def _run_window(self, lines: list[str], service: str, label: str) -> tuple[str, int]:
        prompt = self._build_prompt(lines, service, label)
        response_text = provider.generate(prompt)
        confidence_int = self._extract_confidence(response_text)
        if hasattr(log, "step"):
            log.step(f"{label}: confidence={confidence_int}%")
        else:
            log.info(f"{label}: confidence={confidence_int}%")
        return response_text, confidence_int
