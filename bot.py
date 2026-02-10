import asyncio
import time
import hmac
import hashlib
from urllib.parse import quote
from pyrogram import Client, filters
from pyrogram.types import Message
import config

# UPDATE: in_memory=True added to prevent database locks
app = Client(
    "bot_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    in_memory=True
)

def generate_secure_link(file_id: str) -> str:
    expiry = int(time.time()) + config.TOKEN_EXPIRY
    # Token Payload: file_id + expiry
    payload = f"{file_id}{expiry}".encode()
    
    # Generate Hash
    token = hmac.new(
        config.SECRET_KEY.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    # Construct URL
    return f"{config.BASE_URL}/stream?file_id={quote(file_id)}&token={token}&exp={expiry}"

# --- NEW: Start Command Handler ---
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    await message.reply_text(
        "**Bot is Online!** 🟢\n\n"
        "मुझे कोई भी MKV या वीडियो फाइल फॉरवर्ड करें, "
        "और मैं आपको उसका स्ट्रीमिंग लिंक दूंगा।"
    )

@app.on_message(filters.video | filters.document)
async def handle_video(client: Client, message: Message):
    media = message.video or message.document
    if not media:
        return
    
    # Check if it's actually a video (mime_type check optional but good)
    if hasattr(media, "mime_type") and media.mime_type and "video" not in media.mime_type:
        # Document ho sakta hai par video nahi
        pass 

    file_id = media.file_id
    file_name = media.file_name or "video.mkv"
    
    link = generate_secure_link(file_id)
    
    await message.reply_text(
        f"**File:** `{file_name}`\n\n"
        f"**Stream Link:**\n`{link}`\n\n"
        f"__Link expires in {config.TOKEN_EXPIRY // 60} minutes.__"
    )

if __name__ == "__main__":
    print("Bot started...")
    app.run()
    
