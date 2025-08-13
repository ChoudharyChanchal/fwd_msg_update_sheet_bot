from telethon import TelegramClient, events
from telethon.sessions import StringSession
import os
import re
import gspread
from google.oauth2.service_account import Credentials
import asyncio
from flask import Flask, request, jsonify
from datetime import datetime
import pytz


# ---------------- FLASK APP FOR RENDER ----------------
app = Flask(__name__)

@app.route('/')
def health_check():
    return jsonify({
        'status': 'alive',
        'message': 'Telethon bot is running!',
        'mode': 'user_account_bot'
    })

@app.route('/keep-alive')
def keep_alive_endpoint():
    return jsonify({'status': 'alive', 'timestamp': asyncio.get_event_loop().time()})


# ---------------- TELEGRAM SETUP ----------------
api_id = int(os.environ['API_ID'])
api_hash = os.environ['API_HASH']
session_string = os.environ['SESSION_STRING']  # 👈 NEW: StringSession from env
source_group = int(os.environ['SOURCE_GROUP'])
target_group = int(os.environ['TARGET_GROUP'])

# 👈 CHANGED: Use StringSession instead of file
client = TelegramClient(StringSession(session_string), api_id, api_hash)


# ---------------- GOOGLE SHEET SETUP ----------------
scopes = ["https://www.googleapis.com/auth/spreadsheets"]

# 👈 CHANGED: Handle both local and Render credential paths
credentials_path = '/etc/secrets/credentials.json'
if not os.path.exists(credentials_path):
    credentials_path = os.getenv('GOOGLE_SHEETS_CREDENTIALS_PATH', 'credentials.json')

try:
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    gclient = gspread.authorize(creds)
    sheet_id = os.environ['SHEET_ID']
    worksheet = gclient.open_by_key(sheet_id).worksheet("Sheet1")
    print("✅ Google Sheets client initialized")
except Exception as e:
    print(f"❌ Google Sheets setup failed: {e}")
    gclient = None
    worksheet = None


# ---------------- FIELD EXTRACTION (unchanged) ----------------
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


# ---------------- TELEGRAM HANDLER (unchanged) ----------------
@client.on(events.NewMessage(chats=source_group))
async def handler(event):
    msg = event.raw_text
    print("Message received:", msg)

    if 'mobile' in msg.lower():
        # Extract and update Google Sheet first
        try:
            if worksheet:
                print("Extracting and updating to Google Sheet...")
                # Get current IST date string
                ist = pytz.timezone('Asia/Kolkata')
                current_ist_date = datetime.now(ist).strftime('%Y-%m-%d')
                row = extract_fields(msg)
                # Add date as first column
                row = [current_ist_date] + row
                worksheet.append_row(row)
                print("✅ Google Sheet updated!")
            else:
                print("⚠️ Google Sheets not configured")
        except Exception as e:
            print("❌ Google Sheet update failed:", e)

        # Then try sending to target group
        try:
            print("Forwarding message...")
            await client.send_message(target_group, msg)
            print("✅ Message sent successfully.")
        except Exception as e:
            print("❌ Failed to send message:", e)


# ---------------- BACKGROUND KEEP ALIVE TASK ----------------
async def keep_alive_task():
    while True:
        print("✅ Bot still alive...")
        await asyncio.sleep(600)  # every 10 minutes


# ---------------- MAIN FUNCTION ----------------
async def start_bot():
    """Start the Telethon client"""
    try:
        print("🚀 Starting Telethon client...")
        await client.start()
        print("✅ Client started successfully!")
        print("👂 Listening for messages...")

        # Start background tasks
        asyncio.create_task(keep_alive_task())

        # Run until disconnected
        await client.run_until_disconnected()

    except Exception as e:
        print(f"❌ Error starting client: {e}")
        raise


# ---------------- RENDER DEPLOYMENT SETUP ----------------
if __name__ == '__main__':
    # Check if running on Render or locally
    if os.getenv('RENDER'):
        # Running on Render - start both Flask and Telethon
        print("🌐 Running on Render - starting Flask server...")

        # Start Telethon in background
        import threading
        def run_telethon():
            asyncio.run(start_bot())

        telethon_thread = threading.Thread(target=run_telethon, daemon=True)
        telethon_thread.start()

        # Start Flask server
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)

    else:
        # Running locally - just start Telethon
        print("💻 Running locally...")
        asyncio.run(start_bot())