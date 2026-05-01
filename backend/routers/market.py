import backend.config  # noqa: F401
from fastapi import APIRouter, Query
import yfinance as yf

router = APIRouter()

TICKER_OVERRIDES = {
    "TENCENT": "0700.HK",
}


@router.get("/price")
def get_price(ticker: str = Query(..., description="Stock ticker symbol")):
    raw = ticker.upper().strip()
    sym = TICKER_OVERRIDES.get(raw, raw)
    try:
        t = yf.Ticker(sym)
        info = getattr(t, "fast_info", None)
        price = None
        if info is not None:
            price = getattr(info, "last_price", None) or getattr(info, "lastClose", None)
        if price is None:
            hist = t.history(period="1d")
            if not hist.empty and "Close" in hist.columns:
                price = float(hist["Close"].iloc[-1])
        if price is not None:
            return {"ticker": sym, "price": round(float(price), 4)}
        return {"ticker": sym, "price": None}
    except Exception as e:
        return {"ticker": sym, "price": None, "error": str(e)}
