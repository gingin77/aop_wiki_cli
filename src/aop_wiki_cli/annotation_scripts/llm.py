"""Anthropic client plumbing shared by the annotation scripts.

One place owns client creation, the model name, and the call/parse dance, so
every caller gets the same error handling and JSON extraction.
"""

import json
import os
import re

import anthropic

LLM_MODEL = "claude-sonnet-4-6"


def make_client() -> anthropic.Anthropic | None:
    """Create and return an Anthropic client, or None if the API key is not set."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def call_text(client: anthropic.Anthropic, prompt: str, max_tokens: int) -> str | None:
    """Send one user prompt and return the reply text, or None on API failure."""
    try:
        message = client.messages.create(
            model=LLM_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"  (LLM call failed: {e})")
        return None


def extract_json(raw: str | None) -> dict | None:
    """Parse the first JSON object out of a model reply, or None."""
    if not raw:
        return None
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        return None
    try:
        parsed = json.loads(json_match.group())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def call_json(client: anthropic.Anthropic, prompt: str, max_tokens: int) -> dict | None:
    """Send one user prompt and return the first JSON object in the reply, or None."""
    return extract_json(call_text(client, prompt, max_tokens))


def response_text(message) -> str:
    """Return the text of the first text block in an Anthropic message.

    Thinking-enabled replies may carry a thinking block at position 0, so the
    text block is selected explicitly. Returns "" when there is none.
    """
    return next((b.text for b in message.content if b.type == "text"), "")


def extract_json_value(raw: str | None):
    """Parse the first JSON object OR array from a model reply, or None.

    More tolerant than extract_json: handles replies wrapped in markdown code
    fences, bare JSON embedded in prose, and JSON followed by trailing
    commentary (raw_decode stops at the end of the first complete value
    instead of requiring the whole string to be JSON).
    """
    if not raw:
        return None
    fence_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\]|\{[\s\S]*?\})\s*```', raw)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass  # fall through to raw_decode on the raw text
    first = re.search(r'[\[\{]', raw)
    if not first:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(raw, first.start())
        return obj
    except json.JSONDecodeError:
        return None


def create_message_with_retry(
    client: anthropic.Anthropic,
    *,
    model: str,
    max_tokens: int,
    messages: list[dict],
    system: str | None = None,
    thinking: dict | None = None,
    max_retries: int = 3,
    base_delay: float = 5.0,
):
    """client.messages.create with exponential-backoff retry on 5xx errors.

    For callers that need the full Message (stop_reason, thinking blocks)
    rather than call_text's plain-string convenience.
    """
    import time
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system is not None:
        kwargs["system"] = system
    if thinking is not None:
        kwargs["thinking"] = thinking
    for attempt in range(max_retries):
        try:
            return client.messages.create(**kwargs)
        except anthropic.InternalServerError as exc:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            print(f"  (Anthropic 5xx, attempt {attempt + 1}/{max_retries}: {exc} — retrying in {delay:.0f}s)")
            time.sleep(delay)
