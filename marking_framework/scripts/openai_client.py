#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path


def load_routing(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _post_json(url: str, api_key: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _messages_to_prompt(messages: list) -> str:
    parts = []
    for msg in messages:
        role = (msg.get("role") or "user").upper()
        content = msg.get("content", "")
        parts.append(f"{role}: {content}")
    return "\n\n".join(p for p in parts if p.strip())


def _codex_output_text(raw: str) -> str:
    lines = [line for line in raw.splitlines() if line.strip()]
    parsed = []
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            return raw.strip()
    if not parsed:
        return raw.strip()
    for item in reversed(parsed):
        if item.get("role") == "assistant":
            content = item.get("content", [])
            if isinstance(content, list):
                texts = [c.get("text", "") for c in content if c.get("type") == "output_text"]
                if texts:
                    return "\n".join(t for t in texts if t).strip()
            if "text" in item:
                return str(item["text"]).strip()
    raise ValueError("Codex output missing assistant response.")


def _codex_response(model: str, messages: list) -> dict:
    if not shutil.which("codex"):
        raise RuntimeError("Codex CLI not found. Install codex or switch to OpenAI API mode.")
    prompt = _messages_to_prompt(messages)
    cmd = ["codex", "-q", "--model", model, "--approval-mode", "suggest", "--no-project-doc", prompt]
    last_error = None
    for _ in range(2):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Codex CLI failed: {result.stderr.strip() or 'unknown error'}")
        try:
            text = _codex_output_text(result.stdout or "")
            break
        except ValueError as exc:
            last_error = exc
            text = None
    if text is None:
        raise RuntimeError(str(last_error) if last_error else "Codex CLI failed.")
    return {"output": [{"type": "output_text", "text": text}], "usage": {}}


def _openai_response(model: str, messages: list, temperature: float, reasoning: str, routing: dict,
                     text_format: dict | None = None) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    base_url = routing.get("openai", {}).get("base_url", "https://api.openai.com/v1")
    endpoint = routing.get("openai", {}).get("responses_endpoint", "/responses")
    url = base_url.rstrip("/") + endpoint
    payload = {
        "model": model,
        "input": messages,
        "temperature": temperature,
        "reasoning": {"effort": reasoning},
    }
    if text_format:
        payload["text"] = {"format": text_format}
    return _post_json(url, api_key, payload)


def responses_create(model: str, messages: list, temperature: float = 0.2, reasoning: str = "medium",
                     routing_path: str = "config/llm_routing.json", text_format: dict | None = None) -> dict:
    routing = load_routing(Path(routing_path))
    mode = os.environ.get("LLM_MODE") or routing.get("mode", "openai")
    if mode == "codex_local":
        return _codex_response(model, messages)
    return _openai_response(model, messages, temperature, reasoning, routing, text_format=text_format)


def extract_text(response: dict) -> str:
    # The Responses API returns an array of output items. We collect all text outputs.
    outputs = response.get("output", [])
    parts = []
    for item in outputs:
        if item.get("type") == "output_text":
            parts.append(item.get("text", ""))
        # Some responses may nest content arrays
        for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "\n".join(p for p in parts if p)


def extract_usage(response: dict) -> dict:
    return response.get("usage", {})
