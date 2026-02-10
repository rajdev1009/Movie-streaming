import time
import hmac
import hashlib
import asyncio
from urllib.parse import quote
from typing import Generator

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import StreamingResponse
from pyrogram import Client, filters
from pyrogram.types import Message
import uvicorn
import config

# --- Client Setup ---
# ipv6=False is important for stability on Koyeb
client = Client(
    "unified_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    in_memory=True,
    ipv6=False
)

app = FastAPI()

# --- Global State ---
active_streams_count = 0
lock = asyncio.Lock()

# --- Security & Links ---
def generate_secure_link(file_id: str, file_size: int) -> str:
    expiry = int(time.time()) + config.TOKEN_EXPIRY
    payload = f"{file_id}{expiry}".encode()
    token = hmac.new(config.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"{config.BASE_URL}/stream?file_id={quote(file_id)}&size={file_size}&token={token}&exp={expiry}"

def verify_token(file_id: str, token: str, expiry: int) -> bool:
    if time.time() > expiry: return False
    payload = f"{file_id}{expiry}".encode()
    expected = hmac.new(config.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, token)

# --- Bot Handlers ---
@client.on_message(filters.command("start"))
async def start_handler(c: Client, m: Message):
    await m.reply_text("✅ **Bot Online!**\nSend me an MKV file.")

@client.on_message(filters.video | filters.document)
async def video_handler(c: Client, m: Message):
    media = m.video or m.document
    if not media: return
    
    file_size = media.file_size or 1024*1024*10
    link = generate_secure_link(media.file_id, file_size)
    filename = media.file_name or "video.mkv"
    
    await m.reply_text(
        f"🎬 **File:** `{filename}`\n"
        f"📦 **Size:** `{round(file_size / (1024*1024), 2)} MB`\n\n"
        f"🔗 **Stream Link:**\n{link}\n\n"
        f"⚠️ Expires in {config.TOKEN_EXPIRY // 60} mins."
    )

# --- Server Logic ---
@app.on_event("startup")
async def startup_event():
    print("Starting Client...")
    await client.start()

@app.on_event("shutdown")
async def shutdown_event():
    print("Stopping Client...")
    await client.stop()

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

# --- CORE FIX: Manual Chunk Generator ---
async def file_generator(client: Client, file_id: str, start: int, end: int):
    offset = start
    total_to_fetch = end - start + 1
    chunk_size = 1024 * 1024  # 1 MB Request Block

    # Loop until we fetch all requested bytes
    while total_to_fetch > 0:
        # Calculate how much to fetch in this iteration (max 1MB)
        current_fetch_limit = min(total_to_fetch, chunk_size)
        
        try:
            # We create a FRESH iterator for every 1MB block.
            # This prevents Pyrogram's internal offset tracking from getting corrupted.
            async for chunk in client.stream_media(file_id, offset=offset, limit=current_fetch_limit):
                if not chunk:
                    break
                yield chunk
                
                # Manually update tracking
                chunk_len = len(chunk)
                offset += chunk_len
                total_to_fetch -= chunk_len
                
                if total_to_fetch <= 0:
                    break
        except Exception as e:
            print(f"Stream Error at offset {offset}: {e}")
            break

@app.get("/stream")
async def stream_route(request: Request, file_id: str, size: int, token: str, exp: int):
    if not verify_token(file_id, token, exp):
        raise HTTPException(403, "Invalid/Expired Token")
    
    file_size = size
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
    content_length = end - start + 1

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
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
    
