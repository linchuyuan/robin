"""Command-line entrypoints for Robinhood CLI."""

from __future__ import annotations

import click
import robin_stocks.robinhood as rh

from auth import get_session, logout
from orders import OrderValidationError, place_order
from portfolio import get_quote, list_positions


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
@click.argument("order_id")
def cancel(order_id: str) -> None:
    get_session()
    rh.cancel_stock_order(order_id)
    click.echo(f"Cancellation requested for {order_id}.")


if __name__ == "__main__":
    cli()
