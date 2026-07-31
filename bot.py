import os
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
BOT_USERNAME = 'vvfvdfdfbbxng_bot'
BOT_LINK = f"https://t.me/{BOT_USERNAME}"

# Канал спонсора
SPONSOR_CHANNEL = '@patrickstarsfarm'
SPONSOR_LINK = 'https://t.me/patrickstarsrobot?start=6378686913'

# Хранилище пользователей
user_data = {}

# Путь к фото
PHOTO_PATH = 'M.png'

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
    port = int(os.environ.get('PORT', 8888))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"✅ Веб-сервер запущен на порту {port}")
    server.serve_forever()

# ===== РАБОТА С ДАННЫМИ =====
def get_user_data(user_id):
    if user_id not in user_data:
        user_data[user_id] = {
            'is_subscribed': False,
            'subscription_attempts': 0,
            'groups': [],
            'message': '',
            'spamming': False,
            'client': None,
            'session': None,
            'login_state': None,
            'qr_session': None
        }
    return user_data[user_id]

def get_client(user_id):
    user = get_user_data(user_id)
    if user['client'] is None:
        session_string = user.get('session')
        if session_string:
            client = TelegramClient(
                StringSession(session_string),
                API_ID, API_HASH,
                device_model="Desktop",
                system_version="Windows 10",
                app_version="4.16.30"
            )
        else:
            client = TelegramClient(
                f'session_{user_id}',
                API_ID, API_HASH,
                device_model="Desktop",
                system_version="Windows 10",
                app_version="4.16.30"
            )
        user['client'] = client
    return user['client']

async def is_user_ready(user_id):
    user = get_user_data(user_id)
    client = user['client']
    if client is None:
        return False
    try:
        if not client.is_connected():
            await client.connect()
        return await client.is_user_authorized()
    except:
        return False

# ===== QR-КОД =====
async def generate_qr_code(user_id):
    try:
        client = TelegramClient(
            StringSession(),
            API_ID, API_HASH,
            device_model="Desktop",
            system_version="Windows 10",
            app_version="4.16.30"
        )
        await client.connect()
        qr_login = await client.qr_login()
        
        user = get_user_data(user_id)
        user['qr_session'] = {
            'client': client,
            'qr_login': qr_login,
            'created_at': time.time()
        }
        
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(qr_login.url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        return True, img_bytes, qr_login.url
    except Exception as e:
        return False, None, str(e)

async def check_qr_login(user_id):
    user = get_user_data(user_id)
    qr_data = user.get('qr_session')
    if not qr_data:
        return False, "QR-сессия не найдена"
    
    try:
        result = await qr_data['qr_login'].wait()
        if result is not None:
            client = qr_data['client']
            session_string = client.session.save()
            user['client'] = client
            user['session'] = session_string
            
            with open(f'session_string_{user_id}.txt', 'w') as f:
                f.write(session_string)
            
            user['qr_session'] = None
            return True, "✅ Вход по QR-коду успешен!"
        else:
            return False, "⏳ Ожидание сканирования..."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

async def get_qr_instructions():
    return """
📱 *ВХОД ПО QR-КОДУ*

1️⃣ Нажми кнопку *"Сгенерировать QR"* ниже

2️⃣ Открой Telegram на телефоне

3️⃣ Перейди в *Настройки* → *Устройства* → 
   *Добавить устройство* (или Сканировать QR)

4️⃣ Наведи камеру на QR-код

5️⃣ Подтверди вход на телефоне

⚡ *Быстро и безопасно!*
"""

# ===== ЛОГИН ПО НОМЕРУ =====
async def send_code_phone(user_id, phone):
    try:
        client = get_client(user_id)
        await client.connect()
        result = await client.send_code_request(phone)
        
        user = get_user_data(user_id)
        user['login_state'] = {
            'step': 'code',
            'phone': phone,
            'hash': result.phone_code_hash,
            'attempts': 0
        }
        return True, "✅ Код отправлен в Telegram!"
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

async def verify_code_phone(user_id, code):
    user = get_user_data(user_id)
    login_data = user.get('login_state')
    if not login_data:
        return False, "❌ Сначала введите номер"
    
    client = user['client']
    try:
        await client.sign_in(login_data['phone'], code, phone_code_hash=login_data['hash'])
        user['login_state'] = None
        return True, "✅ Аккаунт авторизован!"
    except errors.PhoneCodeExpiredError:
        try:
            new_result = await client.send_code_request(login_data['phone'])
            user['login_state']['hash'] = new_result.phone_code_hash
            return False, "⚠️ Код истек. Отправлен новый."
        except Exception as e:
            return False, f"❌ Ошибка: {str(e)}"
    except errors.PhoneCodeInvalidError:
        return False, "❌ Неверный код"
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

# ===== ОТПРАВКА С ПОДПИСЬЮ =====
async def send_message_with_signature(client, chat_id, message):
    signed_message = f"{message}\n\n—\n📨 Отправлено через [🤖 Бот]({BOT_LINK})"
    try:
        await client.send_message(chat_id, signed_message, parse_mode='Markdown')
        return True
    except:
        try:
            plain_message = f"{message}\n\n—\n📨 Отправлено через бот: {BOT_LINK}"
            await client.send_message(chat_id, plain_message)
            return True
        except:
            return False

# ===== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ОТПРАВКИ С ФОТО =====
async def send_with_photo(target, text, reply_markup=None, parse_mode='Markdown', is_callback=False):
    """Отправляет сообщение с фото M.png если файл существует"""
    if os.path.exists(PHOTO_PATH):
        with open(PHOTO_PATH, 'rb') as photo:
            if is_callback:
                await target.message.reply_photo(
                    photo=photo,
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                await target.message.delete()
            else:
                await target.reply_photo(
                    photo=photo,
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
    else:
        if is_callback:
            await target.message.reply_text(
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
            await target.message.delete()
        else:
            await target.reply_text(
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )

# ===== ГЛАВНОЕ МЕНЮ =====
async def show_main_menu(update, context, is_callback=False):
    keyboard = [
        [InlineKeyboardButton("📱 Вход по QR", callback_data='qr_login')],
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
    
    text = (
        "🤖 *БОТ ДЛЯ РАССЫЛКИ*\n\n"
        "✅ Вы успешно подписались на спонсора!\n"
        "Теперь вам доступны все функции.\n\n"
        f"📨 Подпись в сообщениях: [🤖 Бот]({BOT_LINK})"
    )
    
    if is_callback:
        await send_with_photo(update.callback_query, text, reply_markup, is_callback=True)
    else:
        await send_with_photo(update.message, text, reply_markup)

async def show_subscription_required(update, is_callback=False):
    keyboard = [
        [InlineKeyboardButton("📢 Подписаться на спонсора", url=SPONSOR_LINK)],
        [InlineKeyboardButton("✅ Проверить подписку", callback_data='check_subscription')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "👋 *Добро пожаловать в бота для рассылки!*\n\n"
        "Чтобы получить доступ к функциям, подпишитесь на спонсора:\n"
        "⭐️ *Патрик Stars | Звёзды и подарки бесплатно*\n\n"
        "После подписки нажмите *'Проверить подписку'*."
    )
    
    if is_callback:
        await send_with_photo(update.callback_query, text, reply_markup, is_callback=True)
    else:
        await send_with_photo(update.message, text, reply_markup)

# ===== КОМАНДА /start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    
    user['subscription_attempts'] = 0
    
    if user['is_subscribed']:
        await show_main_menu(update, context)
        return
    
    await show_subscription_required(update, is_callback=False)

# ===== ОБРАБОТЧИК КНОПОК =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user_data(user_id)
    
    # ===== ПРОВЕРКА ПОДПИСКИ =====
    if query.data == 'check_subscription':
        user['subscription_attempts'] += 1
        
        # Первое нажатие
        if user['subscription_attempts'] == 1:
            keyboard = [
                [InlineKeyboardButton("📢 Подписаться на спонсора", url=SPONSOR_LINK)],
                [InlineKeyboardButton("✅ Я подписался!", callback_data='check_subscription')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.answer()
            await query.edit_message_text(
                "❌ *Вы не подписаны на спонсора!*\n\n"
                "1. Нажмите *'Подписаться'*\n"
                "2. Подпишитесь на канал\n"
                "3. Нажмите *'Я подписался!'*",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return
        
        # Второе нажатие - показываем главное меню
        if user['subscription_attempts'] >= 2:
            user['is_subscribed'] = True
            await query.answer("✅ Доступ получен!")
            await show_main_menu(update, context, is_callback=True)
            return
    
    # ===== ПРОВЕРКА ПОДПИСКИ ДЛЯ ВСЕХ ОСТАЛЬНЫХ ДЕЙСТВИЙ =====
    if not user['is_subscribed']:
        await query.answer()
        await query.edit_message_text("⚠️ Для использования бота подпишитесь на спонсора.")
        await show_subscription_required(update, is_callback=True)
        return
    
    # ===== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ (БЫСТРЫЙ ОТВЕТ) =====
    await query.answer()
    
    if query.data == 'qr_help':
        msg = await get_qr_instructions()
        await send_with_photo(query, msg, is_callback=True)
    
    elif query.data == 'qr_login':
        success, img_bytes, url = await generate_qr_code(user_id)
        if success:
            # Отправляем инструкцию с фото
            await send_with_photo(
                query,
                "📱 *Сканируй QR-код*\n\nTelegram → Настройки → Устройства → Добавить устройство\n\n⏳ Действует: 60 секунд",
                is_callback=True
            )
            # Отправляем QR-код
            await query.message.reply_photo(photo=img_bytes, caption="📸 Отсканируй QR-код для входа")
            asyncio.create_task(check_qr_status(query, user_id))
        else:
            await send_with_photo(query, f"❌ Ошибка: {url}", is_callback=True)
    
    elif query.data == 'phone_login':
        user['login_state'] = {'step': 'phone'}
        await send_with_photo(
            query,
            "📱 Введите номер телефона:\nПример: `+998901234567`\n\nКод придет в Telegram\n\n⚠️ *Если вход по номеру не работает, используйте QR-код*",
            is_callback=True
        )
    
    elif query.data == 'add_group':
        await send_with_photo(
            query,
            "📤 Отправь команду:\n`/add_group @username`\n\nПример: `/add_group @durov`",
            is_callback=True
        )
    
    elif query.data == 'set_msg':
        await send_with_photo(
            query,
            "📤 Отправь команду:\n`/set_msg Твой текст`\n\nПример: `/set_msg Привет всем!`",
            is_callback=True
        )
    
    elif query.data == 'start_spam':
        await start_spam(update, context, is_callback=True)
    
    elif query.data == 'stop_spam':
        user['spamming'] = False
        await send_with_photo(query, "🛑 Рассылка остановлена", is_callback=True)
    
    elif query.data == 'status':
        ready = await is_user_ready(user_id)
        has_session = bool(user.get('session'))
        groups_count = len(user.get('groups', []))
        spam_active = user.get('spamming', False)
        msg_preview = user.get('message', '')[:30]
        
        text = (
            f"📊 *Статус*\n\n"
            f"🔑 Аккаунт: {'✅ Вход выполнен' if ready else '❌ Не авторизован'}\n"
            f"💾 Сессия: {'✅ Сохранена' if has_session else '❌ Нет сессии'}\n"
            f"👥 Групп: {groups_count}\n"
            f"📝 Сообщение: {msg_preview if msg_preview else '❌ Не установлено'}\n"
            f"🔄 Рассылка: {'🔄 Активна' if spam_active else '⏸ Остановлена'}\n"
            f"🔗 Подпись: [🤖 Бот]({BOT_LINK})"
        )
        await send_with_photo(query, text, is_callback=True)
    
    elif query.data == 'groups':
        groups = user.get('groups', [])
        if not groups:
            text = "📭 Нет групп. Добавь через /add_group"
        else:
            text = f"📋 *Группы ({len(groups)}):*\n\n" + "\n".join([f"• {g}" for g in groups])
        await send_with_photo(query, text, is_callback=True)

async def check_qr_status(query, user_id):
    for i in range(20):
        await asyncio.sleep(3)
        success, msg = await check_qr_login(user_id)
        if success:
            await query.message.reply_text("✅ QR-вход успешен!")
            return
    await query.message.reply_text("⏰ QR-код истек. Попробуйте снова.")

# ===== ЗАПУСК РАССЫЛКИ =====
async def start_spam(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    if is_callback:
        query = update.callback_query
        user_id = query.from_user.id
        reply_func = query.edit_message_text
        send_func = send_with_photo
    else:
        user_id = update.effective_user.id
        reply_func = update.message.reply_text
        send_func = send_with_photo
    
    user = get_user_data(user_id)
    
    if not await is_user_ready(user_id):
        await send_func(update, "❌ Сначала войдите в аккаунт", is_callback=is_callback)
        return
    
    if not user.get('message'):
        await send_func(update, "❌ Сначала установите сообщение: /set_msg", is_callback=is_callback)
        return
    
    if not user.get('groups'):
        await send_func(update, "❌ Сначала добавьте группы: /add_group", is_callback=is_callback)
        return
    
    if user.get('spamming', False):
        await send_func(update, "⚠️ Рассылка уже идет!", is_callback=is_callback)
        return
    
    user['spamming'] = True
    client = user['client']
    groups = user['groups'].copy()
    msg = user['message']
    
    await send_func(update, f"🚀 Начинаю рассылку в {len(groups)} групп...", is_callback=is_callback)
    await send_func(update, f"📨 В конце каждого сообщения будет подпись: [🤖 Бот]({BOT_LINK})", is_callback=is_callback)
    
    sent = 0
    errors = 0
    
    for i, group in enumerate(groups, 1):
        if not user['spamming']:
            await send_func(update, f"🛑 Остановлено. Отправлено: {sent}", is_callback=is_callback)
            break
        
        try:
            success = await send_message_with_signature(client, group, msg)
            if success:
                sent += 1
            else:
                errors += 1
            if i % 5 == 0:
                await send_func(update, f"✅ {i}/{len(groups)} отправлено", is_callback=is_callback)
        except errors.FloodWaitError as e:
            wait_time = e.seconds + 2
            await send_func(update, f"⏳ Ожидание {wait_time} сек (флуд)...", is_callback=is_callback)
            await asyncio.sleep(wait_time)
            success = await send_message_with_signature(client, group, msg)
            if success:
                sent += 1
            else:
                errors += 1
        except:
            errors += 1
        
        await asyncio.sleep(3)
    
    user['spamming'] = False
    await send_func(update, f"✅ Готово! Отправлено: {sent}, ошибок: {errors}", is_callback=is_callback)

# ===== ОБРАБОТЧИК СООБЩЕНИЙ =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    user = get_user_data(user_id)
    
    if not user['is_subscribed'] and text not in ['/start', '/help']:
        await send_with_photo(update.message, "⚠️ Для использования бота подпишитесь на спонсора. Используйте /start")
        return
    
    if user.get('login_state'):
        step = user['login_state'].get('step')
        
        if step == 'phone':
            success, msg = await send_code_phone(user_id, text)
            if success:
                await send_with_photo(update.message, msg + "\nВведите код из Telegram:")
            else:
                await send_with_photo(update.message, f"{msg}\nПопробуйте /start")
                user['login_state'] = None
            return
        
        elif step == 'code':
            success, msg = await verify_code_phone(user_id, text)
            if success:
                await send_with_photo(update.message, msg)
                if not user.get('groups'):
                    user['groups'] = []
                if not user.get('message'):
                    user['message'] = ""
                if not user.get('spamming'):
                    user['spamming'] = False
                user['login_state'] = None
            else:
                await send_with_photo(update.message, msg)
            return
    
    if text.startswith('/add_group'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_with_photo(update.message, "❌ /add_group @username")
            return
        
        group = parts[1].strip()
        if not group.startswith('@'):
            group = '@' + group
        
        if group in user.get('groups', []):
            await send_with_photo(update.message, f"⚠️ {group} уже в списке")
        else:
            user['groups'].append(group)
            await send_with_photo(update.message, f"✅ Добавлен {group} | Всего: {len(user['groups'])}")
        return
    
    if text.startswith('/set_msg'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_with_photo(update.message, "❌ /set_msg Текст")
            return
        
        user['message'] = parts[1].strip()
        await send_with_photo(
            update.message,
            f"✅ Сообщение сохранено!\n\n📨 В конце будет подпись: [🤖 Бот]({BOT_LINK})"
        )
        return
    
    if text == '/start':
        await start(update, context)
        return
    
    if text == '/help':
        await send_with_photo(
            update.message,
            "📋 *Команды:*\n\n"
            "/start - Главное меню\n"
            "/add_group @name - Добавить группу\n"
            "/set_msg текст - Установить сообщение\n"
            "/start_spam - Запустить рассылку\n"
            "/stop_spam - Остановить\n"
            "/status - Статус\n"
            "/groups - Список групп\n"
            "/help - Помощь"
        )
        return
    
    if text == '/status':
        ready = await is_user_ready(user_id)
        has_session = bool(user.get('session'))
        groups_count = len(user.get('groups', []))
        spam_active = user.get('spamming', False)
        msg_preview = user.get('message', '')[:30]
        
        text = (
            f"📊 *Статус*\n\n"
            f"🔑 Аккаунт: {'✅ Вход выполнен' if ready else '❌ Не авторизован'}\n"
            f"💾 Сессия: {'✅ Сохранена' if has_session else '❌ Нет сессии'}\n"
            f"👥 Групп: {groups_count}\n"
            f"📝 Сообщение: {msg_preview if msg_preview else '❌ Не установлено'}\n"
            f"🔄 Рассылка: {'🔄 Активна' if spam_active else '⏸ Остановлена'}\n"
            f"🔗 Подпись: [🤖 Бот]({BOT_LINK})"
        )
        await send_with_photo(update.message, text)
        return
    
    if text == '/groups':
        groups = user.get('groups', [])
        if not groups:
            text = "📭 Нет групп"
        else:
            text = f"📋 *Группы ({len(groups)}):*\n\n" + "\n".join([f"• {g}" for g in groups])
        await send_with_photo(update.message, text)
        return
    
    if text == '/start_spam':
        await start_spam(update, context)
        return
    
    if text == '/stop_spam':
        user['spamming'] = False
        await send_with_photo(update.message, "🛑 Рассылка остановлена")
        return
    
    await send_with_photo(update.message, "ℹ️ Неизвестная команда. Используй /help")

# ===== ЗАПУСК =====
def main():
    for file in os.listdir('.'):
        if file.startswith('session_string_') and file.endswith('.txt'):
            try:
                user_id = int(file.replace('session_string_', '').replace('.txt', ''))
                with open(file, 'r') as f:
                    session_string = f.read().strip()
                if session_string:
                    user = get_user_data(user_id)
                    user['session'] = session_string
                    print(f"✅ Загружена сессия пользователя {user_id}")
            except:
                pass
    
    threading.Thread(target=run_webserver, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", handle_message))
    app.add_handler(CommandHandler("add_group", handle_message))
    app.add_handler(CommandHandler("set_msg", handle_message))
    app.add_handler(CommandHandler("start_spam", handle_message))
    app.add_handler(CommandHandler("stop_spam", handle_message))
    app.add_handler(CommandHandler("status", handle_message))
    app.add_handler(CommandHandler("groups", handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен!")
    print(f"🔗 Подпись: {BOT_LINK}")
    if os.path.exists(PHOTO_PATH):
        print(f"📷 Фото {PHOTO_PATH} загружено")
    else:
        print(f"⚠️ Фото {PHOTO_PATH} не найдено")
    app.run_polling()

if __name__ == "__main__":
    main()
