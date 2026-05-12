#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from scripts.codex_runtime import resolve_codex_runtime
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from codex_runtime import resolve_codex_runtime

DEFAULT_LLM_TIMEOUT_SECONDS = 180.0
DEFAULT_CODEX_TIMEOUT_SECONDS = 600.0


def load_routing(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _env_timeout_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _timeout_seconds() -> float:
    # Conservative API default: avoid hanging the UI/pipeline indefinitely.
    return _env_timeout_seconds("LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS)


def _codex_timeout_seconds() -> float:
    # Codex exec includes process startup and can receive larger structured prompts.
    if "CODEX_TIMEOUT_SECONDS" in os.environ:
        return _env_timeout_seconds("CODEX_TIMEOUT_SECONDS", DEFAULT_CODEX_TIMEOUT_SECONDS)
    if "LLM_TIMEOUT_SECONDS" in os.environ:
        return _env_timeout_seconds("LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS)
    return DEFAULT_CODEX_TIMEOUT_SECONDS


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


def _post_json(url: str, api_key: str, payload: dict, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(str(key), str(value))
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


def _codex_cache_payload(model: str, prompt: str, text_format: dict | None, runtime: dict) -> dict:
    return {
        "mode": "codex_local",
        "runtime_kind": runtime.get("kind", ""),
        "runtime_path": runtime.get("path", ""),
        "runtime_version": runtime.get("version", ""),
        "model": model,
        "prompt": prompt,
        "text_format": text_format,
    }


def _run_codex_exec(runtime: dict, model: str, prompt: str) -> tuple[str, str]:
    with tempfile.NamedTemporaryFile(prefix="codex-last-message-", suffix=".txt", delete=False) as handle:
        output_path = Path(handle.name)
    cmd = [
        runtime["path"],
        "exec",
        "--ignore-user-config",
        "--model",
        model,
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--output-last-message",
        str(output_path),
        prompt,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_codex_timeout_seconds())
        last_message = ""
        if output_path.exists():
            last_message = output_path.read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            output_path.unlink()
        except OSError:
            pass
    if result.returncode != 0:
        raise RuntimeError(f"Codex CLI failed: {result.stderr.strip() or result.stdout.strip() or 'unknown error'}")
    return last_message.strip(), result.stdout or ""


def _run_codex_legacy_q(runtime: dict, model: str, prompt: str) -> tuple[str, str]:
    cmd = [runtime["path"], "-q", "--model", model, "--approval-mode", "suggest", "--no-project-doc", prompt]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=_codex_timeout_seconds())
    if result.returncode != 0:
        raise RuntimeError(f"Codex CLI failed: {result.stderr.strip() or 'unknown error'}")
    return "", result.stdout or ""


def _run_codex(runtime: dict, model: str, prompt: str) -> tuple[str, str]:
    try:
        if runtime.get("kind") == "exec":
            return _run_codex_exec(runtime, model, prompt)
        return _run_codex_legacy_q(runtime, model, prompt)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Codex CLI timed out after {_codex_timeout_seconds():.0f}s") from exc


def _codex_response(model: str, messages: list, text_format: dict | None = None) -> dict:
    runtime = resolve_codex_runtime()
    if not runtime.get("available"):
        raise RuntimeError("Codex CLI not found. Install Codex or switch to API provider mode.")
    normalized_format = _normalized_text_format(text_format)
    prompt = _build_codex_prompt(messages, normalized_format)
    cache_key = None
    if _cache_enabled():
        cache_key = _cache_key(_codex_cache_payload(model, prompt, normalized_format, runtime))
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
    last_error = None
    last_stdout = ""
    last_message = ""
    max_attempts = 3 if text_format else 2
    for _ in range(max_attempts):
        last_message, last_stdout = _run_codex(runtime, model, prompt)
        candidate_output = last_message or last_stdout
        structured_text = _coerce_structured_text(candidate_output, normalized_format)
        if structured_text:
            text = structured_text
            break
        try:
            extracted = last_message or _codex_output_text(last_stdout)
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
                continue
            last_error = ValueError("Codex output empty.")
            text = None
        except ValueError as exc:
            last_error = exc
            if normalized_format:
                prompt = _build_codex_prompt(messages, normalized_format, last_stdout)
            text = None
    if text is None:
        # Fall back to raw output so the caller can decide how to recover (e.g., repair prompt).
        fallback_output = last_message or last_stdout
        structured_text = _coerce_structured_text(fallback_output, normalized_format)
        text = structured_text or fallback_output.strip()
        if not text:
            raise RuntimeError(str(last_error) if last_error else "Codex CLI failed.")
    resp = {"output": [{"type": "output_text", "text": text}], "usage": {}}
    if cache_key is not None:
        _cache_put(cache_key, resp)
    return resp


def _active_api_provider_name(routing: dict) -> str:
    return (
        os.environ.get("LLM_API_PROVIDER")
        or os.environ.get("API_PROVIDER")
        or routing.get("api_provider")
        or routing.get("provider")
        or "openai"
    )


def _api_provider_config(routing: dict) -> tuple[str, dict]:
    name = str(_active_api_provider_name(routing)).strip() or "openai"
    providers = routing.get("providers", {})
    provider = providers.get(name) if isinstance(providers, dict) else None
    if not isinstance(provider, dict) and name == "openai":
        provider = dict(routing.get("openai", {}) if isinstance(routing.get("openai"), dict) else {})
        provider.setdefault("kind", "openai_responses")
        provider.setdefault("api_key_env", "OPENAI_API_KEY")
    if not isinstance(provider, dict):
        raise RuntimeError(f"API provider '{name}' is not configured")
    provider = dict(provider)
    provider.setdefault("name", name)
    provider.setdefault("kind", "openai_responses" if name == "openai" else "openai_chat")
    provider.setdefault("api_key_env", "OPENAI_API_KEY" if name == "openai" else f"{name.upper()}_API_KEY")
    return name, provider


def _api_key_for_provider(provider: dict) -> str:
    if os.environ.get("LLM_API_KEY"):
        return str(os.environ["LLM_API_KEY"])
    env_name = str(provider.get("api_key_env") or "OPENAI_API_KEY")
    api_key = os.environ.get(env_name)
    if not api_key:
        raise RuntimeError(f"{env_name} is not set")
    return api_key


def api_provider_status(routing_path: str = "config/llm_routing.json", override_key: str | None = None) -> dict:
    try:
        routing = load_routing(Path(routing_path))
        provider_name, provider = _api_provider_config(routing)
    except Exception as exc:
        return {
            "connected": False,
            "provider": "",
            "kind": "",
            "api_key_env": "",
            "auth_source": "",
            "reason": str(exc),
        }
    key_env = str(provider.get("api_key_env") or "OPENAI_API_KEY")
    auth_source = ""
    if override_key:
        auth_source = "runtime_override"
    elif os.environ.get("LLM_API_KEY"):
        auth_source = "LLM_API_KEY"
    elif os.environ.get(key_env):
        auth_source = key_env
    connected = bool(auth_source)
    return {
        "connected": connected,
        "provider": provider_name,
        "kind": str(provider.get("kind") or ""),
        "api_key_env": key_env,
        "auth_source": auth_source,
        "reason": "API provider key configured" if connected else f"{key_env} is not set",
    }


def _provider_url(provider: dict, endpoint_key: str, default_endpoint: str) -> str:
    base_url = str(provider.get("base_url") or "").rstrip("/")
    if not base_url:
        raise RuntimeError(f"API provider '{provider.get('name', '')}' is missing base_url")
    endpoint = str(provider.get(endpoint_key) or default_endpoint)
    return base_url + endpoint


def _messages_with_contract_hint(messages: list, normalized_format: dict | None) -> list:
    hint = _structured_contract_hint(normalized_format)
    if not hint:
        return messages
    copied = [dict(msg) for msg in messages]
    if copied:
        copied[-1]["content"] = str(copied[-1].get("content", "")) + hint
    else:
        copied.append({"role": "user", "content": hint.strip()})
    return copied


def _openai_responses_payload(
    model: str,
    messages: list,
    temperature: float,
    reasoning: str,
    text_format: dict | None,
    max_output_tokens: int | None,
) -> dict:
    payload = {
        "model": model,
        "input": messages,
        "temperature": temperature,
        "reasoning": {"effort": reasoning},
    }
    if isinstance(max_output_tokens, int) and max_output_tokens > 0:
        payload["max_output_tokens"] = max_output_tokens
    if text_format:
        payload["text"] = {"format": text_format}
        if _prefers_low_verbosity(model):
            payload["text"]["verbosity"] = "low"
    return payload


def _chat_payload(
    model: str,
    messages: list,
    temperature: float,
    text_format: dict | None,
    max_output_tokens: int | None,
) -> dict:
    payload = {
        "model": model,
        "messages": _messages_with_contract_hint(messages, text_format),
        "temperature": temperature,
    }
    if isinstance(max_output_tokens, int) and max_output_tokens > 0:
        payload["max_tokens"] = max_output_tokens
    if isinstance(text_format, dict) and text_format.get("type") == "json_schema":
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": text_format.get("name", "response_contract"),
                "schema": text_format.get("schema", {}),
                "strict": bool(text_format.get("strict", True)),
            },
        }
    elif text_format:
        payload["response_format"] = text_format
    return payload


def _anthropic_payload(
    model: str,
    messages: list,
    temperature: float,
    text_format: dict | None,
    max_output_tokens: int | None,
) -> dict:
    system_parts = []
    user_messages = []
    for msg in _messages_with_contract_hint(messages, text_format):
        role = str(msg.get("role") or "user").lower()
        content = str(msg.get("content", ""))
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            user_messages.append({"role": "assistant", "content": content})
        else:
            user_messages.append({"role": "user", "content": content})
    payload = {
        "model": model,
        "messages": user_messages or [{"role": "user", "content": ""}],
        "temperature": temperature,
        "max_tokens": max_output_tokens if isinstance(max_output_tokens, int) and max_output_tokens > 0 else 1024,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    return payload


def _normalize_chat_response(resp: dict) -> dict:
    choices = resp.get("choices", [])
    text = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message", {})
        if isinstance(message, dict):
            text = str(message.get("content", "") or "")
    return {"output": [{"type": "output_text", "text": text}], "usage": resp.get("usage", {})}


def _normalize_anthropic_response(resp: dict) -> dict:
    parts = []
    for item in resp.get("content", []) if isinstance(resp.get("content"), list) else []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    usage = resp.get("usage", {})
    if isinstance(usage, dict):
        usage = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
    return {"output": [{"type": "output_text", "text": "\n".join(p for p in parts if p)}], "usage": usage}


def _provider_headers(provider: dict) -> dict:
    headers = dict(provider.get("headers", {}) if isinstance(provider.get("headers"), dict) else {})
    if provider.get("kind") == "anthropic_messages":
        headers.setdefault("anthropic-version", str(provider.get("anthropic_version") or "2023-06-01"))
    return headers


def _api_response(
    model: str,
    messages: list,
    temperature: float,
    reasoning: str,
    routing: dict,
    text_format: dict | None = None,
    max_output_tokens: int | None = None,
) -> dict:
    provider_name, provider = _api_provider_config(routing)
    api_key = _api_key_for_provider(provider)
    provider_kind = str(provider.get("kind") or "openai_responses")
    normalized_format = _normalized_text_format(text_format)
    if provider_kind == "anthropic_messages":
        url = _provider_url(provider, "messages_endpoint", "/messages")
        payload = _anthropic_payload(model, messages, temperature, normalized_format, max_output_tokens)
    elif provider_kind == "openai_chat":
        url = _provider_url(provider, "chat_completions_endpoint", "/chat/completions")
        payload = _chat_payload(model, messages, temperature, normalized_format, max_output_tokens)
    else:
        url = _provider_url(provider, "responses_endpoint", "/responses")
        payload = _openai_responses_payload(model, messages, temperature, reasoning, normalized_format, max_output_tokens)
    cache_key = None
    if _cache_enabled():
        cache_key = _cache_key({"mode": "api", "provider": provider_name, "kind": provider_kind, "url": url, "payload": payload})
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
    if provider_kind == "openai_responses":
        resp = _post_openai_with_compat(url, api_key, payload)
    else:
        resp = _post_json(url, api_key, payload, headers=_provider_headers(provider))
        resp = _normalize_anthropic_response(resp) if provider_kind == "anthropic_messages" else _normalize_chat_response(resp)
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
    return _api_response(
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
