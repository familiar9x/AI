import os
import requests
import pandas as pd
import streamlit as st

API_BASE = os.getenv("DASHBOARD_API_BASE", "http://localhost:8000")

st.set_page_config(page_title="Finance AI Internal", layout="wide")

st.title("📈 Finance AI Internal (Level 1)")

tabs = st.tabs(["Company Summary", "News Stream", "Chatbot", "Health"])

with tabs[0]:
    col1, col2 = st.columns([1, 2])

    with col1:
        ticker = st.text_input("Ticker", value="VNM").strip().upper()
        if st.button("Generate Summary"):
            with st.spinner("Generating..."):
                r = requests.get(f"{API_BASE}/public/financial/summary/{ticker}", timeout=60)
                if r.status_code != 200:
                    st.error(r.text)
                else:
                    data = r.json()
                    st.session_state["company_data"] = data

    with col2:
        data = st.session_state.get("company_data")
        if data:
            st.subheader(f"{data['ticker']} – {data['latest_period_end']}")
            st.markdown(data["narrative"])

            st.divider()
            st.subheader("Metrics (latest)")
            df = pd.DataFrame([data["metrics_latest"]])
            st.dataframe(df, use_container_width=True)

            st.subheader("Deltas")
            st.json(data["deltas"])

            st.subheader("Red flags")
            if data["red_flags"]:
                for f in data["red_flags"]:
                    st.warning(f)
            else:
                st.success("No red flags (rule-based).")

with tabs[1]:
    c1, c2 = st.columns([1, 3])
    with c1:
        limit = st.slider("Limit per source", 5, 50, 20)
        if st.button("Fetch News"):
            with st.spinner("Fetching..."):
                r = requests.get(f"{API_BASE}/internal/news/fetch", params={"limit_per_source": limit}, timeout=60)
                if r.status_code != 200:
                    st.error(r.text)
                else:
                    st.session_state["news"] = r.json()
        
        if st.button("Ingest to Vector DB"):
            with st.spinner("Ingesting..."):
                r = requests.post(f"{API_BASE}/internal/news/ingest", params={"limit_per_source": limit}, timeout=120)
                if r.status_code != 200:
                    st.error(r.text)
                else:
                    st.success(r.json())

        st.caption("Nguồn lấy từ config/news_sources.txt (RSS).")

    with c2:
        payload = st.session_state.get("news")
        if payload:
            st.subheader(f"News items: {payload['count']}")
            items = payload["items"]

            # Filters
            all_topics = sorted(list({x["topic"] for x in items}))
            all_sent = ["positive", "neutral", "negative"]

            fcol1, fcol2, fcol3 = st.columns([1, 1, 2])
            with fcol1:
                topic = st.selectbox("Topic", ["(all)"] + all_topics)
            with fcol2:
                sent = st.selectbox("Sentiment", ["(all)"] + all_sent)
            with fcol3:
                ticker_filter = st.text_input("Filter by ticker (optional)", value="").strip().upper()

            def ok(x):
                if topic != "(all)" and x["topic"] != topic:
                    return False
                if sent != "(all)" and x["sentiment"] != sent:
                    return False
                if ticker_filter:
                    return ticker_filter in (x.get("tickers") or [])
                return True

            for it in [x for x in items if ok(x)]:
                st.markdown(f"### {it['title']}")
                st.write(it["published"])
                st.write(f"**Topic:** {it['topic']} | **Sentiment:** {it['sentiment']} | **Tickers:** {', '.join(it.get('tickers') or [])}")
                st.write(it["summary"])
                st.link_button("Open", it["link"])
                st.divider()
        else:
            st.info("Nhấn **Fetch News** để load tin.")

with tabs[2]:
    st.subheader("💬 Chatbot (RAG: BCTC + News)")
    c1, c2 = st.columns([1, 2])
    with c1:
        ticker_chat = st.text_input("Ticker (optional)", value="VNM", key="chat_ticker").strip().upper()
        k_news = st.slider("Top news to retrieve", 1, 10, 6)
    with c2:
        q = st.text_area("Question", value="Tóm tắt BCTC quý gần nhất và có tin tiêu cực gần đây không?")
        if st.button("Ask"):
            with st.spinner("Thinking..."):
                payload = {"question": q, "ticker": ticker_chat if ticker_chat else None, "k_news": k_news}
                r = requests.post(f"{API_BASE}/public/chat/ask", json=payload, timeout=120)
                if r.status_code != 200:
                    st.error(r.text)
                else:
                    data = r.json()
                    st.markdown("### Answer")
                    st.write(data["answer"])

                    st.markdown("### Financial context")
                    st.json(data.get("financial_context"))

                    st.markdown("### News context")
                    for it in data.get("news_context") or []:
                        st.markdown(f"- {it.get('title')} ({it.get('topic')}/{it.get('sentiment')})")
                        if it.get("link"):
                            st.link_button("Open", it["link"])

with tabs[3]:
    r = requests.get(f"{API_BASE}/internal/health", timeout=10)
    st.json(r.json())
