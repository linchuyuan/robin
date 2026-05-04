# Robin

Robin is a local Python trading assistant toolkit for Robinhood accounts. It has two main entry points:

- `cli.py`: a Click command-line interface for account, portfolio, order, quote, news, options, crypto, sentiment, macro, and market-session tasks.
- `server.py`: a FastMCP server that exposes the same broker and market-data functions to AI agents as structured JSON tools.

The project also includes Reddit sentiment tools, quant/technical-analysis tools, economic calendar helpers, and a walk-forward backtest engine for testing a simple scoring strategy.

This is not a fully automated trading bot by itself. The implementation is designed as a broker/data access layer with explicit order submission calls and pre-trade policy checks on MCP order execution.

## What Is Implemented

| Area | Files | What it does |
| --- | --- | --- |
| Authentication | `auth.py` | Loads `.env`, reads Robinhood credentials, caches the Robinhood session in `~/.robinhood-cli/session.json`, and supports logout. |
| CLI | `cli.py`, `robin.bat` | Provides terminal commands for Robinhood, Yahoo Finance, crypto, options, sentiment, macro news, and market status. |
| MCP server | `server.py`, `mcp_reddit_tools.py`, `mcp_quant_tools.py`, `mcp_kalshi_tools.py`, `start_mcp.bat`, `mcp_config.json` | Runs a FastMCP server over stdio, SSE, HTTP, or streamable HTTP. Tools return JSON plus `result_text` for LLM-friendly summaries. |
| Stock account data | `account.py`, `portfolio.py`, `market_data.py`, `order_history.py`, `orders.py` | Fetches account profile, positions, quotes, news, history, open orders, order details, and submits/cancels stock orders. |
| Options and crypto | `robin_options.py`, `crypto.py`, `yahoo_finance.py`, `option_utils.py` | Fetches Robinhood/Yahoo option chains, normalizes option-chain values, calculates Greeks for Robinhood chains, fetches crypto quotes/holdings, and submits crypto orders. |
| Risk guardrails | `pretrade_policy.py` | Blocks MCP stock buys when configured account, exposure, session, pending-order, hard-exclude, or Reddit sentiment checks fail. |
| Market context | `sentiment.py`, `market_calendar.py`, `macro_news.py`, `economic_events.py` | Fetches Fear & Greed, VIX, yield curve, market breadth, market sessions/holidays, macro headlines, and economic events. |
| Reddit data | `reddit_data.py`, `reddit_sentiment.py` | Fetches Reddit posts/comments and computes ticker mentions, normalized sentiment snapshots, hype risk, and trending tickers. |
| Kalshi data | `kalshi.py`, `mcp_kalshi_tools.py` | Browses public Kalshi prediction markets for global, economic, macro, and stock-ticker context. This is read-only market-data access. |
| Quant research | `quant.py`, `backtest_engine.py` | Calculates indicators, daily relative volume context, intraday volume velocity, IV rank, unusual options activity, risk/correlation metrics, peer candidates, and strategy backtests. |
| Advanced risk & attribution | `quant_advanced.py`, `stress_tester.py` | Fama-French 5+MOM factor attribution (Ken French data with ETF-proxy fallback), historical-simulation VaR/CVaR, mean-variance/risk-parity/Kelly sizing, per-position risk attribution, and 7-scenario historical shock replay with 1.5× tail multiplier. |
| Alt-data & flow | `insider_flow.py`, `options_flow.py`, `news_sentiment.py`, `earnings_consensus.py`, `fundamental_revision.py` | Openinsider Form-4 insider transactions (rate-limited, UA-rotated), options flow / unusual activity with smile fit and RR25, VADER-based news sentiment with publisher-tier weighting, earnings-surprise probability, and estimate-revision/earnings-quality scoring from yfinance estimate/trend/financial tables. |
| Macro & regime | `macro_data.py` | Yield-curve / credit-spread / VIX-term-structure / flight-to-quality / sector-breadth dashboards feeding the macro-regime-classifier skill. |
| Execution modeling & learning | `execution_models.py`, `drift_monitor.py`, `confidence_calibration.py` | Empirical slippage curve (size/volatility/time-of-day-aware), VWAP volume-profile slicing, live-fill drift monitor, and decision-trace confidence calibration against benchmark-relative outcomes. |
| Advanced MCP tools | `mcp_advanced_tools.py` | Registers 16 additional MCP tools: `get_macro_regime_dashboard`, `get_sector_breadth_tool`, `get_news_sentiment_tool`, `get_insider_flow_tool`, `get_unusual_options_activity_tool`, `get_earnings_surprise_tool`, `get_fundamental_revision_tool`, `get_factor_attribution_tool`, `get_portfolio_risk_summary_tool`, `get_portfolio_optimization_tool`, `get_stress_test_tool`, `get_slippage_estimate_tool`, `record_live_fill_tool`, `get_drift_report_tool`, `get_confidence_calibration_tool`, `backtest_params_vs_trace_tool`. |

## Installation

Create a virtual environment, then install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuration

Robin reads credentials from environment variables or a local `.env` file:

```bash
ROBINHOOD_USERNAME=alice@example.com
ROBINHOOD_PASSWORD=supersecret
ROBINHOOD_MFA=123456
```

If `ROBINHOOD_USERNAME` or `ROBINHOOD_PASSWORD` is missing, the CLI prompts interactively. In MCP server mode (`MCP_SERVER_MODE=1`), missing credentials raise an error instead of prompting.

Optional Reddit API credentials:

```bash
REDDIT_CLIENT_ID=your_reddit_app_client_id
REDDIT_CLIENT_SECRET=your_reddit_app_client_secret
REDDIT_USER_AGENT=robin-mcp/1.0 by <reddit_username>
```

If Reddit credentials are omitted, the Reddit helpers fall back to public Reddit JSON endpoints where possible.

Optional pre-trade policy variables:

```bash
ROBIN_MAX_DAILY_LOSS_PCT=0.03
ROBIN_MAX_ORDER_NOTIONAL_PCT=0.15
ROBIN_MAX_SYMBOL_EXPOSURE_PCT=0.30
ROBIN_MAX_PENDING_ORDERS_PER_SYMBOL=3
ROBIN_ENABLE_SENTIMENT_GUARDRAIL=1
ROBIN_SENTIMENT_FAIL_CLOSED=1
ROBIN_SENTIMENT_CONFIDENCE_FLOOR=0.45
ROBIN_ENABLE_HARD_EXCLUDE=1
ROBIN_HARD_EXCLUDE_SYMBOLS=AMD,AVGO,CEG,GOOG,NVDA,SLV
```

Optional MCP execution safety variables:

```bash
# Default is live broker execution for MCP mutating tools.
# Set paper explicitly for simulation/testing.
ROBIN_MCP_EXECUTION_MODE=live  # live | paper

# Legacy override: set to 0 to force paper mode when ROBIN_MCP_EXECUTION_MODE is unset.
ROBIN_MCP_ALLOW_LIVE_TRADING=1

# Required only when binding HTTP/SSE/streamable-http to a non-loopback host.
# Remote deployments must be protected by network controls/auth.
ROBIN_MCP_ALLOW_REMOTE=0

# Use the Clawd workspace memory tree for paper orders, drift, traces, and params.
CLAWD_MEMORY_DIR=/path/to/clawd/memory

# Optional explicit paper-order ledger override.
ROBIN_PAPER_ORDER_FILE=/path/to/paper-orders.json
```

Set `ROBIN_MCP_EXECUTION_MODE=paper` or `ROBIN_MCP_ALLOW_LIVE_TRADING=0` for simulation. The CLI remains separate; this setting applies to MCP mutating tools.

For HTTP, SSE, and streamable HTTP transports, `server.py` refuses non-loopback hosts unless `ROBIN_MCP_ALLOW_REMOTE=1` is set. Do not enable remote binding unless the endpoint is behind authentication, TLS, and network allowlisting.

Optional economic calendar variables:

```bash
ROBIN_ECON_CALENDAR_URL=https://nfs.faireconomy.media/ff_calendar_thisweek.json
ROBIN_ECON_CACHE_PATH=/tmp/robin_economic_events_cache.json
ROBIN_ECON_CACHE_TTL_SECONDS=3600
ROBIN_ECON_TIMEOUT_SECONDS=8
```

Optional Kalshi variables:

```bash
KALSHI_API_BASE_URL=https://api.elections.kalshi.com/trade-api/v2
KALSHI_TIMEOUT_SECONDS=8
```

Kalshi market-data tools use public unauthenticated endpoints. No Kalshi trading credentials are used or needed.

Do not commit `.env` or session files.

## CLI Usage

Run commands directly:

```bash
python cli.py --help
python cli.py quote AAPL
python cli.py order AAPL --qty 1 --side buy --order-type market
```

On Windows, the wrapper forwards arguments to `cli.py`:

```powershell
.\robin.bat quote AAPL
.\robin.bat market-status
```

Current CLI commands:

| Command | Description |
| --- | --- |
| `python cli.py login --mfa 123456` | Authenticate and cache a Robinhood session. MFA can be passed with `--mfa` or via `ROBINHOOD_MFA`. |
| `python cli.py logout` | Clear the cached Robinhood session and call Robinhood logout. |
| `python cli.py order SYMBOL --qty 1 --side buy --order-type market` | Submit a stock market or limit order. CLI order types are `market` and `limit`; limit orders require `--price`. Sells prompt unless `--yes` is passed. |
| `python cli.py quote SYMBOL` | Fetch a Robinhood stock quote. |
| `python cli.py portfolio` | List current stock positions with quantity, price, equity, average cost, daily P/L, total P/L, P/E, market cap, and 52-week range. |
| `python cli.py orders` | List open stock orders. |
| `python cli.py cancel ORDER_ID` | Request cancellation for a stock order. |
| `python cli.py history SYMBOL --span week --interval day` | Fetch Robinhood historical candles. |
| `python cli.py news SYMBOL` | Fetch Robinhood news articles. |
| `python cli.py yf-quote SYMBOL` | Fetch a Yahoo Finance quote. |
| `python cli.py yf-news SYMBOL` | Fetch Yahoo Finance news. |
| `python cli.py yf-options SYMBOL` | List Yahoo option expirations when `--expiration` is omitted; otherwise show a Yahoo option chain. |
| `python cli.py options SYMBOL` | List Robinhood option expirations when `--expiration` is omitted; otherwise show a chain with Greeks. |
| `python cli.py account` | Show buying power, cash balances, total equity, and market value. |
| `python cli.py crypto-quote SYMBOL` | Fetch a Robinhood crypto quote, for example `BTC`. |
| `python cli.py crypto-holdings` | List crypto positions. |
| `python cli.py crypto-order SYMBOL --qty 0.1 --side buy` | Submit a crypto market or limit order. Limit orders require `--price`; confirmation is required unless `--yes` is passed. |
| `python cli.py history-orders` | Show the 10 most recent stock orders. |
| `python cli.py order-detail ORDER_ID` | Show detailed stock order information. |
| `python cli.py fundamentals SYMBOL` | Fetch Robinhood fundamental data. |
| `python cli.py sentiment` | Show Fear & Greed and VIX data. |
| `python cli.py macro --limit 10 --today` | Show aggregated macroeconomic headlines. |
| `python cli.py market-status` | Show current market session, schedule, next open/close, holidays, or early closes. |

Global CLI options:

```bash
python cli.py --dry-run order AAPL --qty 1 --side buy
python cli.py --debug login
```

`--dry-run` is implemented for the stock `order` command path.

## MCP Server

Start the server over streamable HTTP:

```powershell
.\start_mcp.bat
```

That wrapper sets `MCP_SERVER_MODE=1` and runs:

```bash
python server.py --transport=streamable-http --host=127.0.0.1 --port=8000 --path=/messages
```

You can also run the server directly:

```bash
python server.py --transport streamable-http --host 127.0.0.1 --port 8000 --path /messages
python server.py --transport stdio
```

Sample MCP client config for HTTP:

```json
{
  "mcpServers": {
    "robinhood": {
      "url": "http://127.0.0.1:8000/messages"
    }
  }
}
```

Sample MCP client config for stdio:

```json
{
  "mcpServers": {
    "robinhood": {
      "command": "c:\\absolute\\path\\to\\robin\\start_mcp.bat",
      "args": ["--transport", "stdio"]
    }
  }
}
```

### MCP Response Contract

MCP tools return dictionaries, not plain text. Successful and failed responses include machine-readable fields plus a short `result_text`. Many market-data tools also include `data_quality`, `source`, `fetched_at_utc`, `as_of_bar`, warnings, or cache metadata so LLM callers can reason about freshness and confidence.

Mutating tools such as `execute_order`, `execute_crypto_order`, and `cancel_order` include `success`. Stock and crypto order responses validate that Robinhood returned an order id before reporting success. Successful live order responses return a redacted summary in `details` instead of echoing the full broker payload.

Stock order tools validate symbols, side, quantity, order type, price, stop price, and time-in-force before calling Robinhood.

### MCP Tool Groups

Broker and account tools:

- `get_portfolio`
- `get_account_info`
- `get_pending_orders`
- `get_stock_order_history`
- `get_order_details`
- `execute_order`
- `cancel_order`
- `get_crypto_price`
- `get_crypto_holdings`
- `execute_crypto_order`

Market data and options tools:

- `get_stock_news`
- `get_stock_history`
- `get_yf_stock_quote`
- `get_yf_stock_news`
- `get_option_expirations`
- `get_option_chain`
- `get_yf_option_expirations`
- `get_yf_option_chain`
- `get_fundamentals`
- `get_earnings_calendar`

Macro, calendar, and timestamp tools:

- `get_market_sentiment`
- `get_macro_news_headlines`
- `get_economic_events`
- `get_market_session`
- `get_timestamp`

Reddit tools:

- `get_reddit_posts`
- `get_reddit_post_comments`
- `get_reddit_symbol_mentions`
- `get_reddit_sentiment_snapshot`
- `get_reddit_ticker_sentiment`
- `get_reddit_trending_tickers`

Kalshi tools:

- `get_kalshi_markets`
- `get_kalshi_market_detail`
- `get_kalshi_event_detail`
- `get_kalshi_economic_market_context`
- `get_kalshi_stock_market_context`

Quant tools:

- `get_technical_indicators_tool`
- `get_volume_velocity_tool`
- `get_sector_performance_tool`
- `get_symbol_peers`
- `get_portfolio_correlation_tool`
- `get_iv_rank_tool`
- `get_unusual_options_activity_tool` (advanced flow/smile/RR25 signal)
- `get_unusual_options_activity_basic_tool` (legacy volume/OI and premium-bias summary)
- `get_fundamental_revision_tool` (estimate-revision and earnings-quality signal)
- `get_portfolio_risk_summary_tool` (advanced VaR/CVaR and risk attribution)
- `get_portfolio_concentration_summary_tool` (legacy position/sector concentration summary)
- `get_multi_stock_quotes`
- `get_confidence_calibration_tool` (confidence-vs-outcome calibration from decision traces)

## Pre-Trade Policy

`execute_order` calls `evaluate_pretrade_policy()` before stock order submission. The policy currently checks:

- Hard-excluded symbols, enabled by default.
- Account data availability for stock buys.
- Buying power after pending buy orders.
- Daily loss limit, using `equity_previous_close` when available, otherwise open-position intraday P/L.
- Maximum order notional as a percent of account equity.
- Maximum symbol exposure after the proposed order and pending buys.
- Maximum open pending stock orders for the same symbol.
- Market session for stock market buys unless `extended_hours=true`.
- Reddit sentiment hype-risk guardrail for stock buys.

The policy returns `allowed`, `blocked_by`, `reason`, `checks`, `metrics`, and `limits`. Failed policy checks block MCP order submission before Robinhood is called.

Crypto MCP orders also call the same policy function, but stock-specific checks are bypassed where the implementation marks them as stock-only.

## Backtesting

Run the single-period strategy backtest:

```bash
python backtest_engine.py --mode single
```

Run walk-forward validation with threshold tuning:

```bash
python backtest_engine.py --mode walk-forward --train-days 252 --test-days 63 --step-days 63 --threshold-grid 65,70,75
```

The backtest uses Yahoo Finance data, SPY as benchmark, next-bar execution, slippage, per-trade commission, max-position sizing, cash buffer, stop losses, Sharpe, information ratio, excess return, and max drawdown.

## Tests

The repository contains lightweight tests for auth/session handling, server contracts, quant functions, pre-trade policy behavior, tool contracts, Kalshi helpers, options helpers, and advanced risk modules:

```bash
python -m unittest \
  test_auth.py \
  test_server_contract.py \
  test_pretrade_policy.py \
  test_quant.py \
  test_option_utils.py \
  test_kalshi.py \
  test_tool_contracts.py \
  test_advanced_modules.py
```

`test_mcp.py` is an integration-style contract script for MCP tool behavior and may require the server/dependencies/configuration expected by the local environment.

## Deployment Helpers

### Docker

The Docker image runs the MCP server as a non-root user and binds to `127.0.0.1` by default. Keep that default unless the container is behind a trusted reverse proxy with authentication, TLS, and network policy.

```bash
docker build -t robin-mcp .
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env robin-mcp
```

Do not expose `/messages` directly on an untrusted network. Any client that can reach the MCP endpoint can invoke broker tools subject to the configured paper/live mode and policy gates.

The `scripts/` directory packages this repo with an OpenClaw skill tree and configures another compute node.

Build a deployment bundle from the repo root:

```bash
SKILLS_DIR=/path/to/clawd/skills ./scripts/build_openclaw_bundle.sh
```

Copy the generated tarball to a target machine, then configure the node:

```bash
tar -xzf /tmp/fulldeploy-YYYYMMDD-HHMMSS.tar.gz -C /tmp
chmod +x /tmp/openclaw_bundle/configure_openclaw_node.sh
/tmp/openclaw_bundle/configure_openclaw_node.sh /tmp/fulldeploy-YYYYMMDD-HHMMSS.tar.gz /opt/openclaw
```

Or from a checkout:

```bash
./scripts/configure_openclaw_node.sh /tmp/fulldeploy-*.tar.gz /opt/openclaw
```

Start the installed stack:

```bash
/opt/openclaw/start_openclaw_stack.sh
```

Useful deployment variables include:

```bash
PYTHON_EXE
ROBIN_MCP_HOST
ROBIN_MCP_PORT
WHATSAPP_DM_POLICY
WHATSAPP_ALLOW_FROM
RUN_CODEX_OAUTH
RUN_WHATSAPP_LOGIN
OPENCLAW_CRON_NAME
OPENCLAW_CRON_EXPR
OPENCLAW_CRON_TZ
OPENCLAW_CRON_MESSAGE
```

The configure script installs OpenClaw and MCPorter, unpacks the Robin MCP server bundle, installs packaged skills, writes MCP/OpenClaw configuration, runs interactive login steps unless disabled, and can register a cron job when `OPENCLAW_CRON_*` variables are provided.

## Security Notes

- Keep `.env`, Robinhood credentials, Reddit credentials, and session cache files out of version control.
- Use `--dry-run` before stock CLI orders when checking command shape.
- MCP mutating tools default to live broker execution; set `ROBIN_MCP_EXECUTION_MODE=paper` for dry-run/simulation environments.
- Put HTTP/streamable MCP behind an authentication boundary before exposing it beyond localhost.
- MCP stock orders are guarded by `pretrade_policy.py`, but those checks are not a substitute for reviewing every order before execution.
- Kalshi integration is read-only and is intended to add prediction-market context to the AI stock-trading workflow, not to place Kalshi trades.
- Network calls depend on third-party APIs and may fail, rate limit, or return incomplete data.
- Broker and market data can be delayed or unavailable; do not treat tool output as guaranteed real-time execution advice.
