import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Keys
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Web Server Config
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
PORT = int(os.environ.get("PORT", 8000))
BIND_ADDR = "0.0.0.0"

# Security
SECRET_KEY = os.environ.get("SECRET_KEY", "change_this_to_a_random_string")
TOKEN_EXPIRY = 3600  # Links valid for 1 hour

# Multi-Token / Flood Protection Config
MULTI_TOKEN_ENABLED = os.environ.get("MULTI_TOKEN_ENABLED", "True").lower() == "true"

if MULTI_TOKEN_ENABLED:
    MAX_CONCURRENT_STREAMS = 6
else:
    MAX_CONCURRENT_STREAMS = 1
  
