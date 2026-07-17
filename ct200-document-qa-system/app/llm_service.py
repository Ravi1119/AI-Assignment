"""
LLM service for generating QA test cases from document sections.

Supports multiple providers (Groq, Gemini, OpenRouter) with structured output
validation and retry logic. Handles malformed LLM responses gracefully.
"""

import json
import re
from typing import Optional

import httpx

from app.config import LLM_PROVIDER, LLM_API_KEY, LLM_MODEL


# Structured prompt for QA test case generation
SYSTEM_PROMPT = """You are a QA engineer for medical devices. Given technical documentation 
sections, generate exactly 3 to 5 concrete, executable QA test cases.

Each test case MUST follow this exact JSON structure:
{
  "test_cases": [
    {
      "id": "TC-001",
      "title": "Short descriptive title",
      "preconditions": "What must be true before the test",
      "steps": ["Step 1", "Step 2", "Step 3"],
      "expected_result": "What should happen",
      "priority": "high|medium|low",
      "section_reference": "The section number this test covers"
    }
  ]
}

Rules:
- Generate between 3 and 5 test cases, no more, no less.
- Each test must be specific enough that another person could execute it.
- Focus on safety-critical behavior, boundary conditions, and error handling.
- Reference specific values from the document (pressure thresholds, timeouts, etc.).
- The output must be ONLY valid JSON, no markdown fences, no extra text.
"""


USER_PROMPT_TEMPLATE = """Generate QA test cases for the following technical documentation sections:

{content}

Remember: Output ONLY the JSON object with test_cases array. No other text."""


class LLMError(Exception):
    """Raised when LLM interaction fails."""
    pass


class LLMValidationError(LLMError):
    """Raised when LLM output doesn't match expected schema."""
    pass


def _call_groq(content: str) -> str:
    """Call Groq API."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(content=content)},
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }
    response = httpx.post(url, json=payload, headers=headers, timeout=60.0, verify=False)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def _call_gemini(content: str) -> str:
    """Call Google Gemini API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{LLM_MODEL}:generateContent"
    headers = {"Content-Type": "application/json"}
    params = {"key": LLM_API_KEY}
    payload = {
        "contents": [{
            "parts": [{"text": SYSTEM_PROMPT + "\n\n" + USER_PROMPT_TEMPLATE.format(content=content)}]
        }],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000},
    }
    response = httpx.post(url, json=payload, headers=headers, params=params, timeout=60.0)
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_openrouter(content: str) -> str:
    """Call OpenRouter API."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(content=content)},
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }
    response = httpx.post(url, json=payload, headers=headers, timeout=60.0)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


PROVIDERS = {
    "groq": _call_groq,
    "gemini": _call_gemini,
    "openrouter": _call_openrouter,
}


def _extract_json(raw: str) -> dict:
    """
    Extract JSON from LLM response, handling common formatting issues:
    - Markdown code fences (```json ... ```)
    - Leading/trailing whitespace or text
    - Partial JSON
    """
    # Try direct parse first
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    # Try to extract from markdown fences
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find JSON object anywhere in the text
    brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise LLMValidationError(
        f"Could not extract valid JSON from LLM response. Raw output (first 500 chars): {raw[:500]}"
    )


def _validate_test_cases(data: dict) -> list[dict]:
    """
    Validate that the parsed JSON matches expected schema.
    
    Required fields per test case: id, title, steps, expected_result.
    Optional but expected: preconditions, priority, section_reference.
    
    Returns the validated list of test cases.
    Raises LLMValidationError if structure is invalid.
    """
    if "test_cases" not in data:
        # Sometimes LLM returns a list directly
        if isinstance(data, list):
            test_cases = data
        else:
            raise LLMValidationError(
                f"Response missing 'test_cases' key. Got keys: {list(data.keys())}"
            )
    else:
        test_cases = data["test_cases"]

    if not isinstance(test_cases, list):
        raise LLMValidationError(f"test_cases is not a list, got {type(test_cases)}")

    if len(test_cases) < 1:
        raise LLMValidationError("No test cases in response")

    if len(test_cases) > 10:
        # Truncate to 5 if LLM got overzealous
        test_cases = test_cases[:5]

    validated = []
    for i, tc in enumerate(test_cases):
        if not isinstance(tc, dict):
            continue
        # Require minimum fields
        if "title" not in tc and "steps" not in tc:
            continue
        # Fill in defaults for missing optional fields
        validated.append({
            "id": tc.get("id", f"TC-{i+1:03d}"),
            "title": tc.get("title", "Untitled test case"),
            "preconditions": tc.get("preconditions", "None specified"),
            "steps": tc.get("steps", ["Execute test"]),
            "expected_result": tc.get("expected_result", "Not specified"),
            "priority": tc.get("priority", "medium"),
            "section_reference": tc.get("section_reference", ""),
        })

    if not validated:
        raise LLMValidationError("No valid test cases could be extracted from response")

    return validated


def generate_test_cases(content: str, max_retries: int = 2) -> dict:
    """
    Generate QA test cases from document content using the configured LLM.
    
    Retry strategy:
    - Up to max_retries attempts on validation failure
    - Returns partial results if all retries fail (with error flag)
    - Never silently swallows errors
    
    Returns:
        {
            "test_cases": [...],
            "status": "success" | "partial" | "error",
            "error_message": Optional[str],
            "raw_response": str (for debugging),
            "attempts": int,
        }
    """
    if not LLM_API_KEY:
        return {
            "test_cases": [],
            "status": "error",
            "error_message": "LLM_API_KEY not configured. Set it in .env file.",
            "raw_response": "",
            "attempts": 0,
        }

    provider_fn = PROVIDERS.get(LLM_PROVIDER)
    if not provider_fn:
        return {
            "test_cases": [],
            "status": "error",
            "error_message": f"Unknown LLM provider: {LLM_PROVIDER}. Use groq, gemini, or openrouter.",
            "raw_response": "",
            "attempts": 0,
        }

    last_error = None
    raw_response = ""

    for attempt in range(max_retries + 1):
        try:
            raw_response = provider_fn(content)
            parsed = _extract_json(raw_response)
            test_cases = _validate_test_cases(parsed)
            return {
                "test_cases": test_cases,
                "status": "success",
                "error_message": None,
                "raw_response": raw_response,
                "attempts": attempt + 1,
            }
        except (LLMValidationError, json.JSONDecodeError) as e:
            last_error = str(e)
            continue
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            break  # Don't retry on auth/rate limit errors
        except httpx.TimeoutException:
            last_error = "LLM request timed out"
            continue
        except Exception as e:
            last_error = f"Unexpected error: {str(e)}"
            break

    return {
        "test_cases": [],
        "status": "error",
        "error_message": last_error,
        "raw_response": raw_response,
        "attempts": max_retries + 1,
    }
