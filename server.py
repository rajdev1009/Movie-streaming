import time
import hmac
import hashlib
import math
import mimetypes
from typing import Generator
import asyncio

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import StreamingResponse
from pyrogram import Client
from pyrogram.file_id import FileId
import uvicorn
import config

# --- Global State ---
active_streams_count = 0
lock = asyncio.Lock()

# --- Pyrogram Client for Server ---
# UPDATE: in_memory=True added to prevent database locks
client = Client(
    "server_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    no_updates=True,
    in_memory=True
)

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    await client.start()

@app.on_event("shutdown")
async def shutdown_event():
    await client.stop()

# --- Utilities ---

def verify_token(file_id: str, token: str, expiry: int) -> bool:
    if time.time() > expiry:
        return False
        
    payload = f"{file_id}{expiry}".encode()
    expected_token = hmac.new(
        config.SECRET_KEY.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_token, token)

class StreamManager:
    """Context manager to handle concurrent stream limits."""
    async def __aenter__(self):
        global active_streams_count
        async with lock:
            if active_streams_count >= config.MAX_CONCURRENT_STREAMS:
                raise HTTPException(status_code=503, detail="Server busy: Max streams reached.")
            active_streams_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        global active_streams_count
        async with lock:
            active_streams_count -= 1

async def telegram_file_generator(
    client: Client, 
    file_id_str: str, 
    start_byte: int, 
    end_byte: int, 
    chunk_size: int = 1024 * 1024
):
    current_offset = start_byte
    remaining_bytes = end_byte - start_byte + 1
    
    while remaining_bytes > 0:
        fetch_size = min(chunk_size, remaining_bytes)
        
        async for chunk in client.stream_media(
            file_id_str,
            offset=current_offset,
            limit=fetch_size
        ):
            if not chunk:
                break
            yield chunk
            chunk_len = len(chunk)
            current_offset += chunk_len
            remaining_bytes -= chunk_len
            
            if remaining_bytes <= 0:
                break

@app.get("/stream")
async def stream_video(
    request: Request,
    file_id: str,
    token: str,
    exp: int
):
    # 1. Security Checks
    if not verify_token(file_id, token, exp):
        raise HTTPException(status_code=403, detail="Invalid or Expired Token")

    # 2. Get File Info
    try:
        decoded_file = FileId.decode(file_id)
        file_size = decoded_file.file_size
        mime_type = "video/x-matroska"
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid File ID")

    # 3. Handle Range Header
    range_header = request.headers.get("range")
    start = 0
    end = file_size - 1
    
    if range_header:
        try:
            unit, ranges = range_header.split("=")
            if unit == "bytes":
                parts = ranges.split("-")
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        except ValueError:
            pass

    if start >= file_size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
    
    end = min(end, file_size - 1)
    content_length = end - start + 1

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Type": mime_type,
        "Content-Disposition": "inline"
    }

    async def protected_generator():
        try:
            async with StreamManager():
                async for chunk in telegram_file_generator(client, file_id, start, end):
                    yield chunk
        except HTTPException:
            pass
        except Exception as e:
            print(f"Streaming error: {e}")
            pass

    return StreamingResponse(
        protected_generator(),
        status_code=206,
        headers=headers
    )

if __name__ == "__main__":
    uvicorn.run(app, host=config.BIND_ADDR, port=config.PORT)
    
