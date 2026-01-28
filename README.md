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
| `python cli.py portfolio` | List current positions with quantity, average price, and market value. |
| `python cli.py cancel ORDER_ID` | Cancel a pending order. |
| `python cli.py history SYMBOL` | Fetch historical price data. Use `--span` (default: week) and `--interval` (default: day) to customize. |
| `python cli.py news SYMBOL` | Fetch recent news articles for a stock. |
| `python cli.py orders` | List all pending/open orders. |
| `python cli.py account` | Show account buying power, cash balance, and unsettled funds. |
| `python cli.py yf-quote SYMBOL` | Fetch real-time quote via Yahoo Finance. |
| `python cli.py yf-news SYMBOL` | Fetch latest news via Yahoo Finance. |
| `python cli.py yf-options SYMBOL` | View option chains via Yahoo Finance. Use `--expiration` for specific dates. |

Each command shares common options via a decorator (e.g., `--debug`, `--dry-run`) so the user can preview requests without submitting them.

## MCP Server (AI Agent Skills)

This project includes a Model Context Protocol (MCP) server, allowing AI agents (like Claude Desktop) to interact with your Robinhood account.

### Capabilities
- **Portfolio Management:** Get current positions and account buying power.
- **Trading:** Place market/limit orders and cancel pending orders.
- **Market Data:** Fetch quotes, news, history, and option chains (via Yahoo Finance).

### Usage
1. Start the MCP server:
   ```powershell
   .\start_mcp.bat
   ```
2. Configure your MCP client (e.g., Claude Desktop) to point to the server.

### Tools Available
- `get_portfolio`: List open positions.
- `get_account_info`: View buying power and cash.
- `get_pending_orders`: List open orders.
- `execute_order`: Place buy/sell orders.
- `cancel_order`: Cancel a specific order.
- `get_stock_news` / `get_yf_stock_news`: Get latest news.
- `get_stock_history`: Get historical price data.
- `get_yf_stock_quote`: Get real-time quote (Yahoo).
- `get_yf_option_chain`: Get option chain (Yahoo).

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
- Tests (not included yet) should mock `robin_stocks` responses.
- Future features: `python cli.py watch SYMBOL`, price alerts, and portfolio rebalancing helpers.
