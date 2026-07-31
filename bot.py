import os
import asyncio
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, errors
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
        pass  # Отключаем логи HTTP запросов

def run_webserver():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🌐 Веб-сервер запущен на порту {port}")
    server.serve_forever()

# ===== РАБОТА С КЛИЕНТАМИ =====
def get_client(user_id):
    """Создает или возвращает существующего клиента"""
    if user_id not in user_clients:
        client = TelegramClient(
            f'session_{user_id}', 
            API_ID, 
            API_HASH,
            system_version="4.16.30-vxCUSTOM",
            device_model="Desktop",
            app_version="4.16.30",
            connection_retries=3,
            retry_delay=2,
            auto_reconnect=True
        )
        user_clients[user_id] = client
    return user_clients[user_id]

async def is_user_ready(user_id):
    """Проверяет, авторизован ли пользователь"""
    if user_id not in user_clients:
        return False
    
    client = user_clients[user_id]
    try:
        if not client.is_connected():
            await client.connect()
        return await client.is_user_authorized()
    except Exception as e:
        print(f"Ошибка проверки авторизации: {e}")
        return False

# ===== ЛОГИН ПО КОДУ =====
async def send_code(user_id, phone):
    """Отправляет код подтверждения на номер телефона"""
    
    # Проверка блокировки
    if user_id in flood_wait_tracker:
        remaining = int(flood_wait_tracker[user_id] - time.time())
        if remaining > 0:
            minutes = remaining // 60
            hours = minutes // 60
            if hours > 0:
                return False, f"⏳ Аккаунт заблокирован на {hours}ч {minutes%60}мин"
            else:
                return False, f"⏳ Аккаунт заблокирован на {minutes}мин"
        else:
            del flood_wait_tracker[user_id]
    
    try:
        client = get_client(user_id)
        
        # Очищаем старое соединение
        if client.is_connected():
            await client.disconnect()
            await asyncio.sleep(2)
        
        # Подключаемся
        await client.connect()
        await asyncio.sleep(1)
        
        # Отправляем запрос кода
        result = await client.send_code_request(phone)
        
        login_states[user_id] = {
            'step': 'code',
            'phone': phone,
            'hash': result.phone_code_hash,
            'attempts': 0
        }
        return True, "✅ Код подтверждения отправлен в Telegram!\n\nПроверьте приложение Telegram на телефоне и введите код цифрами."
    
    except errors.FloodWaitError as e:
        # Сохраняем время разблокировки
        flood_wait_tracker[user_id] = time.time() + e.seconds
        
        # Удаляем сессию и клиент
        if user_id in user_clients:
            try:
                await user_clients[user_id].disconnect()
            except:
                pass
            del user_clients[user_id]
        
        # Удаляем файл сессии
        session_file = f'session_{user_id}.session'
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
            except:
                pass
        
        hours = e.seconds // 3600
        minutes = (e.seconds % 3600) // 60
        
        if hours > 0:
            return False, f"🚫 Telegram заблокировал этот номер на {hours}ч {minutes}мин!\nПопробуйте позже."
        else:
            return False, f"🚫 Telegram заблокировал этот номер на {minutes}мин!\nПопробуйте позже."
    
    except errors.PhoneNumberInvalidError:
        return False, "❌ Неверный формат номера. Используйте международный формат: +79998887766"
    
    except errors.PhoneNumberBannedError:
        return False, "❌ Этот номер заблокирован в Telegram"
    
    except Exception as e:
        error_str = str(e)
        return False, f"❌ Ошибка: {error_str[:150]}\nПроверьте номер и попробуйте позже."

async def verify_code(user_id, code):
    """Проверяет код подтверждения"""
    
    if user_id not in login_states:
        return False, "❌ Сначала используйте /login"
    
    data = login_states[user_id]
    
    if user_id not in user_clients:
        return False, "❌ Сессия потеряна. Используйте /login заново"
    
    client = user_clients[user_id]
    
    try:
        # Проверяем соединение
        if not client.is_connected():
            await client.connect()
            await asyncio.sleep(1)
        
        # Пробуем войти
        await client.sign_in(data['phone'], code, phone_code_hash=data['hash'])
        
        # Очищаем состояние логина
        del login_states[user_id]
        
        # Инициализируем хранилища
        if user_id not in user_groups:
            user_groups[user_id] = []
        if user_id not in user_messages:
            user_messages[user_id] = ""
        if user_id not in user_spamming:
            user_spamming[user_id] = False
        
        return True, "✅ Аккаунт авторизован!\n\nИспользуйте:\n• /add_group @username\n• /set_msg текст\n• /start_spam"
    
    except errors.PhoneCodeExpiredError:
        # Код истек - отправляем новый
        try:
            new_result = await client.send_code_request(data['phone'])
            login_states[user_id]['hash'] = new_result.phone_code_hash
            login_states[user_id]['attempts'] += 1
            return False, "⚠️ Код истек. Новый код отправлен в Telegram. Введите его:"
        except errors.FloodWaitError as e:
            del login_states[user_id]
            return False, f"🚫 Слишком много попыток! Подождите {e.seconds//60} мин."
    
    except errors.PhoneCodeInvalidError:
        return False, "❌ Неверный код. Проверьте и попробуйте еще раз."
    
    except errors.FloodWaitError as e:
        del login_states[user_id]
        return False, f"🚫 Заблокировано на {e.seconds//60} мин."
    
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)[:150]}\nПопробуйте /login заново."

# ===== КОМАНДЫ БОТА =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню"""
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
        "🤖 *БОТ ДЛЯ РАССЫЛКИ В TELEGRAM*\n\n"
        "⚠️ *Важно:* Не пытайтесь входить слишком часто!\n"
        "При блокировке ждите указанное время.\n\n"
        "Все команды доступны по кнопкам ниже ↓",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == 'login':
        # Проверка блокировки
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                if hours > 0:
                    await query.edit_message_text(f"🚫 Вход заблокирован на {hours}ч {minutes}мин")
                else:
                    await query.edit_message_text(f"🚫 Вход заблокирован на {minutes}мин")
                return
        
        # Проверка текущей авторизации
        ready = await is_user_ready(user_id)
        if ready:
            await query.edit_message_text("✅ Вы уже авторизованы!")
            return
        
        # Начинаем процесс логина
        login_states[user_id] = {'step': 'phone'}
        await query.edit_message_text(
            "📱 Введите номер телефона в международном формате:\n\n"
            "`+79998887766`\n\n"
            "⚠️ Будьте внимательны! При ошибке блокировка на 24 часа!",
            parse_mode='Markdown'
        )
    
    elif query.data == 'add_group':
        await query.edit_message_text(
            "Добавьте группу командой:\n"
            "`/add_group @username`\n\n"
            "Пример: `/add_group @durov`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'set_msg':
        await query.edit_message_text(
            "Установите сообщение командой:\n"
            "`/set_msg Текст сообщения`\n\n"
            "Пример: `/set_msg Всем привет!`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'start_spam':
        await start_spam_process(update, context, is_callback=True)
    
    elif query.data == 'stop_spam':
        user_spamming[user_id] = False
        await query.edit_message_text("🛑 Рассылка остановлена")
    
    elif query.data == 'status':
        ready = await is_user_ready(user_id)
        blocked = ""
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                blocked = f"\n• Блокировка: {hours}ч {minutes}мин"
        
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
            await query.edit_message_text("📭 Нет добавленных групп")
        else:
            groups_list = '\n'.join(groups)
            await query.edit_message_text(
                f"📋 *Группы ({len(groups)}):*\n{groups_list}",
                parse_mode='Markdown'
            )

async def start_spam_process(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    """Запускает процесс рассылки"""
    if is_callback:
        query = update.callback_query
        user_id = query.from_user.id
        reply_func = query.edit_message_text
    else:
        user_id = update.effective_user.id
        reply_func = update.message.reply_text
    
    # Проверки
    ready = await is_user_ready(user_id)
    if not ready:
        await reply_func("❌ Сначала авторизуйтесь: нажмите 'Войти' или /login")
        return
    
    if user_id not in user_messages or not user_messages[user_id]:
        await reply_func("❌ Установите сообщение: /set_msg текст")
        return
    
    if user_id not in user_groups or not user_groups[user_id]:
        await reply_func("❌ Добавьте группы: /add_group @username")
        return
    
    if user_spamming.get(user_id, False):
        await reply_func("⚠️ Рассылка уже запущена!")
        return
    
    # Запускаем рассылку
    user_spamming[user_id] = True
    client = user_clients[user_id]
    groups = user_groups[user_id].copy()
    msg = user_messages[user_id]
    
    await reply_func(f"🚀 Рассылка начата в {len(groups)} групп...")
    
    sent = 0
    errors_count = 0
    current_msg = None
    
    for i, group in enumerate(groups, 1):
        if not user_spamming.get(user_id, False):
            try:
                await reply_func(f"🛑 Остановлено пользователем. Отправлено: {sent}/{len(groups)}")
            except:
                pass
            break
        
        try:
            await client.send_message(group, msg)
            sent += 1
            status_text = f"✅ [{i}/{len(groups)}] Отправлено в {group}"
            try:
                if current_msg:
                    await current_msg.edit_text(status_text)
                else:
                    current_msg = await reply_func(status_text)
            except:
                try:
                    await reply_func(status_text)
                except:
                    pass
            
        except errors.FloodWaitError as e:
            status_text = f"⏳ [{i}/{len(groups)}] Пауза {e.seconds}с..."
            try:
                if current_msg:
                    await current_msg.edit_text(status_text)
                else:
                    current_msg = await reply_func(status_text)
            except:
                pass
            
            await asyncio.sleep(e.seconds + 1)
            try:
                await client.send_message(group, msg)
                sent += 1
            except Exception as retry_error:
                errors_count += 1
                
        except Exception as e:
            errors_count += 1
            error_text = f"❌ [{i}/{len(groups)}] Ошибка в {group}: {str(e)[:50]}"
            try:
                if current_msg:
                    await current_msg.edit_text(error_text)
                else:
                    current_msg = await reply_func(error_text)
            except:
                pass
        
        # Задержка между отправками
        await asyncio.sleep(3)
    
    user_spamming[user_id] = False
    final_text = f"✅ Рассылка завершена!\nОтправлено: {sent}/{len(groups)}\nОшибок: {errors_count}"
    try:
        if current_msg:
            await current_msg.edit_text(final_text)
        else:
            await reply_func(final_text)
    except:
        try:
            await reply_func(final_text)
        except:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Обработка состояний логина
    if user_id in login_states:
        step = login_states[user_id]['step']
        
        if step == 'phone':
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            success, error = await send_code(user_id, text)
            await update.message.reply_text(error, parse_mode='Markdown')
            if not success and user_id in login_states:
                del login_states[user_id]
        
        elif step == 'code':
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            success, error = await verify_code(user_id, text)
            await update.message.reply_text(error, parse_mode='Markdown')
        
        return
    
    # Обработка команд
    if text.startswith('/add_group'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Укажите группу: /add_group @username")
            return
        
        group = parts[1].strip()
        if not group.startswith('@'):
            group = '@' + group
        
        if user_id not in user_groups:
            user_groups[user_id] = []
        
        if group in user_groups[user_id]:
            await update.message.reply_text(f"⚠️ Группа {group} уже в списке")
        else:
            user_groups[user_id].append(group)
            await update.message.reply_text(
                f"✅ Добавлена группа: {group}\nВсего групп: {len(user_groups[user_id])}"
            )
    
    elif text.startswith('/set_msg'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Укажите сообщение: /set_msg текст")
            return
        
        message_text = parts[1].strip()
        user_messages[user_id] = message_text
        await update.message.reply_text(
            f"✅ Сообщение сохранено:\n{message_text[:200]}"
        )
    
    elif text == '/login':
        # Проверка блокировки
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                if hours > 0:
                    await update.message.reply_text(f"🚫 Вход заблокирован на {hours}ч {minutes}мин")
                else:
                    await update.message.reply_text(f"🚫 Вход заблокирован на {minutes}мин")
                return
        
        # Проверка текущей авторизации
        ready = await is_user_ready(user_id)
        if ready:
            await update.message.reply_text("✅ Вы уже авторизованы!")
            return
        
        # Начинаем процесс логина
        login_states[user_id] = {'step': 'phone'}
        await update.message.reply_text(
            "📱 Введите номер телефона в международном формате:\n"
            "+79998887766\n\n"
            "⚠️ Будьте внимательны! При ошибке блокировка на 24 часа!"
        )
    
    elif text == '/status':
        ready = await is_user_ready(user_id)
        blocked = ""
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                blocked = f"\n• Блокировка: {hours}ч {minutes}мин"
        
        groups_count = len(user_groups.get(user_id, []))
        message = user_messages.get(user_id, "")
        spamming = user_spamming.get(user_id, False)
        
        await update.message.reply_text(
            f"📊 *Статус:*\n"
            f"• Аккаунт: {'✅ Авторизован' if ready else '❌ Не авторизован'}{blocked}\n"
            f"• Групп: {groups_count}\n"
            f"• Сообщение: {message[:50] if message else '❌ Не задано'}\n"
            f"• Рассылка: {'🔄 Активна' if spamming else '⏸ Остановлена'}",
            parse_mode='Markdown'
        )
    
    elif text == '/groups':
        groups = user_groups.get(user_id, [])
        if not groups:
            await update.message.reply_text("📭 Нет добавленных групп")
        else:
            groups_list = '\n'.join(groups)
            await update.message.reply_text(
                f"📋 *Группы ({len(groups)}):*\n{groups_list}",
                parse_mode='Markdown'
            )
    
    elif text == '/start_spam':
        await start_spam_process(update, context, is_callback=False)
    
    elif text == '/stop_spam':
        user_spamming[user_id] = False
        await update.message.reply_text("🛑 Рассылка остановлена")
    
    elif text == '/help':
        await update.message.reply_text(
            "📚 *Доступные команды:*\n\n"
            "/start - Главное меню\n"
            "/login - Войти в аккаунт Telegram\n"
            "/add_group @username - Добавить группу\n"
            "/set_msg текст - Установить сообщение\n"
            "/start_spam - Запустить рассылку\n"
            "/stop_spam - Остановить рассылку\n"
            "/status - Проверить статус\n"
            "/groups - Список групп\n"
            "/help - Помощь\n\n"
            "⚠️ *Важно:* Не пытайтесь входить слишком часто!",
            parse_mode='Markdown'
        )
    
    elif text == '/start':
        await start(update, context)
    
    else:
        await update.message.reply_text(
            "ℹ️ Неизвестная команда. Используйте /start для меню или /help для списка команд."
        )

# ===== ЗАПУСК =====
def main():
    """Точка входа"""
    # Очистка старых сессий при запуске
    for file in os.listdir('.'):
        if file.startswith('session_') and file.endswith('.session'):
            try:
                os.remove(file)
                print(f"Удалена старая сессия: {file}")
            except Exception as e:
                print(f"Не удалось удалить {file}: {e}")
    
    # Запускаем веб-сервер для Render
    webserver_thread = threading.Thread(target=run_webserver, daemon=True)
    webserver_thread.start()
    print("✅ Веб-сервер запущен")
    
    # Создаем и настраиваем бота
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", lambda u, c: handle_message(u, c)))
    app.add_handler(CommandHandler("login", handle_message))
    app.add_handler(CommandHandler("status", handle_message))
    app.add_handler(CommandHandler("groups", handle_message))
    app.add_handler(CommandHandler("start_spam", handle_message))
    app.add_handler(CommandHandler("stop_spam", handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен!")
    print("Используйте /start в Telegram для начала работы")
    
    # Запускаем бота
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
