import os
import sys
import time
import argparse
import asyncio
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain, get_option_chain, Future
from tastytrade.dxfeed import Greeks, Summary, Quote, Trade
from futures_gex_engine import FuturesGEXCalculator, VolumeIVTracker, PRODUCT_SPECS
from gex_database import init_db, save_snapshot, save_strike_volume_detail, count_snapshots
from instruments_config import GEX_PRODUCTS

load_dotenv()
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

# ================= CONFIGURABLE =================
PRODUCTS = GEX_PRODUCTS     # the 8 tracked instruments (instruments_config.FUTURES + COUNTERPARTS)
COLLECT_SECONDS = 15        # per-product options-chain listen window -- this is what gives
                             # each product's Greeks/OI aggregation its precision; speed comes
                             # from overlapping products, not shortening any single one of them
NUM_EXPIRATIONS = 4         # aggregate the 4 nearest expirations (SpotGamma-style)
SWEEP_CONCURRENCY = 12      # products collected in parallel per batch. Each opens its own
                             # independent websocket (see DXLinkStreamer). Verified empirically:
                             # 5/8/12 all clean, 20 threw "unhandled errors in a TaskGroup" on 2
                             # products -- the API has a real concurrent-connection ceiling
                             # somewhere between 12 and 20. All 8 tracked products fit in one
                             # batch under this ceiling.

# Scheduled sweeps run only inside this Mon-Fri window, in Chicago local time (DST-aware --
# never a hardcoded UTC offset). The actual cadence (every 10 min) lives in the systemd timer
# (gex-collector.timer) that invokes this script; this check is the belt-and-suspenders
# guard so an out-of-window invocation (manual misfire, clock drift, stale timer) is a no-op
# instead of a live pull.
CT = ZoneInfo("America/Chicago")
WINDOW_OPEN = dtime(7, 30)
WINDOW_CLOSE = dtime(16, 0)
# =================================================


def is_in_window():
    now_ct = datetime.now(CT)
    if now_ct.weekday() >= 5:  # Sat/Sun
        return False
    return WINDOW_OPEN <= now_ct.time() <= WINDOW_CLOSE


def is_equity(product):
    return PRODUCT_SPECS.get(product, {}).get("equity", False)


async def run_batch(items, collector_fn):
    """Collect `items` in bounded-concurrency batches -- each item still gets
    its own full collection window (COLLECT_SECONDS), so per-item precision
    is unchanged. Speed comes from SWEEP_CONCURRENCY items running at once
    instead of strictly serial."""
    ok = 0
    for i in range(0, len(items), SWEEP_CONCURRENCY):
        chunk = items[i:i + SWEEP_CONCURRENCY]
        results = await asyncio.gather(*(collector_fn(x) for x in chunk))
        for status in results:
            print(status, flush=True)
            if " OK " in status:
                ok += 1
    return ok


async def collect_one(product):
    try:
        # expiration_of maps each option's streamer_symbol back to which
        # expiration it belongs to -- FuturesGEXCalculator throws this away
        # (it blends all fetched expirations into one row per strike), but
        # the GEX Profile page's per-expiration volume/IV storage needs it.
        expiration_of = {}
        if is_equity(product):
            chain = await get_option_chain(session, product)
            if not chain:
                return f"  {product:6s} SKIP (no chain)"
            exps = sorted(chain.keys())[:NUM_EXPIRATIONS]
            options = []
            for e in exps:
                for o in chain[e]:
                    options.append(o)
                    expiration_of[o.streamer_symbol] = str(e)
            # SPX has no reliable direct quote (wide/stale) -- SPY*10 is the proven proxy.
            # QQQ/USO/GLD stream their own quote directly.
            spot_symbol = "SPY" if product == "SPX" else product
            spot_mult = 10.0 if product == "SPX" else 1.0
        else:
            chain = await get_future_option_chain(session, product)
            if not chain:
                return f"  {product:6s} SKIP (no chain)"
            exps = sorted(chain.keys())[:NUM_EXPIRATIONS]
            options = []
            for e in exps:
                for o in chain[e]:
                    options.append(o)
                    expiration_of[o.streamer_symbol] = str(e)
            underlying = options[0].underlying_symbol
            fut = await Future.get(session, underlying)
            spot_symbol = fut.streamer_symbol
            spot_mult = 1.0

        if not options:
            return f"  {product:6s} SKIP (no options)"

        # nearest fetched expiration -- used both as the snapshot's reference
        # expiration (unchanged, pre-existing behavior) and to scope the
        # separate 0DTE-only engine below. Not always literally "today"
        # (weekends/holidays/no same-day listing), hence the name uses
        # "nearest" internally and only the DB column is called dte_expiration.
        nearest_exp_str = str(exps[0])

        opt_symbols = [o.streamer_symbol for o in options]
        engine = FuturesGEXCalculator(product)
        # Second engine, fed only the nearest expiration's gamma/OI (filtered
        # below via expiration_of) -- `engine` above blends all 4 fetched
        # expirations into one wall/flip reading; dealer hedging concentrated
        # in today's chain can sit at a different level than that blend.
        # Reuses FuturesGEXCalculator completely unmodified -- zero risk to
        # the validated blended math, same pattern as VolumeIVTracker.
        engine_0dte = FuturesGEXCalculator(product)
        vol_tracker = VolumeIVTracker()

        async with DXLinkStreamer(session) as streamer:
            await streamer.subscribe(Quote, [spot_symbol])

            # Get an initial spot fix before deciding Trade's subscription
            # scope. Greeks/Summary need the FULL chain (wall/gamma-flip
            # math depends on every strike), but Trade (day_volume) is only
            # ever needed for strikes within VolumeIVTracker.STRIKE_BAND --
            # that's the only band get_rows() persists anyway. Subscribing
            # Trade for the full chain too on a huge chain (SPX runs
            # 3,600+ contracts across 4 expirations) trips dxfeed's
            # subscription-rate limit ("Your subscription rate is too
            # high") -- confirmed live, reproducible, independent of batch
            # size (tried both BATCH=100 and 300, same error either way,
            # so it's a total-symbols-per-second limit, not a message-size
            # one). Pre-filtering keeps Trade's footprint bounded regardless
            # of how large a product's chain is.
            spot = 0.0
            try:
                async with asyncio.timeout(6):
                    async for x in streamer.listen(Quote):
                        if x.bid_price and x.ask_price:
                            spot = ((float(x.bid_price) + float(x.ask_price)) / 2) * spot_mult
                            break
            except asyncio.TimeoutError:
                pass
            engine.update_spot_price(spot)
            engine_0dte.update_spot_price(spot)
            vol_tracker.update_spot_price(spot)

            if spot > 0:
                band = VolumeIVTracker.STRIKE_BAND
                band_lo, band_hi = spot * (1 - band), spot * (1 + band)
                trade_symbols = [o.streamer_symbol for o in options
                                  if band_lo <= float(o.strike_price) <= band_hi]
            else:
                trade_symbols = opt_symbols  # no spot yet -- don't skip volume entirely

            # subscribe in batches to stay under the streamer frame-size limit
            BATCH = 100
            for i in range(0, len(opt_symbols), BATCH):
                chunk = opt_symbols[i:i+BATCH]
                await streamer.subscribe(Greeks, chunk)
                await streamer.subscribe(Summary, chunk)
            for i in range(0, len(trade_symbols), BATCH):
                await streamer.subscribe(Trade, trade_symbols[i:i+BATCH])

            async def q():
                nonlocal spot
                async for x in streamer.listen(Quote):
                    if x.bid_price and x.ask_price:
                        spot = ((float(x.bid_price) + float(x.ask_price)) / 2) * spot_mult
                        engine.update_spot_price(spot)
                        engine_0dte.update_spot_price(spot)
                        vol_tracker.update_spot_price(spot)
            async def g():
                async for x in streamer.listen(Greeks):
                    engine.update_gamma(x.event_symbol, x.gamma)
                    exp = expiration_of.get(x.event_symbol)
                    if exp == nearest_exp_str:
                        engine_0dte.update_gamma(x.event_symbol, x.gamma)
                    if exp is not None:
                        vol_tracker.update_iv(x.event_symbol, exp, x.volatility)
            async def s():
                async for x in streamer.listen(Summary):
                    engine.update_open_interest(x.event_symbol, x.open_interest)
                    if expiration_of.get(x.event_symbol) == nearest_exp_str:
                        engine_0dte.update_open_interest(x.event_symbol, x.open_interest)
            async def t():
                async for x in streamer.listen(Trade):
                    exp = expiration_of.get(x.event_symbol)
                    if exp is not None:
                        vol_tracker.update_volume(x.event_symbol, exp, x.day_volume)

            try:
                async with asyncio.timeout(COLLECT_SECONDS):
                    await asyncio.gather(q(), g(), s(), t())
            except asyncio.TimeoutError:
                pass

        levels = engine.get_levels()
        strikes = engine.get_gex_by_strike()
        if levels["num_strikes"] == 0 or spot == 0:
            return f"  {product:6s} SKIP (no live data)"

        levels_0dte = engine_0dte.get_levels()
        has_0dte = levels_0dte["num_strikes"] > 0

        # store the nearest expiration label for reference
        sid = save_snapshot(product, exps[0], spot, levels, strikes,
                             levels_0dte=levels_0dte if has_0dte else None,
                             dte_expiration=nearest_exp_str if has_0dte else None)
        save_strike_volume_detail(sid, vol_tracker.get_rows())
        flip = f"{levels['gamma_flip']:.1f}" if levels['gamma_flip'] else "n/a"
        flip0 = f"{levels_0dte['gamma_flip']:.1f}" if has_0dte and levels_0dte['gamma_flip'] else "n/a"
        return (f"  {product:6s} OK  #{sid}  spot={spot:.2f}  "
                f"CW={levels['call_wall']} PW={levels['put_wall']} flip={flip}  "
                f"0dte_flip={flip0}  [{len(exps)}exp]")
    except Exception as e:
        return f"  {product:6s} ERROR: {str(e)[:55]}"


async def run_sweep():
    """Scheduled path -- invoked every 10 min by gex-collector.timer. No-ops
    immediately outside the Mon-Fri 07:30-16:00 America/Chicago window."""
    init_db()
    stamp = datetime.now(CT).strftime("%H:%M:%S %Z")
    if not is_in_window():
        print(f"[{stamp}] outside scheduled window (Mon-Fri {WINDOW_OPEN}-{WINDOW_CLOSE} "
              f"America/Chicago) -- exiting without pulling.", flush=True)
        return
    print(f"[{stamp}] sweep start -- {len(PRODUCTS)} products", flush=True)
    t0 = time.monotonic()
    ok = await run_batch(PRODUCTS, collect_one)
    print(f"----- sweep: {ok}/{len(PRODUCTS)} saved in {time.monotonic()-t0:.0f}s -----", flush=True)


async def run_pull(symbols):
    """Manual pull path -- used by the dashboard's Refresh / per-card Pull
    buttons (subprocess call). Deliberately bypasses the window check: manual
    pulls are the one allowed exception to the scheduled window."""
    init_db()
    stamp = datetime.now(CT).strftime("%H:%M:%S %Z")
    print(f"[{stamp}] manual pull requested for {', '.join(symbols)} "
          f"(window check bypassed)", flush=True)
    t0 = time.monotonic()
    ok = await run_batch(symbols, collect_one)
    print(f"----- pull: {ok}/{len(symbols)} saved in {time.monotonic()-t0:.0f}s -----", flush=True)


def main():
    parser = argparse.ArgumentParser(description="GexFlows collector -- 8-instrument GEX sweep.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sweep", action="store_true",
                        help="Scheduled sweep of all products, gated by the Chicago window "
                             "(default mode -- this is what the systemd timer invokes).")
    group.add_argument("--pull", metavar="SYMBOL",
                        help="One-off pull for a single instrument, bypassing the window check.")
    group.add_argument("--pull-all", action="store_true",
                        help="One-off pull for all 8 instruments, bypassing the window check.")
    args = parser.parse_args()

    if args.pull:
        if args.pull not in PRODUCTS:
            print(f"'{args.pull}' is not one of the tracked instruments: {PRODUCTS}", flush=True)
            sys.exit(1)
        asyncio.run(run_pull([args.pull]))
    elif args.pull_all:
        asyncio.run(run_pull(PRODUCTS))
    else:
        asyncio.run(run_sweep())


if __name__ == "__main__":
    # Without this guard, merely *importing* this module (e.g. the dashboard
    # reusing collect_one) launched a live pull as an import side effect --
    # found while testing Part 1.
    main()
