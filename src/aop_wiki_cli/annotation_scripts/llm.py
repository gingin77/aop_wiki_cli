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
