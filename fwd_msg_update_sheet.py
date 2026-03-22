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
# Configure global logging so all messages are formatted and flushed to stdout.
# This is important because Render captures logs from stdout/stderr.
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Ensure print() flushes immediately (important for logs in Render)
print = lambda *args, **kwargs: __builtins__.print(*args, **{**kwargs, "flush": True})


# ---------------- FLASK APP ----------------
# Flask is used as a lightweight server so Render keeps the service "alive".
# Render automatically spins down free services after 15 min idle, so we need this.
app = Flask(__name__)

@app.route('/')
def health_check():
    """Health check endpoint - lets you verify bot is alive."""
    return jsonify({
        'status': 'alive',
        'message': 'Telethon bot is running!',
        'mode': 'user_account_bot'
    })

@app.route('/keep-alive')
def keep_alive_endpoint():
    """Keep-alive endpoint to be pinged periodically."""
    return jsonify({'status': 'alive', 'timestamp': datetime.now().isoformat()})


# ---------------- TELEGRAM SETUP ----------------
# Required secrets for Telethon client, stored in environment variables
api_id = int(os.environ['API_ID'])
api_hash = os.environ['API_HASH']
session_string = os.environ['SESSION_STRING']
source_group = int(os.environ['SOURCE_GROUP'])  # Source group from which we read messages

# Initialize Telethon client
client = TelegramClient(StringSession(session_string), api_id, api_hash)


# ---------------- GOOGLE SHEETS SETUP ----------------
# Authenticate with Google Sheets using a Service Account
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
credentials_path = '/etc/secrets/credentials.json'
if not os.path.exists(credentials_path):
    # fallback: allow custom path via env var
    credentials_path = os.getenv('GOOGLE_SHEETS_CREDENTIALS_PATH', 'credentials.json')

try:
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    gclient = gspread.authorize(creds)
    logger.info("✅ Google Sheets client initialized")
except Exception as e:
    logger.error(f"❌ Google Sheets setup failed: {e}")
    gclient = None


# ---------------- CONFIGURATION ----------------
# We now support multiple source groups.
# Each source group has its own set of categories and target groups.

# 1. Primary Source Group (Group A - RTS main group)
SOURCE_GROUP_A = int(os.environ['SOURCE_GROUP'])
CATEGORIES_A = {
    "mobile": {
        "keywords": ["item group : mobile phone", "item group : neckband", "item group : trimmer", "hair dryer", "hair straightner", "item group : earbuds", "item group : adaptors", "item group : audio accessories", "item group : power bank", "item group : headphone", "boat", "noise", "hapipola", "stufcool", "stuffcool"],
        "sheet_id": os.environ.get("SHEET_ID_MOBILE"),
        "targets": [int(x) for x in os.environ.get("TARGET_GROUPS_MOBILE", "").split(",") if x]
    },
    "laptop": {
        "keywords": ["item group : laptop", "keyboard", "mouse", "item group : monitor", "computer accessories"],
        "sheet_id": os.environ.get("SHEET_ID_LAPTOP"),
        "targets": [int(x) for x in os.environ.get("TARGET_GROUPS_LAPTOP", "").split(",") if x]
    },
    "accessories": {
        "keywords": ["item group : neckband","item group : trimmer", "hair dryer", "hair straightner", "item group : earbuds", "item group : adaptors", "item group : audio accessories", "item group : power bank", "item group : headphone", "boat", "noise", "hapipola", "stufcool", "stuffcool"],
        "sheet_id": os.environ.get("SHEET_ID_ACCESSORIES"),
        "targets": [int(x) for x in os.environ.get("TARGET_GROUPS_ACCESSORIES", "").split(",") if x]
    }
}

# 2. Secondary Source Group (Group B) - Optional
# If SOURCE_GROUP_B is not set, we just ignore it.
try:
    SOURCE_GROUP_B = int(os.environ.get('SOURCE_GROUP_B', 0))
except ValueError:
    SOURCE_GROUP_B = 0

CATEGORIES_B = {
    "mobile": {
        "keywords": ["item group : mobile phone", "item group : neckband", "item group : trimmer", "hair dryer", "hair straightner", "item group : earbuds", "item group : adaptors", "item group : audio accessories", "item group : power bank", "item group : headphone", "boat", "noise", "hapipola", "stufcool", "stuffcool"],
        # Reusing the same sheet IDs as Group A for now, unless specific ones are provided
        "sheet_id": os.environ.get("SHEET_ID_MOBILE_INV") or os.environ.get("SHEET_ID_MOBILE"),
        "targets": [int(x) for x in os.environ.get("TARGET_GROUPS_MOBILE_INV", "").split(",") if x]
    },
    "laptop": {
        "keywords": ["item group : laptop", "keyboard", "mouse", "item group : monitor", "computer accessories"],
        "sheet_id": os.environ.get("SHEET_ID_LAPTOP_INV") or os.environ.get("SHEET_ID_LAPTOP"),
        "targets": [int(x) for x in os.environ.get("TARGET_GROUPS_LAPTOP_INV", "").split(",") if x]
    }
    # ----- Comment out accessories part for now ----
    #"accessories": {
    #    "keywords": ["item group : neckband","item group : trimmer", "hair dryer", "hair straightner", "item group : earbuds", "item group : adaptors", "item group : audio accessories", "item group : power bank", "item group : headphone", "boat", "noise", "hapipola", "stufcool", "stuffcool"],
    #    "sheet_id": os.environ.get("SHEET_ID_ACCESSORIES_INV") or os.environ.get("SHEET_ID_ACCESSORIES"),
    #    "targets": [int(x) for x in os.environ.get("TARGET_GROUPS_ACCESSORIES_INV", "").split(",") if x]
    #}
}

# 3. Store IDs 
STORE_GROUP_IDS = {
    "WKD": int(os.environ['WKD_STORE_ALL_SALES']),
    "CHD": int(os.environ['CHD_STORE_ALL_SALES']),
    "BSR": int(os.environ['BSR_VSW_STORE_ALL_SALES']),
    "VSW": int(os.environ['BSR_VSW_STORE_ALL_SALES']),
    "MNB": int(os.environ['MNB_DYR_STORE_ALL_SALES']),
    "DYR": int(os.environ['MNB_DYR_STORE_ALL_SALES']),
    "KHD": int(os.environ['KHD_MNR_NRG_STORE_ALL_SALES']),
    "MNR": int(os.environ['KHD_MNR_NRG_STORE_ALL_SALES']),
    "NRG": int(os.environ['KHD_MNR_NRG_STORE_ALL_SALES']),
    "SKP": int(os.environ['SKP_SRR_PLT_STORE_ALL_SALES']),
    "SRR": int(os.environ['SKP_SRR_PLT_STORE_ALL_SALES']),
    "PLT": int(os.environ['SKP_SRR_PLT_STORE_ALL_SALES']),
    "HDP": int(os.environ['HDP_STORE_ALL_SALES'])
}


# Map source group ID to its specific configuration
SOURCE_CONFIGS = {
    SOURCE_GROUP_A: CATEGORIES_A
}
if SOURCE_GROUP_B:
    SOURCE_CONFIGS[SOURCE_GROUP_B] = CATEGORIES_B


# ---------------- FIELD EXTRACTION ----------------
def extract_fields(text):
    """
    Extracts structured fields from the Telegram message text.
    Each field has a regex pattern. If missing, it's set to 'MISSING'.
    """
    fields = {
        "Branch": "MISSING",
        "DocNum": "MISSING",
        "Salesperson": "MISSING",
        "Customer Name": "MISSING",
        "Product Description": "MISSING",
        "Serial Number": "MISSING",
        "Item Group": "MISSING",
        "Remarks": "MISSING",
        "Exchange": "MISSING",
        "MRP": "MISSING",
        "DP": "MISSING",
        "Last Purchase Price (PP)": "MISSING",
        "Negotiated Price (NP)": "MISSING",
        "SRP Price": "MISSING",
        "Selling Price (SP)": "MISSING"
    }
    # Regex patterns for each field
    patterns = {
        "Branch": r"Branch\s*:\s*(.+)",
        "DocNum": r"DocNum\s*:\s*(.+)",
        "Salesperson": r"Salesperson\s*:\s*(.+)",
        "Customer Name": r"Customer\s*Name\s*:\s*(.+)",
        "Product Description": r"Product\s*Description\s*:\s*(.+)",
        "Serial Number": r"Serial\s*Number\s*:\s*(.+)",
        "Item Group": r"Item\s*Group\s*:\s*(.+)",
        "Remarks": r"Remarks\s*:\s*(.+)",
        "Exchange": r"Exchange\s*:\s*(.+)",
        "MRP": r"MRP\s*:\s*(.+)",
        "DP": r"DP\s*:\s*(.+)",
        "Last Purchase Price (PP)": r"Last\s*Purchase\s*Price\s*\(.*PP.*\)\s*:\s*(.+)",
        "Negotiated Price (NP)": r"Negotiated\s*Price\s*\(.*NP.*\)\s*:\s*(.+)",
        "SRP Price": r"SRP\s*Price\s*:\s*(.+)",
        "Selling Price (SP)": r"Selling\s*Price\s*\(.*SP.*\)?\s*:\s*(.+)"
    }
    # Loop over each line in message and apply regex
    for line in text.splitlines():
        for field, pattern in patterns.items():
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                fields[field] = match.group(1).strip()
    return list(fields.values())

# ---------------- BRANCH EXTRACTION ----------------
def extract_branch(text):
    match = re.search(r"Branch\s*:\s*(.+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip().upper()
    return None

# ---------------- TELEGRAM HANDLER ----------------
# Listen to both source groups (if B is configured)
source_chats = [SOURCE_GROUP_A]
if SOURCE_GROUP_B:
    source_chats.append(SOURCE_GROUP_B)

@client.on(events.NewMessage(chats=source_chats))
async def handler(event):
    """
    Main handler: triggered when a new message arrives in any source group.
    It:
    - Identifies the source group
    - Selects the appropriate configuration (categories & targets)
    - Detects which category (mobile, laptop, accessories) it belongs to
    - Updates the corresponding Google Sheet
    - Forwards the message to category's target groups
    """
    msg = event.raw_text
    chat_id = event.chat_id
    logger.info(f"📩 Message received from {chat_id}: {msg}")

    # Get config for this specific source group
    config_map = SOURCE_CONFIGS.get(chat_id)
    if not config_map:
        logger.warning(f"⚠️ Received message from unconfigured chat {chat_id}")
        return

    # Loop over all categories in the selected config and check keyword matches
    for category, config in config_map.items():
        if any(keyword.lower() in msg.lower() for keyword in config["keywords"]):
            logger.info(f"✅ Matched category: {category} (Source: {chat_id})")

            # 1. Update Google Sheet
            if gclient and config["sheet_id"]:
                try:
                    worksheet = gclient.open_by_key(config["sheet_id"]).worksheet("Sheet1")
                    ist = pytz.timezone('Asia/Kolkata')
                    current_ist_date = datetime.now(ist).strftime('%Y-%m-%d')
                    row = [current_ist_date] + extract_fields(msg)
                    worksheet.append_row(row)
                    logger.info(f"📊 Data appended to {category} sheet")
                except Exception as e:
                    logger.error(f"❌ Failed to update Google Sheet for {category}: {e}")

            # 2. Forward to target Telegram groups
            for tg in config["targets"]:
                try:
                    await client.send_message(tg, msg)
                    logger.info(f"➡️ Forwarded to group {tg}")
                except Exception as e:
                    logger.error(f"❌ Failed to forward to {tg}: {e}")

    # ---------------- Branch routing ONLY for Group A i.e., Surya Real Time Sales ----------------
    if chat_id == SOURCE_GROUP_A:
        try:
            branch_value = extract_branch(msg)

            if branch_value:
                logger.info(f"🏬 Detected branch: {branch_value}")

            if branch_value and branch_value in STORE_GROUP_IDS:
                branch_target = STORE_GROUP_IDS[branch_value]

                await client.send_message(branch_target, msg)
                logger.info(f"🏬 Branch routing → {branch_value} → {branch_target}")

        except Exception as e:
            logger.error(f"❌ Branch routing failed: {e}")

# ---------------- KEEP ALIVE ----------------
async def keep_alive_task():
    """
    Periodically pings the Flask keep-alive endpoint
    so that Render does not spin down the service.
    """
    while True:
        try:
            service_url = os.getenv('RENDER_EXTERNAL_URL')
            if service_url:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{service_url}/keep-alive") as response:
                        logger.info(f"Keep-alive: {response.status}")
            else:
                logger.info("Keep-alive skipped (no RENDER_EXTERNAL_URL)")
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")
        await asyncio.sleep(840)  # Ping every 14 minutes (before Render timeout)


# ---------------- MAIN FUNCTION ----------------
async def start_bot():
    """
    Starts the Telethon client, begins listening for messages,
    and launches keep-alive task.
    """
    try:
        await client.start()
        logger.info("🚀 Client started successfully! Listening for messages...")
        asyncio.create_task(keep_alive_task())
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"❌ Error starting client: {e}")
        raise


if __name__ == '__main__':
    # Render requires Flask + Telethon to run in parallel
    if os.getenv('RENDER'):
        def run_telethon():
            asyncio.run(start_bot())
        threading.Thread(target=run_telethon, daemon=True).start()

        # Start Flask server
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
    else:
        # Local run: only start Telethon
        asyncio.run(start_bot())