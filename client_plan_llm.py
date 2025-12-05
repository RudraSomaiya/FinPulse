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
    first_inv = ctx.get("first_investment_date")
    total_invested = ctx.get("total_invested_sgd")
    transactions: List[Dict[str, Any]] = ctx.get("transactions", []) or []
    products: List[str] = ctx.get("available_product_types", []) or []

    parts: List[str] = []

    parts.append(
        "You are an expert financial advisor. "
        "Given the client context below, propose a concise, thoughtful future investment plan. "
        "You must perfectly balance exploitation (building on what already works for this client) "
        "and exploration (carefully testing other suitable product types)."
    )

    parts.append("\n\nClient profile and investment history:")
    parts.append(f"- Name: {client_name}")
    if cluster:
        parts.append(f"- Segment / cluster: {cluster}")
    if total_tx is not None:
        parts.append(f"- Total historical transactions: {total_tx}")
    if first_inv is not None:
        parts.append(f"- Date of first investment: {first_inv}")
    if total_invested is not None:
        try:
            tot_val = float(total_invested)
            parts.append(f"- Total invested to date (approx.): {tot_val:,.0f} SGD")
        except Exception:
            parts.append(f"- Total invested to date (approx.): {total_invested} SGD")
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
        "You must produce TWO clearly separated sections, in this exact order, both based on the SAME underlying plan.\n"
        "Section 1 is a concise bullet summary for the advisor. Section 2 is a client-facing narrative.\n"
        "Do not invent extra facts in Section 1 that are not consistent with Section 2; Section 1 should be a structured "
        "summary of the same content you provide to the client.\n"
        "Do NOT output the literal phrases 'SECTION 1 FORMAT' or 'SECTION 2 FORMAT' anywhere.\n\n"
        "------------------------------\n"
        "SECTION 1 (advisor summary) – OUTPUT REQUIREMENTS:\n"
        f"First line: '{client_name} (summary for advisor)' on its own line.\n"
        "Then use MARKDOWN bullet syntax so the output renders cleanly in a UI:\n"
        "- A top-level bullet called 'Investment summary' with nested bullets for:\n"
        "  - Date of first investment: <fill using the provided data>\n"
        "  - Total number of investments made: <fill using the provided data>\n"
        "  - Invested amount: <use the total invested figure, in SGD, rounded and readable>\n"
        "- A top-level bullet called 'Background' with nested bullets for:\n"
        "  - Cluster and description: <describe cluster and key behavioural traits in one short sentence>\n"
        "  - Immediate actions: <one or two short sentences describing what to do with core holdings (e.g., keep DPMS/ETFs "
        "as majority of portfolio) including rough percentage ranges or qualitative sizing>\n"
        "  - Alternative actions: <one short sentence describing exploratory product types (e.g., stocks or bonds)>\n"
        "    - Allocation: <rough percentage range OR qualitative wording such as 'small portion' if you are not confident>\n"
        "    - Timeline: <vague time horizon such as 'over the next few months' or 'over the coming year'>\n"
        "    - Upside: <1–2 very short phrases on benefits (e.g., higher return potential, diversification). This MUST always be present.>\n"
        "    - Downside: <1–2 very short phrases on risks (e.g., volatility, capital loss risk). This MUST always be present.>\n"
        "The four child bullets 'Allocation', 'Timeline', 'Upside', and 'Downside' must each be on their own line and indented under 'Alternative actions'; do NOT combine them into the same sentence.\n\n"
        "------------------------------\n"
        "SECTION 2 (client narrative) – OUTPUT REQUIREMENTS:\n"
        f"First line: '{client_name} (summary for client)' on its own line.\n"
        "Then write ONE paragraph of natural prose, similar in style to this pattern (do not copy wording exactly):\n"
        "'Hi B75. Given your profile as a passive long-term investor and investments primarily with DPMS and ETFs, our "
        "future recommendations will continue primarily with these. Concurrently, we can also cautiously explore other "
        "options that could diversify your portfolio while staying near to your stated goals and risk appetite. We propose "
        "maintaining 60-70% of the portfolio with DPMS and ETF. In addition, we would also recommend allocating around "
        "20-30% of the investment budget toward other product types such as stocks or bonds. These smaller allocations can "
        "potentially increase your yield and diversify the portfolio. The downside is that there might be some short term "
        "volatility. With your permission, during our next communication, we can share some of these ideas with you. Thank you.'\n"
        "Your paragraph must:\n"
        "- Start with a greeting that includes the client's name (for example, 'Hi B75.').\n"
        "- Focus on a future plan only. Do NOT mention specific calendar dates; instead use vague time expressions like "
        "'over the next few months', 'later in the year', 'from time to time', etc.\n"
        "- Propose how the client could allocate their portfolio between core products (that match their history and "
        "cluster) and exploratory products. When you are confident, you may suggest approximate percentage ranges; if not, "
        "use qualitative wording such as 'most of your portfolio' versus 'a smaller portion'.\n"
        "- Always mention both potential upside (e.g., yield or diversification) and downside or risks (e.g., volatility).\n"
        "- End with a simple closing like 'Thank you.' but DO NOT add any signature or placeholder such as '[YOUR NAME]' or "
        "'[Advisor]'.\n"
        "- Use plain, conversational language that a banker could read directly to the client.\n"
        "Do not add any extra commentary outside these two sections, and do not include any placeholder text in square brackets."
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
        # Preserve the two-section structure; just strip leading/trailing whitespace.
        return str(text).strip()
    except Exception as e:
        print("[client_plan_llm] Unexpected error in generate_client_plan:", repr(e))
        return "Future plan is temporarily unavailable (unexpected error). Please try again later."
