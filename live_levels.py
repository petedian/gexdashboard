import os
import asyncio
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain, Future
from tastytrade.dxfeed import Greeks, Summary, Quote
from futures_gex_engine import FuturesGEXCalculator

load_dotenv()
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

PRODUCT = "/ES"

async def main():
    print(f"Building {PRODUCT} gamma levels...\n")

    chain = await get_future_option_chain(session, PRODUCT)
    nearest = sorted(chain.keys())[0]
    options = chain[nearest]
    print(f"Expiration {nearest}: {len(options)} contracts")

    # underlying future symbol comes straight from an option in the chain
    underlying_future_symbol = options[0].underlying_symbol
    print(f"Underlying future: {underlying_future_symbol}")

    # fetch that future to get its streamer symbol for the live price
    fut = await Future.get(session, underlying_future_symbol)
    fut_streamer = fut.streamer_symbol
    print(f"Future streamer symbol: {fut_streamer}")

    opt_symbols = [o.streamer_symbol for o in options]
    engine = FuturesGEXCalculator(PRODUCT)

    print("\nConnecting to live stream (collecting ~20 seconds of data)...")
    async with DXLinkStreamer(session) as streamer:
        await streamer.subscribe(Quote, [fut_streamer])
        await streamer.subscribe(Greeks, opt_symbols)
        await streamer.subscribe(Summary, opt_symbols)

        got_gamma = 0
        got_oi = 0
        spot = 0.0

        async def collect_quotes():
            nonlocal spot
            async for q in streamer.listen(Quote):
                if q.bid_price and q.ask_price:
                    spot = (float(q.bid_price) + float(q.ask_price)) / 2
                    engine.update_spot_price(spot)

        async def collect_greeks():
            nonlocal got_gamma
            async for g in streamer.listen(Greeks):
                engine.update_gamma(g.event_symbol, g.gamma)
                got_gamma += 1

        async def collect_summary():
            nonlocal got_oi
            async for s in streamer.listen(Summary):
                engine.update_open_interest(s.event_symbol, s.open_interest)
                got_oi += 1

        try:
            async with asyncio.timeout(20):
                await asyncio.gather(collect_quotes(), collect_greeks(), collect_summary())
        except asyncio.TimeoutError:
            pass

    print(f"\nData collected: spot={spot:.2f}, {got_gamma} gamma updates, {got_oi} OI updates")

    levels = engine.get_levels()
    print("\n" + "="*45)
    print(f"  {PRODUCT} GAMMA LEVELS")
    print("="*45)
    print(f"  Spot Price:  {spot:,.2f}")
    print(f"  Call Wall:   {levels['call_wall']}")
    print(f"  Put Wall:    {levels['put_wall']}")
    if levels['gamma_flip']:
        print(f"  Gamma Flip:  {levels['gamma_flip']:,.2f}")
    else:
        print(f"  Gamma Flip:  (no zero-crossing found)")
    print(f"  Strikes:     {levels['num_strikes']}")
    print("="*45)

asyncio.run(main())
