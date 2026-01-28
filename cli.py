#!/usr/bin/env python3
"""Command-line entrypoints for Robinhood CLI."""

from __future__ import annotations

import click
import robin_stocks.robinhood as rh

from auth import get_session, logout
from orders import OrderValidationError, place_order
from portfolio import get_quote, list_positions
from account import get_account_profile
from market_data import get_history, get_news
from yahoo_finance import get_yf_quote, get_yf_news, get_yf_options


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--debug", is_flag=True, help="Show debug output for API calls.")
@click.option("--dry-run", is_flag=True, help="Don\'t submit transactions, only simulate the payload.")
@click.pass_context
def cli(ctx: click.Context, debug: bool, dry_run: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    ctx.obj["dry_run"] = dry_run


@cli.command()
@click.option("--mfa", help="One-time password (if required) from your authenticator app.")
@click.pass_context
def login(ctx: click.Context, mfa: str | None) -> None:
    session = get_session()
    if ctx.obj["debug"]:
        click.echo(f"Session cached at {session.get('access_token')[:8]}...")
    click.echo("Logged in and session cached.")


@cli.command()
def logout_cmd() -> None:
    logout()
    click.echo("Session cleared; you are logged out.")


@cli.command()
@click.argument("symbol")
@click.option("--qty", required=True, type=float)
@click.option("--side", type=click.Choice(["buy", "sell"]), required=True)
@click.option("--order-type", "order_type", type=click.Choice(["market", "limit"]), default="market")
@click.option("--price", type=float)
@click.option("--yes", is_flag=True, help="Skip confirmation for risky orders.")
@click.pass_context
def order(ctx: click.Context, symbol: str, qty: float, side: str, order_type: str, price: float | None, yes: bool) -> None:
    get_session()
    if order_type == "limit" and price is None:
        raise click.UsageError("Limit orders require --price.")
    if side == "sell" and not yes:
        click.confirm("You are about to sell. Continue?", abort=True)
    if ctx.obj["dry_run"]:
        click.echo("Dry run enabled. Payload would be sent but not executed.")
        return
    try:
        session = get_session()
        result = place_order(symbol.upper(), qty, side, order_type, price, session)
        click.echo(f"Order submitted: {result.get('id')}")
    except OrderValidationError as exc:
        raise click.ClickException(str(exc))


@cli.command()
@click.argument("symbol")
def quote(symbol: str) -> None:
    get_session()
    data = get_quote(symbol.upper())
    click.echo(f"{symbol.upper()}: {data}")


@cli.command()
def portfolio_cmd() -> None:
    get_session()
    positions = list_positions()
    if not positions:
        click.echo("No open positions.")
        return
    for pos in positions:
        click.echo(f"{pos['symbol']}: {pos['quantity']} shares at avg {pos['average_buy_price']}")


@cli.command()
def orders() -> None:
    """List pending orders."""
    get_session()
    open_orders = rh.get_all_open_stock_orders()
    if not open_orders:
        click.echo("No pending orders.")
        return
    for order in open_orders:
        click.echo(f"ID: {order['id']} | {order['side']} {order['quantity']} {order['symbol']} @ {order.get('price', 'market')}")

@cli.command()
@click.argument("order_id")
def cancel(order_id: str) -> None:
    get_session()
    rh.cancel_stock_order(order_id)
    click.echo(f"Cancellation requested for {order_id}.")


@cli.command()
@click.argument("symbol")
@click.option("--interval", type=click.Choice(["5minute", "10minute", "hour", "day", "week"]), default="day")
@click.option("--span", type=click.Choice(["day", "week", "month", "3month", "year", "5year"]), default="week")
def history(symbol: str, interval: str, span: str) -> None:
    """Fetch historical data for a stock."""
    get_session()
    data = get_history(symbol.upper(), interval, span)
    if not data:
        click.echo("No historical data found.")
        return
    for point in data:
        click.echo(f"{point['begins_at']}: Open {point['open_price']}, Close {point['close_price']}")


@cli.command()
@click.argument("symbol")
def news(symbol: str) -> None:
    """Fetch news for a stock."""
    get_session()
    articles = get_news(symbol.upper())
    if not articles:
        click.echo("No news found.")
        return
    for article in articles:
        click.echo(f"{article['published_at']} - {article['title']}\n{article['url']}\n")



@cli.command()
@click.argument("symbol")
def yf_quote(symbol: str) -> None:
    """Fetch real-time stock quote from Yahoo Finance."""
    try:
        quote = get_yf_quote(symbol)
        click.echo(f"Symbol: {quote['symbol']}")
        click.echo(f"Price: {quote['current_price']}")
        click.echo(f"Open: {quote['open']}")
        click.echo(f"High: {quote['high']}")
        click.echo(f"Low: {quote['low']}")
        click.echo(f"Volume: {quote['volume']}")
        click.echo(f"Market Cap: {quote['market_cap']}")
        click.echo(f"P/E Ratio: {quote['pe_ratio']}")
        click.echo(f"Dividend Yield: {quote['dividend_yield']}")
    except Exception as e:
        click.echo(f"Error fetching Yahoo Finance quote: {str(e)}")

@cli.command()
@click.argument("symbol")
def yf_news(symbol: str) -> None:
    """Fetch latest news from Yahoo Finance."""
    try:
        news = get_yf_news(symbol)
        if not news:
            click.echo(f"No Yahoo Finance news found for {symbol}.")
            return
        
        for art in news[:5]:
            title = art.get('title', 'No Title')
            link = art.get('link', '#')
            publisher = art.get('publisher', 'Unknown')
            click.echo(f"- {title} ({publisher})\n  Link: {link}\n")
    except Exception as e:
        click.echo(f"Error fetching Yahoo Finance news: {str(e)}")

@cli.command()
@click.argument("symbol")
@click.option("--expiration", help="Expiration date (YYYY-MM-DD)")
def yf_options(symbol: str, expiration: str | None) -> None:
    """Fetch option chain data from Yahoo Finance."""
    try:
        data = get_yf_options(symbol, expiration)
        
        if "expirations" in data and "calls" not in data:
            click.echo(f"Available expiration dates for {symbol}:")
            for date in data["expirations"]:
                click.echo(date)
            return
        
        click.echo(f"Option Chain for {symbol} (Exp: {data['expiration_date']})")
        current_price = data.get("current_price", 0.0)
        click.echo(f"Current Price: {current_price}\n")
        
        click.echo("CALLS (Top 5 near money):")
        calls = data.get("calls", [])
        # Sort by distance to current price
        calls.sort(key=lambda x: abs(float(x.get('strike', 0)) - current_price))
        for c in calls[:5]:
            click.echo(f"Strike: {c.get('strike')} | Bid: {c.get('bid')} | Ask: {c.get('ask')} | Vol: {c.get('volume')}")
            
        click.echo("\nPUTS (Top 5 near money):")
        puts = data.get("puts", [])
        # Sort by distance to current price
        puts.sort(key=lambda x: abs(float(x.get('strike', 0)) - current_price))
        for p in puts[:5]:
            click.echo(f"Strike: {p.get('strike')} | Bid: {p.get('bid')} | Ask: {p.get('ask')} | Vol: {p.get('volume')}")
            
    except Exception as e:
        click.echo(f"Error fetching options: {str(e)}")

@cli.command()
def account() -> None:
    """Get account buying power and cash info."""
    get_session()
    profile = get_account_profile()
    
    click.echo(f"Buying Power: {profile.get('buying_power')}")
    click.echo(f"Cash Available for Withdrawal: {profile.get('cash_available_for_withdrawal')}")
    click.echo(f"Cash Held for Orders: {profile.get('cash_held_for_orders')}")
    click.echo(f"Unsettled Funds: {profile.get('unsettled_funds')}")

if __name__ == "__main__":
    cli()
