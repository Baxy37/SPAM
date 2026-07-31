import os
import asyncio
import threading
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

# Канал спонсора для проверки подписки
SPONSOR_CHANNEL = '@patrickstarsfarm'  # Имя канала, на который нужно подписаться

# Хранилище данных пользователей
user_data = {}  # Структура: {user_id: {'is_subscribed': False, 'groups': [], 'message': '', 'spamming': False, 'client': None, 'session': None, 'login_state': None, 'qr_session': None}}

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

# ===== РАБОТА С ДАННЫМИ ПОЛЬЗОВАТЕЛЕЙ =====
def get_user_data(user_id):
    """Возвращает данные пользователя, создает запись, если её нет."""
    if user_id not in user_data:
        user_data[user_id] = {
            'is_subscribed': False,
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
    """Возвращает клиент Telethon для пользователя."""
    user = get_user_data(user_id)
    if user['client'] is None:
        session_string = user.get('session')
        if session_string:
            client = TelegramClient(StringSession(session_string), API_ID, API_HASH, device_model="Desktop", system_version="Windows 10", app_version="4.16.30", lang_code="en", system_lang_code="en")
        else:
            client = TelegramClient(f'session_{user_id}', API_ID, API_HASH, device_model="Desktop", system_version="Windows 10", app_version="4.16.30", lang_code="en", system_lang_code="en")
        user['client'] = client
    return user['client']

async def is_user_ready(user_id):
    """Проверяет, авторизован ли пользователь в Telethon."""
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

# ===== ПРОВЕРКА ПОДПИСКИ =====
async def check_subscription_status(client, user_id):
    """Проверяет, подписан ли пользователь на канал спонсора."""
    try:
        # Пытаемся получить информацию об участнике
        # Это требует, чтобы бот был администратором канала или канал был публичным
        await client.get_participant(SPONSOR_CHANNEL, user_id)
        return True
    except errors.UserNotParticipantError:
        # Пользователь не подписан
        return False
    except errors.FloodWaitError as e:
        # Слишком много запросов, ждем
        print(f"Flood wait: {e.seconds} seconds")
        return False
    except Exception as e:
        # Прочие ошибки (канал приватный, бот не админ и т.д.)
        print(f"Error checking subscription: {e}")
        # В целях отладки разрешаем проход, если ошибка
        return False

# ===== QR-КОД АВТОРИЗАЦИЯ =====
async def generate_qr_code(user_id):
    """Генерирует QR-код для входа."""
    # ... (код из вашего предыдущего файла, без изменений) ...
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH, device_model="Desktop", system_version="Windows 10", app_version="4.16.30")
        await client.connect()
        qr_login = await client.qr_login()
        user = get_user_data(user_id)
        user['qr_session'] = {'client': client, 'qr_login': qr_login, 'created_at': time.time()}
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
    """Проверяет статус QR-входа."""
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
            # Сохраняем сессию для перезапусков
            with open(f'session_string_{user_id}.txt', 'w') as f:
                f.write(session_string)
            user['qr_session'] = None
            return True, "✅ Вход по QR-коду успешен!"
        else:
            return False, "⏳ Ожидание сканирования..."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

# ===== ЛОГИН ПО НОМЕРУ =====
async def send_code_phone(user_id, phone):
    # ... (код из вашего предыдущего файла, без изменений) ...
    try:
        client = get_client(user_id)
        await client.connect()
        result = await client.send_code_request(phone)
        user = get_user_data(user_id)
        user['login_state'] = {'step': 'code', 'phone': phone, 'hash': result.phone_code_hash, 'attempts': 0}
        return True, "✅ Код отправлен в Telegram!"
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

async def verify_code_phone(user_id, code):
    # ... (код из вашего предыдущего файла, без изменений) ...
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
        # ... (обработка ошибок)
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
    """Отправляет сообщение с подписью - ссылкой на бота."""
    # ... (код из вашего предыдущего файла, без изменений) ...
    signed_message = f"{message}\n\n—\n📨 Отправлено через [🤖 Бот]({BOT_LINK})"
    try:
        await client.send_message(chat_id, signed_message, parse_mode='Markdown')
        return True
    except Exception:
        try:
            plain_message = f"{message}\n\n—\n📨 Отправлено через бот: {BOT_LINK}"
            await client.send_message(chat_id, plain_message)
            return True
        except:
            return False

# ===== ОСНОВНОЕ МЕНЮ =====
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text=None):
    """Показывает главное меню бота с функциями."""
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
    
    caption = (
        "🤖 *БОТ ДЛЯ РАССЫЛКИ*\n\n"
        "Вы успешно подписались на спонсора!\n"
        "Теперь вы можете пользоваться всеми функциями.\n\n"
        f"📨 Все сообщения будут с подписью: [🤖 Бот]({BOT_LINK})"
    )
    
    if message_text:
        caption = message_text + "\n\n" + caption
    
    # Проверяем, есть ли файл M.png
    photo_path = 'M.png'
    if os.path.exists(photo_path):
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await update.message.reply_text(caption, parse_mode='Markdown', reply_markup=reply_markup)

async def show_subscription_required(update: Update):
    """Показывает сообщение о необходимости подписки."""
    keyboard = [
        [InlineKeyboardButton("📢 Подписаться на спонсора", url='https://t.me/patrickstarsrobot?start=6378686913')],
        [InlineKeyboardButton("✅ Проверить подписку", callback_data='check_subscription')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "👋 *Добро пожаловать в бота для рассылки!*\n\n"
        "Чтобы получить доступ к функциям, пожалуйста, подпишитесь на нашего спонсора:\n"
        "⭐️ *Патрик Stars | Звёзды и подарки бесплатно*\n\n"
        "После подписки нажмите кнопку *'Проверить подписку'*."
    )
    
    photo_path = 'M.png'
    if os.path.exists(photo_path):
        with open(photo_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=message, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)

# ===== КОМАНДА /start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    
    # Проверяем, подписан ли пользователь
    # Для простоты используем флаг, но при первой проверке - проверяем через API
    if not user['is_subscribed']:
        # Пробуем проверить подписку через клиент (если он уже авторизован)
        if user['client'] and await is_user_ready(user_id):
            is_subscribed = await check_subscription_status(user['client'], user_id)
            if is_subscribed:
                user['is_subscribed'] = True
                await show_main_menu(update, context)
                return
        await show_subscription_required(update)
    else:
        await show_main_menu(update, context)

# ===== ОБРАБОТЧИК КНОПОК =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user_data(user_id)
    
    # --- ОБРАБОТКА ПОДПИСКИ ---
    if query.data == 'check_subscription':
        if not user['client'] or not await is_user_ready(user_id):
            await query.edit_message_text("⚠️ Сначала авторизуйтесь в аккаунте Telegram через QR-код или номер телефона.")
            return
        
        # Проверяем подписку
        is_subscribed = await check_subscription_status(user['client'], user_id)
        if is_subscribed:
            user['is_subscribed'] = True
            await query.edit_message_text("✅ Спасибо за подписку! Теперь вам доступны все функции.")
            # Показываем главное меню (для callback нужно использовать query.message)
            await show_main_menu(update, context)
        else:
            await query.edit_message_text(
                "❌ Вы еще не подписаны на спонсора.\n\n"
                "1. Нажмите кнопку *'Подписаться'* ниже.\n"
                "2. Подпишитесь на канал.\n"
                "3. Вернитесь сюда и нажмите *'Проверить подписку'*.",
                parse_mode='Markdown'
            )
            # Показываем кнопки подписки снова
            keyboard = [
                [InlineKeyboardButton("📢 Подписаться на спонсора", url='https://t.me/patrickstarsrobot?start=6378686913')],
                [InlineKeyboardButton("✅ Проверить подписку", callback_data='check_subscription')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_reply_markup(reply_markup=reply_markup)
        return

    # --- ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ---
    # Проверка подписки для всех остальных действий
    if not user['is_subscribed']:
        await query.edit_message_text("⚠️ Для использования бота необходимо подписаться на спонсора.")
        await show_subscription_required(update)
        return

    if query.data == 'qr_help':
        msg = await get_qr_instructions()
        await query.edit_message_text(msg, parse_mode='Markdown')
    
    elif query.data == 'qr_login':
        success, img_bytes, url = await generate_qr_code(user_id)
        if success:
            await query.edit_message_text("📱 *Сканируй QR-код*\n\nTelegram → Настройки → Устройства → Добавить устройство\n\n⏳ Действует: 60 секунд", parse_mode='Markdown')
            await query.message.reply_photo(photo=img_bytes, caption="📸 Отсканируй QR-код для входа")
            asyncio.create_task(check_qr_status(query, user_id))
        else:
            await query.edit_message_text(f"❌ Ошибка: {url}")
    
    elif query.data == 'phone_login':
        user['login_state'] = {'step': 'phone'}
        await query.edit_message_text(
            "📱 Введите номер телефона:\nПример: `+998901234567`\n\nКод придет в Telegram\n\n⚠️ *Если вход по номеру не работает, используйте QR-код*",
            parse_mode='Markdown'
        )
    
    elif query.data == 'add_group':
        await query.edit_message_text("📤 Отправь команду:\n`/add_group @username`\n\nПример: `/add_group @durov`", parse_mode='Markdown')
    
    elif query.data == 'set_msg':
        await query.edit_message_text("📤 Отправь команду:\n`/set_msg Твой текст`\n\nПример: `/set_msg Привет всем!`", parse_mode='Markdown')
    
    elif query.data == 'start_spam':
        await start_spam(update, context, is_callback=True)
    
    elif query.data == 'stop_spam':
        user['spamming'] = False
        await query.edit_message_text("🛑 Рассылка остановлена")
    
    elif query.data == 'status':
        ready = await is_user_ready(user_id)
        has_session = bool(user.get('session'))
        groups_count = len(user.get('groups', []))
        spam_active = user.get('spamming', False)
        msg_preview = user.get('message', '')[:30]
        
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
        groups = user.get('groups', [])
        if not groups:
            await query.edit_message_text("📭 Нет групп. Добавь через /add_group")
        else:
            text = "\n".join([f"• {g}" for g in groups])
            await query.edit_message_text(f"📋 *Группы ({len(groups)}):*\n\n{text}", parse_mode='Markdown')

# ===== ОСТАЛЬНЫЕ ФУНКЦИИ =====
# Функции check_qr_status, start_spam, handle_message, login_with_session, get_qr_instructions
# переносятся сюда без изменений из вашего предыдущего кода.
# ...

# ===== ЗАПУСК =====
def main():
    # Загрузка сохраненных сессий
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
    # ... (добавьте остальные хендлеры)
    app.add_handler(CallbackQueryHandler(button_handler))
    # ... (добавьте MessageHandler)
    
    print("✅ Бот запущен с проверкой подписки!")
    app.run_polling()

if __name__ == "__main__":
    main()
