"""Groq API wrapper with robust JSON extraction."""

from __future__ import annotations

import json
import re

import streamlit as st
from pydantic import BaseModel, ValidationError

MODEL = "llama-3.3-70b-versatile"


@st.cache_resource
def get_client():
    """Lazy-init Groq client using GROQ_API_KEY from st.secrets."""
    from groq import Groq

    api_key = st.secrets.get("GROQ_API_KEY", "")
    if not api_key:
        st.error("GROQ_API_KEYが設定されていません。.streamlit/secrets.toml を確認してください。")
        st.stop()
    return Groq(api_key=api_key)


def call_claude(system: str, user: str, max_tokens: int = 4096) -> str:
    """Call Groq and return the raw text content."""
    client = get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    return response.choices[0].message.content


def _fix_unescaped_newlines(text: str) -> str:
    """Escape literal newlines inside JSON string values."""
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == "\\" and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch == "\n":
            result.append("\\n")
        elif in_string and ch == "\r":
            result.append("\\r")
        elif in_string and ch == "\t":
            result.append("\\t")
        else:
            result.append(ch)
    return "".join(result)


def extract_json(raw: str) -> dict:
    """
    Extract JSON from response using a 4-step strategy:
    1. Direct json.loads (clean JSON response)
    2. Strip ```json ... ``` fences
    3. Find first { to last } substring
    4. Fix unescaped newlines inside string values, then retry steps 1-3
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

    # Strategy 4: fix unescaped newlines, then retry strategies 1-3
    fixed = _fix_unescaped_newlines(stripped)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    m2 = re.search(r"```(?:json)?\s*([\s\S]*?)```", fixed)
    if m2:
        try:
            return json.loads(m2.group(1).strip())
        except json.JSONDecodeError:
            pass

    start2 = fixed.find("{")
    end2 = fixed.rfind("}")
    if start2 != -1 and end2 != -1 and end2 > start2:
        try:
            return json.loads(fixed[start2 : end2 + 1])
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
    Call Groq, extract JSON, validate with Pydantic model.
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
