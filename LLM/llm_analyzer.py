"""
Batched LLM analysis layer.

One API call per analysis cycle covers ALL active nodes' recent windows —
not one call per node. This is a deliberate compute-efficiency choice: it
frames EdgeWatch as a centralized inference layer sitting over distributed
edge telemetry, rather than a naive per-device chatbot wrapper.

Supports Claude and Gemini behind the same LLMAnalyzer.analyze() interface,
so pipeline.py doesn't need to know which provider is active. Pick one with
--provider claude|gemini (pipeline.py) or the `provider=` arg here directly.
"""

import json
import os
from typing import Dict, List, Optional

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
FREELLM_MODEL = os.environ.get(
    "FREELLM_MODEL", 
    "auto"
)

FREELLM_BASE_URL = os.environ.get(
    "FREELLM_BASE_URL",
    "http://localhost:3001/v1"
)

SYSTEM_PROMPT = """You are an infrastructure reliability analyst for a fleet of edge/compute nodes.

You receive a JSON object mapping node_id -> a time-ordered list of recent telemetry
readings (oldest first). Each reading has:
  - behavior: the node's own self-reported mode ("normal", "degrading_voltage",
    "degrading_temp") -- treat this as a HINT about likely root cause, not a verdict;
    verify it against the actual numeric trend.
  - temperature_c, voltage_v, vibration_g, rssi_dbm (signal strength),
    cpu_load_pct, uptime_sec.

Note: cpu_load_pct tends to rise on nodes that are already destabilizing (retry
overhead from power instability, or throttling overhead from overheating) -- a
climbing cpu_load_pct alongside a voltage or temperature trend is a stronger signal
than either alone, not two unrelated metrics.

Cross-check behavior against status against the actual numeric TREND across the window
(not just the latest snapshot) -- e.g. a steady voltage decline is more significant than
one low reading, and a node whose status says "OK" but whose numbers are trending toward
a threshold is still worth flagging early. Decide anomaly status and a failure risk score
for each node.

Respond with ONLY a JSON object, no markdown fences, no prose outside the JSON, in this
exact shape:
{
  "nodes": [
    {
      "node_id": "string",
      "anomaly": true/false,
      "risk_score": 0-100,
      "trend": "stable" | "degrading" | "critical",
      "predicted_failure_window": "string or null, e.g. '10-15 min'",
      "reasoning": "1-2 sentences, grounded in the actual numbers you saw"
    }
  ],
  "fleet_summary": "1-2 sentence overview of fleet health",
  "confidence": 0-100  // your confidence in this fleet_summary and the risk scores above,
                        // given how many readings you actually had to work with (fewer
                        // readings per node = lower confidence; a clean multi-reading
                        // trend = higher confidence)
}"""


def _clean_json_text(text: Optional[str]) -> str:
    if text is None:
        return ""
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return text


def _parse_or_fallback(text: Optional[str]) -> dict:
    if text is None:
        text = ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "nodes": [],
            "fleet_summary": "LLM response could not be parsed as JSON.",
            "raw_response": text,
        }


def log_batch_result(flagged: List[dict]) -> None:
    """Emit a lightweight log for the flagged nodes in a batch."""
    if not flagged:
        return
    print(json.dumps({"flagged_nodes": flagged}, default=str))


class ClaudeAnalyzer:
    def __init__(self, api_key: Optional[str] = None, model: str = CLAUDE_MODEL):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)  # falls back to ANTHROPIC_API_KEY env var
        self.model = model

    def analyze(self, node_windows: Dict[str, List[dict]]) -> dict:
        if not node_windows:
            return {"nodes": [], "fleet_summary": "No telemetry buffered yet."}

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(node_windows)}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return _parse_or_fallback(_clean_json_text(text))


class GeminiAnalyzer:
    def __init__(self, api_key: Optional[str] = None, model: str = GEMINI_MODEL):
        from google import genai

        # falls back to GEMINI_API_KEY env var if api_key is None
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self.model = model

    def analyze(self, node_windows: Dict[str, List[dict]]) -> dict:
        if not node_windows:
            return {"nodes": [], "fleet_summary": "No telemetry buffered yet."}

        response = self.client.models.generate_content(
            model=self.model,
            contents=json.dumps(node_windows),
            config={
                "system_instruction": SYSTEM_PROMPT,
                "response_mime_type": "application/json",
            },
        )
        return _parse_or_fallback(_clean_json_text(response.text))

class FreeLLMAnalyzer:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = FREELLM_MODEL,
        base_url: str = FREELLM_BASE_URL,
    ):
        from openai import OpenAI

        self.client = OpenAI(
            api_key=api_key or os.environ.get("FREELLM_API_KEY"),
            base_url=base_url,
        )

        self.model = model

    def analyze(
        self,
        node_windows: Dict[str, List[dict]]
    ) -> dict:

        if not node_windows:
            return {
                "nodes": [],
                "fleet_summary": "No telemetry buffered yet."
            }

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(node_windows),
                },
            ],
            temperature=0,
        )

        text = response.choices[0].message.content or ""

        result = _parse_or_fallback(
            _clean_json_text(text)
        )

        flagged = [
            n
            for n in result.get("nodes", [])
            if n.get("anomaly")
        ]

        log_batch_result(flagged)

        return result

def LLMAnalyzer(provider: str = "claude", api_key: Optional[str] = None, model: Optional[str] = None):
    """Factory returning a ClaudeAnalyzer or GeminiAnalyzer, both exposing .analyze()."""
    if provider == "claude":
        return ClaudeAnalyzer(api_key=api_key, model=model or CLAUDE_MODEL)
    if provider == "gemini":
        return GeminiAnalyzer(api_key=api_key, model=model or GEMINI_MODEL)
    if provider == "freellm":
        return FreeLLMAnalyzer(api_key=api_key, model=model or FREELLM_MODEL,base_url=FREELLM_BASE_URL)
    raise  ValueError(f"unknown provider: {provider!r} (expected 'claude', 'gemini', or 'freellm')")