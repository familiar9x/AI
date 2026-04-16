# Finance AI Internal (Level 1) – Docker

## 1) Setup
- Copy `.env.example` -> `.env`
- Update MariaDB connection in `.env`
- Update schema mapping in `config/schema_map.yaml`
- (Optional) add RSS sources in `config/news_sources.txt`

## 2) Run
```bash
docker compose up -d --build
```

## 3) Access

- **API**: http://localhost:8000/docs
- **Dashboard**: http://localhost:8501

## 4) Optional LLM (Ollama)

If `LLM_PROVIDER=ollama`, pull model:

```bash
docker exec -it ai_private_for_finance-ollama-1 ollama pull qwen2.5:7b-instruct
```

(Replace container name if different)

## 5) Ingest News to Vector DB

1. Go to Dashboard: http://localhost:8501
2. Navigate to "News Stream" tab
3. Click "Ingest to Vector DB"

## 6) Use Chatbot (RAG)

1. Go to "Chatbot" tab in Dashboard
2. Enter ticker (optional) and your question
3. The bot will retrieve financial data + relevant news using vector search

## Architecture

- **Backend (FastAPI)**: Financial analysis engine + RAG chatbot
- **Dashboard (Streamlit)**: User interface
- **Redis**: Cache for API responses (5 min for financial, 2 min for chat)
- **Qdrant**: Vector database for news articles
- **Ollama**: Local LLM for text generation and embeddings
- **MariaDB**: External database with financial statements (finn_data schema)

## API Endpoints

- `GET /health` - Health check
- `GET /financial/summary/{ticker}` - Financial analysis with cache
- `GET /news/sources` - List configured news sources
- `GET /news/fetch` - Fetch latest news from RSS
- `POST /news/ingest` - Ingest news to vector DB with dedup
- `POST /chat/ask` - RAG chatbot endpoint

## Configuration

### Schema Mapping (`config/schema_map.yaml`)

Map your actual database table/column names:

```yaml
financial_table:
  name: finn_data.financial_statements
  ticker_col: ticker
  period_end_col: period_end
  period_type_col: period_type
  currency_unit_col: currency_unit

columns:
  revenue: revenue
  net_income: net_income
  gross_profit: gross_profit
  operating_cash_flow: operating_cash_flow
  total_debt: total_debt
  cash_and_equiv: cash_and_equiv
  equity: equity
  total_assets: total_assets
  total_liabilities: total_liabilities
```

### News Sources (`config/news_sources.txt`)

Add RSS feed URLs (one per line):

```
https://vnexpress.net/rss/kinh-doanh.rss
https://cafef.vn/trang-chu.rss
```

## Next Steps (Enterprise Ready)

- Add Auth (SSO/LDAP or JWT)
- Add alerts/watchlist stored in DB
- Add audit log for user queries
- Expand red flag rules
- Add more financial ratios (ROE, ROA, margins, etc.)
