#!/usr/bin/env python3
import hashlib
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def load_routing(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def _timeout_seconds() -> float:
    # Conservative default: avoid hanging the UI/pipeline indefinitely.
    raw = os.environ.get("LLM_TIMEOUT_SECONDS", "180").strip()
    try:
        value = float(raw)
    except ValueError:
        return 180.0
    return value if value > 0 else 180.0


def _cache_enabled() -> bool:
    return os.environ.get("LLM_CACHE", "1").strip().lower() not in {"0", "false", "off", "no"}


def _cache_dir() -> Path:
    root = os.environ.get("LLM_CACHE_DIR", "cache/llm")
    path = Path(root).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cache_path(key: str) -> Path:
    return _cache_dir() / f"{key}.json"


def _cache_get(key: str) -> dict | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data["cached"] = True
        return data
    return None


def _cache_put(key: str, response: dict):
    path = _cache_path(key)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(response, ensure_ascii=True), encoding="utf-8")
    tmp.replace(path)


def _post_json(url: str, api_key: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=_timeout_seconds()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _unsupported_parameter(error_body: str) -> str | None:
    marker = "Unsupported parameter: '"
    start = error_body.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = error_body.find("'", start)
    if end <= start:
        return None
    return error_body[start:end]


def _post_openai_with_compat(url: str, api_key: str, payload: dict) -> dict:
    request_payload = dict(payload)
    for _ in range(3):
        try:
            return _post_json(url, api_key, request_payload)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            unsupported = _unsupported_parameter(body)
            if exc.code == 400 and unsupported in {"temperature", "reasoning"} and unsupported in request_payload:
                request_payload.pop(unsupported, None)
                continue
            raise RuntimeError(f"OpenAI API error {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI API network error: {exc}") from exc
    raise RuntimeError("OpenAI API request failed after compatibility retries.")


def _messages_to_prompt(messages: list) -> str:
    parts = []
    for msg in messages:
        role = (msg.get("role") or "user").upper()
        content = msg.get("content", "")
        parts.append(f"{role}: {content}")
    return "\n\n".join(p for p in parts if p.strip())


def _schema_required_keys(text_format: dict | None) -> list[str]:
    if not isinstance(text_format, dict):
        return []
    schema = text_format.get("schema")
    if not isinstance(schema, dict):
        return []
    required = schema.get("required", [])
    return [str(key) for key in required if isinstance(key, str)]


def _structured_contract_hint(text_format: dict | None) -> str:
    if not isinstance(text_format, dict):
        return ""
    if text_format.get("type") != "json_schema":
        return ""
    schema = text_format.get("schema")
    if not isinstance(schema, dict):
        return ""
    schema_text = json.dumps(schema, separators=(",", ":"), ensure_ascii=True)
    return (
        "\n\nIMPORTANT OUTPUT CONTRACT:\n"
        "- Return ONLY one valid JSON object.\n"
        "- No markdown fences.\n"
        "- No explanations.\n"
        f"- Follow this schema exactly: {schema_text}\n"
    )


def _json_candidates(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    out = []
    idx = 0
    while True:
        start = text.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict):  # pragma: no branch - JSON objects starting with '{' are dicts
            out.append(obj)
        idx = start + end
    return out


def _coerce_structured_text(text: str, text_format: dict | None) -> str | None:
    if not isinstance(text_format, dict):
        return None
    required = _schema_required_keys(text_format)
    candidates = _json_candidates(text)
    if not candidates:
        return None
    for candidate in reversed(candidates):
        if required and any(key not in candidate for key in required):
            continue
        return json.dumps(candidate, separators=(",", ":"), ensure_ascii=True)
    return None


def _normalized_text_format(text_format: dict | None) -> dict | None:
    if not isinstance(text_format, dict):
        return text_format
    if text_format.get("type") != "json_schema":
        return text_format
    if text_format.get("name"):
        return text_format
    normalized = dict(text_format)
    normalized["name"] = "response_contract"
    return normalized


def _build_codex_prompt(messages: list, text_format: dict | None, previous_output: str = "") -> str:
    normalized_format = _normalized_text_format(text_format)
    prompt = _messages_to_prompt(messages)
    hint = _structured_contract_hint(normalized_format)
    if hint:
        prompt += hint
    if previous_output:
        preview = previous_output[:2000]
        prompt += (
            "\nPrevious output violated the contract.\n"
            "Fix it and output only compliant JSON.\n"
            f"Previous output:\n{preview}\n"
        )
    return prompt


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


def _codex_response(model: str, messages: list, text_format: dict | None = None) -> dict:
    if not shutil.which("codex"):
        raise RuntimeError("Codex CLI not found. Install codex or switch to OpenAI API mode.")
    normalized_format = _normalized_text_format(text_format)
    prompt = _build_codex_prompt(messages, normalized_format)
    cache_key = None
    if _cache_enabled():
        cache_key = _cache_key({"mode": "codex_local", "model": model, "prompt": prompt, "text_format": normalized_format})
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
    cmd = ["codex", "-q", "--model", model, "--approval-mode", "suggest", "--no-project-doc", prompt]
    last_error = None
    last_stdout = ""
    max_attempts = 3 if text_format else 2
    for _ in range(max_attempts):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=_timeout_seconds())
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Codex CLI timed out after {_timeout_seconds():.0f}s") from exc
        if result.returncode != 0:
            raise RuntimeError(f"Codex CLI failed: {result.stderr.strip() or 'unknown error'}")
        last_stdout = result.stdout or ""
        structured_text = _coerce_structured_text(last_stdout, normalized_format)
        if structured_text:
            text = structured_text
            break
        try:
            extracted = _codex_output_text(last_stdout)
            structured_text = _coerce_structured_text(extracted, normalized_format)
            if structured_text:
                text = structured_text
                break
            if extracted.strip():
                text = extracted if not normalized_format else None
                if text:
                    break
                last_error = ValueError("Codex structured output invalid.")
                prompt = _build_codex_prompt(messages, normalized_format, extracted)
                cmd[-1] = prompt
                continue
            last_error = ValueError("Codex output empty.")
            text = None
        except ValueError as exc:
            last_error = exc
            if normalized_format:
                prompt = _build_codex_prompt(messages, normalized_format, last_stdout)
                cmd[-1] = prompt
            text = None
    if text is None:
        # Fall back to raw output so the caller can decide how to recover (e.g., repair prompt).
        structured_text = _coerce_structured_text(last_stdout, normalized_format)
        text = structured_text or last_stdout.strip()
        if not text:
            raise RuntimeError(str(last_error) if last_error else "Codex CLI failed.")
    resp = {"output": [{"type": "output_text", "text": text}], "usage": {}}
    if cache_key is not None:
        _cache_put(cache_key, resp)
    return resp


def _openai_response(
    model: str,
    messages: list,
    temperature: float,
    reasoning: str,
    routing: dict,
    text_format: dict | None = None,
    max_output_tokens: int | None = None,
) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    base_url = routing.get("openai", {}).get("base_url", "https://api.openai.com/v1")
    endpoint = routing.get("openai", {}).get("responses_endpoint", "/responses")
    url = base_url.rstrip("/") + endpoint
    normalized_format = _normalized_text_format(text_format)
    payload = {
        "model": model,
        "input": messages,
        "temperature": temperature,
        "reasoning": {"effort": reasoning},
    }
    if isinstance(max_output_tokens, int) and max_output_tokens > 0:
        payload["max_output_tokens"] = max_output_tokens
    if normalized_format:
        payload["text"] = {"format": normalized_format}
    cache_key = None
    if _cache_enabled():
        cache_key = _cache_key({"mode": "openai", "url": url, "payload": payload})
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
    resp = _post_openai_with_compat(url, api_key, payload)
    if cache_key is not None:
        _cache_put(cache_key, resp)
    return resp


def responses_create(
    model: str,
    messages: list,
    temperature: float = 0.2,
    reasoning: str = "medium",
    routing_path: str = "config/llm_routing.json",
    text_format: dict | None = None,
    max_output_tokens: int | None = None,
) -> dict:
    routing = load_routing(Path(routing_path))
    mode = os.environ.get("LLM_MODE") or routing.get("mode", "openai")
    if mode == "codex_local":
        return _codex_response(model, messages, text_format=text_format)
    return _openai_response(
        model,
        messages,
        temperature,
        reasoning,
        routing,
        text_format=text_format,
        max_output_tokens=max_output_tokens,
    )


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
