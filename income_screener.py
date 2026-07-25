"""
Daily/every-few-days options income screener. Two adaptable modes from one
watchlist pull, ~45 DTE (35-55 window):

SELL mode (IVR > IVR_MIN): builds call/put credit verticals and iron
condors around a target-delta short strike and screens for:
  - R:R <= MAX_RR                (max_loss <= MAX_RR * max_profit)
  - POP >= breakeven_win_rate + MIN_MARGIN   (via Black-Scholes N(d2)
    on each leg's live IV, not a flat delta-proxy)
  - leg liquidity floor (min OI, max bid/ask spread as % of mid)

BUY mode (IVR < LOW_IVR_MAX and IV30/HV30 <= CHEAP_VOL_RATIO_MAX): flags
symbols where options are priced cheap relative to the stock's own
realized volatility -- a real, measurable edge for buying premium rather
than selling it. Reports the ATM call and ATM put (both already
defined-risk: max loss = premium paid). Direction is NOT inferred here;
pick your own side based on your thesis.

POP/breakeven math is the same approach validated on the SPX screen.
Commission is NOT included per-candidate here (that requires a live
dry-run order per trade); for the final trade(s) you pick, run a
dry-run via Account.place_order(..., dry_run=True) to get exact fees
before entering.

CAVEAT: this script cannot see forward earnings dates reliably from
the Tastytrade metrics API (only past earnings are exposed). Manually
confirm no earnings release falls before your chosen expiration.

Usage: python income_screener.py
"""
import os
import asyncio
import math
from datetime import datetime, timezone
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_option_chain
from tastytrade.dxfeed import Greeks, Quote, Summary
from tastytrade.watchlists import PublicWatchlist
from tastytrade.metrics import get_market_metrics

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

# ---- config ----
WATCHLIST_NAME = "High Options Volume"
IVR_MIN = 0.50
LIQUIDITY_MIN = 3
DTE_MIN, DTE_MAX = 35, 55   # ~45 DTE monthly cycle: more premium, more strikes to work with
STRIKE_BAND = 0.30          # +/- around spot when pulling strikes to stream (wider: 45 DTE moves more)
DELTA_MIN, DELTA_MAX = 0.05, 0.35   # short-strike delta band, both sides
WIDTH_STEPS = range(1, 9)  # 1..8 strike increments wide (45 DTE structures run wider)
MIN_OI = 25          # further-dated OI is structurally thinner than near-week OI
MAX_SPREAD_PCT = 0.20
MAX_RR = 2.0
MIN_MARGIN = 0.05          # POP must clear breakeven win rate by >= 5pts
R_RATE = 0.043
MAX_SYMBOLS_STREAMED = 120   # safety cap on universe size per run

# ---- low-IV / long-premium (buy) mode ----
# When IV is cheap relative to the stock's own realized movement, selling
# premium has no edge -- buying it does. This is a real, measurable signal
# (IV vs HV), not a guessed technical indicator. Direction (call vs put) is
# NOT inferred here -- pick your own side; the edge is "options are cheap,"
# not "the stock goes up."
LOW_IVR_MAX = 0.30
CHEAP_VOL_RATIO_MAX = 0.85   # IV30 / HV30 <= this -> options priced cheap vs realized move
MAX_CHEAP_VOL_SYMBOLS = 15
LEVERAGED_DENYLIST = {
    "SOXL", "SOXS", "TQQQ", "SQQQ", "UVXY", "SVXY", "TZA", "TNA", "SPXU",
    "UPRO", "SDOW", "UDOW", "LABU", "LABD", "YINN", "YANG", "FAS", "FAZ",
    "NUGT", "DUST", "JNUG", "JDST", "BOIL", "KOLD", "TMF", "TMV", "GDXU",
    "GDXD", "FNGU", "FNGD",
}


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def pop_above(spot, breakeven, iv, T):
    if iv is None or iv <= 0 or T <= 0:
        return None
    d2 = (math.log(spot / breakeven) + (R_RATE - 0.5 * iv * iv) * T) / (iv * math.sqrt(T))
    return norm_cdf(d2)


def pop_below(spot, breakeven, iv, T):
    p = pop_above(spot, breakeven, iv, T)
    return None if p is None else 1 - p


def mid(v):
    if v.get("bid") is None or v.get("ask") is None:
        return None
    return (v["bid"] + v["ask"]) / 2


async def build_universe():
    """Returns (sell_candidates, buy_candidates) -- high-IVR names for credit
    spreads/condors, and low-IVR-but-cheap-vs-realized names for long premium."""
    wl = await PublicWatchlist.get(session, WATCHLIST_NAME)
    symbols = [e["symbol"] for e in wl.watchlist_entries
               if e.get("instrument-type") == "Equity" and e["symbol"] not in LEVERAGED_DENYLIST]
    metrics = await get_market_metrics(session, symbols)

    sell_cand, buy_cand = [], []
    for m in metrics:
        if m.liquidity_rating is None or m.liquidity_rating < LIQUIDITY_MIN:
            continue
        ivr = float(m.implied_volatility_index_rank) if m.implied_volatility_index_rank is not None else None
        iv30 = float(m.implied_volatility_30_day) if m.implied_volatility_30_day is not None else None
        hv30 = float(m.historical_volatility_30_day) if m.historical_volatility_30_day is not None else None
        if ivr is None or iv30 is None:
            continue

        if ivr > IVR_MIN:
            sell_cand.append((m.symbol, ivr))
        elif ivr < LOW_IVR_MAX and hv30 and hv30 > 0:
            ratio = iv30 / hv30
            if ratio <= CHEAP_VOL_RATIO_MAX:
                buy_cand.append((m.symbol, ivr, iv30, hv30, ratio))

    sell_cand.sort(key=lambda t: -t[1])
    buy_cand.sort(key=lambda t: t[4])  # cheapest iv/hv ratio first
    return ([s for s, _ in sell_cand[:MAX_SYMBOLS_STREAMED]],
            buy_cand[:MAX_CHEAP_VOL_SYMBOLS])


async def fetch_chains(symbols):
    now = datetime.now(timezone.utc)
    out = {}
    sem = asyncio.Semaphore(10)

    async def one(sym):
        async with sem:
            try:
                chain = await get_option_chain(session, sym)
            except Exception:
                return
            exps = sorted(chain.keys())
            target_dte = (DTE_MIN + DTE_MAX) / 2
            in_window = [e for e in exps if DTE_MIN <= (e - now.date()).days <= DTE_MAX]
            if in_window:
                # closest to the middle of the window, not just the first hit --
                # OI concentrates on standard monthlies, which may not be the
                # earliest expiration inside the window.
                target = min(in_window, key=lambda e: abs((e - now.date()).days - target_dte))
            else:
                target = None
                for e in exps:
                    if (e - now.date()).days >= DTE_MIN:
                        target = e
                        break
            if target is None:
                return
            out[sym] = {
                "expiration": str(target),
                "dte": (target - now.date()).days,
                "options": [
                    {"symbol": o.symbol, "streamer_symbol": o.streamer_symbol,
                     "strike": float(o.strike_price), "type": str(o.option_type),
                     "expires_at": o.expires_at.isoformat() if o.expires_at else None}
                    for o in chain[target]
                ],
            }

    await asyncio.gather(*(one(s) for s in symbols))
    return out


async def stream_market(symbols_info):
    spot = {}
    async with DXLinkStreamer(session) as streamer:
        underlyings = list(symbols_info.keys())
        for i in range(0, len(underlyings), 50):
            await streamer.subscribe(Quote, underlyings[i:i + 50])
            await asyncio.sleep(0.4)
        try:
            async with asyncio.timeout(20):
                async for x in streamer.listen(Quote):
                    if x.event_symbol in symbols_info and x.bid_price and x.ask_price:
                        spot[x.event_symbol] = (float(x.bid_price) + float(x.ask_price)) / 2
                    if len(spot) >= len(symbols_info):
                        break
        except asyncio.TimeoutError:
            pass

    market = {}
    opt_symbols = []
    for sym, info in symbols_info.items():
        sp = spot.get(sym)
        if not sp:
            continue
        lo, hi = sp * (1 - STRIKE_BAND), sp * (1 + STRIKE_BAND)
        for o in info["options"]:
            if lo <= o["strike"] <= hi:
                market[o["streamer_symbol"]] = {
                    "underlying": sym, "symbol": o["symbol"], "strike": o["strike"],
                    "type": o["type"], "expiration": info["expiration"],
                    "expires_at": o["expires_at"], "spot": sp,
                }
                opt_symbols.append(o["streamer_symbol"])

    await asyncio.sleep(1.0)
    async with DXLinkStreamer(session) as streamer:
        BATCH = 50
        for i in range(0, len(opt_symbols), BATCH):
            chunk = opt_symbols[i:i + BATCH]
            await streamer.subscribe(Quote, chunk)
            await asyncio.sleep(0.4)
            await streamer.subscribe(Greeks, chunk)
            await asyncio.sleep(0.4)
            await streamer.subscribe(Summary, chunk)
            await asyncio.sleep(0.4)

        async def q():
            async for x in streamer.listen(Quote):
                if x.event_symbol in market:
                    if x.bid_price is not None:
                        market[x.event_symbol]["bid"] = float(x.bid_price)
                    if x.ask_price is not None:
                        market[x.event_symbol]["ask"] = float(x.ask_price)

        async def g():
            async for x in streamer.listen(Greeks):
                if x.event_symbol in market:
                    market[x.event_symbol]["delta"] = float(x.delta) if x.delta is not None else None
                    market[x.event_symbol]["iv"] = float(x.volatility) if x.volatility is not None else None

        async def s():
            async for x in streamer.listen(Summary):
                if x.event_symbol in market:
                    market[x.event_symbol]["oi"] = x.open_interest

        try:
            async with asyncio.timeout(60):
                await asyncio.gather(q(), g(), s())
        except asyncio.TimeoutError:
            pass

    return spot, market


def screen(market, spot_map, only_symbols=None):
    now = datetime.now(timezone.utc)
    by_symbol = {}
    for v in market.values():
        if only_symbols is not None and v["underlying"] not in only_symbols:
            continue
        by_symbol.setdefault(v["underlying"], []).append(v)

    def liquid(leg):
        if leg is None or leg.get("oi") is None or leg["oi"] < MIN_OI:
            return False
        m = mid(leg)
        if m is None or m <= 0 or leg.get("bid") is None or leg.get("ask") is None:
            return False
        return (leg["ask"] - leg["bid"]) <= max(MAX_SPREAD_PCT * m, 0.05)

    results = []
    for sym, legs in by_symbol.items():
        spot = spot_map[sym]
        exp_dt = datetime.fromisoformat(legs[0]["expires_at"])
        T = max((exp_dt - now).total_seconds(), 60) / (365 * 24 * 3600)

        call_strikes = {l["strike"]: l for l in legs if l["type"] == "C"}
        put_strikes = {l["strike"]: l for l in legs if l["type"] == "P"}
        all_call_k = sorted(call_strikes.keys())
        step = None
        if len(all_call_k) > 1:
            diffs = sorted(set(round(b - a, 2) for a, b in zip(all_call_k, all_call_k[1:])))
            step = diffs[0] if diffs else None
        if not step:
            continue

        otm_calls = [l for l in legs if l["type"] == "C" and l["strike"] > spot
                     and l.get("delta") is not None and DELTA_MIN <= l["delta"] <= DELTA_MAX]
        otm_puts = [l for l in legs if l["type"] == "P" and l["strike"] < spot
                    and l.get("delta") is not None and -DELTA_MAX <= l["delta"] <= -DELTA_MIN]

        sym_results = []
        for sc in otm_calls:
            if not liquid(sc):
                continue
            for w in WIDTH_STEPS:
                lc = call_strikes.get(round(sc["strike"] + w * step, 2))
                if not liquid(lc):
                    continue
                width_pts = lc["strike"] - sc["strike"]
                credit = mid(sc) - mid(lc)
                if credit <= 0:
                    continue
                max_profit, max_loss = credit * 100, (width_pts - credit) * 100
                if max_loss <= 0:
                    continue
                be = sc["strike"] + credit
                pop = pop_below(spot, be, sc.get("iv"), T)
                if pop is None:
                    continue
                sym_results.append({
                    "symbol": sym, "structure": "call credit vertical", "expiration": legs[0]["expiration"],
                    "dte": round(T * 365, 1), "short_strike": sc["strike"], "long_strike": lc["strike"],
                    "width_pts": width_pts, "credit": credit, "max_profit": max_profit, "max_loss": max_loss,
                    "breakeven": be, "pop": pop, "short_oi": sc["oi"], "long_oi": lc["oi"],
                    "legs": [("SELL", sc["symbol"]), ("BUY", lc["symbol"])],
                })

        for sp_ in otm_puts:
            if not liquid(sp_):
                continue
            for w in WIDTH_STEPS:
                lp = put_strikes.get(round(sp_["strike"] - w * step, 2))
                if not liquid(lp):
                    continue
                width_pts = sp_["strike"] - lp["strike"]
                credit = mid(sp_) - mid(lp)
                if credit <= 0:
                    continue
                max_profit, max_loss = credit * 100, (width_pts - credit) * 100
                if max_loss <= 0:
                    continue
                be = sp_["strike"] - credit
                pop = pop_above(spot, be, sp_.get("iv"), T)
                if pop is None:
                    continue
                sym_results.append({
                    "symbol": sym, "structure": "put credit vertical", "expiration": legs[0]["expiration"],
                    "dte": round(T * 365, 1), "short_strike": sp_["strike"], "long_strike": lp["strike"],
                    "width_pts": width_pts, "credit": credit, "max_profit": max_profit, "max_loss": max_loss,
                    "breakeven": be, "pop": pop, "short_oi": sp_["oi"], "long_oi": lp["oi"],
                    "legs": [("SELL", sp_["symbol"]), ("BUY", lp["symbol"])],
                })

        calls_by_w = {}
        puts_by_w = {}
        for r in sym_results:
            tgt = calls_by_w if r["structure"] == "call credit vertical" else puts_by_w
            tgt.setdefault(r["width_pts"], []).append(r)

        for w, clist in calls_by_w.items():
            for c in clist:
                sc_leg = call_strikes[c["short_strike"]]
                for p in puts_by_w.get(w, []):
                    sp_leg = put_strikes[p["short_strike"]]
                    credit = c["credit"] + p["credit"]
                    max_profit, max_loss = credit * 100, (w - credit) * 100
                    if max_loss <= 0:
                        continue
                    p_call_breach = 1 - pop_below(spot, c["breakeven"], sc_leg.get("iv"), T)
                    p_put_breach = 1 - pop_above(spot, p["breakeven"], sp_leg.get("iv"), T)
                    pop = 1 - p_call_breach - p_put_breach
                    sym_results.append({
                        "symbol": sym, "structure": "iron condor", "expiration": legs[0]["expiration"],
                        "dte": round(T * 365, 1),
                        "short_strike": f"{p['short_strike']}/{c['short_strike']}",
                        "long_strike": f"{p['long_strike']}/{c['long_strike']}",
                        "width_pts": w, "credit": credit, "max_profit": max_profit, "max_loss": max_loss,
                        "breakeven": f"{p['breakeven']:.2f}/{c['breakeven']:.2f}", "pop": pop,
                        "short_oi": min(c["short_oi"], p["short_oi"]), "long_oi": min(c["long_oi"], p["long_oi"]),
                        "legs": p["legs"] + c["legs"],
                    })

        results.extend(sym_results)

    passing, near_miss_traps = [], []
    for r in results:
        mp, ml = r["max_profit"], r["max_loss"]
        if mp <= 0 or ml <= 0 or r["pop"] is None:
            continue
        rr = ml / mp
        be_wr = ml / (ml + mp)
        margin = r["pop"] - be_wr
        r["rr"], r["be_wr"], r["margin"] = rr, be_wr, margin
        if rr <= MAX_RR and margin >= MIN_MARGIN:
            passing.append(r)
        elif rr > MAX_RR and margin >= MIN_MARGIN:
            near_miss_traps.append(r)  # good margin, bad R:R -- the trap pattern

    passing.sort(key=lambda r: -r["margin"])
    near_miss_traps.sort(key=lambda r: -r["margin"])
    return passing, near_miss_traps, len(results)


def build_long_premium_ideas(market, spot_map, buy_meta):
    """For cheap-vol symbols, find the ATM call and ATM put at the target
    expiration. Long options are already defined-risk (max loss = premium
    paid) -- no second leg needed. Direction is left to the user."""
    now = datetime.now(timezone.utc)
    meta_by_symbol = {sym: (ivr, iv30, hv30, ratio) for sym, ivr, iv30, hv30, ratio in buy_meta}
    by_symbol = {}
    for v in market.values():
        if v["underlying"] in meta_by_symbol:
            by_symbol.setdefault(v["underlying"], []).append(v)

    def liquid(leg):
        if leg is None or leg.get("oi") is None or leg["oi"] < MIN_OI:
            return False
        m = mid(leg)
        if m is None or m <= 0 or leg.get("bid") is None or leg.get("ask") is None:
            return False
        return (leg["ask"] - leg["bid"]) <= max(MAX_SPREAD_PCT * m, 0.05)

    ideas = []
    for sym, legs in by_symbol.items():
        spot = spot_map[sym]
        exp_dt = datetime.fromisoformat(legs[0]["expires_at"])
        T = max((exp_dt - now).total_seconds(), 60) / (365 * 24 * 3600)
        calls = [l for l in legs if l["type"] == "C"]
        puts = [l for l in legs if l["type"] == "P"]
        if not calls or not puts:
            continue
        atm_call = min(calls, key=lambda l: abs(l["strike"] - spot))
        atm_put = min(puts, key=lambda l: abs(l["strike"] - spot))
        ivr, iv30, hv30, ratio = meta_by_symbol[sym]
        entry = {
            "symbol": sym, "spot": spot, "expiration": legs[0]["expiration"],
            "dte": round(T * 365, 1), "ivr": ivr, "iv30": iv30, "hv30": hv30, "iv_hv_ratio": ratio,
        }
        if liquid(atm_call):
            c_mid = mid(atm_call)
            entry["call"] = {"strike": atm_call["strike"], "cost": c_mid,
                              "breakeven": atm_call["strike"] + c_mid,
                              "max_loss": c_mid * 100, "oi": atm_call["oi"]}
        if liquid(atm_put):
            p_mid = mid(atm_put)
            entry["put"] = {"strike": atm_put["strike"], "cost": p_mid,
                             "breakeven": atm_put["strike"] - p_mid,
                             "max_loss": p_mid * 100, "oi": atm_put["oi"]}
        if "call" in entry or "put" in entry:
            ideas.append(entry)

    ideas.sort(key=lambda e: e["iv_hv_ratio"])
    return ideas


def fmt(r):
    return (f"{r['symbol']:6s} [{r['structure']:20s}] exp={r['expiration']} ({r['dte']}DTE) "
            f"short={r['short_strike']} long={r['long_strike']} w={r['width_pts']:.1f} "
            f"credit={r['credit']:.2f} maxP=${r['max_profit']:.0f} maxL=${r['max_loss']:.0f} "
            f"RR={r['rr']:.2f} BE_WR={r['be_wr']*100:.1f}% POP={r['pop']*100:.1f}% "
            f"margin={r['margin']*100:.1f}pt  OI(s/l)={r['short_oi']}/{r['long_oi']}")


async def main():
    print(f"=== Income screener run @ {datetime.now(timezone.utc).isoformat()} ===")
    print(f"Sell universe: '{WATCHLIST_NAME}' watchlist, IVR>{IVR_MIN*100:.0f}, liquidity>={LIQUIDITY_MIN}")
    print(f"Buy universe:  same watchlist, IVR<{LOW_IVR_MAX*100:.0f} AND IV30/HV30<={CHEAP_VOL_RATIO_MAX}")
    print("(leveraged/inverse ETFs excluded from both)\n")

    sell_symbols, buy_meta = await build_universe()
    buy_symbols = [t[0] for t in buy_meta]
    print(f"Sell-side candidates: {len(sell_symbols)} (capped at {MAX_SYMBOLS_STREAMED})")
    print(f"Buy-side (cheap-vol) candidates: {len(buy_symbols)} (capped at {MAX_CHEAP_VOL_SYMBOLS})\n")

    all_symbols = sell_symbols + buy_symbols
    chains = await fetch_chains(all_symbols)
    print(f"Chains fetched: {len(chains)}/{len(all_symbols)}\n")

    spot, market = await stream_market(chains)
    print(f"Spot quotes: {len(spot)}   Option legs streamed: {len(market)}\n")

    passing, traps, total = screen(market, spot, only_symbols=set(sell_symbols))
    print(f"[SELL] Total spread/condor combinations evaluated: {total}")
    print(f"[SELL] Passing (R:R<={MAX_RR}:1 AND POP-breakeven>={MIN_MARGIN*100:.0f}pt): {len(passing)}\n")

    print("=" * 100)
    print("SELL-SIDE: PASSING CREDIT SPREAD / CONDOR CANDIDATES")
    print("=" * 100)
    if not passing:
        print("None today. Do not force a trade -- wait for the next run.")
    for r in passing:
        print(fmt(r))

    print()
    print("=" * 100)
    print("REJECTED -- high POP but R:R worse than 2:1 (the trap pattern)")
    print("=" * 100)
    for r in traps[:10]:
        print(fmt(r))

    ideas = build_long_premium_ideas(market, spot, buy_meta)
    print()
    print("=" * 100)
    print("BUY-SIDE: CHEAP-VOL LONG PREMIUM CANDIDATES (directional -- pick your own side)")
    print("=" * 100)
    print("Edge here is 'IV is cheap vs this stock's own realized move,' NOT a directional call.")
    print("Max loss on any long option = premium paid (already defined-risk, no second leg needed).\n")
    if not ideas:
        print("None today.")
    for e in ideas:
        print(f"{e['symbol']:6s} spot={e['spot']:.2f}  exp={e['expiration']} ({e['dte']}DTE)  "
              f"IVR={e['ivr']*100:.1f}  IV30={e['iv30']:.1f}  HV30={e['hv30']:.1f}  "
              f"IV/HV={e['iv_hv_ratio']:.2f}")
        if "call" in e:
            c = e["call"]
            print(f"       CALL strike={c['strike']:.1f}  cost=${c['cost']:.2f} (max loss ${c['max_loss']:.0f})  "
                  f"breakeven={c['breakeven']:.2f}  OI={c['oi']}")
        if "put" in e:
            p = e["put"]
            print(f"       PUT  strike={p['strike']:.1f}  cost=${p['cost']:.2f} (max loss ${p['max_loss']:.0f})  "
                  f"breakeven={p['breakeven']:.2f}  OI={p['oi']}")

    print("\nReminder: verify no earnings release falls before expiration for any candidate")
    print("(this script cannot see forward earnings dates). Run a dry-run order for exact")
    print("commission before entering: Account.place_order(session, order, dry_run=True).")


if __name__ == "__main__":
    asyncio.run(main())
