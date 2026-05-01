#!/usr/bin/env python3
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


CODEX_APP_CLI_PATH = Path("/Applications/Codex.app/Contents/Resources/codex")
PIPELINE_PROGRESS_PREFIX = "PIPELINE_PROGRESS "


def load_routing(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _emit_pipeline_progress(message: str, **fields):
    payload = {"message": str(message)}
    for key, value in fields.items():
        if value is not None:
            payload[str(key)] = str(value)
    print(f"{PIPELINE_PROGRESS_PREFIX}{json.dumps(payload, ensure_ascii=True, sort_keys=True)}", file=sys.stderr, flush=True)

def _timeout_seconds() -> float:
    # Conservative default: avoid hanging the UI/pipeline indefinitely.
    raw = os.environ.get("LLM_TIMEOUT_SECONDS", "180").strip()
    try:
        value = float(raw)
    except ValueError:
        return 180.0
    return value if value > 0 else 180.0


def _retry_attempts() -> int:
    raw = os.environ.get("OPENAI_MAX_RETRIES", "5").strip()
    try:
        value = int(raw)
    except ValueError:
        return 5
    return min(8, max(1, value))


def _retry_backoff_seconds(attempt: int) -> float:
    raw = os.environ.get("OPENAI_RETRY_BACKOFF_SECONDS", "0.75").strip()
    try:
        base = float(raw)
    except ValueError:
        base = 0.75
    base = min(2.0, max(0.05, base))
    step = max(0, int(attempt) - 1)
    return min(4.0, base * (2 ** step))


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


def _retryable_http_status(code: int) -> bool:
    return code in {408, 409, 429} or 500 <= int(code) <= 599


def _post_openai_with_compat(url: str, api_key: str, payload: dict) -> dict:
    request_payload = dict(payload)
    attempts = _retry_attempts()
    attempt = 1
    compatibility_adjustments = 0
    max_compatibility_adjustments = 4
    while attempt <= attempts:
        try:
            return _post_json(url, api_key, request_payload)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            unsupported = _unsupported_parameter(body)
            if exc.code == 400 and unsupported in {"temperature", "reasoning"} and unsupported in request_payload:
                request_payload.pop(unsupported, None)
                compatibility_adjustments += 1
                if compatibility_adjustments > max_compatibility_adjustments:
                    raise RuntimeError(f"OpenAI API compatibility retry loop exceeded: {body[:500]}") from exc
                # Compatibility stripping is not a transient retry; do not
                # consume the user's retry budget. This matters when
                # OPENAI_MAX_RETRIES=1 is used for bounded live validation.
                continue
            if _retryable_http_status(exc.code) and attempt < attempts:
                time.sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            raise RuntimeError(f"OpenAI API error {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            if attempt < attempts:
                time.sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            raise RuntimeError(f"OpenAI API network error: {exc}") from exc
        attempt += 1
    raise RuntimeError("OpenAI API request failed after retry/compatibility attempts.")


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


def _prefers_low_verbosity(model: str) -> bool:
    token = str(model or "").strip().lower()
    return token.startswith("gpt-5.4-mini") or token.startswith("gpt-5.4-nano")


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


def _resolve_codex_cli_path(routing: dict) -> str:
    configured = str(routing.get("codex_cli_path") or os.environ.get("CODEX_CLI_PATH") or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return str(path)
        raise RuntimeError(f"Configured Codex CLI not found: {path}")
    found = shutil.which("codex")
    if found:
        return found
    if CODEX_APP_CLI_PATH.exists():
        return str(CODEX_APP_CLI_PATH)
    raise RuntimeError("Codex CLI not found. Install Codex.app/codex or switch to OpenAI API mode.")


def _codex_cli_interface(routing: dict, cli_path: str) -> str:
    configured = str(routing.get("codex_cli_interface") or os.environ.get("CODEX_CLI_INTERFACE") or "").strip().lower()
    if configured:
        if configured not in {"exec", "legacy"}:
            raise RuntimeError(f"Unsupported Codex CLI interface: {configured}")
        return configured
    try:
        if Path(cli_path).expanduser().resolve() == CODEX_APP_CLI_PATH.resolve():
            return "exec"
    except OSError:
        pass
    return "legacy"


def _codex_cache_payload(cli_path: str, cli_interface: str, model: str, prompt: str, text_format: dict | None) -> dict:
    return {
        "mode": "codex_local",
        "cli_path": cli_path,
        "cli_interface": cli_interface,
        "model": model,
        "prompt": prompt,
        "text_format": text_format,
    }


def _run_codex_exec(cli_path: str, model: str, prompt: str) -> tuple[object, str]:
    handle = tempfile.NamedTemporaryFile(prefix="codex-last-message-", suffix=".txt", delete=False)
    output_path = Path(handle.name)
    handle.close()
    cmd = [
        cli_path,
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
        "--output-last-message",
        str(output_path),
        "--model",
        model,
        "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=_timeout_seconds(),
        )
        output_text = ""
        if output_path.exists():
            output_text = output_path.read_text(encoding="utf-8", errors="replace").strip()
        return result, output_text or (result.stdout or "")
    finally:
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass


def _run_codex_legacy(cli_path: str, model: str, prompt: str) -> tuple[object, str]:
    cmd = [cli_path, "-q", "--model", model, "--approval-mode", "suggest", "--no-project-doc", prompt]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=_timeout_seconds())
    return result, result.stdout or ""


def _codex_response(model: str, messages: list, routing: dict, text_format: dict | None = None) -> dict:
    cli_path = _resolve_codex_cli_path(routing)
    cli_interface = _codex_cli_interface(routing, cli_path)
    normalized_format = _normalized_text_format(text_format)
    prompt = _build_codex_prompt(messages, normalized_format)
    cache_key = None
    if _cache_enabled():
        cache_key = _cache_key(_codex_cache_payload(cli_path, cli_interface, model, prompt, normalized_format))
        cached = _cache_get(cache_key)
        if cached is not None:
            _emit_pipeline_progress("Reused cached Codex OAuth response", model=model, interface=cli_interface, status="cache_hit")
            return cached
    last_error = None
    last_stdout = ""
    max_attempts = 3 if text_format else 2
    for attempt_index in range(max_attempts):
        _emit_pipeline_progress(
            "Codex OAuth call started",
            model=model,
            interface=cli_interface,
            status="started",
            attempt=attempt_index + 1,
        )
        try:
            if cli_interface == "exec":
                result, last_stdout = _run_codex_exec(cli_path, model, prompt)
            else:
                result, last_stdout = _run_codex_legacy(cli_path, model, prompt)
        except subprocess.TimeoutExpired as exc:
            _emit_pipeline_progress("Codex OAuth call timed out", model=model, interface=cli_interface, status="timeout", attempt=attempt_index + 1)
            raise RuntimeError(f"Codex CLI timed out after {_timeout_seconds():.0f}s") from exc
        if result.returncode != 0:
            detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
            _emit_pipeline_progress("Codex OAuth call failed", model=model, interface=cli_interface, status="failed", attempt=attempt_index + 1)
            raise RuntimeError(f"Codex CLI failed ({cli_interface} at {cli_path}): {detail or 'unknown error'}")
        _emit_pipeline_progress("Codex OAuth response received", model=model, interface=cli_interface, status="received", attempt=attempt_index + 1)
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
                _emit_pipeline_progress("Codex OAuth structured output retrying", model=model, interface=cli_interface, status="retrying", attempt=attempt_index + 1)
                prompt = _build_codex_prompt(messages, normalized_format, extracted)
                continue
            last_error = ValueError("Codex output empty.")
            text = None
        except ValueError as exc:
            last_error = exc
            if normalized_format:
                _emit_pipeline_progress("Codex OAuth structured output retrying", model=model, interface=cli_interface, status="retrying", attempt=attempt_index + 1)
                prompt = _build_codex_prompt(messages, normalized_format, last_stdout)
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


def _provider_config(routing: dict, provider: str) -> dict:
    config = routing.get(provider, {})
    return config if isinstance(config, dict) else {}


def _provider_api_key(routing: dict, provider: str) -> tuple[str, str]:
    config = _provider_config(routing, provider)
    api_key_env = (
        routing.get("api_key_env")
        or config.get("api_key_env")
        or ("OPENAI_API_KEY" if provider == "openai" else f"{provider.upper()}_API_KEY")
    )
    api_key = os.environ.get(str(api_key_env))
    if not api_key:
        raise RuntimeError(f"{api_key_env} is not set")
    return str(api_key_env), api_key


def _provider_url(routing: dict, provider: str) -> str:
    config = _provider_config(routing, provider)
    base_url_env = routing.get("base_url_env") or config.get("base_url_env")
    base_url = os.environ.get(str(base_url_env)) if base_url_env else ""
    base_url = base_url or routing.get("base_url") or config.get("base_url")
    if not base_url:
        base_url = "https://api.openai.com/v1" if provider == "openai" else ""
    if not base_url:
        raise RuntimeError(f"Base URL is not configured for provider {provider}")
    endpoint = routing.get("responses_endpoint") or config.get("responses_endpoint") or "/responses"
    return str(base_url).rstrip("/") + str(endpoint)


def _openai_response(
    model: str,
    messages: list,
    temperature: float,
    reasoning: str,
    routing: dict,
    text_format: dict | None = None,
    max_output_tokens: int | None = None,
) -> dict:
    provider = str(routing.get("provider") or ("openai" if routing.get("mode") == "openai" else "openai_compatible"))
    api_key_env, api_key = _provider_api_key(routing, provider)
    url = _provider_url(routing, provider)
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
        if _prefers_low_verbosity(model):
            payload["text"]["verbosity"] = "low"
    cache_key = None
    if _cache_enabled():
        cache_payload = {"mode": routing.get("mode", "openai"), "url": url, "payload": payload}
        if provider != "openai" or api_key_env != "OPENAI_API_KEY":
            cache_payload.update({"provider": provider, "api_key_env": api_key_env})
        cache_key = _cache_key(cache_payload)
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
        return _codex_response(model, messages, routing, text_format=text_format)
    if mode not in {"openai", "openai_compatible"}:
        raise RuntimeError(f"Unsupported LLM mode: {mode}")
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
