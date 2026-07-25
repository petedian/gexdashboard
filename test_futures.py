import os
import asyncio
from dotenv import load_dotenv
from tastytrade import Session
from tastytrade.instruments import get_future_option_chain

load_dotenv()
session = Session(os.getenv("CLIENT_SECRET"), os.getenv("REFRESH_TOKEN"))

async def main():
    print("Fetching /ES futures options chain...")
    try:
        chain = await get_future_option_chain(session, "/ES")
        expirations = sorted(chain.keys())
        print(f"SUCCESS! Found {len(expirations)} expiration dates for /ES options.")
        print("First few expirations:", expirations[:5])
        if expirations:
            nearest = expirations[0]
            print(f"Nearest expiration {nearest} has {len(chain[nearest])} option contracts.")
    except Exception as e:
        print("FAILED to fetch futures chain.")
        print("Error was:", e)

asyncio.run(main())
