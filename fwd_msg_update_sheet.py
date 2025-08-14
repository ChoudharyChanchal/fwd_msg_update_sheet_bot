
import os
import re
import sys
import asyncio
import logging
import gspread
import pytz
import aiohttp
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from google.oauth2.service_account import Credentials
from flask import Flask, request, jsonify
import threading


# ---------------- LOGGING SETUP ----------------
# Global logging config so Render can capture everything
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# Make sure print() flushes immediately
print = lambda *args, **kwargs: __builtins__.print(*args, **{**kwargs, "flush": True})


# ---------------- FLASK APP ----------------
app = Flask(__name__)


@app.route('/')
def health_check():
    logger.info("Health check ping received")
    return jsonify({
        'status': 'alive',
        'message': 'Telethon bot is running!',
        'mode': 'user_account_bot'
    })


@app.route('/keep-alive')
def keep_alive_endpoint():
    logger.info("Keep-alive endpoint hit")
    return jsonify({'status': 'alive', 'timestamp': datetime.now().isoformat()})


# ---------------- TELEGRAM SETUP ----------------
api_id = int(os.environ['API_ID'])
api_hash = os.environ['API_HASH']
session_string = os.environ['SESSION_STRING']
source_group = int(os.environ['SOURCE_GROUP'])
target_group = int(os.environ['TARGET_GROUP'])


client = TelegramClient(StringSession(session_string), api_id, api_hash)


# ---------------- GOOGLE SHEETS SETUP ----------------
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
credentials_path = '/etc/secrets/credentials.json'
if not os.path.exists(credentials_path):
    credentials_path = os.getenv('GOOGLE_SHEETS_CREDENTIALS_PATH', 'credentials.json')


try:
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    gclient = gspread.authorize(creds)
    sheet_id = os.environ['SHEET_ID']
    worksheet = gclient.open_by_key(sheet_id).worksheet("Sheet1")
    logger.info("✅ Google Sheets client initialized")
except Exception as e:
    logger.error(f"❌ Google Sheets setup failed: {e}")
    gclient = None
    worksheet = None


# ---------------- FIELD EXTRACTION ----------------
def extract_fields(text):
    fields = {
        "Branch": "MISSING",
        "Salesperson": "MISSING",
        "Customer Name": "MISSING",
        "Product Description": "MISSING",
        "Exchange": "MISSING",
        "MRP": "MISSING",
        "DP": "MISSING",
        "Last Purchase Price (PP)": "MISSING",
        "Negotiated Price (NP)": "MISSING",
        "SRP Price": "MISSING",
        "Selling Price (SP)": "MISSING"
    }
    patterns = {
        "Branch": r"Branch\s*:\s*(.+)",
        "Salesperson": r"Salesperson\s*:\s*(.+)",
        "Customer Name": r"Customer\s*Name\s*:\s*(.+)",
        "Product Description": r"Product\s*Description\s*:\s*(.+)",
        "Exchange": r"Exchange\s*:\s*(.+)",
        "MRP": r"MRP\s*:\s*(.+)",
        "DP": r"DP\s*:\s*(.+)",
        "Last Purchase Price (PP)": r"Last\s*Purchase\s*Price\s*\(.*PP.*\)\s*:\s*(.+)",
        "Negotiated Price (NP)": r"Negotiated\s*Price\s*\(.*NP.*\)\s*:\s*(.+)",
        "SRP Price": r"SRP\s*Price\s*:\s*(.+)",
        "Selling Price (SP)": r"Selling\s*Price\s*\(.*SP.*\)?\s*:\s*(.+)"
    }
    for line in text.splitlines():
        for field, pattern in patterns.items():
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                fields[field] = match.group(1).strip()
    return list(fields.values())


# ---------------- TELEGRAM HANDLER ----------------
@client.on(events.NewMessage(chats=source_group))
async def handler(event):
    msg = event.raw_text
    logger.info(f"Message received: {msg}")


    if 'mobile' in msg.lower():
        try:
            if worksheet:
                logger.info("Extracting and updating to Google Sheet...")
                ist = pytz.timezone('Asia/Kolkata')
                current_ist_date = datetime.now(ist).strftime('%Y-%m-%d')
                row = extract_fields(msg)
                row = [current_ist_date] + row
                worksheet.append_row(row)
                logger.info("✅ Google Sheet updated!")
            else:
                logger.warning("⚠️ Google Sheets not configured")
        except Exception as e:
            logger.error(f"❌ Google Sheet update failed: {e}")


        try:
            logger.info("Forwarding message to target group...")
            await client.send_message(target_group, msg)
            logger.info("✅ Message sent successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to send message: {e}")


# ---------------- IMPROVED KEEP ALIVE TASK ----------------
async def keep_alive_task():
    """
    Keep alive task that makes HTTP requests to prevent Render from sleeping.
    Render spins down free services after 15 minutes of inactivity.
    """
    while True:
        try:
            # Get the service URL from environment variable or construct it
            service_url = os.getenv('RENDER_EXTERNAL_URL')
            if not service_url:
                # If RENDER_EXTERNAL_URL is not set, we can't self-ping
                logger.info("🔄 Keep-alive: RENDER_EXTERNAL_URL not set, cannot self-ping")
                await asyncio.sleep(840)  # 14 minutes
                continue

            # Make HTTP request to keep service alive
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                ping_url = f"{service_url}/keep-alive"
                async with session.get(ping_url) as response:
                    if response.status == 200:
                        logger.info(f"✅ Keep-alive ping successful: {response.status}")
                    else:
                        logger.warning(f"⚠️ Keep-alive ping returned status: {response.status}")

        except Exception as e:
            logger.error(f"❌ Keep-alive ping failed: {e}")

        # Wait 14 minutes (840 seconds) - less than Render's 15-minute timeout
        await asyncio.sleep(840)


# ---------------- MAIN FUNCTION ----------------
async def start_bot():
    try:
        logger.info("🚀 Starting Telethon client...")
        await client.start()
        logger.info("✅ Client started successfully! Listening for messages...")

        # Start keep-alive task
        asyncio.create_task(keep_alive_task())
        logger.info("🔄 Keep-alive task started")

        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"❌ Error starting client: {e}")
        raise


# ---------------- RENDER DEPLOYMENT ----------------
if __name__ == '__main__':
    if os.getenv('RENDER'):
        logger.info("🌐 Running on Render - starting Flask server and Telethon in parallel")
        def run_telethon():
            asyncio.run(start_bot())
        telethon_thread = threading.Thread(target=run_telethon, daemon=True)
        telethon_thread.start()
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
    else:
        logger.info("💻 Running locally...")
        asyncio.run(start_bot())
