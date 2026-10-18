"""One paper per gpt-4.1-mini chat completion. Shared by the pilot and the foundation run."""

import json
import ssl
import urllib.error
import urllib.request

import certifi

from extract_prompt import FACET_KEYS, MAX_COMPLETION_TOKENS, MODEL, SCHEMA, SYSTEM, numbered

CHAT_URL = "https://api.openai.com/v1/chat/completions"
ALLOWED_MODEL = "gpt-4.1-mini"


class CallError(Exception):
    def __init__(self, status, detail, retryable, retry_after):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.detail = detail
        self.retryable = retryable
        self.retry_after = retry_after


def ssl_context():
    return ssl.create_default_context(cafile=certifi.where())


def request_body(sentences):
    if MODEL != ALLOWED_MODEL:
        raise RuntimeError(f"refusing model {MODEL}")
    return {
        "model": MODEL,
        "temperature": 0,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "paper_facets", "strict": True, "schema": SCHEMA},
        },
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": numbered(sentences)},
        ],
    }


def salvage_json(text):
    """Keep complete items when the token cap cuts the last one."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    cut = max(text.rfind("},"), text.rfind("}]"))
    if cut < 0:
        return None
    fragment = text[: cut + 1]
    fragment += "]" * max(0, fragment.count("[") - fragment.count("]"))
    fragment += "}" * max(0, fragment.count("{") - fragment.count("}"))
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        return None


def validate(parsed, sentences):
    errors = []
    if not isinstance(parsed, dict):
        return ["response is not an object"]
    for key in FACET_KEYS:
        if key not in parsed or not isinstance(parsed[key], list):
            errors.append(f"missing {key}")
    if errors:
        return errors
    for key in FACET_KEYS:
        for item in parsed[key]:
            span = item.get("sentence_number")
            if not isinstance(span, int) or not 0 <= span < len(sentences):
                errors.append(f"{key} sentence_number {span} outside 0..{len(sentences) - 1}")
                continue
            if not str(item.get("label", "")).strip():
                errors.append(f"{key} empty label")
    return errors


def interpret_response(raw, sentences):
    choice = raw["choices"][0]
    message = choice["message"]["content"] or ""
    finish = choice.get("finish_reason")
    try:
        parsed = json.loads(message)
        errors = validate(parsed, sentences)
    except json.JSONDecodeError as exc:
        parsed = salvage_json(message)
        errors = [f"JSON decode: {exc}"]
        if parsed is not None:
            errors.append("kept the complete items from the cut reply")
            errors.extend(validate(parsed, sentences))
    if finish == "length":
        errors.append(f"completion hit the {MAX_COMPLETION_TOKENS} token cap")
    return {
        "returned_model": raw.get("model", ""),
        "finish_reason": finish,
        "usage": raw.get("usage", {}),
        "errors": errors,
        "raw_content": message,
        "facets": parsed,
    }


def post_completion(sentences, api_key, context, timeout=300):
    body_obj = request_body(sentences)
    if body_obj["model"] != ALLOWED_MODEL:
        raise RuntimeError("refusing request model")
    req = urllib.request.Request(
        CHAT_URL,
        data=json.dumps(body_obj).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        header = exc.headers.get("Retry-After") if exc.headers else None
        retry_after = int(header) if header and header.isdigit() else None
        retryable = exc.code == 429 or exc.code >= 500
        raise CallError(exc.code, detail, retryable, retry_after) from None
