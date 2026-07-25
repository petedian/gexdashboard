import os
import asyncio
from dotenv import load_dotenv
from tastytrade import Session
from tastytrade.instruments import get_option_chain

load_dotenv()
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

async def main():
    print("Fetching SPX options chain...")
    try:
        chain = await get_option_chain(session, "SPX")
        expirations = sorted(chain.keys())
        print(f"SUCCESS! SPX has {len(expirations)} expiration dates.")
        print("First few:", expirations[:5])
        if expirations:
            nearest = expirations[0]
            print(f"Nearest expiration {nearest} has {len(chain[nearest])} contracts.")
            sample = chain[nearest][0]
            print(f"Sample contract streamer symbol: {sample.streamer_symbol}")
    except Exception as e:
        print("FAILED:", e)

asyncio.run(main())
