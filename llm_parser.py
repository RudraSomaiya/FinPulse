import os
import json
import time
from typing import Any, Dict

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - optional dependency for Ollama fallback
    requests = None  # type: ignore[assignment]
from dotenv import load_dotenv

# Primary: Gemini 2.5 Flash via google-generativeai, optional; fall back to Ollama qwen2.5:7b-instruct
try:
    import google.generativeai as genai  # type: ignore
except Exception:
    genai = None  # allow running without SDK if not installed


load_dotenv()

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


SYSTEM_PROMPT = (
    "You convert banker instructions into a strict JSON action list for a recommendation editor. "
    "No prose. JSON only. Schema: {\n"
    "  rules: [\n"
    "    {type: 'suppress_client', client: string|[string], reason?: string},\n"
    "    {type: 'amount_multiplier', client: string|[string], factor: number, scope?: object, reason?: string},\n"
    "    {type: 'amount_set', client: string|[string], amount_p50: number, amount_p10?: number, amount_p90?: number, scope?: object, reason?: string},\n"
    "    {type: 'change_recommendation', client: string|[string], product_type: string, reason?: string},\n"
    "    {type: 'seasonality_inject', client: string, product_type: string, day_of_month: number, months?: [number], amount_p50: number|'match_last', amount_p10?: number, amount_p90?: number, effective_from: string, effective_to?: string, as_additional?: boolean, reason?: string},\n"
    "    {type: 'change_frequency', client: string|[string], frequency: 'daily'|'weekly'|'biweekly'|'monthly'|'quarterly', start_from?: string, count?: number, as_additional?: boolean, reason?: string},\n"
    "    {type: 'add_entry', client: string, date: string, product_type?: string, amount_p50: number, amount_p10?: number, amount_p90?: number, reason?: string},\n"
    "    {type: 'add_recurring', client: string, product_type?: string, amount_p50: number, amount_p10?: number, amount_p90?: number, frequency: 'daily'|'weekly'|'monthly', day_of_week?: string, day_of_month?: number, start_date?: string, end_date?: string, reason?: string},\n"
    "    {type: 'set_reminder', date: string, subject: string, content?: string},\n"
    "    {type: 'remove_reminder', date: string, subject: string}\n"
    "  ]\n"
    "}\n"
    "Allowed product types include STOCK, BONDS, and any present in the data. Return strictly JSON."
)


def _validate_actions(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Very lightweight validator to ensure shape and allowed fields. Returns cleaned actions or {}."""
    if not isinstance(obj, dict):
        return {}
    rules = obj.get("rules")
    if not isinstance(rules, list):
        return {}
    cleaned = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        rtype = str(r.get("type", "")).strip().lower()
        if rtype not in {
            "suppress_client",
            "amount_multiplier",
            "amount_set",
            "change_recommendation",
            "seasonality_inject",
            "change_frequency",
            "add_entry",
            "add_recurring",
            # tolerated aliases that we normalize downstream
            "delete_where",
            "remove_entry",
            "set_reminder",
            "remove_reminder",
        }:
            continue
        # Keep only known keys
        allowed_keys = {
            "type","client","factor","scope","where","reason","product_type","amount_p10","amount_p50","amount_p90",
            "frequency","start_from","count","as_additional","day_of_month","months","effective_from","effective_to",
            "date","day_of_week","start_date","end_date","subject","content"
        }
        cr = {k: v for k, v in r.items() if k in allowed_keys}
        cr["type"] = rtype
        cleaned.append(cr)
    return {"rules": cleaned}


def _gemini_call(prompt: str, timeout: float = 8.0) -> Dict[str, Any] | None:
    if not GEMINI_API_KEY or genai is None:
        return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        # Request JSON only
        full_prompt = (
            SYSTEM_PROMPT + "\n\nInstructions:" + "\n" + prompt + "\n\nReturn JSON only."
        )
        start = time.time()
        resp = model.generate_content(full_prompt, generation_config={
            "temperature": 0.1,
            "top_p": 0.8,
            "max_output_tokens": 1024,
        })
        if time.time() - start > timeout:
            return None
        text = resp.text.strip() if hasattr(resp, "text") else ""
        # Strip code fences if any
        if text.startswith("```") or text.startswith("```json"):
            # remove leading fence line
            parts = text.split("\n", 1)
            text = parts[1] if len(parts) > 1 else ""
            if text.endswith("```"):
                text = text[:-3]
        try:
            data = json.loads(text)
            return _validate_actions(data)
        except Exception:
            return None
    except Exception:
        return None


def _ollama_call(prompt: str, timeout: float = 12.0) -> Dict[str, Any] | None:
    # If requests is not available, we cannot call Ollama; treat as unavailable.
    if requests is None:
        return None
    try:
        url = f"{DEFAULT_OLLAMA_URL}/api/generate"
        req = {
            "model": OLLAMA_MODEL,
            "prompt": SYSTEM_PROMPT + "\n\nInstructions:\n" + prompt + "\n\nReturn JSON only.",
            "options": {"temperature": 0.1},
        }
        r = requests.post(url, json=req, timeout=timeout)
        r.raise_for_status()
        # Ollama streams by default; collect final response
        lines = r.text.splitlines()
        bufs = []
        for line in lines:
            try:
                obj = json.loads(line)
                if "response" in obj:
                    bufs.append(obj["response"]) 
            except Exception:
                continue
        text = "".join(bufs).strip()
        if not text:
            return None
        try:
            data = json.loads(text)
            return _validate_actions(data)
        except Exception:
            return None
    except Exception:
        return None


def parse_instructions(nl_text: str) -> Dict[str, Any]:
    """Primary Gemini, fallback to Ollama. Returns {rules: [...]} or {}."""
    nl_text = (nl_text or "").strip()
    if not nl_text:
        return {}
    data = _gemini_call(nl_text)
    if data and data.get("rules"):
        return data
    data = _ollama_call(nl_text)
    if data and data.get("rules"):
        return data
    return {}
