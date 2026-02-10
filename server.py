import time
import hmac
import hashlib
import asyncio
from urllib.parse import quote
from typing import Generator

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import StreamingResponse, HTMLResponse
from pyrogram import Client, filters
from pyrogram.types import Message
import uvicorn
import config

# --- Client Setup ---
# STABILITY FIX: ipv6=False is crucial for Koyeb/Telegram connection
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

# --- Security ---
def generate_secure_link(file_id: str, file_size: int, endpoint: str = "watch") -> str:
    expiry = int(time.time()) + config.TOKEN_EXPIRY
    payload = f"{file_id}{expiry}".encode()
    token = hmac.new(config.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"{config.BASE_URL}/{endpoint}?file_id={quote(file_id)}&size={file_size}&token={token}&exp={expiry}"

def verify_token(file_id: str, token: str, expiry: int) -> bool:
    if time.time() > expiry: return False
    payload = f"{file_id}{expiry}".encode()
    expected = hmac.new(config.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, token)

# --- Bot Handlers ---
@client.on_message(filters.command("start"))
async def start_handler(c: Client, m: Message):
    await m.reply_text("✅ **Bot Online!**\nSend me an MKV file to watch.")

@client.on_message(filters.video | filters.document)
async def video_handler(c: Client, m: Message):
    media = m.video or m.document
    if not media: return
    
    file_size = media.file_size or 1024*1024*10
    
    watch_link = generate_secure_link(media.file_id, file_size, endpoint="watch")
    filename = media.file_name or "video.mp4"
    
    await m.reply_text(
        f"🎬 **File:** `{filename}`\n"
        f"📦 **Size:** `{round(file_size / (1024*1024), 2)} MB`\n\n"
        f"▶️ **Click to Watch:**\n{watch_link}\n\n"
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

# --- STREAM GENERATOR (Stable) ---
async def file_generator(client: Client, file_id: str, start: int, end: int):
    length = end - start + 1
    # Using standard stream_media with offset. 
    # ipv6=False in client config prevents the black screen/timeout issues.
    try:
        async for chunk in client.stream_media(file_id, offset=start):
            if length <= 0:
                break
            chunk_len = len(chunk)
            if chunk_len > length:
                yield chunk[:length]
                length = 0
                break
            else:
                yield chunk
                length -= chunk_len
    except Exception as e:
        print(f"Stream Error: {e}")
        pass

# --- HTML Player Endpoint (UI Fixed) ---
@app.get("/watch", response_class=HTMLResponse)
async def watch_video(request: Request, file_id: str, size: int, token: str, exp: int):
    if not verify_token(file_id, token, exp):
        return "<h1>Invalid or Expired Link</h1>"

    stream_url = f"{config.BASE_URL}/stream?file_id={quote(file_id)}&size={size}&token={token}&exp={exp}"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Astra Player</title>
        <style>
            body {{ 
                background: #000000; 
                margin: 0; 
                height: 100vh; 
                display: flex; 
                flex-direction: column; 
                justify-content: center; /* Vertically Center */
                align-items: center; /* Horizontally Center */
                font-family: sans-serif;
            }}
            
            video {{ 
                width: 95%; 
                max-width: 800px; 
                border-radius: 8px; 
                background: #000; 
                box-shadow: 0 0 20px rgba(255,255,255,0.1);
                max-height: 70vh;
            }}

            .btn-container {{ 
                margin-top: 40px; /* Exactly ~1 cm gap */
                display: flex; 
                gap: 15px; 
                flex-wrap: wrap; 
                justify-content: center; 
                width: 100%;
            }}

            .btn {{ 
                padding: 12px 25px; 
                border-radius: 50px; 
                text-decoration: none; 
                color: white; 
                font-weight: bold; 
                font-size: 14px; 
                border: none; 
                cursor: pointer; 
                display: flex;
                align-items: center;
                transition: transform 0.2s;
            }}
            
            .btn:active {{ transform: scale(0.95); }}
            
            .vlc {{ background: linear-gradient(45deg, #ff5722, #ff9800); }}
            .playit {{ background: linear-gradient(45deg, #5c3eff, #9e3eff); }}
            
        </style>
    </head>
    <body>
        
        <video controls autoplay playsinline>
            <source src="{stream_url}" type="video/mp4">
            Your browser does not support the video tag.
        </video>

        <div class="btn-container">
            <a href="intent:{stream_url}#Intent;package=org.videolan.vlc;type=video/*;scheme=https;end" class="btn vlc">
                Open in VLC
            </a>
            
            <a href="intent:{stream_url}#Intent;package=com.playit.videoplayer;type=video/*;scheme=https;end" class="btn playit">
                Open in Playit
            </a>
        </div>

    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# --- Stream Endpoint ---
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
        "Content-Type": "video/mp4",
        "Connection": "keep-alive"
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
    
