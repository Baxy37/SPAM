import os
import asyncio
import threading
import time
import qrcode
import io
import logging
import sys
import signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TimedOut, RetryAfter, Conflict

# === ЛОГИРОВАНИЕ ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === КОНФИГ ===
API_ID = 36474738
API_HASH = '4dd8134517fc74300fe610a4d385eaa5'
BOT_TOKEN = '8868463698:AAE2C7pPOdyk7ouT64w_O3LMW-BScIqQSCg'
BOT_USERNAME = 'vvfvdfdfbbxng_bot'
BOT_LINK = f"https://t.me/{BOT_USERNAME}"
SPONSOR_LINK = 'https://t.me/patrickstarsrobot?start=6378686913'
PHOTO_PATH = 'M.png'

PORT = int(os.environ.get('PORT', 8080))

user_data = {}
active_qr_tasks = {}

# === ВЕБ-СЕРВЕР ДЛЯ HEALTH CHECK ===
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/health', '/'):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        pass

def run_webserver():
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    logger.info(f"Health-сервер на порту {PORT}")
    server.serve_forever()

# === УТИЛИТЫ ===
def normalize_phone(phone):
    return '+' + ''.join(ch for ch in phone if ch.isdigit())

async def safe_send_message(context, chat_id, text, parse_mode='Markdown', reply_markup=None):
    try:
        await context.bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        return False

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
            'qr_session': None,
            'qr_checked': False,
            'photo_file_id': None,      # новое для фото
            'awaiting_group': False,    # новое для ввода группы
            'awaiting_msg': False       # новое для ввода сообщения
        }
    return user_data[user_id]

def get_client(user_id):
    user = get_user_data(user_id)
    if user['client'] is None:
        session_string = user.get('session')
        if session_string:
            client = TelegramClient(StringSession(session_string), API_ID, API_HASH,
                                    device_model="Desktop", system_version="Windows 10", app_version="4.16.30")
        else:
            client = TelegramClient(StringSession(), API_ID, API_HASH,
                                    device_model="Desktop", system_version="Windows 10", app_version="4.16.30")
        user['client'] = client
    return user['client']

async def is_user_ready(user_id):
    user = get_user_data(user_id)
    client = user.get('client')
    if client is None:
        return False
    try:
        if not client.is_connected():
            await client.connect()
        return await client.is_user_authorized()
    except:
        return False

# === QR-КОД (с запросом пароля 2FA в чате) ===
async def generate_qr_code(user_id):
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH,
                                device_model="Desktop", system_version="Windows 10", app_version="4.16.30")
        await client.connect()
        qr_login = await client.qr_login()
        user = get_user_data(user_id)
        user['qr_session'] = {
            'client': client,
            'qr_login': qr_login,
            'created_at': time.time()
        }
        user['qr_checked'] = False
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(qr_login.url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return True, img_bytes, qr_login.url
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        return False, None, str(e)

async def check_qr_login(user_id, context, chat_id):
    user = get_user_data(user_id)
    qr_data = user.get('qr_session')
    if not qr_data:
        return False, "QR-сессия не найдена"
    try:
        client = qr_data['client']
        qr_login = qr_data['qr_login']
        try:
            result = await qr_login.wait(timeout=1)
            if result is not None:
                session_string = client.session.save()
                user['client'] = client
                user['session'] = session_string
                user['qr_checked'] = True
                with open(f'session_string_{user_id}.txt', 'w') as f:
                    f.write(session_string)
                user['qr_session'] = None
                return True, "✅ Вход по QR-коду успешен!"
        except asyncio.TimeoutError:
            pass
        except errors.SessionPasswordNeededError:
            user['login_state'] = {'step': 'password', 'client': client, 'qr_login': qr_login}
            await safe_send_message(context, chat_id,
                                    "🔐 Требуется пароль двухфакторной аутентификации. Введите пароль (напишите его в чат):")
            return False, "PASSWORD_NEEDED"
        except Exception as e:
            logger.error(f"QR check error: {e}")
            await safe_send_message(context, chat_id, f"❌ Ошибка входа: {str(e)}")
            return False, f"Ошибка: {str(e)}"

        if await client.is_user_authorized():
            session_string = client.session.save()
            user['client'] = client
            user['session'] = session_string
            user['qr_checked'] = True
            with open(f'session_string_{user_id}.txt', 'w') as f:
                f.write(session_string)
            user['qr_session'] = None
            return True, "✅ Вход по QR-коду успешен!"
        return False, "⏳ Ожидание..."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

async def check_qr_status(query, user_id, context):
    if user_id in active_qr_tasks:
        active_qr_tasks[user_id].cancel()
    active_qr_tasks[user_id] = asyncio.current_task()
    chat_id = query.message.chat_id
    await safe_send_message(context, chat_id,
        "⏳ Ожидание входа...\n\n"
        "📱 Отсканируйте QR-код в приложении Telegram (Настройки → Устройства → Добавить устройство).\n"
        "🔐 Если появится запрос пароля — бот попросит его ввести здесь."
    )
    for i in range(60):
        await asyncio.sleep(2)
        success, msg = await check_qr_login(user_id, context, chat_id)
        if success:
            await safe_send_message(context, chat_id, "✅ QR-вход успешен! Аккаунт авторизован.")
            await show_main_menu_after_login(query, user_id)
            return
        if msg == "PASSWORD_NEEDED":
            return
        if "ошибка" in msg.lower():
            await safe_send_message(context, chat_id, msg)
            return
        if i % 10 == 0 and i > 0:
            await safe_send_message(context, chat_id, f"⏳ Всё ещё ждём... ({i*2} сек)")
    await safe_send_message(context, chat_id, "⏰ Время ожидания истекло. Попробуйте снова.")
    user = get_user_data(user_id)
    if user.get('qr_session'):
        try:
            await user['qr_session']['client'].disconnect()
        except:
            pass
        user['qr_session'] = None

async def finish_qr_with_password(user_id, password):
    user = get_user_data(user_id)
    login_state = user.get('login_state')
    if not login_state or login_state.get('step') != 'password':
        return False, "❌ Нет активного запроса пароля."
    client = login_state['client']
    try:
        await client.sign_in(password=password)
        session_string = client.session.save()
        user['client'] = client
        user['session'] = session_string
        user['qr_checked'] = True
        with open(f'session_string_{user_id}.txt', 'w') as f:
            f.write(session_string)
        user['login_state'] = None
        user['qr_session'] = None
        return True, "✅ Аккаунт успешно авторизован с паролем!"
    except errors.SessionPasswordNeededError:
        return False, "❌ Неверный пароль. Попробуйте снова."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

# === ВХОД ПО НОМЕРУ (с запросом пароля 2FA в чате) ===
async def send_code_phone(user_id, phone):
    phone = normalize_phone(phone)
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
    except errors.FloodWaitError as e:
        wait_min = e.seconds // 60
        return False, f"⏳ Слишком много попыток. Подождите {wait_min} мин. Используйте QR-код."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

async def verify_code_phone(user_id, code, context, chat_id):
    user = get_user_data(user_id)
    login_data = user.get('login_state')
    if not login_data or login_data.get('step') != 'code':
        return False, "❌ Сначала введите номер"
    client = user['client']
    phone = login_data['phone']
    hash_code = login_data['hash']
    try:
        await client.sign_in(phone, code, phone_code_hash=hash_code)
        user['login_state'] = None
        session_string = client.session.save()
        user['session'] = session_string
        with open(f'session_string_{user_id}.txt', 'w') as f:
            f.write(session_string)
        return True, "✅ Аккаунт авторизован!"
    except errors.SessionPasswordNeededError:
        user['login_state'] = {'step': 'password_phone', 'client': client, 'phone': phone}
        await safe_send_message(context, chat_id,
                                "🔐 Требуется пароль двухфакторной аутентификации. Введите пароль (напишите его в чат):")
        return False, "PASSWORD_NEEDED"
    except errors.PhoneCodeExpiredError:
        user['login_state'] = None
        return False, "⚠️ Код истек. Запросите новый код через повторный ввод номера."
    except errors.PhoneCodeInvalidError:
        user['login_state'] = None
        return False, "❌ Неверный код. Запросите новый код через повторный ввод номера."
    except errors.FloodWaitError as e:
        wait_min = e.seconds // 60
        return False, f"⏳ Слишком много попыток. Подождите {wait_min} мин. Используйте QR-код."
    except Exception as e:
        user['login_state'] = None
        logger.error(f"Ошибка входа по номеру: {type(e).__name__}: {e}")
        return False, f"❌ Ошибка: {str(e)}"

async def finish_phone_with_password(user_id, password):
    user = get_user_data(user_id)
    login_state = user.get('login_state')
    if not login_state or login_state.get('step') != 'password_phone':
        return False, "❌ Нет активного запроса пароля."
    client = login_state['client']
    try:
        await client.sign_in(password=password)
        session_string = client.session.save()
        user['client'] = client
        user['session'] = session_string
        with open(f'session_string_{user_id}.txt', 'w') as f:
            f.write(session_string)
        user['login_state'] = None
        return True, "✅ Аккаунт авторизован!"
    except errors.SessionPasswordNeededError:
        return False, "❌ Неверный пароль. Попробуйте снова."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

# === РАССЫЛКА (с поддержкой фото) ===
async def send_message_with_signature(client, chat_id, message, photo_file_id=None):
    signed = f"{message}\n\n—\n📨 Отправлено через [🤖 Бот]({BOT_LINK})"
    try:
        if photo_file_id:
            await client.send_file(chat_id, photo_file_id, caption=signed, parse_mode='Markdown')
        else:
            await client.send_message(chat_id, signed, parse_mode='Markdown')
        return True
    except:
        try:
            plain = f"{message}\n\n—\n📨 Отправлено через бот: {BOT_LINK}"
            if photo_file_id:
                await client.send_file(chat_id, photo_file_id, caption=plain)
            else:
                await client.send_message(chat_id, plain)
            return True
        except:
            return False

# === МЕНЮ ===
async def send_menu_message(target, text, reply_markup, photo_bytes=None):
    for _ in range(2):
        try:
            if photo_bytes:
                await target.reply_photo(photo=photo_bytes, caption=text, parse_mode='Markdown', reply_markup=reply_markup)
            else:
                await target.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
            return True
        except (TimedOut, RetryAfter):
            await asyncio.sleep(1)
        except Exception:
            return False
    return False

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
    user_id = update.effective_user.id
    ready = await is_user_ready(user_id)
    status_text = "✅ Аккаунт подключен" if ready else "❌ Аккаунт не подключен"
    text = (
        f"🤖 *БОТ ДЛЯ РАССЫЛКИ*\n\n"
        f"{status_text}\n\n"
        "✅ Вы успешно активировали бота!\n"
        "Теперь вам доступны все функции.\n\n"
        f"📨 Подпись в сообщениях: [🤖 Бот]({BOT_LINK})"
    )

    target = update.callback_query.message if is_callback else update.message
    if is_callback:
        try:
            await update.callback_query.answer()
        except:
            pass

    photo_bytes = None
    if os.path.exists(PHOTO_PATH):
        with open(PHOTO_PATH, 'rb') as photo:
            photo_bytes = photo.read()

    await send_menu_message(target, text, reply_markup, photo_bytes)

    if is_callback:
        try:
            await target.delete()
        except:
            pass

async def show_main_menu_after_login(query, user_id):
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
        f"🤖 *БОТ ДЛЯ РАССЫЛКИ*\n\n"
        f"✅ Аккаунт подключен\n\n"
        "✅ Вы успешно активировали бота!\n"
        "Теперь вам доступны все функции.\n\n"
        f"📨 Подпись в сообщениях: [🤖 Бот]({BOT_LINK})"
    )
    photo_bytes = None
    if os.path.exists(PHOTO_PATH):
        with open(PHOTO_PATH, 'rb') as photo:
            photo_bytes = photo.read()
    await send_menu_message(query.message, text, reply_markup, photo_bytes)

async def show_subscription_required(update, is_callback=False):
    keyboard = [
        [InlineKeyboardButton("📢 Подписаться на канал", url=SPONSOR_LINK)],
        [InlineKeyboardButton("✅ Подтвердить подписку", callback_data='check_subscription')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        "👋 *Добро пожаловать в бота для рассылки!*\n\n"
        "Чтобы получить доступ к функциям:\n"
        "1️⃣ Подписаться на канал\n"
        "2️⃣ Активировать бота\n\n"
        "После подписки нажмите *'Подтвердить подписку'*."
    )
    if is_callback:
        target = update.callback_query.message
        try:
            await update.callback_query.answer()
        except:
            pass
        await target.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        try:
            await target.delete()
        except:
            pass
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

# === КОМАНДЫ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    user['login_state'] = None
    user['qr_session'] = None
    user['subscription_attempts'] = 0
    if user['is_subscribed']:
        await show_main_menu(update, context)
    else:
        await show_subscription_required(update, is_callback=False)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    user['login_state'] = None
    user['qr_session'] = None
    user['spamming'] = False
    if user.get('client'):
        try:
            await user['client'].disconnect()
        except:
            pass
        user['client'] = None
    await update.message.reply_text("🔄 Состояние сброшено.")
    await show_main_menu(update, context)

# === ОБРАБОТЧИК КНОПОК ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user_data(user_id)

    if query.data == 'check_subscription':
        user['subscription_attempts'] += 1
        if user['subscription_attempts'] == 1:
            keyboard = [
                [InlineKeyboardButton("📢 Подписаться на канал", url=SPONSOR_LINK)],
                [InlineKeyboardButton("✅ Активировать бота", callback_data='check_subscription')],
            ]
            await query.answer("Подпишитесь на канал")
            await query.message.reply_text(
                "❌ *Вы не подписаны на канал!*\n\n"
                "1. Нажмите *'Подписаться на канал'*\n"
                "2. Подпишитесь\n"
                "3. Нажмите *'Активировать бота'*",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            try:
                await query.message.delete()
            except:
                pass
            return
        if user['subscription_attempts'] >= 2:
            user['is_subscribed'] = True
            await query.answer("✅ Бот активирован!")
            await show_main_menu(update, context, is_callback=True)
            return

    if not user['is_subscribed']:
        await query.answer("⚠️ Подпишитесь на канал")
        await query.message.reply_text("⚠️ Для использования бота подпишитесь на канал.")
        await show_subscription_required(update, is_callback=True)
        return

    await query.answer()

    if query.data == 'qr_help':
        msg = (
            "📱 *ВХОД ПО QR-КОДУ*\n\n"
            "1️⃣ Нажми кнопку *«Сгенерировать QR»* ниже\n"
            "2️⃣ Открой Telegram на телефоне\n"
            "3️⃣ Перейди в *Настройки* → *Устройства* → *Добавить устройство*\n"
            "4️⃣ Наведи камеру на QR-код\n"
            "5️⃣ Подтверди вход на телефоне\n"
            "🔐 *Если появится запрос облачного пароля – введите его прямо сюда, в чат с ботом.*\n"
            "⚡ *Быстро и безопасно!*"
        )
        await query.message.reply_text(msg, parse_mode='Markdown')
        try:
            await query.message.delete()
        except:
            pass

    elif query.data == 'qr_login':
        success, img_bytes, url = await generate_qr_code(user_id)
        if success:
            await query.message.reply_text(
                "📱 *Сканируй QR-код*\n\n"
                "Telegram → Настройки → Устройства → Добавить устройство\n\n"
                "🔐 Если потребуется пароль – бот попросит его здесь.\n"
                "⏳ Ожидание до 2 минут",
                parse_mode='Markdown'
            )
            await query.message.reply_photo(photo=img_bytes, caption="📸 Отсканируй QR-код для входа")
            try:
                await query.message.delete()
            except:
                pass
            asyncio.create_task(check_qr_status(query, user_id, context))
        else:
            await query.message.reply_text(f"❌ Ошибка: {url}")
            try:
                await query.message.delete()
            except:
                pass

    elif query.data == 'phone_login':
        user['login_state'] = {'step': 'phone'}
        await query.message.reply_text(
            "📱 Введите номер телефона:\n"
            "Пример: `+79675604496` или `89675604496`\n\n"
            "Код придет в Telegram\n\n"
            "⚠️ *Если вход по номеру не работает, используйте QR-код*",
            parse_mode='Markdown'
        )
        try:
            await query.message.delete()
        except:
            pass

    # === ИЗМЕНЁННЫЕ КНОПКИ (без @bot) ===
    elif query.data == 'add_group':
        user['awaiting_group'] = True
        user['awaiting_msg'] = False
        await query.message.reply_text(
            "📤 *Добавление группы*\n\n"
            "✏️ Введите *username* или *ссылку* на группу.\n"
            "📌 *Примеры:* `@durov` или `https://t.me/durov`\n\n"
            "Просто напишите это в чат.",
            parse_mode='Markdown'
        )
        try:
            await query.message.delete()
        except:
            pass

    elif query.data == 'set_msg':
        user['awaiting_msg'] = True
        user['awaiting_group'] = False
        await query.message.reply_text(
            "📝 *Установка сообщения*\n\n"
            "✏️ Введите текст сообщения.\n"
            "📌 *Пример:* `Всем привет! Это тестовое сообщение.`\n\n"
            "Просто напишите его в чат.",
            parse_mode='Markdown'
        )
        try:
            await query.message.delete()
        except:
            pass

    elif query.data == 'back_to_menu':
        # Эта кнопка больше не используется, но оставлена для совместимости
        await show_main_menu(update, context, is_callback=True)

    elif query.data == 'start_spam':
        await start_spam(update, context, is_callback=True)

    elif query.data == 'stop_spam':
        user['spamming'] = False
        await query.message.reply_text("🛑 Рассылка остановлена")
        try:
            await query.message.delete()
        except:
            pass

    elif query.data in ('status', 'groups'):
        ready = await is_user_ready(user_id)
        groups = user.get('groups', [])
        msg_preview = user.get('message', '')[:30]
        if query.data == 'status':
            text = (
                f"📊 *Статус*\n\n"
                f"🔑 Аккаунт: {'✅ Вход выполнен' if ready else '❌ Не авторизован'}\n"
                f"💾 Сессия: {'✅ Сохранена' if user.get('session') else '❌ Нет'}\n"
                f"👥 Групп: {len(groups)}\n"
                f"📝 Сообщение: {msg_preview if msg_preview else '❌ Не установлено'}\n"
                f"🔄 Рассылка: {'🔄 Активна' if user.get('spamming') else '⏸ Остановлена'}\n"
                f"🔗 Подпись: [🤖 Бот]({BOT_LINK})"
            )
        else:
            text = f"📋 *Группы ({len(groups)}):*\n\n" + "\n".join([f"• {g}" for g in groups]) if groups else "📭 Нет групп"
        await query.message.reply_text(text, parse_mode='Markdown')
        try:
            await query.message.delete()
        except:
            pass

# === ЗАПУСК РАССЫЛКИ (ЦИКЛИЧЕСКИ) ===
async def start_spam(update, context, is_callback=False):
    query = update.callback_query if is_callback else None
    user_id = query.from_user.id if is_callback else update.effective_user.id
    reply = query.message.reply_text if is_callback else update.message.reply_text
    user = get_user_data(user_id)

    if not await is_user_ready(user_id):
        await reply("❌ Сначала войдите в аккаунт")
        return
    if not user.get('message'):
        await reply("❌ Сначала установите сообщение")
        return
    if not user.get('groups'):
        await reply("❌ Сначала добавьте группы")
        return
    if user.get('spamming', False):
        await reply("⚠️ Рассылка уже идет!")
        return

    user['spamming'] = True
    client = user['client']
    groups = user['groups'][:]
    msg = user['message']
    photo = user.get('photo_file_id')
    await reply(f"🚀 Начинаю рассылку в {len(groups)} групп. Цикл каждые 2 минуты.")
    sent_total = 0
    errors_total = 0

    while user['spamming']:
        sent = 0
        errors = 0
        for group in groups:
            if not user['spamming']:
                break
            try:
                success = await send_message_with_signature(client, group, msg, photo)
                if success:
                    sent += 1
                else:
                    errors += 1
            except errors.FloodWaitError as e:
                await reply(f"⏳ Ожидание {e.seconds+2} сек...")
                await asyncio.sleep(e.seconds+2)
                success = await send_message_with_signature(client, group, msg, photo)
                if success:
                    sent += 1
                else:
                    errors += 1
            except Exception:
                errors += 1
            await asyncio.sleep(2)

        sent_total += sent
        errors_total += errors

        if user['spamming']:
            await reply(
                f"🔄 Цикл завершен. Отправлено в этом цикле: {sent}, ошибок: {errors}. "
                f"Всего отправлено: {sent_total}. Пауза 2 минуты..."
            )
            for _ in range(120):
                if not user['spamming']:
                    break
                await asyncio.sleep(1)

    user['spamming'] = False
    await reply(f"🛑 Рассылка остановлена. Всего отправлено: {sent_total}, ошибок: {errors_total}")

# === ОБРАБОТЧИК ТЕКСТА (включая подписи к фото) ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else None
    user = get_user_data(user_id)
    chat_id = update.effective_chat.id

    # === Обработка состояний входа ===
    if user.get('login_state'):
        step = user['login_state']['step']
        if step == 'phone':
            if not text:
                await update.message.reply_text("❌ Пожалуйста, отправьте номер текстом.")
                return
            phone = normalize_phone(text)
            success, msg = await send_code_phone(user_id, phone)
            await update.message.reply_text(msg)
            return
        elif step == 'code':
            if not text:
                await update.message.reply_text("❌ Отправьте код подтверждения.")
                return
            success, msg = await verify_code_phone(user_id, text, context, chat_id)
            if success:
                await update.message.reply_text(msg)
                await show_main_menu(update, context)
            elif msg != "PASSWORD_NEEDED":
                await update.message.reply_text(msg)
            return
        elif step == 'password':
            if not text:
                await update.message.reply_text("❌ Отправьте пароль.")
                return
            success, msg = await finish_qr_with_password(user_id, text)
            await update.message.reply_text(msg)
            if success:
                await show_main_menu(update, context)
            return
        elif step == 'password_phone':
            if not text:
                await update.message.reply_text("❌ Отправьте пароль.")
                return
            success, msg = await finish_phone_with_password(user_id, text)
            await update.message.reply_text(msg)
            if success:
                await show_main_menu(update, context)
            return

    # === Обработка ожиданий ввода (группа или сообщение) ===
    if user.get('awaiting_group'):
        user['awaiting_group'] = False
        if not text:
            await update.message.reply_text("❌ Введите текст.")
            return
        group = text.strip()
        if not group.startswith('@') and not group.startswith('https://t.me/'):
            group = '@' + group
        if group in user.get('groups', []):
            await update.message.reply_text(f"⚠️ {group} уже в списке")
        else:
            user['groups'].append(group)
            await update.message.reply_text(f"✅ Добавлен {group} | Всего: {len(user['groups'])}")
        return

    if user.get('awaiting_msg'):
        user['awaiting_msg'] = False
        if not text:
            await update.message.reply_text("❌ Введите текст.")
            return
        user['message'] = text.strip()
        await update.message.reply_text(f"✅ Сообщение сохранено! 📨 Будет подпись: [🤖 Бот]({BOT_LINK})", parse_mode='Markdown')
        return

    # === Обработка фото (если пользователь прислал фото для рассылки) ===
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        user['photo_file_id'] = photo_file_id
        if update.message.caption:
            user['message'] = update.message.caption.strip()
        await update.message.reply_text("📸 Фото сохранено для рассылки!" + 
                              (f"\nТекст: {user['message'][:50]}..." if user.get('message') else ""))
        return

    # === Проверка подписки ===
    if not user['is_subscribed']:
        await update.message.reply_text("⚠️ Подпишитесь на канал. /start")
        return

    # === Команды (без @bot) ===
    if text and text.startswith('/'):
        parts = text.split(maxsplit=1)
        raw_cmd = parts[0].strip()
        cmd = raw_cmd.split('@')[0]
        arg = parts[1].strip() if len(parts) > 1 else None

        if cmd == '/add_group':
            if arg is None:
                await update.message.reply_text("❌ Введите username группы. Пример: `/add_group @durov`")
            else:
                group = arg
                if not group.startswith('@') and not group.startswith('https://t.me/'):
                    group = '@' + group
                if group in user.get('groups', []):
                    await update.message.reply_text(f"⚠️ {group} уже в списке")
                else:
                    user['groups'].append(group)
                    await update.message.reply_text(f"✅ Добавлен {group} | Всего: {len(user['groups'])}")
            return

        elif cmd == '/set_msg':
            if arg is None:
                await update.message.reply_text("❌ Введите текст сообщения. Пример: `/set_msg Всем привет!`")
            else:
                user['message'] = arg
                await update.message.reply_text(f"✅ Сообщение сохранено! 📨 Будет подпись: [🤖 Бот]({BOT_LINK})", parse_mode='Markdown')
            return

        elif cmd == '/start':
            await start(update, context)
            return
        elif cmd == '/reset':
            await reset(update, context)
            return
        elif cmd == '/help':
            await update.message.reply_text(
                "📋 *Команды:*\n\n"
                "/start - Главное меню\n"
                "/reset - Сбросить состояние входа\n"
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
        elif cmd == '/status':
            ready = await is_user_ready(user_id)
            has_session = bool(user.get('session'))
            groups_count = len(user.get('groups', []))
            spam_active = user.get('spamming', False)
            msg_preview = user.get('message', '')[:30]
            await update.message.reply_text(
                f"📊 *Статус*\n\n"
                f"🔑 Аккаунт: {'✅ Вход выполнен' if ready else '❌ Не авторизован'}\n"
                f"💾 Сессия: {'✅ Сохранена' if has_session else '❌ Нет'}\n"
                f"👥 Групп: {groups_count}\n"
                f"📝 Сообщение: {msg_preview if msg_preview else '❌ Не установлено'}\n"
                f"🔄 Рассылка: {'🔄 Активна' if spam_active else '⏸ Остановлена'}\n"
                f"🔗 Подпись: [🤖 Бот]({BOT_LINK})",
                parse_mode='Markdown'
            )
            return
        elif cmd == '/groups':
            groups = user.get('groups', [])
            text_out = f"📋 *Группы ({len(groups)}):*\n\n" + "\n".join([f"• {g}" for g in groups]) if groups else "📭 Нет групп"
            await update.message.reply_text(text_out, parse_mode='Markdown')
            return
        elif cmd == '/start_spam':
            await start_spam(update, context, is_callback=False)
            return
        elif cmd == '/stop_spam':
            user['spamming'] = False
            await update.message.reply_text("🛑 Рассылка остановлена")
            return
        else:
            await update.message.reply_text("ℹ️ Неизвестная команда. Используй /help")
            return
    else:
        if text:
            await update.message.reply_text("ℹ️ Отправьте команду или воспользуйтесь кнопками.")

# === ЗАПУСК ===
def main():
    # Загрузка сохранённых сессий
    for file in os.listdir('.'):
        if file.startswith('session_string_') and file.endswith('.txt'):
            try:
                uid = int(file.replace('session_string_', '').replace('.txt', ''))
                with open(file, 'r') as f:
                    session_str = f.read().strip()
                if session_str:
                    get_user_data(uid)['session'] = session_str
                    logger.info(f"Загружена сессия {uid}")
            except:
                pass

    threading.Thread(target=run_webserver, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("help", handle_message))
    application.add_handler(CommandHandler("add_group", handle_message))
    application.add_handler(CommandHandler("set_msg", handle_message))
    application.add_handler(CommandHandler("start_spam", handle_message))
    application.add_handler(CommandHandler("stop_spam", handle_message))
    application.add_handler(CommandHandler("status", handle_message))
    application.add_handler(CommandHandler("groups", handle_message))

    # Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_handler))

    # Обработчики для текста, фото с подписью и фото без подписи
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO & filters.CAPTION, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO & ~filters.CAPTION, handle_message))

    logger.info("Бот запущен...")

    max_retries = 5
    for attempt in range(max_retries):
        try:
            application.run_polling(drop_pending_updates=True, stop_signals=(signal.SIGINT, signal.SIGTERM))
            break
        except Conflict:
            wait = 2 ** attempt
            logger.warning(f"Конфликт ({attempt+1}/{max_retries}), ожидание {wait}с")
            time.sleep(wait)
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
