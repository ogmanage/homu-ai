"""Google Gemini API wrapper with robust JSON extraction."""

from __future__ import annotations

import json
import re

import streamlit as st
from pydantic import BaseModel, ValidationError

MODEL = "gemini-2.0-flash"


@st.cache_resource
def get_client():
    """Lazy-init Gemini client using GEMINI_API_KEY from st.secrets."""
    from google import genai

    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key or "ここに" in api_key:
        st.error("GEMINI_API_KEYが設定されていません。.streamlit/secrets.toml を確認してください。")
        st.stop()
    return genai.Client(api_key=api_key)


def call_claude(system: str, user: str, max_tokens: int = 4096) -> str:
    """Call Gemini and return the raw text content."""
    from google.genai import types

    client = get_client()
    response = client.models.generate_content(
        model=MODEL,
        contents=f"{system}\n\n{user}",
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=0.2,
        ),
    )
    return response.text


def extract_json(raw: str) -> dict:
    """
    Extract JSON from Gemini's response using a 3-step strategy:
    1. Direct json.loads (clean JSON response)
    2. Strip ```json ... ``` fences
    3. Find first { to last } substring
    """
    stripped = raw.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Strategy 2: markdown code fence
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: find outermost { ... }
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"AIのレスポンスからJSONを抽出できませんでした。\n\n"
        f"レスポンス先頭500文字:\n{raw[:500]}"
    )


def call_claude_structured(
    system: str,
    user: str,
    model_cls: type[BaseModel],
    max_tokens: int = 4096,
) -> BaseModel:
    """
    Call Gemini, extract JSON, validate with Pydantic model.
    Raises ValueError on JSON parse failure or ValidationError on schema mismatch.
    """
    raw = call_claude(system, user, max_tokens)
    data = extract_json(raw)
    try:
        return model_cls.model_validate(data)
    except ValidationError as e:
        raise ValueError(
            f"AIのレスポンスが期待するスキーマと一致しませんでした。\n{e}\n\n"
            f"生レスポンス先頭500文字:\n{raw[:500]}"
        ) from e
