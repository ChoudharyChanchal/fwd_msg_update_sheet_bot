from telethon import TelegramClient, events
import os
import re
import gspread
from google.oauth2.service_account import Credentials
import asyncio

# ---------------- KEEP-ALIVE TASK ----------------
async def keep_alive():
    while True:
        print("✅ Still alive...")
        await asyncio.sleep(10)  # every 10 minutes

# ---------------- TELEGRAM SETUP ----------------
api_id = int(os.environ['API_ID'])
api_hash = os.environ['API_HASH']
source_group = int(os.environ['SOURCE_GROUP'])
target_group = int(os.environ['TARGET_GROUP'])

client = TelegramClient('bot_session', api_id, api_hash)

# ---------------- GOOGLE SHEET SETUP ----------------
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
gclient = gspread.authorize(creds)
sheet_id = os.environ['SHEET_ID']
worksheet = gclient.open_by_key(sheet_id).worksheet("Sheet1")

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

    # Define regex patterns for each field
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
    print("Message received:", msg)

    if 'mobile' in msg.lower():
        # Extract and update Google Sheet first
        try:
            print("Extracting and updating to Google Sheet...")
            row = extract_fields(msg)
            worksheet.append_row(row)
            print("✅ Google Sheet updated!")
        except Exception as e:
            print("❌ Google Sheet update failed:", e)

        # Then try sending to target group
        try:
            print("Forwarding message...")
            await client.send_message(target_group, msg)
            print("✅ Message sent successfully.")
        except Exception as e:
            print("❌ Failed to send message:", e)

# ---------------- RUN ----------------
async def main():
    await client.start()
    print("Bot is running...")

    await asyncio.gather(
        client.run_until_disconnected(),
        keep_alive()
    )

asyncio.run(main())