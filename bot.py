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

API_ID = 36474738
API_HASH = '4dd8134517fc74300fe610a4d385eaa5'
BOT_TOKEN = '8868463698:AAE2C7pPOdyk7ouT64w_O3LMW-BScIqQSCg'

user_clients = {}
user_groups = {}
user_messages = {}
user_spamming = {}
login_states = {}
flood_wait_tracker = {}
user_string_sessions = {}

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

async def get_session_instructions():
    return """
Инструкция для входа:

1. Установи Python с python.org
2. Открой командную строку и введи: pip install telethon
3. Создай файл get_session.py с кодом:

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 36474738
API_HASH = '4dd8134517fc74300fe610a4d385eaa5'

async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start()
    print(client.session.save())

import asyncio
asyncio.run(main())

4. Запусти: python get_session.py
5. Введи номер и код из Telegram
6. Отправь полученную строку в бота: /session СТРОКА
"""

async def login_with_session(user_id, session_string):
    try:
        if user_id in user_clients:
            try:
                await user_clients[user_id].disconnect()
            except:
                pass
            del user_clients[user_id]
        
        session_file = f'session_{user_id}.session'
        if os.path.exists(session_file):
            os.remove(session_file)
        
        client = TelegramClient(
            StringSession(session_string),
            API_ID,
            API_HASH,
            device_model="Desktop",
            system_version="Windows 10",
            app_version="4.16.30"
        )
        
        await client.connect()
        await asyncio.sleep(1)
        
        if await client.is_user_authorized():
            user_clients[user_id] = client
            user_string_sessions[user_id] = session_string
            
            with open(f'session_string_{user_id}.txt', 'w') as f:
                f.write(session_string)
            
            if user_id not in user_groups:
                user_groups[user_id] = []
            if user_id not in user_messages:
                user_messages[user_id] = ""
            if user_id not in user_spamming:
                user_spamming[user_id] = False
            
            return True, "Успешный вход! Теперь можно делать рассылку."
        else:
            await client.disconnect()
            return False, "Сессия недействительна. Попробуйте снова."
    except Exception as e:
        return False, f"Ошибка: {str(e)[:100]}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Инструкция по входу", callback_data='login_help')],
        [InlineKeyboardButton("Войти по сессии", callback_data='login_session')],
        [InlineKeyboardButton("Добавить группу", callback_data='add_group')],
        [InlineKeyboardButton("Сообщение", callback_data='set_msg')],
        [InlineKeyboardButton("Запустить", callback_data='start_spam')],
        [InlineKeyboardButton("Остановить", callback_data='stop_spam')],
        [InlineKeyboardButton("Статус", callback_data='status')],
        [InlineKeyboardButton("Группы", callback_data='groups')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "БОТ ДЛЯ РАССЫЛКИ\n\n"
        "Используй вход по сессии - это работает.\n"
        "Нажми Инструкция по входу чтобы узнать как.",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == 'login_help':
        msg = await get_session_instructions()
        await query.edit_message_text(msg)
    
    elif query.data == 'login_session':
        await query.edit_message_text(
            "Отправь команду:\n/session ТВОЯ_СТРОКА_СЕССИИ\n\n"
            "Если нет сессии - нажми Инструкция по входу"
        )
    
    elif query.data == 'add_group':
        await query.edit_message_text("Отправь команду:\n/add_group @username\n\nПример: /add_group @durov")
    
    elif query.data == 'set_msg':
        await query.edit_message_text("Отправь команду:\n/set_msg Твой текст\n\nПример: /set_msg Привет всем!")
    
    elif query.data == 'start_spam':
        await start_spam(update, context, is_callback=True)
    
    elif query.data == 'stop_spam':
        user_spamming[user_id] = False
        await query.edit_message_text("Рассылка остановлена")
    
    elif query.data == 'status':
        ready = await is_user_ready(user_id)
        has_session = user_id in user_string_sessions
        groups_count = len(user_groups.get(user_id, []))
        spam_active = user_spamming.get(user_id, False)
        msg_preview = user_messages.get(user_id, "")[:30]
        
        await query.edit_message_text(
            f"Статус\n\n"
            f"Аккаунт: {'OK' if ready else 'Нет'}\n"
            f"Сессия: {'OK' if has_session else 'Нет'}\n"
            f"Групп: {groups_count}\n"
            f"Сообщение: {msg_preview if msg_preview else '---'}\n"
            f"Рассылка: {'активна' if spam_active else 'остановлена'}"
        )
    
    elif query.data == 'groups':
        groups = user_groups.get(user_id, [])
        if not groups:
            await query.edit_message_text("Нет групп. Добавь через /add_group")
        else:
            text = "\n".join([f"{g}" for g in groups])
            await query.edit_message_text(f"Группы ({len(groups)}):\n\n{text}")

async def start_spam(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    if is_callback:
        query = update.callback_query
        user_id = query.from_user.id
        reply = query.edit_message_text
    else:
        user_id = update.effective_user.id
        reply = update.message.reply_text
    
    if not await is_user_ready(user_id):
        await reply("Сначала войди в аккаунт")
        return
    
    if user_id not in user_messages or not user_messages[user_id]:
        await reply("Сначала установи сообщение: /set_msg")
        return
    
    if user_id not in user_groups or not user_groups[user_id]:
        await reply("Сначала добавь группы: /add_group")
        return
    
    if user_spamming.get(user_id, False):
        await reply("Рассылка уже идёт")
        return
    
    user_spamming[user_id] = True
    client = user_clients[user_id]
    groups = user_groups[user_id].copy()
    msg = user_messages[user_id]
    
    await reply(f"Начинаю рассылку в {len(groups)} групп...")
    
    sent = 0
    errors = 0
    
    for i, group in enumerate(groups, 1):
        if not user_spamming.get(user_id, False):
            await reply(f"Остановлено. Отправлено: {sent}")
            break
        
        try:
            await client.send_message(group, msg)
            sent += 1
            if i % 5 == 0:
                await reply(f"{i}/{len(groups)} отправлено")
        except errors.FloodWaitError as e:
            await asyncio.sleep(e.seconds + 2)
            try:
                await client.send_message(group, msg)
                sent += 1
            except:
                errors += 1
        except:
            errors += 1
        
        await asyncio.sleep(3)
    
    user_spamming[user_id] = False
    await reply(f"Готово! Отправлено: {sent}, ошибок: {errors}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text.startswith('/session'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("Отправь сессию так:\n/session ТВОЯ_СТРОКА\n\nЕсли нет сессии - нажми /start и потом Инструкция по входу")
            return
        
        await update.message.reply_text("Проверяю сессию...")
        session_string = parts[1].strip()
        success, msg = await login_with_session(user_id, session_string)
        await update.message.reply_text(msg)
        return
    
    if text.startswith('/add_group'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("/add_group @username")
            return
        
        group = parts[1].strip()
        if not group.startswith('@'):
            group = '@' + group
        
        if user_id not in user_groups:
            user_groups[user_id] = []
        
        if group in user_groups[user_id]:
            await update.message.reply_text(f"{group} уже в списке")
        else:
            user_groups[user_id].append(group)
            await update.message.reply_text(f"Добавлен {group} | Всего: {len(user_groups[user_id])}")
        return
    
    if text.startswith('/set_msg'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("/set_msg Текст сообщения")
            return
        
        user_messages[user_id] = parts[1].strip()
        await update.message.reply_text("Сообщение сохранено")
        return
    
    if text == '/start':
        await start(update, context)
        return
    
    if text == '/help':
        await update.message.reply_text(
            "Команды:\n\n"
            "/start - главное меню\n"
            "/session СТРОКА - вход по сессии\n"
            "/add_group @name - добавить группу\n"
            "/set_msg текст - сообщение\n"
            "/start_spam - запустить рассылку\n"
            "/stop_spam - остановить\n"
            "/status - статус\n"
            "/groups - список групп\n"
            "/help - помощь"
        )
        return
    
    if text == '/status':
        ready = await is_user_ready(user_id)
        has_session = user_id in user_string_sessions
        groups_count = len(user_groups.get(user_id, []))
        spam_active = user_spamming.get(user_id, False)
        
        await update.message.reply_text(
            f"Статус\n\n"
            f"Аккаунт: {'OK' if ready else 'Нет'}\n"
            f"Сессия: {'OK' if has_session else 'Нет'}\n"
            f"Групп: {groups_count}\n"
            f"Рассылка: {'активна' if spam_active else 'остановлена'}"
        )
        return
    
    if text == '/groups':
        groups = user_groups.get(user_id, [])
        if not groups:
            await update.message.reply_text("Нет групп")
        else:
            text = "\n".join([f"{g}" for g in groups])
            await update.message.reply_text(f"Группы ({len(groups)}):\n\n{text}")
        return
    
    if text == '/start_spam':
        await start_spam(update, context)
        return
    
    if text == '/stop_spam':
        user_spamming[user_id] = False
        await update.message.reply_text("Рассылка остановлена")
        return
    
    await update.message.reply_text("Неизвестная команда. Используй /help для списка команд.")

def main():
    for file in os.listdir('.'):
        if file.startswith('session_string_') and file.endswith('.txt'):
            try:
                user_id = int(file.replace('session_string_', '').replace('.txt', ''))
                with open(file, 'r') as f:
                    session_string = f.read().strip()
                    user_string_sessions[user_id] = session_string
                print(f"Загружена сессия пользователя {user_id}")
            except:
                pass
    
    threading.Thread(target=run_webserver, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", handle_message))
    app.add_handler(CommandHandler("session", handle_message))
    app.add_handler(CommandHandler("add_group", handle_message))
    app.add_handler(CommandHandler("set_msg", handle_message))
    app.add_handler(CommandHandler("start_spam", handle_message))
    app.add_handler(CommandHandler("stop_spam", handle_message))
    app.add_handler(CommandHandler("status", handle_message))
    app.add_handler(CommandHandler("groups", handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
