import os
import re
import asyncio
import threading
import time
import qrcode
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ===== КОНФИГ =====
API_ID = 36474738
API_HASH = '4dd8134517fc74300fe610a4d385eaa5'
BOT_TOKEN = '8868463698:AAE2C7pPOdyk7ouT64w_O3LMW-BScIqQSCg'
BOT_USERNAME = 'ваш_бот_username'  # ЗАМЕНИТЕ НА ВАШ!

# Ссылка на бота для подписи
BOT_LINK = f"https://t.me/{BOT_USERNAME}"

# Хранилище
user_clients = {}
user_groups = {}
user_messages = {}
user_spamming = {}
login_states = {}
flood_wait_tracker = {}
user_string_sessions = {}
qr_sessions = {}  # Для хранения QR-кодов

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
    print(f"✅ Веб-сервер запущен на порту {port}")
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

# ===== QR-КОД АВТОРИЗАЦИЯ (как в Джарвисе) =====
async def generate_qr_code(user_id):
    """Генерирует QR-код для входа как в Джарвисе"""
    try:
        # Создаем клиент для QR-входа
        client = TelegramClient(
            StringSession(),
            API_ID,
            API_HASH,
            device_model="Desktop",
            system_version="Windows 10",
            app_version="4.16.30"
        )
        
        await client.connect()
        
        # Генерируем QR-код
        qr_login = await client.qr_login()
        
        # Сохраняем данные для проверки
        qr_sessions[user_id] = {
            'client': client,
            'qr_login': qr_login,
            'created_at': time.time()
        }
        
        # Создаем изображение QR-кода
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_login.url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Сохраняем в байты
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        return True, img_bytes, qr_login.url
    except Exception as e:
        return False, None, str(e)

async def check_qr_login(user_id):
    """Проверяет статус QR-входа"""
    if user_id not in qr_sessions:
        return False, "QR-сессия не найдена"
    
    data = qr_sessions[user_id]
    try:
        # Проверяем статус
        result = await data['qr_login'].wait()
        
        if result is not None:
            # Вход успешен
            client = data['client']
            session_string = client.session.save()
            
            # Сохраняем сессию
            user_string_sessions[user_id] = session_string
            user_clients[user_id] = client
            
            # Сохраняем файл
            with open(f'session_string_{user_id}.txt', 'w') as f:
                f.write(session_string)
            
            # Инициализируем хранилища
            if user_id not in user_groups:
                user_groups[user_id] = []
            if user_id not in user_messages:
                user_messages[user_id] = ""
            if user_id not in user_spamming:
                user_spamming[user_id] = False
            
            del qr_sessions[user_id]
            return True, "✅ Вход по QR-коду успешен!"
        else:
            return False, "⏳ Ожидание сканирования..."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

async def get_qr_instructions():
    return """
📱 *ВХОД ПО QR-КОДУ (как в Джарвисе)*

1️⃣ Нажми кнопку *"Сгенерировать QR"* ниже

2️⃣ Открой Telegram на телефоне

3️⃣ Перейди в *Настройки* → *Устройства* → 
   *Добавить устройство* (или Сканировать QR)

4️⃣ Наведи камеру на QR-код

5️⃣ Подтверди вход на телефоне

⚡ *Быстро и безопасно!*

ИЛИ используй вход по номеру телефона.
"""

# ===== ЛОГИН ПО НОМЕРУ (как в Джарвисе) =====
async def send_code_phone(user_id, phone):
    try:
        client = get_client(user_id)
        await client.connect()
        
        result = await client.send_code_request(phone)
        
        login_states[user_id] = {
            'step': 'code',
            'phone': phone,
            'hash': result.phone_code_hash,
            'attempts': 0
        }
        return True, "✅ Код отправлен в Telegram!"
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

async def verify_code_phone(user_id, code):
    if user_id not in login_states:
        return False, "❌ Сначала введите номер"
    
    data = login_states[user_id]
    client = get_client(user_id)
    
    try:
        await client.sign_in(data['phone'], code, phone_code_hash=data['hash'])
        del login_states[user_id]
        return True, "✅ Аккаунт авторизован!"
    except errors.PhoneCodeExpiredError:
        try:
            new_result = await client.send_code_request(data['phone'])
            login_states[user_id]['hash'] = new_result.phone_code_hash
            return False, "⚠️ Код истек. Отправлен новый."
        except Exception as e:
            return False, f"❌ Ошибка: {str(e)}"
    except errors.PhoneCodeInvalidError:
        return False, "❌ Неверный код"
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

# ===== ОТПРАВКА С ПОДПИСЬЮ =====
async def send_message_with_signature(client, chat_id, message):
    """Отправляет сообщение с подписью - ссылкой на бота"""
    signed_message = f"{message}\n\n—\n📨 Отправлено через [🤖 Бот]({BOT_LINK})"
    
    try:
        await client.send_message(chat_id, signed_message, parse_mode='Markdown')
        return True
    except Exception as e:
        # Если Markdown не поддерживается, отправляем без форматирования
        try:
            plain_message = f"{message}\n\n—\n📨 Отправлено через бот: {BOT_LINK}"
            await client.send_message(chat_id, plain_message)
            return True
        except:
            return False

# ===== КОМАНДЫ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📱 Вход по QR (как в Джарвисе)", callback_data='qr_login')],
        [InlineKeyboardButton("📱 Инструкция QR", callback_data='qr_help')],
        [InlineKeyboardButton("📱 Вход по номеру", callback_data='phone_login')],
        [InlineKeyboardButton("➕ Добавить группу", callback_data='add_group')],
        [InlineKeyboardButton("📝 Установить сообщение", callback_data='set_msg')],
        [InlineKeyboardButton("🚀 Запустить рассылку", callback_data='start_spam')],
        [InlineKeyboardButton("🛑 Остановить рассылку", callback_data='stop_spam')],
        [InlineKeyboardButton("📊 Статус", callback_data='status')],
        [InlineKeyboardButton("📋 Список групп", callback_data='groups')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🤖 *БОТ ДЛЯ РАССЫЛКИ*\n\n"
        "Войдите как в *Jarvis*:\n"
        "• QR-код (быстро и безопасно)\n"
        "• Или по номеру телефона\n\n"
        f"📨 Все сообщения будут с подписью: [🤖 Бот]({BOT_LINK})",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == 'qr_help':
        msg = await get_qr_instructions()
        await query.edit_message_text(msg, parse_mode='Markdown')
    
    elif query.data == 'qr_login':
        success, img_bytes, url = await generate_qr_code(user_id)
        if success:
            await query.edit_message_text(
                "📱 *Сканируй QR-код*\n\n"
                "Telegram → Настройки → Устройства → Добавить устройство\n\n"
                "⏳ Действует: 60 секунд",
                parse_mode='Markdown'
            )
            # Отправляем изображение QR-кода
            await query.message.reply_photo(
                photo=img_bytes,
                caption="📸 Отсканируй QR-код для входа"
            )
            
            # Запускаем проверку статуса
            asyncio.create_task(check_qr_status(query, user_id))
        else:
            await query.edit_message_text(f"❌ Ошибка: {url}")
    
    elif query.data == 'phone_login':
        login_states[user_id] = {'step': 'phone'}
        await query.edit_message_text(
            "📱 Введите номер телефона:\n"
            "Пример: `+998901234567`\n\n"
            "Код придет в Telegram",
            parse_mode='Markdown'
        )
    
    elif query.data == 'add_group':
        await query.edit_message_text(
            "📤 Отправь команду:\n`/add_group @username`\n\n"
            "Пример: `/add_group @durov`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'set_msg':
        await query.edit_message_text(
            "📤 Отправь команду:\n`/set_msg Твой текст`\n\n"
            "Пример: `/set_msg Привет всем!`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'start_spam':
        await start_spam(update, context, is_callback=True)
    
    elif query.data == 'stop_spam':
        user_spamming[user_id] = False
        await query.edit_message_text("🛑 Рассылка остановлена")
    
    elif query.data == 'status':
        ready = await is_user_ready(user_id)
        has_session = user_id in user_string_sessions
        groups_count = len(user_groups.get(user_id, []))
        spam_active = user_spamming.get(user_id, False)
        msg_preview = user_messages.get(user_id, "")[:30]
        
        await query.edit_message_text(
            f"📊 *Статус*\n\n"
            f"🔑 Аккаунт: {'✅ Вход выполнен' if ready else '❌ Не авторизован'}\n"
            f"💾 Сессия: {'✅ Сохранена' if has_session else '❌ Нет сессии'}\n"
            f"👥 Групп: {groups_count}\n"
            f"📝 Сообщение: {msg_preview if msg_preview else '❌ Не установлено'}\n"
            f"🔄 Рассылка: {'🔄 Активна' if spam_active else '⏸ Остановлена'}\n"
            f"🔗 Подпись: [🤖 Бот]({BOT_LINK})",
            parse_mode='Markdown'
        )
    
    elif query.data == 'groups':
        groups = user_groups.get(user_id, [])
        if not groups:
            await query.edit_message_text("📭 Нет групп. Добавь через /add_group")
        else:
            text = "\n".join([f"• {g}" for g in groups])
            await query.edit_message_text(f"📋 *Группы ({len(groups)}):*\n\n{text}", parse_mode='Markdown')

async def check_qr_status(query, user_id):
    """Проверяет статус QR-входа каждые 3 секунды"""
    for i in range(20):  # 20 попыток (60 секунд)
        await asyncio.sleep(3)
        success, msg = await check_qr_login(user_id)
        if success:
            await query.message.reply_text("✅ QR-вход успешен! Аккаунт авторизован.")
            return
        elif "не найдена" in msg:
            await query.message.reply_text("⏳ QR-сессия истекла. Попробуйте снова.")
            return
    
    await query.message.reply_text("⏰ QR-код истек. Попробуйте снова.")

async def start_spam(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    if is_callback:
        query = update.callback_query
        user_id = query.from_user.id
        reply = query.edit_message_text
    else:
        user_id = update.effective_user.id
        reply = update.message.reply_text
    
    if not await is_user_ready(user_id):
        await reply("❌ Сначала войдите в аккаунт")
        return
    
    if user_id not in user_messages or not user_messages[user_id]:
        await reply("❌ Сначала установите сообщение: /set_msg")
        return
    
    if user_id not in user_groups or not user_groups[user_id]:
        await reply("❌ Сначала добавьте группы: /add_group")
        return
    
    if user_spamming.get(user_id, False):
        await reply("⚠️ Рассылка уже идет!")
        return
    
    user_spamming[user_id] = True
    client = user_clients[user_id]
    groups = user_groups[user_id].copy()
    msg = user_messages[user_id]
    
    await reply(f"🚀 Начинаю рассылку в {len(groups)} групп...")
    await reply(f"📨 В конце каждого сообщения будет подпись: [🤖 Бот]({BOT_LINK})", parse_mode='Markdown')
    
    sent = 0
    errors = 0
    
    for i, group in enumerate(groups, 1):
        if not user_spamming.get(user_id, False):
            await reply(f"🛑 Остановлено. Отправлено: {sent}")
            break
        
        try:
            # Отправляем с подписью
            success = await send_message_with_signature(client, group, msg)
            if success:
                sent += 1
            else:
                errors += 1
                
            if i % 5 == 0:
                await reply(f"✅ {i}/{len(groups)} отправлено")
        except errors.FloodWaitError as e:
            wait_time = e.seconds + 2
            await reply(f"⏳ Ожидание {wait_time} сек (флуд)...")
            await asyncio.sleep(wait_time)
            # Пробуем еще раз
            success = await send_message_with_signature(client, group, msg)
            if success:
                sent += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1
            if errors % 5 == 0:
                await reply(f"⚠️ Ошибок: {errors}")
        
        await asyncio.sleep(3)
    
    user_spamming[user_id] = False
    await reply(f"✅ Готово! Отправлено: {sent}, ошибок: {errors}")

# ===== ОБРАБОТЧИК СООБЩЕНИЙ =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Обработка входа по номеру
    if user_id in login_states:
        step = login_states[user_id]['step']
        
        if step == 'phone':
            success, msg = await send_code_phone(user_id, text)
            if success:
                await update.message.reply_text(msg + "\nВведите код из Telegram:")
            else:
                await update.message.reply_text(f"{msg}\nПопробуйте /start")
                del login_states[user_id]
            return
        
        elif step == 'code':
            success, msg = await verify_code_phone(user_id, text)
            if success:
                await update.message.reply_text(msg)
                if user_id not in user_groups:
                    user_groups[user_id] = []
                if user_id not in user_messages:
                    user_messages[user_id] = ""
                if user_id not in user_spamming:
                    user_spamming[user_id] = False
                del login_states[user_id]
            else:
                await update.message.reply_text(msg)
            return
    
    # Остальные команды
    if text.startswith('/session'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ /session СТРОКА_СЕССИИ")
            return
        
        await update.message.reply_text("🔄 Проверяю...")
        session_string = parts[1].strip()
        success, msg = await login_with_session(user_id, session_string)
        await update.message.reply_text(msg)
        return
    
    if text.startswith('/add_group'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ /add_group @username")
            return
        
        group = parts[1].strip()
        if not group.startswith('@'):
            group = '@' + group
        
        if user_id not in user_groups:
            user_groups[user_id] = []
        
        if group in user_groups[user_id]:
            await update.message.reply_text(f"⚠️ {group} уже в списке")
        else:
            user_groups[user_id].append(group)
            await update.message.reply_text(f"✅ Добавлен {group} | Всего: {len(user_groups[user_id])}")
        return
    
    if text.startswith('/set_msg'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ /set_msg Текст")
            return
        
        user_messages[user_id] = parts[1].strip()
        await update.message.reply_text(
            f"✅ Сообщение сохранено!\n\n"
            f"📨 В конце будет добавлена подпись: [🤖 Бот]({BOT_LINK})",
            parse_mode='Markdown'
        )
        return
    
    if text == '/start':
        await start(update, context)
        return
    
    if text == '/help':
        await update.message.reply_text(
            "📋 *Команды:*\n\n"
            "/start - Главное меню\n"
            "/session СТРОКА - Вход по сессии\n"
            "/add_group @name - Добавить группу\n"
            "/set_msg текст - Установить сообщение\n"
            "/start_spam - Запустить рассылку\n"
            "/stop_spam - Остановить\n"
            "/status - Статус\n"
            "/groups - Список групп\n"
            "/help - Помощь",
            parse_mode='Markdown'
        )
        return
    
    if text == '/status':
        ready = await is_user_ready(user_id)
        has_session = user_id in user_string_sessions
        groups_count = len(user_groups.get(user_id, []))
        spam_active = user_spamming.get(user_id, False)
        msg_preview = user_messages.get(user_id, "")[:30]
        
        await update.message.reply_text(
            f"📊 *Статус*\n\n"
            f"🔑 Аккаунт: {'✅ Вход выполнен' if ready else '❌ Не авторизован'}\n"
            f"💾 Сессия: {'✅ Сохранена' if has_session else '❌ Нет сессии'}\n"
            f"👥 Групп: {groups_count}\n"
            f"📝 Сообщение: {msg_preview if msg_preview else '❌ Не установлено'}\n"
            f"🔄 Рассылка: {'🔄 Активна' if spam_active else '⏸ Остановлена'}\n"
            f"🔗 Подпись: [🤖 Бот]({BOT_LINK})",
            parse_mode='Markdown'
        )
        return
    
    if text == '/groups':
        groups = user_groups.get(user_id, [])
        if not groups:
            await update.message.reply_text("📭 Нет групп")
        else:
            text_list = "\n".join([f"• {g}" for g in groups])
            await update.message.reply_text(f"📋 *Группы ({len(groups)}):*\n\n{text_list}", parse_mode='Markdown')
        return
    
    if text == '/start_spam':
        await start_spam(update, context)
        return
    
    if text == '/stop_spam':
        user_spamming[user_id] = False
        await update.message.reply_text("🛑 Рассылка остановлена")
        return
    
    await update.message.reply_text(
        "ℹ️ Неизвестная команда. Используй /help"
    )

# ===== ВОССТАНОВЛЕНИЕ СЕССИЙ =====
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
            
            return True, "✅ Успешный вход!"
        else:
            await client.disconnect()
            return False, "❌ Сессия недействительна"
    
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)[:100]}"

# ===== ЗАПУСК =====
def main():
    # Восстанавливаем сессии
    for file in os.listdir('.'):
        if file.startswith('session_string_') and file.endswith('.txt'):
            try:
                user_id = int(file.replace('session_string_', '').replace('.txt', ''))
                with open(file, 'r') as f:
                    session_string = f.read().strip()
                if session_string:
                    user_string_sessions[user_id] = session_string
                    print(f"✅ Загружена сессия пользователя {user_id}")
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
    
    print("✅ Бот запущен с QR-входом (как в Джарвисе)!")
    print(f"🔗 Подпись: {BOT_LINK}")
    app.run_polling()

if __name__ == "__main__":
    main()
