import time
import hmac
import hashlib
import asyncio
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import StreamingResponse, HTMLResponse
from pyrogram import Client, filters
from pyrogram.types import Message
import uvicorn
import config

# --- Client Setup ---
client = Client(
    "unified_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    in_memory=True,
    ipv6=False,
    workers=4
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

def generate_secure_link(file_id: str, file_size: int, endpoint: str) -> str:
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
    await m.reply_text("✅ **Bot Online!**\nSend me a video file.")

@client.on_message(filters.video | filters.document)
async def video_handler(c: Client, m: Message):
    media = m.video or m.document
    if not media: return
    file_size = media.file_size or 1024*1024*10
    watch_link = generate_secure_link(media.file_id, file_size, endpoint="watch")
    filename = media.file_name or "video.mp4"
    await m.reply_text(
        f"🎬 **File:** `{filename}`\n📦 **Size:** `{human_size(file_size)}`\n\n▶️ **Click to Watch / Download:**\n{watch_link}\n\n⚠️ Expires in {config.TOKEN_EXPIRY // 60} mins."
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

# --- FIX: NATIVE GENERATOR (Auto DC Switch) ---
async def file_generator(client: Client, file_id_str: str, start: int, end: int):
    total_bytes_to_serve = end - start + 1
    bytes_served = 0
    
    try:
        # stream_media handles FILE_MIGRATE automatically
        async for chunk in client.stream_media(file_id_str, offset=start):
            chunk_len = len(chunk)
            
            if bytes_served + chunk_len > total_bytes_to_serve:
                remaining = total_bytes_to_serve - bytes_served
                yield chunk[:remaining]
                break
            
            yield chunk
            bytes_served += chunk_len
            
            if bytes_served >= total_bytes_to_serve:
                break
                
    except Exception as e:
        print(f"Stream Error: {e}")
        pass

# --- UI HTML Player ---
@app.get("/watch", response_class=HTMLResponse)
async def watch_video(request: Request, file_id: str, size: int, token: str, exp: int):
    if not verify_token(file_id, token, exp): return "<h1>Invalid/Expired Link</h1>"
    stream_url = generate_secure_link(file_id, size, endpoint="stream")
    download_url = generate_secure_link(file_id, size, endpoint="download")
    
    profile_img_url = "https://i.ibb.co/kY1Nyzs/1765464889401-2.jpg"
    random_middle_img = "https://picsum.photos/150/100?grayscale"
    playit_icon_url = "https://cdn-icons-png.flaticon.com/512/0/375.png"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Raj_hd_movies Player</title>
        <style>
            body {{ background-color: #000; color: #fff; font-family: sans-serif; display: flex; flex-direction: column; align-items: center; margin: 0; padding: 20px 10px; text-align: center; min-height: 100vh; box-sizing: border-box; }}
            .header-title {{ font-size: 3.5em; font-family: "Brush Script MT", cursive, sans-serif; margin-bottom: 5px; line-height: 1.2; }}
            .sub-title {{ color: #888; font-size: 1em; margin-bottom: 25px; }}
            .profile-img {{ width: 90px; height: 90px; border-radius: 50%; object-fit: cover; margin-bottom: 25px; border: 2px solid #222; }}
            video {{ width: 100%; max-width: 800px; aspect-ratio: 16 / 9; border-radius: 8px; margin-bottom: 25px; background: #111; box-shadow: 0 4px 15px rgba(255,255,255,0.1); }}
            .channel-name {{ font-size: 2.8em; font-weight: bold; margin-bottom: 35px; letter-spacing: 1px; }}
            .players-row {{ display: flex; justify-content: space-between; align-items: center; width: 100%; max-width: 600px; margin: 0 auto 40px auto; padding: 0 10px; box-sizing: border-box; }}
            .player-link {{ text-decoration: none; color: white; font-size: 2.2em; font-weight: bold; display: flex; align-items: center; }}
            .playit-icon-img {{ width: 35px; height: 35px; margin-right: 10px; filter: brightness(0) saturate(100%) invert(63%) sepia(68%) saturate(450%) hue-rotate(346deg) brightness(101%) contrast(101%); }}
            .middle-img-container {{ flex-grow: 1; display: flex; justify-content: center; padding: 0 15px; }}
            .middle-img {{ width: 100%; max-width: 140px; height: auto; border-radius: 6px; object-fit: cover; opacity: 0.8; }}
            .download-btn {{ background: linear-gradient(to bottom, #53e03d, #3ab028); border: 2px solid #2ecc71; border-radius: 12px; padding: 12px 25px; display: flex; align-items: center; justify-content: space-between; text-decoration: none; color: white; width: 90%; max-width: 380px; margin-bottom: 50px; box-shadow: 0 6px 15px rgba(76, 209, 55, 0.4); transition: transform 0.1s; }}
            .download-btn:active {{ transform: scale(0.98); }}
            .dl-arrow-left {{ font-size: 2.5em; margin-right: 15px; font-weight: bold; color: #dfffce; text-shadow: 0 2px 2px rgba(0,0,0,0.2); }}
            .dl-text-container {{ text-align: left; flex-grow: 1; }}
            .dl-small {{ font-size: 1em; display: block; opacity: 0.9; }}
            .dl-big {{ font-size: 1.6em; font-weight: 900; display: block; text-transform: uppercase; }}
            .dl-icon-right {{ font-size: 1.8em; margin-left: 15px; }}
            .footer-text {{ font-weight: bold; margin-bottom: 15px; font-size: 1.2em; }}
        </style>
    </head>
    <body>
        <div class="header-title">Raj_hd_movies</div>
        <div class="sub-title">powered by Rajdev</div>
        <img src="{profile_img_url}" alt="Profile" class="profile-img">
        <video controls autoplay playsinline>
            <source src="{stream_url}" type="video/mp4">
            Your browser does not support the video tag.
        </video>
        <div class="channel-name">AstraToonix</div>
        <div class="players-row">
            <a href="intent:{stream_url}#Intent;package=com.playit.videoplayer;type=video/*;scheme=https;end" class="player-link">
                <img src="{playit_icon_url}" alt="play" class="playit-icon-img">
                <span>playit</span>
            </a>
            <div class="middle-img-container"><img src="{random_middle_img}" alt="Random" class="middle-img"></div>
            <a href="intent:{stream_url}#Intent;package=org.videolan.vlc;type=video/*;scheme=https;end" class="player-link"><span>vlc</span></a>
        </div>
        <a href="{download_url}" class="download-btn">
            <div class="dl-arrow-left">≫</div>
            <div class="dl-text-container"><span class="dl-small">Click here to</span><span class="dl-big">DOWNLOAD</span></div>
            <div class="dl-icon-right">📥</div>
        </a>
        <div class="footer-text">powered by Rajdev</div>
        <div class="footer-text">ram ram</div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

async def stream_logic(request: Request, file_id: str, size: int, disposition: str):
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
        "Content-Disposition": disposition,
        "Connection": "keep-alive"
    }
    async def gen():
        try:
            async with StreamManager():
                async for chunk in file_generator(client, file_id, start, end):
                    yield chunk
        except: pass
    return StreamingResponse(gen(), status_code=206, headers=headers)

@app.get("/stream")
async def stream_route(request: Request, file_id: str, size: int, token: str, exp: int):
    if not verify_token(file_id, token, exp): raise HTTPException(403, "Invalid Token")
    return await stream_logic(request, file_id, size, "inline")

@app.get("/download")
async def download_route(request: Request, file_id: str, size: int, token: str, exp: int):
    if not verify_token(file_id, token, exp): raise HTTPException(403, "Invalid Token")
    return await stream_logic(request, file_id, size, "attachment")

if __name__ == "__main__":
    uvicorn.run(app, host=config.BIND_ADDR, port=config.PORT)
    
