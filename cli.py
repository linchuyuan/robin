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
from macro_news import get_macro_news
from yahoo_finance import get_yf_quote, get_yf_news, get_yf_options
from order_history import get_order_history, get_order_detail
from robin_options import get_option_chain
from sentiment import get_fear_and_greed, get_vix


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
    """List current positions with detailed P/L metrics."""
    get_session()
    positions = list_positions()
    if not positions:
        click.echo("No open positions.")
        return
        
    # Header
    click.echo(f"{'Symbol':<6} {'Qty':>8} {'Price':>10} {'Equity':>10} {'Avg Cost':>10} {'Today P/L':>18} {'Total P/L':>18} {'P/E':>8} {'Mkt Cap':>12} {'52W High':>10} {'52W Low':>10}")
    click.echo("-" * 130)
    
    for pos in positions:
        symbol = pos['symbol']
        qty = f"{pos['quantity']:.4f}"
        price = f"{pos['price']:.2f}"
        equity = f"{pos['equity']:.2f}"
        avg_cost = f"{pos['average_buy_price']:.2f}"
        
        # Today's P/L
        day_pl_val = pos['intraday_profit_loss']
        day_pl_pct = pos['intraday_percent_change']
        day_pl = f"{day_pl_val:+.2f} ({day_pl_pct:+.2f}%)"
        
        # Total P/L
        total_pl_val = pos['equity_change']
        total_pl_pct = pos['percent_change']
        total_pl = f"{total_pl_val:+.2f} ({total_pl_pct:+.2f}%)"

        pe_ratio = pos.get('pe_ratio')
        pe_ratio = f"{float(pe_ratio):.2f}" if pe_ratio and pe_ratio != 'N/A' else 'N/A'

        market_cap = pos.get('market_cap')
        if market_cap and market_cap != 'N/A':
            # Format large numbers for market cap
            mc = float(market_cap)
            if mc >= 1e12:
                market_cap = f"{mc/1e12:.2f}T"
            elif mc >= 1e9:
                market_cap = f"{mc/1e9:.2f}B"
            elif mc >= 1e6:
                market_cap = f"{mc/1e6:.2f}M"
            else:
                market_cap = f"{mc:.0f}"
        else:
            market_cap = 'N/A'

        high_52 = pos.get('high_52_weeks')
        high_52 = f"{float(high_52):.2f}" if high_52 and high_52 != 'N/A' else 'N/A'

        low_52 = pos.get('low_52_weeks')
        low_52 = f"{float(low_52):.2f}" if low_52 and low_52 != 'N/A' else 'N/A'
        
        click.echo(f"{symbol:<6} {qty:>8} {price:>10} {equity:>10} {avg_cost:>10} {day_pl:>18} {total_pl:>18} {pe_ratio:>8} {market_cap:>12} {high_52:>10} {low_52:>10}")


@cli.command()
def orders() -> None:
    """List pending orders."""
    get_session()
    open_orders = rh.get_all_open_stock_orders()
    if not open_orders:
        click.echo("No pending orders.")
        return
    for order in open_orders:
        symbol = order.get('symbol') or order.get('instrument_id') or 'N/A'
        click.echo(f"ID: {order['id']} | {order.get('side')} {order.get('quantity')} {symbol} @ {order.get('price', 'market')}")

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

@click.command()
@click.argument("symbol")
@click.option("--expiration", help="Expiration date (YYYY-MM-DD)")
@click.option("--strikes", default=5, help="Number of strikes above/below current price to show.")
def yf_options(symbol: str, expiration: str | None, strikes: int) -> None:
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
        
        click.echo("CALLS:")
        calls = data.get("calls", [])
        
        # Get N strikes below current price (closest first)
        calls_below = sorted(
            [c for c in calls if float(c.get('strike', 0)) < current_price],
            key=lambda x: float(x.get('strike', 0)), 
            reverse=True
        )[:strikes]
        
        # Get N strikes above current price (closest first)
        calls_above = sorted(
            [c for c in calls if float(c.get('strike', 0)) >= current_price],
            key=lambda x: float(x.get('strike', 0))
        )[:strikes]
        
        # Combine and sort by strike for display
        selected_calls = sorted(calls_below + calls_above, key=lambda x: float(x.get('strike', 0)))
        
        for c in selected_calls:
            click.echo(f"Strike: {c.get('strike')} | Bid: {c.get('bid')} | Ask: {c.get('ask')} | Vol: {c.get('volume')}")
            
        click.echo("\nPUTS:")
        puts = data.get("puts", [])
        
        # Get N strikes below current price (closest first)
        puts_below = sorted(
            [p for p in puts if float(p.get('strike', 0)) < current_price],
            key=lambda x: float(x.get('strike', 0)),
            reverse=True
        )[:strikes]
        
        # Get N strikes above current price (closest first)
        puts_above = sorted(
            [p for p in puts if float(p.get('strike', 0)) >= current_price],
            key=lambda x: float(x.get('strike', 0))
        )[:strikes]
        
        # Combine and sort by strike for display
        selected_puts = sorted(puts_below + puts_above, key=lambda x: float(x.get('strike', 0)))
        
        for p in selected_puts:
            click.echo(f"Strike: {p.get('strike')} | Bid: {p.get('bid')} | Ask: {p.get('ask')} | Vol: {p.get('volume')}")
            
    except Exception as e:
        click.echo(f"Error fetching options: {str(e)}")

@cli.command()
@click.argument("symbol")
@click.option("--expiration", help="Expiration date (YYYY-MM-DD)")
@click.option("--strikes", default=5, help="Number of strikes above/below current price to show.")
def options(symbol: str, expiration: str | None, strikes: int) -> None:
    """Fetch option chain data from Robinhood (with Greeks)."""
    get_session()
    try:
        data = get_option_chain(symbol, expiration)
        
        if "expirations" in data and "calls" not in data:
            click.echo(f"Available expiration dates for {symbol}:")
            for date in data["expirations"]:
                click.echo(date)
            return
        
        click.echo(f"Option Chain for {symbol} (Exp: {data['expiration_date']})")
        current_price = data.get("current_price", 0.0)
        click.echo(f"Current Price: {current_price}\n")
        
        def print_option(opt):
            click.echo(f"Strike: {opt['strike']} | Price: {opt['price']} | "
                       f"Delta: {opt['delta']:.3f} | Gamma: {opt['gamma']:.3f} | "
                       f"Theta: {opt['theta']:.3f} | Vega: {opt['vega']:.3f}")

        click.echo("CALLS:")
        calls = data.get("calls", [])
        
        calls_below = sorted(
            [c for c in calls if float(c.get('strike', 0)) < current_price],
            key=lambda x: float(x.get('strike', 0)),
            reverse=True
        )[:strikes]
        
        calls_above = sorted(
            [c for c in calls if float(c.get('strike', 0)) >= current_price],
            key=lambda x: float(x.get('strike', 0))
        )[:strikes]
        
        selected_calls = sorted(calls_below + calls_above, key=lambda x: float(x.get('strike', 0)))
        
        for c in selected_calls:
            print_option(c)
            
        click.echo("\nPUTS:")
        puts = data.get("puts", [])
        
        puts_below = sorted(
            [p for p in puts if float(p.get('strike', 0)) < current_price],
            key=lambda x: float(x.get('strike', 0)),
            reverse=True
        )[:strikes]
        
        puts_above = sorted(
            [p for p in puts if float(p.get('strike', 0)) >= current_price],
            key=lambda x: float(x.get('strike', 0))
        )[:strikes]
        
        selected_puts = sorted(puts_below + puts_above, key=lambda x: float(x.get('strike', 0)))
        
        for p in selected_puts:
            print_option(p)
            
    except Exception as e:
        click.echo(f"Error fetching options: {str(e)}")

@cli.command()
def account() -> None:
    """Get account buying power and cash info."""
    get_session()
    profile = get_account_profile()
    
    click.echo(f"Buying Power: {profile.get('buying_power')}")
    click.echo(f"Total Cash: {profile.get('cash')}")
    click.echo(f"Cash Available for Withdrawal: {profile.get('cash_available_for_withdrawal')}")
    click.echo(f"Cash Held for Orders: {profile.get('cash_held_for_orders')}")
    click.echo(f"Unsettled Funds: {profile.get('unsettled_funds')}")
    click.echo(f"Total Equity: {profile.get('equity')}")
    click.echo(f"Market Value: {profile.get('market_value')}")

@cli.command()
@click.argument("symbol")
def crypto_quote(symbol: str) -> None:
    """Fetch crypto quote."""
    get_session()
    try:
        quote = get_crypto_quote(symbol)
        click.echo(f"Symbol: {quote['symbol']}")
        click.echo(f"Mark Price: {quote['mark_price']}")
        click.echo(f"Bid: {quote['bid_price']}")
        click.echo(f"Ask: {quote['ask_price']}")
        click.echo(f"High: {quote['high_price']}")
        click.echo(f"Low: {quote['low_price']}")
    except Exception as e:
        click.echo(f"Error fetching crypto quote: {str(e)}")

@cli.command()
def crypto_holdings() -> None:
    """List current crypto positions."""
    get_session()
    try:
        positions = get_crypto_positions()
        if not positions:
            click.echo("No crypto positions found.")
            return
        for pos in positions:
            click.echo(f"{pos['symbol']}: {pos['quantity']} (Cost Basis: {pos['cost_basis']})")
    except Exception as e:
        click.echo(f"Error fetching crypto holdings: {str(e)}")

@cli.command()
@click.argument("symbol")
@click.option("--qty", required=True, type=float)
@click.option("--side", type=click.Choice(["buy", "sell"]), required=True)
@click.option("--order-type", type=click.Choice(["market", "limit"]), default="market")
@click.option("--price", type=float)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def crypto_order(symbol: str, qty: float, side: str, order_type: str, price: float | None, yes: bool) -> None:
    """Place a crypto order."""
    get_session()
    
    if order_type == "limit" and price is None:
        raise click.UsageError("Limit orders require --price.")
        
    if not yes:
        click.confirm(f"About to {side} {qty} of {symbol} ({order_type}). Continue?", abort=True)
        
    try:
        result = place_crypto_order(symbol, qty, side, order_type, price)
        click.echo(f"Crypto Order submitted: {result.get('id')}\nDetails: {result}")
    except Exception as e:
        click.echo(f"Error placing crypto order: {str(e)}")

@cli.command()
def history_orders() -> None:
    """Fetch history of all stock orders."""
    get_session()
    try:
        orders = get_order_history()
        if not orders:
            click.echo("No order history found.")
            return
        
        for order in orders[:10]: # Limit to most recent 10
            symbol = order.get('symbol') or order.get('instrument_id') or 'N/A'
            state = order.get('state', 'unknown')
            date = order.get('created_at', 'N/A')
            click.echo(f"ID: {order.get('id')} | {date} | {symbol} | {order.get('side')} {order.get('quantity')} | {state} | Price: {order.get('average_price')}")
    except Exception as e:
        click.echo(f"Error fetching order history: {str(e)}")


@cli.command()
@click.argument("order_id")
def order_detail(order_id: str) -> None:
    """Fetch details of a specific order by UUID."""
    get_session()
    try:
        order = get_order_detail(order_id)
        if not order:
            click.echo(f"Order {order_id} not found.")
            return

        symbol = rh.get_symbol_by_url(order.get('instrument')) or 'N/A'

        click.echo(f"Order ID: {order.get('id')}")
        click.echo(f"Symbol: {symbol}")
        click.echo(f"State: {order.get('state')}")
        click.echo(f"Side: {order.get('side')}")
        click.echo(f"Quantity: {order.get('quantity')}")
        click.echo(f"Price: {order.get('price') or order.get('average_price') or 'Market'}")
        click.echo(f"Type: {order.get('type')}")
        click.echo(f"Created At: {order.get('created_at')}")
        click.echo(f"Updated At: {order.get('updated_at')}")
        click.echo(f"Fees: {order.get('fees')}")
        click.echo(f"Executions: {len(order.get('executions', []))}")
        
    except Exception as e:
        click.echo(f"Error fetching order details: {str(e)}")

@cli.command()
@click.argument("symbol")
def fundamentals(symbol: str) -> None:
    """Fetch fundamental data for a stock."""
    get_session()
    try:
        data = rh.get_fundamentals(symbol)
        if not data or not isinstance(data, list) or len(data) == 0:
            click.echo(f"No fundamentals found for {symbol}.")
            return
        
        f = data[0]
        # Format and display key attributes
        click.echo(f"--- Fundamentals for {f.get('symbol')} ---")
        click.echo(f"Open:           {f.get('open')}")
        click.echo(f"High:           {f.get('high')}")
        click.echo(f"Low:            {f.get('low')}")
        click.echo(f"Market Cap:     {f.get('market_cap')}")
        click.echo(f"P/E Ratio:      {f.get('pe_ratio')}")
        click.echo(f"Div Yield:      {f.get('dividend_yield')}")
        click.echo(f"52 Wk High:     {f.get('high_52_weeks')}")
        click.echo(f"52 Wk Low:      {f.get('low_52_weeks')}")
        click.echo(f"Volume:         {f.get('volume')}")
        click.echo(f"Avg Vol (30d):  {f.get('average_volume_30_days')}")
        click.echo(f"CEO:            {f.get('ceo')}")
        
    except Exception as e:
        click.echo(f"Error fetching fundamentals: {str(e)}")

@cli.command()
def sentiment() -> None:
    """Get market sentiment (Fear & Greed, VIX)."""
    # Fear & Greed
    fg = get_fear_and_greed()
    if "error" in fg:
        click.echo(f"Fear & Greed: Error ({fg['error']})")
    else:
        click.echo("--- Fear & Greed Index ---")
        score = fg.get('score', 0)
        rating = fg.get('rating', 'Unknown').upper()
        click.echo(f"Score:    {score:.0f}/100")
        click.echo(f"Rating:   {rating}")
        click.echo(f"Previous: {fg.get('previous_close', 0):.0f}")
    
    click.echo("")
    
    # VIX
    vix = get_vix()
    if "error" in vix:
        click.echo(f"VIX: Error ({vix['error']})")
    else:
        click.echo("--- VIX (Volatility) ---")
        price = vix.get('price')
        change = vix.get('change', 0)
        pct = vix.get('percent_change', 0)
        
        # Colorize if possible (not using colors here to keep it simple)
        click.echo(f"Price:    {price}")
        click.echo(f"Change:   {change:+.2f} ({pct:+.2f}%)")
        click.echo(f"Range:    {vix.get('day_low')} - {vix.get('day_high')}")

@cli.command()
@click.option('--limit', default=5, help='Number of news items to fetch')
def macro(limit: int) -> None:
    """Get latest macroeconomic news headlines."""
    news_items = get_macro_news(limit)
    if not news_items:
        click.echo("No macro news found.")
        return
        
    if "error" in news_items[0]:
        click.echo(f"Error fetching news: {news_items[0]['error']}")
        return
        
    click.echo("--- Macroeconomic News (Source: CNBC) ---")
    for item in news_items:
        click.echo(f"- {item['title']}")
        click.echo(f"  {item['published']}")
        click.echo(f"  {item['link']}\n")

if __name__ == "__main__":
    cli()
