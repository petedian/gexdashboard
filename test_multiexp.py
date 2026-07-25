import os
import asyncio
from dotenv import load_dotenv
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain
from tastytrade.dxfeed import Greeks

load_dotenv()
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

async def main():
    chain = await get_future_option_chain(session, "/ES")
    exps = sorted(chain.keys())[:4]
    options = []
    for e in exps:
        options.extend(chain[e])
    symbols = [o.streamer_symbol for o in options]
    print(f"4 expirations = {len(symbols)} symbols total")
    print("Trying to subscribe to all at once...")
    try:
        async with DXLinkStreamer(session) as streamer:
            await streamer.subscribe(Greeks, symbols)
            print("Subscribe accepted. Listening 5s...")
            count = 0
            try:
                async with asyncio.timeout(5):
                    async for g in streamer.listen(Greeks):
                        count += 1
                        if count >= 5:
                            break
            except asyncio.TimeoutError:
                pass
            print(f"Got {count} greeks - subscribe works fine with {len(symbols)} symbols")
    except Exception as e:
        import traceback
        print("REAL ERROR:")
        traceback.print_exc()

asyncio.run(main())
