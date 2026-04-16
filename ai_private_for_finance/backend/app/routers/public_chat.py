from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.vector import embed_text, search_news
from app.services.financial import build_financial_summary
from app.services.llm import llm_client
from app.services.cache import cache_get, cache_set

router = APIRouter(prefix="/public/chat", tags=["public-chat"])

SYSTEM_GUARDRAILS = """
Bạn là trợ lý phân tích tài chính. Quy tắc:
- Không đưa khuyến nghị mua/bán cụ thể.
- Không phóng đại độ chắc chắn. Trình bày dưới dạng nhận định và rủi ro.
- Không bịa số. Chỉ dùng số liệu được cung cấp.
- Nếu thiếu dữ liệu: nói rõ thiếu.
- Tin tức: phải kèm link nguồn.
- Kết thúc với disclaimer: "Thông tin chỉ mang tính tham khảo."
""".strip()


@router.post("/ask")
async def ask(payload: dict, db: Session = Depends(get_db)):
    question = (payload.get("question") or "").strip()
    ticker = (payload.get("ticker") or "").strip().upper()
    k_news = int(payload.get("k_news") or 6)

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    cache_key = f"chat:{ticker}:{hash(question)}:{k_news}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    # Vector retrieve
    try:
        qvec = await embed_text(question)
        news_hits = search_news(qvec, limit=k_news)
    except Exception:
        news_hits = []

    # Financial context
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

    prompt = f"""
{SYSTEM_GUARDRAILS}

Câu hỏi: {question}

Dữ liệu BCTC (nếu có):
{fin}

Tin tức liên quan (nếu có):
{news_hits}

Hãy trả lời ngắn gọn, có cấu trúc:
1) Tóm tắt dữ liệu
2) Điểm đáng chú ý / rủi ro
3) Danh sách nguồn tin (link)
4) Disclaimer
""".strip()

    llm_out = await llm_client.generate(prompt)
    answer = llm_out if llm_out else (
        "LLM chưa bật. Hãy xem financial_context và news_context trong response.\n"
        "Thông tin chỉ mang tính tham khảo."
    )

    resp = {
        "question": question,
        "ticker": ticker or None,
        "answer": answer,
        "financial_context": fin,
        "news_context": news_hits,
        "disclaimer": "Thông tin chỉ mang tính tham khảo, không phải khuyến nghị đầu tư."
    }
    cache_set(cache_key, resp, ttl_seconds=120)
    return resp
