import os
import re
import asyncio
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ===== КОНФИГ =====
API_ID = 36474738
API_HASH = '4dd8134517fc74300fe610a4d385eaa5'
BOT_TOKEN = '8868463698:AAE2C7pPOdyk7ouT64w_O3LMW-BScIqQSCg'

# Хранилище
user_clients = {}
user_groups = {}
user_messages = {}
user_spamming = {}
login_states = {}
flood_wait_tracker = {}
user_string_sessions = {}

# ===== ВЕБ-СЕРВЕР =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running!')
    
    def log_message(self, format, *args):
        pass

def run_webserver():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"Web server on port {port}")
    server.serve_forever()

# ===== КЛИЕНТЫ =====
def get_client(user_id):
    if user_id not in user_clients:
        session_string = user_string_sessions.get(user_id)
        if session_string:
            client = TelegramClient(
                StringSession(session_string),
                API_ID, 
                API_HASH,
                device_model="Desktop",
                system_version="Windows 10",
                app_version="4.16.30",
                lang_code="en",
                system_lang_code="en"
            )
        else:
            client = TelegramClient(
                f'session_{user_id}', 
                API_ID, 
                API_HASH,
                device_model="Desktop",
                system_version="Windows 10",
                app_version="4.16.30",
                lang_code="en",
                system_lang_code="en"
            )
        user_clients[user_id] = client
    return user_clients[user_id]

async def is_user_ready(user_id):
    if user_id not in user_clients:
        return False
    
    client = user_clients[user_id]
    try:
        if not client.is_connected():
            await client.connect()
        return await client.is_user_authorized()
    except:
        return False

# ===== ГЕНЕРАЦИЯ СЕССИИ (делается на компе пользователя) =====
async def get_session_instructions():
    """Инструкция по получению session string"""
    return """
📱 *ИНСТРУКЦИЯ ДЛЯ ВХОДА:*

1️⃣ Установи Python с https://python.org
2️⃣ Открой командную строку и введи:
`pip install telethon`

3️⃣ Создай файл `get_session.py` с кодом:
```python
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 36474738
API_HASH = '4dd8134517fc74300fe610a4d385eaa5'

async def main():
    client = TelegramClient(
        StringSession(), 
        API_ID, 
        API_HASH
    )
    await client.start()
    print("\\nТВОЯ СЕССИЯ (скопируй всю строку):")
    print(client.session.save())

import asyncio
asyncio.run(main())
