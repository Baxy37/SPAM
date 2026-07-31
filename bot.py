import os
import re
import asyncio
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, errors
from telethon.network import MTProtoSender
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
user_sessions = {}

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
    print(f"Веб-сервер на порту {port}")
    server.serve_forever()

# ===== СИНХРОНИЗАЦИЯ ВРЕМЕНИ =====
async def sync_time_with_telegram(client):
    """Принудительная синхронизация времени с серверами Telegram"""
    try:
        # Получаем текущее время с сервера
        from telethon import utils
        dc = await client.get_me()
        return True
    except:
        pass
    
    try:
        # Альтернативный метод синхронизации
        if hasattr(client, '_sender') and client._sender:
            await client._sender.send_time()
        return True
    except Exception as e:
        print(f"Ошибка синхронизации времени: {e}")
        return False

# ===== РАБОТА С КЛИЕНТАМИ =====
def get_client(user_id):
    if user_id not in user_clients:
        client = TelegramClient(
            f'session_{user_id}', 
            API_ID, 
            API_HASH,
            system_version="4.16.30-vxCUSTOM",
            device_model="Desktop",
            app_version="4.16.30",
            connection_retries=5,
            retry_delay=2,
            auto_reconnect=True,
            timeout=30
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
            await sync_time_with_telegram(client)
        return await client.is_user_authorized()
    except Exception as e:
        print(f"Ошибка проверки: {e}")
        return False

def format_phone_number(phone):
    """Красиво форматирует номер телефона"""
    digits = phone[1:] if phone.startswith('+') else phone
    
    if digits.startswith('1') and len(digits) >= 11:
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:11]}"
    elif digits.startswith('7') and len(digits) >= 11:
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    elif digits.startswith('44') and len(digits) >= 12:
        return f"+44 {digits[2:5]} {digits[5:9]} {digits[9:12]}"
    elif digits.startswith('380') and len(digits) >= 12:
        return f"+380 ({digits[3:5]}) {digits[5:8]}-{digits[8:10]}-{digits[10:12]}"
    
    if len(digits) > 6:
        formatted = '+' + digits[:2]
        for i in range(2, len(digits), 3):
            formatted += ' ' + digits[i:i+3]
        return formatted
    
    return '+' + digits

# ===== ЛОГИН ПО КОДУ =====
async def send_code(user_id, phone):
    """Отправляет код подтверждения"""
    
    # Проверка блокировки
    if user_id in flood_wait_tracker:
        remaining = int(flood_wait_tracker[user_id] - time.time())
        if remaining > 0:
            minutes = remaining // 60
            hours = minutes // 60
            if hours > 0:
                return False, f"⏳ Заблокирован на {hours}ч {minutes%60}мин"
            else:
                return False, f"⏳ Заблокирован на {minutes}мин"
        else:
            del flood_wait_tracker[user_id]
    
    try:
        # Очистка номера
        phone_clean = phone.strip()
        phone_clean = re.sub(r'[\s\-\(\)\.]', '', phone_clean)
        
        if not phone_clean.startswith('+'):
            if phone_clean.startswith('8') and len(phone_clean) == 11:
                phone_clean = '+7' + phone_clean[1:]
            elif phone_clean.startswith('7') and len(phone_clean) == 11:
                phone_clean = '+' + phone_clean
            else:
                return False, "❌ Введите номер в международном формате: +79998887766"
        
        if not re.match(r'^\+\d+$', phone_clean):
            return False, "❌ Номер должен содержать только + и цифры"
        
        digits = phone_clean[1:]
        if len(digits) < 8 or len(digits) > 15:
            return False, f"❌ Неверная длина номера ({len(digits)} цифр)"
        
        client = get_client(user_id)
        
        # Принудительно переподключаемся
        if client.is_connected():
            await client.disconnect()
            await asyncio.sleep(2)
        
        await client.connect()
        
        # Синхронизируем время
        await sync_time_with_telegram(client)
        await asyncio.sleep(1)
        
        # Отправляем запрос кода
        result = await client.send_code_request(phone_clean)
        
        login_states[user_id] = {
            'step': 'code',
            'phone': phone_clean,
            'hash': result.phone_code_hash,
            'time_sent': time.time()
        }
        
        phone_display = format_phone_number(phone_clean)
        
        return True, f"✅ Код отправлен на {phone_display}\nВведите код из Telegram:"
    
    except errors.FloodWaitError as e:
        flood_wait_tracker[user_id] = time.time() + e.seconds
        
        if user_id in user_clients:
            try:
                await user_clients[user_id].disconnect()
            except:
                pass
            del user_clients[user_id]
        
        session_file = f'session_{user_id}.session'
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
            except:
                pass
        
        if e.seconds > 3600:
            return False, f"🚫 Заблокирован на {e.seconds//3600}ч"
        else:
            return False, f"🚫 Заблокирован на {e.seconds//60}мин"
    
    except errors.PhoneNumberInvalidError:
        return False, "❌ Неверный номер. Проверьте код страны."
    
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)[:100]}"

async def verify_code(user_id, code):
    """Проверяет код подтверждения"""
    
    if user_id not in login_states:
        return False, "❌ Сначала нажмите /login"
    
    data = login_states[user_id]
    
    if user_id not in user_clients:
        return False, "❌ Сессия потеряна. Нажмите /login заново"
    
    client = user_clients[user_id]
    
    try:
        # Проверяем соединение и синхронизируем время
        if not client.is_connected():
            await client.connect()
            await sync_time_with_telegram(client)
            await asyncio.sleep(1)
        
        # Пробуем войти
        await client.sign_in(data['phone'], code, phone_code_hash=data['hash'])
        
        phone_display = format_phone_number(data['phone'])
        del login_states[user_id]
        
        if user_id not in user_groups:
            user_groups[user_id] = []
        if user_id not in user_messages:
            user_messages[user_id] = ""
        if user_id not in user_spamming:
            user_spamming[user_id] = False
        
        return True, f"✅ Успешный вход!\n📱 {phone_display}\n\nИспользуйте:\n/add_group @username\n/set_msg текст\n/start_spam"
    
    except errors.PhoneCodeExpiredError:
        # Код истек - отправляем новый
        try:
            # Переподключаемся и синхронизируем время
            if client.is_connected():
                await client.disconnect()
                await asyncio.sleep(2)
            
            await client.connect()
            await sync_time_with_telegram(client)
            await asyncio.sleep(1)
            
            new_result = await client.send_code_request(data['phone'])
            login_states[user_id]['hash'] = new_result.phone_code_hash
            login_states[user_id]['time_sent'] = time.time()
            login_states[user_id]['attempts'] = login_states[user_id].get('attempts', 0) + 1
            return False, "⚠️ Код истек. Новый код отправлен. Введите:"
        except errors.FloodWaitError as e:
            del login_states[user_id]
            return False, f"🚫 Много попыток. Ждите {e.seconds//60}мин"
    
    except errors.PhoneCodeInvalidError:
        return False, "❌ Неверный код. Попробуйте еще раз."
    
    except errors.FloodWaitError as e:
        del login_states[user_id]
        return False, f"🚫 Заблокирован на {e.seconds//60}мин"
    
    except Exception as e:
        error_str = str(e)
        # Если ошибка времени - пробуем ещё раз с синхронизацией
        if 'TIME' in error_str.upper() or 'SYNC' in error_str.upper():
            try:
                await client.disconnect()
                await asyncio.sleep(3)
                await client.connect()
                await sync_time_with_telegram(client)
                await asyncio.sleep(2)
                
                await client.sign_in(data['phone'], code, phone_code_hash=data['hash'])
                
                phone_display = format_phone_number(data['phone'])
                del login_states[user_id]
                return True, f"✅ Вход выполнен!\n📱 {phone_display}"
            except Exception as retry_error:
                return False, f"❌ Ошибка синхронизации времени. Попробуйте /login заново"
        
        return False, f"❌ Ошибка: {error_str[:100]}"

# ===== КОМАНДЫ БОТА =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔑 Войти в аккаунт", callback_data='login')],
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
        "📱 Поддерживаются номера всех стран\n"
        "⚠️ Не входите слишком часто - будет блокировка\n\n"
        "Выберите действие:",
        parse_mode='Markdown',
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
                if hours > 0:
                    await query.edit_message_text(f"🚫 Заблокирован на {hours}ч {minutes}мин")
                else:
                    await query.edit_message_text(f"🚫 Заблокирован на {minutes}мин")
                return
        
        ready = await is_user_ready(user_id)
        if ready:
            await query.edit_message_text("✅ Вы уже авторизованы!")
            return
        
        login_states[user_id] = {'step': 'phone'}
        await query.edit_message_text(
            "📱 Введите номер телефона:\n"
            "+79998887766"
        )
    
    elif query.data == 'add_group':
        await query.edit_message_text(
            "`/add_group @username`\nПример: `/add_group @durov`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'set_msg':
        await query.edit_message_text(
            "`/set_msg Текст`\nПример: `/set_msg Привет!`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'start_spam':
        await start_spam_process(update, context, is_callback=True)
    
    elif query.data == 'stop_spam':
        user_spamming[user_id] = False
        await query.edit_message_text("🛑 Остановлено")
    
    elif query.data == 'status':
        ready = await is_user_ready(user_id)
        blocked = ""
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                blocked = f"\n• Блокировка: {remaining//3600}ч {(remaining%3600)//60}мин"
        
        groups_count = len(user_groups.get(user_id, []))
        message = user_messages.get(user_id, "")
        spamming = user_spamming.get(user_id, False)
        
        await query.edit_message_text(
            f"📊 *Статус:*\n"
            f"• Аккаунт: {'✅ Авторизован' if ready else '❌ Не авторизован'}{blocked}\n"
            f"• Групп: {groups_count}\n"
            f"• Сообщение: {message[:50] if message else '❌ Не задано'}\n"
            f"• Рассылка: {'🔄 Активна' if spamming else '⏸ Остановлена'}",
            parse_mode='Markdown'
        )
    
    elif query.data == 'groups':
        groups = user_groups.get(user_id, [])
        if not groups:
            await query.edit_message_text("📭 Нет групп")
        else:
            await query.edit_message_text(
                f"📋 *Группы ({len(groups)}):*\n" + '\n'.join(groups),
                parse_mode='Markdown'
            )

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
        await reply_func("❌ Сначала войдите в аккаунт")
        return
    
    if user_id not in user_messages or not user_messages[user_id]:
        await reply_func("❌ Установите сообщение: /set_msg")
        return
    
    if user_id not in user_groups or not user_groups[user_id]:
        await reply_func("❌ Добавьте группы: /add_group")
        return
    
    if user_spamming.get(user_id, False):
        await reply_func("⚠️ Рассылка уже идет!")
        return
    
    user_spamming[user_id] = True
    client = user_clients[user_id]
    groups = user_groups[user_id].copy()
    msg = user_messages[user_id]
    
    await reply_func(f"🚀 Отправка в {len(groups)} групп...")
    
    sent = 0
    errors_count = 0
    
    for i, group in enumerate(groups, 1):
        if not user_spamming.get(user_id, False):
            await reply_func(f"🛑 Остановлено. Отправлено: {sent}")
            break
        
        try:
            await client.send_message(group, msg)
            sent += 1
            await reply_func(f"✅ [{i}/{len(groups)}] {group}")
        except errors.FloodWaitError as e:
            await reply_func(f"⏳ Пауза {e.seconds}с...")
            await asyncio.sleep(e.seconds + 1)
            try:
                await client.send_message(group, msg)
                sent += 1
            except:
                errors_count += 1
        except Exception as e:
            errors_count += 1
            await reply_func(f"❌ [{i}/{len(groups)}] Ошибка")
        
        await asyncio.sleep(3)
    
    user_spamming[user_id] = False
    await reply_func(f"✅ Завершено! Отправлено: {sent}, ошибок: {errors_count}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if user_id in login_states:
        step = login_states[user_id]['step']
        
        if step == 'phone':
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            success, error = await send_code(user_id, text)
            await update.message.reply_text(error)
            if not success and user_id in login_states:
                del login_states[user_id]
        
        elif step == 'code':
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            success, error = await verify_code(user_id, text)
            await update.message.reply_text(error)
        
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
            await update.message.reply_text(f"⚠️ Уже есть: {group}")
        else:
            user_groups[user_id].append(group)
            await update.message.reply_text(f"✅ Добавлено: {group} ({len(user_groups[user_id])})")
    
    elif text.startswith('/set_msg'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ /set_msg текст")
            return
        
        user_messages[user_id] = parts[1].strip()
        await update.message.reply_text(f"✅ Сообщение сохранено")
    
    elif text == '/login':
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                await update.message.reply_text(f"🚫 Заблокирован на {hours}ч {minutes}мин")
                return
        
        ready = await is_user_ready(user_id)
        if ready:
            await update.message.reply_text("✅ Уже авторизованы!")
            return
        
        login_states[user_id] = {'step': 'phone'}
        await update.message.reply_text("📱 Введите номер:\n+79998887766")
    
    elif text == '/status':
        ready = await is_user_ready(user_id)
        blocked = ""
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                blocked = f"\n• Блокировка: {remaining//3600}ч {(remaining%3600)//60}мин"
        
        await update.message.reply_text(
            f"📊 *Статус:*\n"
            f"• Аккаунт: {'✅ Авторизован' if ready else '❌ Не авторизован'}{blocked}\n"
            f"• Групп: {len(user_groups.get(user_id, []))}\n"
            f"• Сообщение: {user_messages.get(user_id, '❌')[:50]}\n"
            f"• Рассылка: {'🔄 Активна' if user_spamming.get(user_id, False) else '⏸ Остановлена'}",
            parse_mode='Markdown'
        )
    
    elif text == '/groups':
        groups = user_groups.get(user_id, [])
        if not groups:
            await update.message.reply_text("📭 Групп нет")
        else:
            await update.message.reply_text(f"📋 Группы ({len(groups)}):\n" + '\n'.join(groups))
    
    elif text == '/start_spam':
        await start_spam_process(update, context, is_callback=False)
    
    elif text == '/stop_spam':
        user_spamming[user_id] = False
        await update.message.reply_text("🛑 Остановлено")
    
    elif text == '/help':
        await update.message.reply_text(
            "/start - Меню\n"
            "/login - Войти\n"
            "/add_group @name - Добавить группу\n"
            "/set_msg текст - Сообщение\n"
            "/start_spam - Запустить\n"
            "/stop_spam - Остановить\n"
            "/status - Статус\n"
            "/groups - Список групп"
        )
    
    elif text == '/start':
        await start(update, context)
    
    else:
        await update.message.reply_text("ℹ️ Используйте /start")

# ===== ЗАПУСК =====
def main():
    for file in os.listdir('.'):
        if file.startswith('session_') and file.endswith('.session'):
            try:
                os.remove(file)
            except:
                pass
    
    threading.Thread(target=run_webserver, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", handle_message))
    app.add_handler(CommandHandler("status", handle_message))
    app.add_handler(CommandHandler("groups", handle_message))
    app.add_handler(CommandHandler("start_spam", handle_message))
    app.add_handler(CommandHandler("stop_spam", handle_message))
    app.add_handler(CommandHandler("help", handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
