from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.vector import embed_text, search_news
from app.services.financial import build_financial_summary
from app.services.llm import llm_client
from app.services.cache import cache_get, cache_set

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/ask")
async def ask(payload: dict, db: Session = Depends(get_db)):
    """
    payload:
      {
        "question": "...",
        "ticker": "VNM" (optional),
        "k_news": 6 (optional)
      }
    """
    question = (payload.get("question") or "").strip()
    ticker = (payload.get("ticker") or "").strip().upper()
    k_news = int(payload.get("k_news") or 6)

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    # Cache key
    cache_key = f"chat:{ticker}:{hash(question)}:{k_news}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    # 1) Retrieve news context from Qdrant
    news_hits = []
    try:
        qvec = await embed_text(question)
        news_hits = search_news(qvec, limit=k_news)
    except Exception:
        # If vector search not ready, just proceed without it
        news_hits = []

    # 2) Retrieve financial summary if ticker provided
    fin = None
    if ticker:
        try:
            fin_res = await build_financial_summary(db, ticker)
            fin = {
                "ticker": fin_res.ticker,
                "latest_period_end": fin_res.latest_period_end,
                "metrics_latest": fin_res.metrics_latest,
                "deltas": fin_res.deltas,
                "red_flags": fin_res.red_flags,
            }
        except Exception as e:
            fin = {"error": str(e)}

    # 3) Compose answer
    if fin is None and not news_hits:
        # No context => best-effort
        llm_prompt = f"Hãy trả lời câu hỏi sau bằng tiếng Việt, ngắn gọn và thận trọng:\n\n{question}"
    else:
        llm_prompt = f"""
Bạn là trợ lý phân tích tài chính nội bộ. Trả lời bằng tiếng Việt.
Nguyên tắc:
- Không bịa số.
- Nếu thiếu dữ liệu, nói rõ thiếu.
- Nếu có tin tức, hãy trích dẫn link.

Câu hỏi: {question}

Dữ liệu BCTC (nếu có):
{fin}

Tin tức liên quan (nếu có):
{news_hits}
""".strip()

    llm_out = await llm_client.generate(llm_prompt)
    answer = llm_out if llm_out else "LLM chưa bật hoặc không trả lời được. Hãy xem dữ liệu thô trong response."

    resp = {
        "question": question,
        "ticker": ticker or None,
        "answer": answer,
        "financial_context": fin,
        "news_context": news_hits,
    }
    cache_set(cache_key, resp, ttl_seconds=120)  # cache 2 phút cho chat
    return resp
