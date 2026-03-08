"""JSON parsing utilities for LLM responses."""

import json
import re
from typing import Any


def parse_llm_json(text: str, required_fields: list[str] | None = None) -> dict[str, Any]:
    """Parse JSON from LLM response, handling markdown code fences and validation.

    Args:
        text: Raw text from LLM that may contain JSON
        required_fields: Optional list of fields that must be present in the JSON

    Returns:
        Parsed JSON as dictionary

    Raises:
        ValueError: If JSON is invalid or missing required fields
    """
    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    text = text.strip()

    # Remove markdown fences
    if text.startswith("```"):
        # Find the first newline after ```json or ```
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        # Remove trailing ```
        if text.endswith("```"):
            text = text[:-3]

    text = text.strip()

    # Try to parse JSON
    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from LLM: {e}\nText: {text[:200]}...")

    # Validate required fields
    if required_fields:
        missing = [f for f in required_fields if f not in result]
        if missing:
            raise ValueError(
                f"Missing required fields in LLM JSON: {', '.join(missing)}\n"
                f"Got: {list(result.keys())}"
            )

    return result


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    """Extract first JSON object from text that may contain non-JSON content.

    Useful when LLM includes explanations before/after the JSON.

    Args:
        text: Text that may contain JSON

    Returns:
        First valid JSON object found, or None if no valid JSON
    """
    # Try to find JSON object boundaries
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None
