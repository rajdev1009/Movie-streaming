import time
import hmac
import hashlib
import asyncio
from urllib.parse import quote
from typing import Generator

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import StreamingResponse
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.file_id import FileId
import uvicorn
import config

# --- Setup Client (Single Instance) ---
# We use in_memory=True, but since there is only 1 client now, 
# it won't conflict with anything else.
client = Client(
    "unified_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    in_memory=True
)

app = FastAPI()

# --- Global State ---
active_streams_count = 0
lock = asyncio.Lock()

# ==============================
#  BOT LOGIC (Handlers)
# ==============================

def generate_secure_link(file_id: str) -> str:
    expiry = int(time.time()) + config.TOKEN_EXPIRY
    payload = f"{file_id}{expiry}".encode()
    token = hmac.new(config.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"{config.BASE_URL}/stream?file_id={quote(file_id)}&token={token}&exp={expiry}"

@client.on_message(filters.command("start"))
async def start_handler(c: Client, m: Message):
    await m.reply_text(
        "**Bot is Online!** (Unified Server) 🟢\n\n"
        "Send me an MKV file to get a stream link."
    )

@client.on_message(filters.video | filters.document)
async def video_handler(c: Client, m: Message):
    media = m.video or m.document
    if not media: return
    
    link = generate_secure_link(media.file_id)
    filename = media.file_name or "video.mkv"
    
    await m.reply_text(
        f"**File:** `{filename}`\n\n"
        f"**Stream Link:**\n`{link}`\n\n"
        f"__Expires in {config.TOKEN_EXPIRY // 60} mins.__"
    )

# ==============================
#  SERVER LOGIC (Streaming)
# ==============================

@app.on_event("startup")
async def startup_event():
    print("Starting Telegram Client...")
    await client.start()
    print("Client Started!")

@app.on_event("shutdown")
async def shutdown_event():
    print("Stopping Telegram Client...")
    await client.stop()

def verify_token(file_id: str, token: str, expiry: int) -> bool:
    if time.time() > expiry: return False
    payload = f"{file_id}{expiry}".encode()
    expected = hmac.new(config.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, token)

class StreamManager:
    async def __aenter__(self):
        global active_streams_count
        async with lock:
            if active_streams_count >= config.MAX_CONCURRENT_STREAMS:
                raise HTTPException(503, "Server busy")
            active_streams_count += 1
        return self
    async def __aexit__(self, *args):
        global active_streams_count
        async with lock:
            active_streams_count -= 1

async def file_generator(client: Client, file_id: str, start: int, end: int):
    chunk_size = 1024 * 1024
    offset = start
    left = end - start + 1
    
    while left > 0:
        fetch = min(chunk_size, left)
        async for chunk in client.stream_media(file_id, offset=offset, limit=fetch):
            if not chunk: break
            yield chunk
            offset += len(chunk)
            left -= len(chunk)
            if left <= 0: break

@app.get("/stream")
async def stream_route(request: Request, file_id: str, token: str, exp: int):
    if not verify_token(file_id, token, exp):
        raise HTTPException(403, "Invalid/Expired Token")
    
    try:
        f_info = FileId.decode(file_id)
        file_size = f_info.file_size
    except:
        raise HTTPException(400, "Invalid File ID")

    range_header = request.headers.get("range")
    start, end = 0, file_size - 1
    
    if range_header:
        try:
            unit, r = range_header.split("=")
            if unit == "bytes":
                parts = r.split("-")
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        except: pass

    if start >= file_size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    end = min(end, file_size - 1)
    
    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Type": "video/x-matroska",
    }

    async def gen():
        try:
            async with StreamManager():
                async for chunk in file_generator(client, file_id, start, end):
                    yield chunk
        except: pass

    return StreamingResponse(gen(), status_code=206, headers=headers)

if __name__ == "__main__":
    uvicorn.run(app, host=config.BIND_ADDR, port=config.PORT)
    
