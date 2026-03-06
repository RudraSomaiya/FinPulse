"""
Single entry point for LLM calls: Gemini 2.5 Flash first, Ollama fallback.
Provides ask_llm(prompt) -> str for the data-aware agent and other consumers.
"""

import json
import os
from typing import List

try:
    import requests  # type: ignore
except Exception:
    requests = None  # type: ignore[assignment]
from dotenv import load_dotenv

try:
    import google.generativeai as genai  # type: ignore
except Exception:
    genai = None

load_dotenv()

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def _call_gemini(prompt: str, timeout: float = 30.0) -> str | None:
    """Call Gemini API. Returns response text or None on failure."""
    if not GEMINI_API_KEY or genai is None:
        return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.3,
                "top_p": 0.9,
                "max_output_tokens": 8192,
            },
        )
        text = getattr(resp, "text", "")
        text = (text or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            parts = text.split("\n", 1)
            text = parts[1] if len(parts) > 1 else ""
            if text.endswith("```"):
                text = text[:-3].strip()
        return text.strip() or None
    except Exception:
        return None


def _call_ollama(prompt: str, timeout: float = 60.0) -> str | None:
    """Call Ollama API. Returns response text or None on failure."""
    if requests is None:
        return None
    try:
        url = f"{DEFAULT_OLLAMA_URL}/api/generate"
        req = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "options": {"temperature": 0.3},
            "stream": False,
        }
        r = requests.post(url, json=req, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        text = (data.get("response") or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            parts = text.split("\n", 1)
            text = parts[1] if len(parts) > 1 else ""
            if text.endswith("```"):
                text = text[:-3].strip()
        return text.strip() or None
    except Exception:
        return None


def ask_llm(prompt: str) -> str:
    """
    Send a prompt to the LLM: try Gemini 2.5 Flash first, fall back to Ollama.
    Returns the model response as a string, or a short fallback message on total failure.
    """
    result = _call_gemini(prompt)
    if result:
        return result
    result = _call_ollama(prompt)
    if result:
        return result
    return "LLM unavailable (Gemini and Ollama both failed). Please check API key and Ollama."
