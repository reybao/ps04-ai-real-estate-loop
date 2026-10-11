#!/usr/bin/env python3
"""Small Responses API adapter used by the editorial/content components.

The adapter deliberately has no third-party dependency.  It returns parsed
Structured Output and a safe metadata record; it never prints or stores the
API key.
"""

from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]
API_URL = "https://api.openai.com/v1/responses"


class OpenAIRequestError(RuntimeError):
    pass


def _read_env_file(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def configuration() -> tuple[str, str, str]:
    local = _read_env_file(ROOT / ".env.local")
    key = os.environ.get("OPENAI_API_KEY") or local.get("OPENAI_API_KEY", "")
    if not key.strip():
        raise OpenAIRequestError(
            "OPENAI_API_KEY is not configured; add it to the ignored .env.local file before running AI stages"
        )
    model = os.environ.get("OPENAI_MODEL") or local.get("OPENAI_MODEL") or "gpt-6-luna"
    effort = (
        os.environ.get("OPENAI_REASONING_EFFORT")
        or local.get("OPENAI_REASONING_EFFORT")
        or "low"
    )
    if effort not in {"none", "low", "medium", "high", "xhigh", "max"}:
        raise OpenAIRequestError(f"unsupported OPENAI_REASONING_EFFORT: {effort}")
    return key, model, effort


def _output_text(response: dict) -> str:
    chunks: list[str] = []
    for output in response.get("output", []):
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        for content in output.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                raise OpenAIRequestError(f"model refused the request: {content.get('refusal', 'no detail')}")
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    if not chunks:
        raise OpenAIRequestError(
            f"Responses API returned no output text (status={response.get('status', 'unknown')})"
        )
    return "".join(chunks)


def request_json(
    *,
    instructions: str,
    input_payload: object,
    schema_name: str,
    schema: dict,
    max_output_tokens: int = 20000,
) -> tuple[object, dict]:
    key, model, effort = configuration()
    body = {
        "model": model,
        "instructions": instructions,
        "input": json.dumps(input_payload, ensure_ascii=False, separators=(",", ":")),
        "reasoning": {"effort": effort},
        "max_output_tokens": max_output_tokens,
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "MIT-1.125-PS04/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as result:
            response = json.loads(result.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message")
        except Exception:
            detail = None
        raise OpenAIRequestError(f"OpenAI API HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise OpenAIRequestError(f"OpenAI API connection failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAIRequestError("OpenAI API returned invalid JSON") from exc

    if response.get("status") != "completed":
        detail = response.get("incomplete_details") or response.get("error") or {}
        raise OpenAIRequestError(
            f"OpenAI response did not complete: {response.get('status', 'unknown')}; "
            f"detail={detail}; usage={response.get('usage')}"
        )
    text = _output_text(response)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenAIRequestError("structured model output was not valid JSON") from exc
    metadata = {
        "provider": "openai",
        "model": response.get("model", model),
        "response_id": response.get("id"),
        "status": response.get("status"),
        "usage": response.get("usage"),
        "cost_usd": None,
    }
    return parsed, metadata


def write_metadata(path: pathlib.Path, metadata: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
