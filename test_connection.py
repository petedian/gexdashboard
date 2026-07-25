import os
from dotenv import load_dotenv
from tastytrade import Session

load_dotenv()

client_secret = os.getenv("CLIENT_SECRET")
refresh_token = os.getenv("REFRESH_TOKEN")

print("Attempting to connect to Tastytrade...")

try:
    session = Session(client_secret, refresh_token)
    print("SUCCESS: Connected to Tastytrade!")
    print("Your API keys work. We can pull data.")
except Exception as e:
    print("FAILED to connect.")
    print("Error was:", e)
