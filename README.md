# Robinhood CLI

A lightweight Python CLI for placing orders on Robinhood with a safety-first workflow. The CLI provides commands for authentication, order placement, portfolio introspection, and session management while keeping sensitive data out of source control.

## Design Overview

- **Command structure:** Built with `click` for clearly named commands and shared options. Each command calls into a small domain layer (`auth`, `order`, `portfolio`) so the CLI stays thin.
- **Session management:** Authentication is cached in `~/.robinhood-cli/session.json` with explicit login/logout helpers; each command checks for a valid session before running.
- **Order safety:** All trade commands require explicit confirmation (`--yes`) for sells or when the order size is large. Limit orders require providing a price, and market orders optionally log the current quote for review.
- **Extensible helpers:** Utility modules expose helpers for quoting, validating symbols, and formatting responses so additional commands (e.g., `watch`, `history`) can be added without duplicating logic.

## Installation

1. Create and activate a virtual environment (recommended).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Export credentials in your shell or via a `.env` file (never commit this file):
   ```bash
   export ROBINHOOD_USERNAME="alice@example.com"
   export ROBINHOOD_PASSWORD="supersecret"
   export ROBINHOOD_MFA="123456"
   # Optional for Reddit tools: if omitted, CLI/MCP will use public Reddit JSON mode
   export REDDIT_CLIENT_ID="your_reddit_app_client_id"
   export REDDIT_CLIENT_SECRET="your_reddit_app_client_secret"
   export REDDIT_USER_AGENT="robin-mcp/1.0 by <reddit_username>"
   ```
2. The CLI reads these values via `python-dotenv` (if a `.env` is present) and falls back to environment variables. If either the username or password is missing, the CLI will prompt you interactively.
3. A cached session token (with TTL) is stored at `~/.robinhood-cli/session.json`. Delete it or run `python cli.py logout` to purge credentials.

## CLI Commands

| Command | Description |
| --- | --- |
| `python cli.py login` | Authenticate with Robinhood and cache the session. Use `--mfa` to provide a one-time password. |
| `python cli.py logout` | Clear cached credentials and logout from Robinhood. |
| `python cli.py order SYMBOL --qty 1 --side buy --order-type market` | Place a market or limit order. Market orders can optionally log the latest quote before submission. Limit orders require `--price`. |
| `python cli.py quote SYMBOL` | Fetch the latest price and 52-week range before trading. |
| `python cli.py portfolio` | List current positions with detailed P/L metrics (Today's P/L, Total P/L, Equity). |
| `python cli.py cancel ORDER_ID` | Cancel a pending order. |
| `python cli.py history SYMBOL` | Fetch historical price data. Use `--span` (default: week) and `--interval` (default: day) to customize. |
| `python cli.py news SYMBOL` | Fetch recent news articles for a stock. |
| `python cli.py orders` | List all pending/open orders. |
| `python cli.py history-orders` | List the last 10 stock orders (open or closed) with their Order IDs. |
| `python cli.py order-detail ORDER_ID` | Show detailed information for a specific order. You can get the `ORDER_ID` from the `history-orders` command output. |
| `python cli.py account` | Show account buying power, cash balance, and total equity. |
| `python cli.py crypto-quote SYMBOL` | Fetch crypto quote (e.g. BTC). |
| `python cli.py crypto-holdings` | List current crypto positions. |
| `python cli.py crypto-order SYMBOL --qty 0.1 --side buy` | Place a crypto order. |
| `python cli.py yf-quote SYMBOL` | Fetch real-time quote via Yahoo Finance. |
| `python cli.py yf-news SYMBOL` | Fetch latest news via Yahoo Finance. |
| `python cli.py options SYMBOL` | Fetch option chain data from Robinhood (with Greeks). Use `--expiration` (required) and `--strikes` (default: 5) to control depth. |
| `python cli.py yf-options SYMBOL` | View option chains via Yahoo Finance. Use `--expiration` (required) and `--strikes` (default: 5) to control depth. |
| `python cli.py fundamentals SYMBOL` | Fetch key fundamental stats (P/E, Market Cap, 52-week range, Volume, Sector, etc.). |
| `python cli.py sentiment` | Get market sentiment (Fear & Greed Index, VIX). |
| `python cli.py macro` | Get aggregated latest macroeconomic news from Investing.com, Bloomberg, and CNBC. Supports `--limit` (default: 10) and `--today`. |
| `python cli.py market-status` | Show current market session (pre-market, regular, after-hours, closed), today's schedule, and next open/close. Use `--holidays` or `--early-closes` for calendar info. |

Each command shares common options via a decorator (e.g., `--debug`, `--dry-run`) so the user can preview requests without submitting them.

## MCP Server (AI Agent Skills)

This project includes a Model Context Protocol (MCP) server, allowing AI agents (like Claude Desktop) to interact with your Robinhood account.

### Capabilities
- **Portfolio Management:** Get current positions and account buying power.
- **Trading:** Place market/limit orders and cancel pending orders.
- **Market Data:** Fetch quotes, news, history, and option chains (via Yahoo Finance).
- **Pre-Trade Safety:** Policy checks (buying power, exposure, pending-order limits, session/risk guardrails) run before stock order submission.
  - Includes account-level daily loss guard using equity vs previous close when available.
  - Sentiment guardrail supports fail-closed mode via `ROBIN_SENTIMENT_FAIL_CLOSED=1` (default).

### Response format (LLM-friendly)
All MCP tools return **JSON** (not plain text). Each response includes:
- **Structured data** (e.g. `positions`, `orders`, `quote`, `profile`) for parsing and reasoning.
- **`result_text`**: a short human-readable summary for the model to cite or summarize.
- **`error`**: set when the call failed, with a descriptive message.
- For mutating tools (for example `execute_order`, `execute_crypto_order`, `cancel_order`), a **`success`** boolean is included.
- `execute_order` responses include a **`policy`** object summarizing pre-trade checks.

This keeps outputs consistent and easy for agents to consume (e.g. via `mcporter call … --output json`).

### Usage
1. Configure your MCP client (e.g., Claude Desktop, MCPorter) to point to the server.

   **Standard MCP Config (stdio transport):**
   Add this to your client's config file (e.g., `%APPDATA%\Claude\claude_desktop_config.json`):
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
   *Note: I have created a sample `mcp_config.json` in the root of this project that you can copy from. Update the path to match your actual location.*

   **HTTP Transport (recommended):**
   If running the server manually (`.\start_mcp.bat`), it defaults to streamable HTTP at `http://127.0.0.1:8000/messages`.
   ```json
   {
     "mcpServers": {
       "robinhood": {
         "url": "http://127.0.0.1:8000/messages"
       }
     }
   }
   ```

2. Start the MCP server:
   ```powershell
   .\start_mcp.bat
   ```
   (Only needed if using HTTP transport or manual testing)

### Tools Available
- `get_portfolio`: List open positions with detailed P/L metrics.
- `get_account_info`: View buying power, cash, and total equity.
- `get_pending_orders`: List open orders.
- `get_stock_order_history`: List recent stock orders.
- `get_order_details`: Get full details of an order by ID.
- `execute_order`: Place buy/sell orders.
- `cancel_order`: Cancel a specific order.
- `get_stock_news` / `get_yf_stock_news`: Get latest news.
- `get_stock_history`: Get historical price data.
- `get_yf_stock_quote`: Get real-time quote (Yahoo).
- `get_yf_option_expirations`: Get available Yahoo option expiration dates for a symbol (plus nearest expiration). Preferred helper before Yahoo chain fetches.
- `get_yf_option_chain`: Get option chain (Yahoo). Requires `expiration_date`; supports `strikes` parameter. Preferred default in this setup.
- `get_option_expirations`: Get available Robinhood option expiration dates for a symbol (plus nearest expiration). Use when falling back to Robinhood chain.
- `get_option_chain`: Get option chain with Greeks (Robinhood). Requires `expiration_date`; supports `strikes` parameter. Fallback/confirmatory source.
- Endpoint priority note: Yahoo-first is only for option-chain fetches; for other categories, prefer Robinhood endpoints.
- `get_crypto_price`: Get crypto quote.
- `get_fundamentals`: Get P/E, Market Cap, and other stats (Robinhood).
- `get_market_sentiment`: Get Fear & Greed Index and VIX.
- `get_macro_news_headlines`: Get aggregated latest macroeconomic news. Supports `limit` and `only_today`.
- `get_market_session`: Get current market session status (pre-market/regular/after-hours/closed), schedule, holidays, and next open/close.
- `get_earnings_calendar`: Get upcoming earnings dates for one or more symbols (comma-separated).
- `get_reddit_posts`: Query recent Reddit posts across selected subreddits.
- `get_reddit_post_comments`: Fetch comments for a specific Reddit post.
- `get_reddit_symbol_mentions`: Count ticker mentions and context in Reddit posts/comments.
- `get_reddit_sentiment_snapshot`: Compute normalized Reddit sentiment factors per symbol.
- `get_reddit_ticker_sentiment`: Compute Reddit sentiment for a manual comma-separated ticker list.
- `get_reddit_trending_tickers`: Discover fast-rising ticker mentions on Reddit.
- `get_timestamp`: Get current server timestamp.
- `get_crypto_holdings`: Get crypto positions.
- `execute_crypto_order`: Place crypto orders.
- `get_technical_indicators_tool`: Get calculated technicals (RSI, SMA50/200, ATR, RS-vs-SPY percentile, Returns, Rel Vol, ATR-based sizing) for a symbol.
- `get_sector_performance_tool`: Get 5-day performance of major sector ETFs.
- `get_symbol_peers`: Get peer ticker candidates plus sector/industry context.
- `get_portfolio_correlation_tool`: Get correlation matrix and high-correlation pairs for a list of symbols.

## Execution

On Linux/macOS, you can run the CLI directly:
```bash
./cli.py login
```

On Windows, use the provided batch wrapper:
```powershell
.\robin portfolio
.\robin history AAPL
```

## Authentication & Order Flow

- `auth.get_session()` reads cached credentials or prompts for them, then logs in with `robin_stocks.robinhood.login`.
- `order.build_payload()` validates the symbol, side, quantity, order type, and optional limit price before calling Robinhood.
- All network interactions bubble errors that are caught by the CLI layer to provide user-friendly messages.

## Security & Best Practices

- Do not commit credentials or `.env` to version control. Use `git update-index --skip-worktree .env` if needed.
- Limit orders must include `--price`; the CLI prevents misuse by failing fast.
- Confirm large sells with `--yes` or run a `--dry-run` first.
- Rate-limit calls by reusing the Robinhood session and caching quotes locally when practical.

## Development Notes

- The main modules (`auth.py`, `orders.py`, `portfolio.py`, and `cli.py`) live at the project root, and `cli.py` exposes the `click` group that powers the commands.
- MCP tool registrations are split by domain (`mcp_reddit_tools.py`, `mcp_quant_tools.py`) and composed in `server.py`.
- `pretrade_policy.py` centralizes order guardrails used by `execute_order`.
- `backtest_engine.py` supports single-run and walk-forward protocols:
  - `python backtest_engine.py --mode single`
  - `python backtest_engine.py --mode walk-forward --train-days 252 --test-days 63 --step-days 63 --threshold-grid 65,70,75`
- Tests should mock `robin_stocks` responses where possible.
- Future features: `python cli.py watch SYMBOL`, price alerts, and portfolio rebalancing helpers.

## Last Updated
2026-02-17
