#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path


ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for idx, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double and (idx == 0 or value[idx - 1].isspace()):
            return value[:idx].rstrip()
    return value.strip()


def _parse_env_value(raw: str) -> str:
    value = _strip_inline_comment(raw.strip())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        inner = value[1:-1]
        if value[0] == '"':
            return inner.replace(r"\\", "\\").replace(r"\"", '"').replace(r"\n", "\n")
        return inner
    return value


def load_local_env(root: Path, filenames: tuple[str, ...] = (".env.local", ".env")) -> list[str]:
    """Load local env files without overriding process env or logging values."""

    loaded: list[str] = []
    for filename in filenames:
        path = Path(root) / filename
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                stripped = stripped[len("export ") :].strip()
            if "=" not in stripped:
                continue
            key, raw_value = stripped.split("=", 1)
            key = key.strip()
            if not ENV_KEY_RE.match(key) or key in os.environ:
                continue
            os.environ[key] = _parse_env_value(raw_value)
            loaded.append(key)
    return loaded
