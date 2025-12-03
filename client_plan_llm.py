import os
import json
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv

try:
    import google.generativeai as genai  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    genai = None


load_dotenv()

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def _call_gemini(prompt: str, timeout: float = 12.0) -> str | None:
    if not GEMINI_API_KEY or genai is None:
        print("[client_plan_llm] Gemini not configured (missing GEMINI_API_KEY or google-generativeai).")
        return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.4,
                "top_p": 0.9,
                "max_output_tokens": 768,
            },
        )
        text = getattr(resp, "text", "")
        text = (text or "").strip()
        if not text:
            print("[client_plan_llm] Gemini call returned empty text.")
            return None
        # Strip code fences if any
        if text.startswith("```"):
            parts = text.split("\n", 1)
            text = parts[1] if len(parts) > 1 else ""
            if text.endswith("```"):
                text = text[:-3]
        cleaned = text.strip() or None
        if cleaned is None:
            print("[client_plan_llm] Gemini cleaned text is empty.")
        return cleaned
    except Exception as e:
        print("[client_plan_llm] Gemini error:", repr(e))
        return None


def _call_ollama(prompt: str, timeout: float = 16.0) -> str | None:
    try:
        url = f"{DEFAULT_OLLAMA_URL}/api/generate"
        req = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "options": {"temperature": 0.4},
        }
        r = requests.post(url, json=req, timeout=timeout)
        r.raise_for_status()
        # Ollama may stream; collect all response chunks if present
        text = ""
        try:
            lines = r.text.splitlines()
            bufs: List[str] = []
            for line in lines:
                try:
                    obj = json.loads(line)
                    if "response" in obj:
                        bufs.append(str(obj["response"]))
                except Exception:
                    continue
            text = "".join(bufs).strip()
        except Exception:
            text = r.text.strip()
        if not text:
            print("[client_plan_llm] Ollama call returned empty text.")
        return text or None
    except Exception as e:
        print("[client_plan_llm] Ollama error:", repr(e))
        return None


def _build_prompt(ctx: Dict[str, Any]) -> str:
    client_name = str(ctx.get("client_name", "the client"))
    cluster = str(ctx.get("cluster", "")).strip()
    rec_ptype = str(ctx.get("recommended_product_type", "")).strip()
    confidence = str(ctx.get("confidence", "")).strip()
    pred_amt = ctx.get("predicted_amount_sgd")
    avg_hist = ctx.get("avg_historical_amount")
    total_tx = ctx.get("total_transactions")
    transactions: List[Dict[str, Any]] = ctx.get("transactions", []) or []
    products: List[str] = ctx.get("available_product_types", []) or []

    parts: List[str] = []

    parts.append(
        "You are an expert financial advisor. "
        "Given the client context below, propose a concise, thoughtful future investment plan. "
        "You must perfectly balance exploitation (building on what already works for this client) "
        "and exploration (carefully testing other suitable product types)."
    )

    parts.append("\n\nClient profile:")
    parts.append(f"- Name: {client_name}")
    if cluster:
        parts.append(f"- Segment / cluster: {cluster}")
    if total_tx is not None:
        parts.append(f"- Total historical transactions: {total_tx}")
    if avg_hist is not None:
        try:
            avg_val = float(avg_hist)
            parts.append(f"- Average historical ticket size (approx.): {avg_val:,.0f} SGD")
        except Exception:
            parts.append(f"- Average historical ticket size (approx.): {avg_hist} SGD")

    parts.append("\nHistorical transaction pattern (no dates; only product types and amounts):")
    if transactions:
        for t in transactions:
            p = str(t.get("product", "-"))
            a = t.get("amount")
            if a is not None:
                try:
                    a_val = float(a)
                    parts.append(f"- {p}: {a_val:,.0f} SGD")
                except Exception:
                    parts.append(f"- {p}: {a} SGD")
            else:
                parts.append(f"- {p}")
    else:
        parts.append("- No detailed history available.")

    parts.append("\nModel recommendation summary:")
    if rec_ptype:
        parts.append(f"- Recommended product type: {rec_ptype}")
    if pred_amt is not None:
        try:
            p_val = float(pred_amt)
            parts.append(f"- Predicted investment size (approx.): {p_val:,.0f} SGD")
        except Exception:
            parts.append(f"- Predicted investment size (approx.): {pred_amt} SGD")
    if confidence:
        parts.append(f"- Recommendation confidence: {confidence}")

    if products:
        uniq = sorted({str(p).strip() for p in products if str(p).strip()})
        parts.append("\nUniverse of available product types:")
        parts.append("- " + ", ".join(uniq))

    parts.append(
        "\n\nInstructions for your answer (very important):\n"
        "- Write your answer as natural prose in 1 or 2 short paragraphs. Do not use bullet points or markdown.\n"
        "- Start with a polite greeting that includes the client's name (for example, 'Hi B75.'), then describe their "
        "profile and current investment behaviour in your own words.\n"
        "- Focus on a future plan only. Do NOT mention specific calendar dates; instead use vague time expressions like "
        "'over the next few months', 'later in the year', 'from time to time', etc.\n"
        "- Propose how the client could allocate their portfolio between core products (that match their history and "
        "cluster) and exploratory products. When you are confident, you may suggest approximate percentage ranges "
        "(for example, 'about 60–70% in DPMS and ETFs, and 20–30% in stocks or bonds'). If you are not confident about "
        "precise ranges, use qualitative wording instead (for example, 'most of the portfolio' versus 'a smaller portion').\n"
        "- Always mention both the potential upside (for example, yield or diversification benefits) and the potential "
        "downside or risks (for example, short-term volatility or capital risk).\n"
        "- Include a gentle next step and a polite closing sentence (for example, suggesting discussing ideas in the next "
        "conversation and thanking the client).\n"
        "- Vary your phrasing and structure; do not follow a fixed template across clients, but keep to this overall flow.\n"
        "- Use plain language that a banker could read directly to the client."
    )

    return "\n".join(parts)


def generate_client_plan(context: Dict[str, Any]) -> str:
    """Generate a future investment plan paragraph for a client.

    Uses Gemini 2.5 Pro when available, falling back to a local Qwen/Ollama model.
    Returns a single paragraph of plain text. On failure, returns a short fallback message.
    """
    try:
        prompt = _build_prompt(context or {})
        # For client plans, rely only on the local model (Ollama/Qwen) to avoid Gemini safety stops.
        text = _call_ollama(prompt)
        if not text:
            print("[client_plan_llm] Local model (Ollama) returned no text for client plan.")
            return "Future plan is temporarily unavailable (local model call failed). Please try again later."
        # Ensure single paragraph
        return " ".join(str(text).strip().split())
    except Exception as e:
        print("[client_plan_llm] Unexpected error in generate_client_plan:", repr(e))
        return "Future plan is temporarily unavailable (unexpected error). Please try again later."
