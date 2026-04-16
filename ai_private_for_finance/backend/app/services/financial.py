from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schema_map import load_schema_map
from app.services.llm import llm_client


@dataclass
class FinancialSummaryResult:
    ticker: str
    latest_period_end: str
    metrics_latest: Dict[str, Any]
    deltas: Dict[str, Any]
    red_flags: List[str]
    narrative: str


def _safe_pct_change(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or prev is None:
        return None
    if prev == 0:
        return None
    return (curr - prev) / abs(prev) * 100.0


def _pick(df: pd.DataFrame, col: str) -> Optional[float]:
    if col not in df.columns:
        return None
    v = df.iloc[0][col]
    if pd.isna(v):
        return None
    try:
        return float(v)
    except Exception:
        return None


def _add_flag(flags: list[str], cond: bool, msg: str):
    if cond:
        flags.append(msg)


async def build_financial_summary(db: Session, ticker: str) -> FinancialSummaryResult:
    smap = load_schema_map()
    t = smap.financial_table["name"]
    ticker_col = smap.financial_table["ticker_col"]
    period_end_col = smap.financial_table["period_end_col"]

    # Pull last 8 periods (enough for QoQ + YoY)
    q = text(f"""
        SELECT *
        FROM {t}
        WHERE {ticker_col} = :ticker
        ORDER BY {period_end_col} DESC
        LIMIT 8
    """)
    rows = db.execute(q, {"ticker": ticker}).mappings().all()
    if not rows:
        raise ValueError(f"No financial data for ticker={ticker}")

    df = pd.DataFrame(rows)

    # Normalize period_end to string
    if period_end_col in df.columns:
        df[period_end_col] = pd.to_datetime(df[period_end_col], errors="coerce")
        df = df.sort_values(period_end_col, ascending=False).reset_index(drop=True)

    # Map key metrics
    c = smap.columns
    latest = df.iloc[[0]]
    prev = df.iloc[[1]] if len(df) > 1 else None
    yoy = df.iloc[[4]] if len(df) > 4 else None  # approximate: 4 quarters back

    # Extract latest metrics
    metrics_latest = {
        "revenue": _pick(latest, c.get("revenue", "revenue")),
        "net_income": _pick(latest, c.get("net_income", "net_income")),
        "gross_profit": _pick(latest, c.get("gross_profit", "gross_profit")),
        "operating_cash_flow": _pick(latest, c.get("operating_cash_flow", "operating_cash_flow")),
        "total_debt": _pick(latest, c.get("total_debt", "total_debt")),
        "cash_and_equiv": _pick(latest, c.get("cash_and_equiv", "cash_and_equiv")),
        "equity": _pick(latest, c.get("equity", "equity")),
        "total_assets": _pick(latest, c.get("total_assets", "total_assets")),
        "total_liabilities": _pick(latest, c.get("total_liabilities", "total_liabilities")),
    }

    # Compute deltas
    deltas: Dict[str, Any] = {}
    if prev is not None:
        deltas["qoq"] = {
            "revenue_pct": _safe_pct_change(metrics_latest["revenue"], _pick(prev, c.get("revenue", "revenue"))),
            "net_income_pct": _safe_pct_change(metrics_latest["net_income"], _pick(prev, c.get("net_income", "net_income"))),
            "ocf_pct": _safe_pct_change(metrics_latest["operating_cash_flow"], _pick(prev, c.get("operating_cash_flow", "operating_cash_flow"))),
            "debt_pct": _safe_pct_change(metrics_latest["total_debt"], _pick(prev, c.get("total_debt", "total_debt"))),
        }
    if yoy is not None:
        deltas["yoy"] = {
            "revenue_pct": _safe_pct_change(metrics_latest["revenue"], _pick(yoy, c.get("revenue", "revenue"))),
            "net_income_pct": _safe_pct_change(metrics_latest["net_income"], _pick(yoy, c.get("net_income", "net_income"))),
            "ocf_pct": _safe_pct_change(metrics_latest["operating_cash_flow"], _pick(yoy, c.get("operating_cash_flow", "operating_cash_flow"))),
        }

    # Simple red flag rules
    flags: list[str] = []
    ni = metrics_latest["net_income"]
    ocf = metrics_latest["operating_cash_flow"]
    debt = metrics_latest["total_debt"]
    cash = metrics_latest["cash_and_equiv"]
    assets = metrics_latest["total_assets"]
    equity = metrics_latest["equity"]

    _add_flag(flags, (ni is not None and ocf is not None and ni > 0 and ocf < 0),
              "LNST dương nhưng OCF âm (cần kiểm tra chất lượng lợi nhuận).")
    _add_flag(flags, (debt is not None and cash is not None and debt > 2 * cash),
              "Nợ vay cao so với tiền mặt (áp lực thanh khoản/lãi vay).")
    _add_flag(flags, (assets is not None and equity is not None and equity <= 0),
              "Vốn chủ sở hữu thấp/âm (rủi ro đòn bẩy và khả năng huy động vốn).")

    # Build narrative: if LLM available, generate; else template
    latest_period = str(df.iloc[0][period_end_col].date()) if pd.notna(df.iloc[0][period_end_col]) else "unknown"

    prompt = f"""
Bạn là chuyên viên phân tích tài chính. Hãy viết bản tóm tắt 1 trang (tiếng Việt) cho mã {ticker} dựa trên số liệu sau.
Yêu cầu:
- Bullet points rõ ràng: Highlights / Red flags / Câu hỏi cần làm rõ.
- Không bịa số. Chỉ dùng số được đưa ra.
- Nếu thiếu dữ liệu thì nói "chưa có dữ liệu".

Kỳ gần nhất: {latest_period}

Số liệu kỳ gần nhất:
{metrics_latest}

Biến động:
{deltas}

Red flags (rules):
{flags}
""".strip()

    narrative = ""
    llm_out = await llm_client.generate(prompt)
    if llm_out:
        narrative = llm_out
    else:
        # fallback narrative
        narrative = (
            f"**{ticker} – Tóm tắt kỳ {latest_period}**\n\n"
            f"**Highlights**\n"
            f"- Doanh thu: {metrics_latest.get('revenue')}\n"
            f"- LNST: {metrics_latest.get('net_income')}\n"
            f"- OCF: {metrics_latest.get('operating_cash_flow')}\n\n"
            f"**Red flags**\n"
            + ("\n".join([f"- {x}" for x in flags]) if flags else "- Chưa phát hiện red flag theo rule hiện tại.\n")
            + "\n\n**Biến động**\n"
            + f"- QoQ: {deltas.get('qoq')}\n"
            + f"- YoY: {deltas.get('yoy')}\n"
        )

    return FinancialSummaryResult(
        ticker=ticker,
        latest_period_end=latest_period,
        metrics_latest=metrics_latest,
        deltas=deltas,
        red_flags=flags,
        narrative=narrative,
    )
