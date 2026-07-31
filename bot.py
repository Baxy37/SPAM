import os
import re
import asyncio
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import GetHistoryRequest
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

# ===== ВЕБ-СЕРВЕР ДЛЯ RENDER =====
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

# ===== РАБОТА С КЛИЕНТАМИ =====
def get_client(user_id):
    if user_id not in user_clients:
        # Используем стандартные параметры как у официального клиента
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

# ===== ЛОГИН =====
async def send_code(user_id, phone):
    """Отправляет код подтверждения"""
    
    if user_id in flood_wait_tracker:
        remaining = int(flood_wait_tracker[user_id] - time.time())
        if remaining > 0:
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            if hours > 0:
                return False, f"Заблокирован на {hours}ч {minutes}мин"
            else:
                return False, f"Заблокирован на {minutes}мин"
        else:
            del flood_wait_tracker[user_id]
    
    try:
        # Очистка номера
        phone_clean = phone.strip()
        phone_clean = re.sub(r'[\s\-\(\)\.]', '', phone_clean)
        
        if not phone_clean.startswith('+'):
            if phone_clean.startswith('8') and len(phone_clean) == 11:
                phone_clean = '+7' + phone_clean[1:]
            elif len(phone_clean) == 11 and phone_clean.startswith('7'):
                phone_clean = '+' + phone_clean
            else:
                return False, "Введите номер в формате: +79998887766"
        
        if not re.match(r'^\+\d{8,15}$', phone_clean):
            return False, "Неверный формат номера"
        
        client = get_client(user_id)
        
        # Отключаем если был подключен
        if client.is_connected():
            await client.disconnect()
            await asyncio.sleep(1)
        
        # Подключаемся
        await client.connect()
        await asyncio.sleep(1)
        
        # Отправляем код
        result = await client.send_code_request(phone_clean)
        
        login_states[user_id] = {
            'step': 'code',
            'phone': phone_clean,
            'hash': result.phone_code_hash
        }
        
        return True, "Код отправлен в Telegram. Введите его:"
    
    except errors.FloodWaitError as e:
        flood_wait_tracker[user_id] = time.time() + e.seconds
        
        # Очищаем сессию
        if user_id in user_clients:
            try:
                await user_clients[user_id].disconnect()
            except:
                pass
            del user_clients[user_id]
        
        session_file = f'session_{user_id}.session'
        if os.path.exists(session_file):
            os.remove(session_file)
        
        return False, f"Заблокирован на {e.seconds//60}мин"
    
    except Exception as e:
        return False, f"Ошибка: {str(e)[:100]}"

async def verify_code(user_id, code):
    """Проверяет код"""
    
    if user_id not in login_states:
        return False, "Сначала нажмите /login"
    
    data = login_states[user_id]
    
    if user_id not in user_clients:
        return False, "Сессия потеряна. Нажмите /login"
    
    client = user_clients[user_id]
    
    try:
        if not client.is_connected():
            await client.connect()
            await asyncio.sleep(1)
        
        # ВАЖНО: Не передаем phone_code_hash если он не нужен
        await client.sign_in(
            phone=data['phone'],
            code=code,
            phone_code_hash=data['hash']
        )
        
        del login_states[user_id]
        
        # Инициализация
        if user_id not in user_groups:
            user_groups[user_id] = []
        if user_id not in user_messages:
            user_messages[user_id] = ""
        if user_id not in user_spamming:
            user_spamming[user_id] = False
        
        return True, "✅ Успешный вход!"
    
    except errors.SessionPasswordNeededError:
        # Нужен 2FA пароль
        login_states[user_id]['step'] = '2fa'
        return False, "Введите пароль двухфакторной аутентификации:"
    
    except errors.PhoneCodeExpiredError:
        try:
            # Переподключаемся
            if client.is_connected():
                await client.disconnect()
                await asyncio.sleep(1)
            
            await client.connect()
            await asyncio.sleep(1)
            
            new_result = await client.send_code_request(data['phone'])
            login_states[user_id]['hash'] = new_result.phone_code_hash
            return False, "Код истек. Отправлен новый код:"
        except Exception as e:
            del login_states[user_id]
            return False, f"Ошибка: {str(e)[:100]}"
    
    except errors.PhoneCodeInvalidError:
        return False, "Неверный код"
    
    except errors.FloodWaitError as e:
        del login_states[user_id]
        return False, f"Заблокирован на {e.seconds//60}мин"
    
    except Exception as e:
        error_str = str(e)
        return False, f"Ошибка: {error_str[:100]}"

async def verify_2fa(user_id, password):
    """Проверяет пароль 2FA"""
    
    if user_id not in login_states or login_states[user_id].get('step') != '2fa':
        return False, "Сначала введите код"
    
    data = login_states[user_id]
    client = user_clients[user_id]
    
    try:
        await client.sign_in(password=password)
        
        del login_states[user_id]
        
        if user_id not in user_groups:
            user_groups[user_id] = []
        if user_id not in user_messages:
            user_messages[user_id] = ""
        if user_id not in user_spamming:
            user_spamming[user_id] = False
        
        return True, "✅ Успешный вход!"
    
    except errors.PasswordHashInvalidError:
        return False, "Неверный пароль"
    
    except Exception as e:
        return False, f"Ошибка: {str(e)[:100]}"

# ===== КОМАНДЫ БОТА =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔑 Войти", callback_data='login')],
        [InlineKeyboardButton("➕ Добавить группу", callback_data='add_group')],
        [InlineKeyboardButton("📝 Сообщение", callback_data='set_msg')],
        [InlineKeyboardButton("🚀 Запустить", callback_data='start_spam')],
        [InlineKeyboardButton("🛑 Остановить", callback_data='stop_spam')],
        [InlineKeyboardButton("📊 Статус", callback_data='status')],
        [InlineKeyboardButton("📋 Группы", callback_data='groups')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🤖 Бот для рассылки\n\n"
        "⚠️ После получения кода НЕ сообщайте его никому!\n"
        "Вводите код только в этом боте.\n\n"
        "Если вход заблокирован - подождите и попробуйте позже.",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == 'login':
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                await query.edit_message_text(f"🚫 Заблокирован на {hours}ч {minutes}мин")
                return
        
        ready = await is_user_ready(user_id)
        if ready:
            await query.edit_message_text("✅ Уже авторизованы")
            return
        
        login_states[user_id] = {'step': 'phone'}
        await query.edit_message_text("📱 Введите номер:\n+79998887766")
    
    elif query.data == 'add_group':
        await query.edit_message_text("/add_group @username")
    
    elif query.data == 'set_msg':
        await query.edit_message_text("/set_msg Текст")
    
    elif query.data == 'start_spam':
        await start_spam_process(update, context, is_callback=True)
    
    elif query.data == 'stop_spam':
        user_spamming[user_id] = False
        await query.edit_message_text("🛑 Остановлено")
    
    elif query.data == 'status':
        ready = await is_user_ready(user_id)
        await query.edit_message_text(
            f"📊 Статус:\n"
            f"Аккаунт: {'✅' if ready else '❌'}\n"
            f"Групп: {len(user_groups.get(user_id, []))}\n"
            f"Рассылка: {'🔄' if user_spamming.get(user_id, False) else '⏸'}"
        )
    
    elif query.data == 'groups':
        groups = user_groups.get(user_id, [])
        if not groups:
            await query.edit_message_text("Нет групп")
        else:
            await query.edit_message_text('\n'.join(groups))

async def start_spam_process(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    if is_callback:
        query = update.callback_query
        user_id = query.from_user.id
        reply_func = query.edit_message_text
    else:
        user_id = update.effective_user.id
        reply_func = update.message.reply_text
    
    ready = await is_user_ready(user_id)
    if not ready:
        await reply_func("❌ Сначала войдите")
        return
    
    if user_id not in user_messages or not user_messages[user_id]:
        await reply_func("❌ /set_msg текст")
        return
    
    if user_id not in user_groups or not user_groups[user_id]:
        await reply_func("❌ /add_group @username")
        return
    
    if user_spamming.get(user_id, False):
        await reply_func("⚠️ Уже запущена")
        return
    
    user_spamming[user_id] = True
    client = user_clients[user_id]
    groups = user_groups[user_id].copy()
    msg = user_messages[user_id]
    
    await reply_func(f"🚀 Отправка в {len(groups)} групп...")
    
    sent = 0
    errors = 0
    
    for group in groups:
        if not user_spamming.get(user_id, False):
            break
        
        try:
            await client.send_message(group, msg)
            sent += 1
        except errors.FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
            try:
                await client.send_message(group, msg)
                sent += 1
            except:
                errors += 1
        except:
            errors += 1
        
        await asyncio.sleep(3)
    
    user_spamming[user_id] = False
    await reply_func(f"✅ Готово! Отправлено: {sent}, ошибок: {errors}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Обработка логина
    if user_id in login_states:
        state = login_states[user_id]
        
        if state['step'] == 'phone':
            success, msg = await send_code(user_id, text)
            await update.message.reply_text(msg)
            if not success and user_id in login_states:
                del login_states[user_id]
        
        elif state['step'] == 'code':
            success, msg = await verify_code(user_id, text)
            await update.message.reply_text(msg)
            if success:
                await update.message.reply_text("Используйте:\n/add_group @username\n/set_msg текст\n/start_spam")
        
        elif state.get('step') == '2fa':
            success, msg = await verify_2fa(user_id, text)
            await update.message.reply_text(msg)
            if success:
                await update.message.reply_text("Используйте:\n/add_group @username\n/set_msg текст\n/start_spam")
        
        return
    
    # Команды
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
            await update.message.reply_text(f"Уже есть: {group}")
        else:
            user_groups[user_id].append(group)
            await update.message.reply_text(f"✅ {group}")
    
    elif text.startswith('/set_msg'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("/set_msg текст")
            return
        user_messages[user_id] = parts[1].strip()
        await update.message.reply_text("✅ Сообщение сохранено")
    
    elif text == '/login':
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                await update.message.reply_text(f"Заблокирован на {remaining//60}мин")
                return
        
        ready = await is_user_ready(user_id)
        if ready:
            await update.message.reply_text("✅ Уже авторизованы")
            return
        
        login_states[user_id] = {'step': 'phone'}
        await update.message.reply_text("📱 Введите номер:\n+79998887766")
    
    elif text == '/start_spam':
        await start_spam_process(update, context)
    
    elif text == '/stop_spam':
        user_spamming[user_id] = False
        await update.message.reply_text("🛑 Остановлено")
    
    elif text == '/status':
        ready = await is_user_ready(user_id)
        await update.message.reply_text(
            f"Аккаунт: {'✅' if ready else '❌'}\n"
            f"Групп: {len(user_groups.get(user_id, []))}\n"
            f"Рассылка: {'🔄' if user_spamming.get(user_id, False) else '⏸'}"
        )
    
    elif text == '/groups':
        groups = user_groups.get(user_id, [])
        await update.message.reply_text('\n'.join(groups) if groups else "Нет групп")
    
    elif text == '/help':
        await update.message.reply_text(
            "/login - Войти\n"
            "/add_group @name - Группа\n"
            "/set_msg текст - Сообщение\n"
            "/start_spam - Рассылка\n"
            "/stop_spam - Стоп\n"
            "/status - Статус\n"
            "/groups - Группы"
        )
    
    elif text == '/start':
        await start(update, context)

# ===== ЗАПУСК =====
def main():
    # Очистка старых сессий
    for file in os.listdir('.'):
        if file.startswith('session_') and file.endswith('.session'):
            try:
                os.remove(file)
            except:
                pass
    
    threading.Thread(target=run_webserver, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
