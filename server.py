import time
import hmac
import hashlib
import asyncio
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import StreamingResponse, HTMLResponse
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.raw.functions.upload import GetFile
from pyrogram.raw.types import InputDocumentFileLocation
from pyrogram.file_id import FileId
import uvicorn
import config

# --- Client Setup ---
client = Client(
    "unified_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    in_memory=True,
    ipv6=False 
)

app = FastAPI()
active_streams_count = 0
lock = asyncio.Lock()

# --- Helper Functions ---
def human_size(bytes, units=['B', 'KB', 'MB', 'GB', 'TB']):
    if bytes < 1024: return f"{int(bytes)} {units[0]}"
    for unit in units:
        if bytes < 1024: return f"{bytes:.2f} {unit}"
        bytes /= 1024
    return f"{bytes:.2f} {units[-1]}"

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
    await m.reply_text("✅ **Bot Online!**\nSend MKV file.")

@client.on_message(filters.video | filters.document)
async def video_handler(c: Client, m: Message):
    media = m.video or m.document
    if not media: return
    file_size = media.file_size or 1024*1024*10
    watch_link = generate_secure_link(media.file_id, file_size, endpoint="watch")
    filename = media.file_name or "video.mp4"
    await m.reply_text(
        f"🎬 **File:** `{filename}`\n📦 **Size:** `{human_size(file_size)}`\n\n▶️ **Click to Watch:**\n{watch_link}\n\n⚠️ Expires in {config.TOKEN_EXPIRY // 60} mins."
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

# --- THE REAL FIX: 4KB Aligned Generator ---
async def file_generator(client: Client, file_id_str: str, start: int, end: int):
    try:
        decoded = FileId.decode(file_id_str)
        location = InputDocumentFileLocation(
            id=decoded.media_id,
            access_hash=decoded.access_hash,
            file_reference=decoded.file_reference,
            thumb_size=""
        )
    except: return

    # 1. Align the Start Offset to 4KB (Telegram Requirement)
    # If start is 4097, aligned_start becomes 4096.
    offset = start - (start % 4096) 
    
    # 2. Calculate how many bytes to skip initially
    first_chunk_skip = start - offset
    
    # 3. Always request 1MB chunks
    limit = 1024 * 1024 
    
    while offset <= end:
        try:
            r = await client.invoke(
                GetFile(
                    location=location,
                    offset=offset,
                    limit=limit 
                )
            )
            
            if not r or not r.bytes: break
            
            chunk = r.bytes
            
            # 4. If this is the first chunk, skip the unneeded bytes
            if first_chunk_skip > 0:
                if len(chunk) > first_chunk_skip:
                    chunk = chunk[first_chunk_skip:]
                    first_chunk_skip = 0
                else:
                    # If chunk is smaller than skip (rare), skip all and continue
                    first_chunk_skip -= len(chunk)
                    offset += len(r.bytes)
                    continue

            # 5. Trim the end if we fetched more than needed
            bytes_left = end - (offset + (len(r.bytes) - len(chunk))) + 1
            if len(chunk) > bytes_left:
                chunk = chunk[:bytes_left]
            
            if not chunk: break
            
            yield chunk
            
            # Update offset based on RAW bytes received from Telegram (not the cut chunk)
            offset += len(r.bytes)
            
        except Exception as e:
            print(f"Gen Error: {e}")
            break

# --- HTML Player ---
@app.get("/watch", response_class=HTMLResponse)
async def watch_video(request: Request, file_id: str, size: int, token: str, exp: int):
    if not verify_token(file_id, token, exp): return "<h1>Invalid/Expired</h1>"
    stream_url = f"{config.BASE_URL}/stream?file_id={quote(file_id)}&size={size}&token={token}&exp={exp}"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Astra Player</title>
        <style>
            body {{ background: #000; margin: 0; height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; font-family: sans-serif; }}
            video {{ width: 95%; max-width: 800px; border-radius: 8px; background: #000; box-shadow: 0 0 20px rgba(255,255,255,0.1); }}
            .btn-container {{ margin-top: 40px; display: flex; gap: 15px; flex-wrap: wrap; justify-content: center; width: 100%; }}
            .btn {{ padding: 12px 25px; border-radius: 50px; text-decoration: none; color: white; font-weight: bold; font-size: 14px; border: none; cursor: pointer; display: flex; align-items: center; background: #333; }}
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
            <a href="intent:{stream_url}#Intent;package=org.videolan.vlc;type=video/*;scheme=https;end" class="btn vlc">Open in VLC</a>
            <a href="intent:{stream_url}#Intent;package=com.playit.videoplayer;type=video/*;scheme=https;end" class="btn playit">Open in Playit</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/stream")
async def stream_route(request: Request, file_id: str, size: int, token: str, exp: int):
    if not verify_token(file_id, token, exp): raise HTTPException(403, "Invalid/Expired Token")
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
    
    if start >= file_size: return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
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
    
