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
flood_wait_tracker = {}  # Отслеживание блокировок

# ===== ВЕБ-СЕРВЕР ДЛЯ RENDER =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running!')

def run_webserver():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

# ===== РАБОТА С КЛИЕНТАМИ =====
def get_client(user_id, use_test_server=False):
    """Создание клиента с возможностью использования тестового сервера"""
    session_name = f'session_{user_id}'
    
    # Если пользователь заблокирован, создаем новую сессию
    if user_id in flood_wait_tracker:
        remaining = flood_wait_tracker[user_id] - time.time()
        if remaining > 0:
            return None, f"❌ Аккаунт заблокирован на {int(remaining/60)} минут"
        else:
            del flood_wait_tracker[user_id]
            # Удаляем старую сессию
            if os.path.exists(f'{session_name}.session'):
                os.remove(f'{session_name}.session')
            if user_id in user_clients:
                del user_clients[user_id]
    
    if user_id not in user_clients:
        client = TelegramClient(
            session_name,
            API_ID, 
            API_HASH,
            system_version="4.16.30-vxCUSTOM",
            device_model="PC",
            app_version="4.16.30",
            connection_retries=1,  # Уменьшаем попытки
            retry_delay=5,
            auto_reconnect=False,  # Отключаем авто-переподключение
            request_retries=1  # Минимум повторных запросов
        )
        user_clients[user_id] = client
    
    return user_clients[user_id], None

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

# ===== ИСПРАВЛЕННЫЙ ЛОГИН =====
async def send_code(user_id, phone):
    # Проверка блокировки
    if user_id in flood_wait_tracker:
        remaining = int(flood_wait_tracker[user_id] - time.time())
        if remaining > 0:
            minutes = remaining // 60
            hours = minutes // 60
            if hours > 0:
                return False, f"⏳ Аккаунт заблокирован на {hours} часов. Попробуйте позже."
            else:
                return False, f"⏳ Аккаунт заблокирован на {minutes} минут. Попробуйте позже."
        else:
            del flood_wait_tracker[user_id]
    
    try:
        client = get_client(user_id)
        if client is None:
            return False, "❌ Ошибка создания клиента"
        
        # Всегда начинаем с чистого подключения
        if client.is_connected():
            await client.disconnect()
            await asyncio.sleep(2)
        
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
        
        minutes = e.seconds // 60
        hours = minutes // 60
        
        if hours > 0:
            return False, f"🚫 Telegram заблокировал этот номер на {hours} часов!\n\n"
        else:
            return False, f"🚫 Telegram заблокировал этот номер на {minutes} минут!\n\n"
    
    except errors.PhoneNumberInvalidError:
        return False, "❌ Неверный формат номера. Используйте международный формат: +79998887766"
    
    except errors.PhoneNumberBannedError:
        return False, "❌ Этот номер заблокирован в Telegram"
    
    except Exception as e:
        error_str = str(e)
        if 'FLOOD' in error_str.upper():
            # Извлекаем время из ошибки если возможно
            try:
                wait_time = int(''.join(filter(str.isdigit, error_str)))
                flood_wait_tracker[user_id] = time.time() + wait_time
            except:
                flood_wait_tracker[user_id] = time.time() + 86400  # 24 часа по умолчанию
            
            return False, f"🚫 Слишком много попыток! Подождите несколько часов."
        
        return False, f"❌ Ошибка: {error_str[:100]}\nПопробуйте позже или проверьте номер."

async def verify_code(user_id, code):
    if user_id not in login_states:
        return False, "❌ Сначала используйте /login"
    
    data = login_states[user_id]
    client = user_clients.get(user_id)
    
    if not client:
        return False, "❌ Сессия потеряна. Используйте /login заново"
    
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
        
        return True, "✅ Аккаунт авторизован! Теперь можно делать рассылку.\n\nИспользуйте:\n• /add_group @username\n• /set_msg ваш текст\n• /start_spam"
    
    except errors.PhoneCodeExpiredError:
        # Код истек - отправляем новый
        try:
            new_result = await client.send_code_request(data['phone'])
            login_states[user_id]['hash'] = new_result.phone_code_hash
            login_states[user_id]['attempts'] += 1
            return False, "⚠️ Код истек. Новый код отправлен в Telegram. Введите его:"
        except errors.FloodWaitError as e:
            del login_states[user_id]
            return False, f"🚫 Слишком много попыток! Подождите {e.seconds//60} минут."
    
    except errors.PhoneCodeInvalidError:
        return False, "❌ Неверный код. Проверьте и попробуйте еще раз."
    
    except errors.FloodWaitError as e:
        del login_states[user_id]
        return False, f"🚫 Заблокировано на {e.seconds//60} минут."
    
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)[:100]}"

# ===== ОСТАЛЬНЫЕ ФУНКЦИИ (без изменений, только улучшенный spam) =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔑 Войти", callback_data='login')],
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
        "⚠️ *Важно:* Не пытайтесь входить слишком часто!\n"
        "Если получили блокировку - ждите.\n\n"
        "Все команды доступны по кнопкам ↓",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                await query.edit_message_text(
                    f"🚫 Вход заблокирован!\n"
                    f"Попробуйте через {hours}ч {minutes}мин"
                )
                return
        
        ready = await is_user_ready(user_id)
        if ready:
            await query.edit_message_text("✅ Вы уже авторизованы!")
            return
        
        login_states[user_id] = {'step': 'phone'}
        await query.edit_message_text(
            "📱 Введите номер телефона в международном формате:\n"
            "+79998887766\n\n"
            "⚠️ *Вводите осторожно! При ошибке ждите 24 часа!*\n\n"
            "После ввода номера, код придет в Telegram.",
            parse_mode='Markdown'
        )
    
    # Остальные кнопки остаются без изменений
    elif query.data == 'add_group':
        await query.edit_message_text(
            "Введите команду:\n"
            "`/add_group @username`\n\n"
            "Пример: `/add_group @durov`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'set_msg':
        await query.edit_message_text(
            "Введите команду:\n"
            "`/set_msg Текст сообщения`\n\n"
            "Пример: `/set_msg Всем привет!`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'start_spam':
        ready = await is_user_ready(user_id)
        if not ready:
            await query.edit_message_text("❌ Сначала войдите: нажмите 'Войти'")
            return
        if user_id not in user_messages or not user_messages[user_id]:
            await query.edit_message_text("❌ Установите сообщение: /set_msg")
            return
        if user_id not in user_groups or not user_groups[user_id]:
            await query.edit_message_text("❌ Добавьте группы: /add_group")
            return
        if user_spamming.get(user_id, False):
            await query.edit_message_text("⚠️ Рассылка уже идет!")
            return
        
        user_spamming[user_id] = True
        client = user_clients[user_id]
        groups = user_groups[user_id][:]
        msg = user_messages[user_id]
        
        status_msg = await query.edit_message_text(f"🚀 Рассылка начата в {len(groups)} групп...")
        
        sent = 0
        errors_count = 0
        for i, group in enumerate(groups, 1):
            if not user_spamming.get(user_id, False):
                await status_msg.edit_text(f"🛑 Остановлено. Отправлено: {sent}")
                break
            
            try:
                await client.send_message(group, msg)
                sent += 1
                await status_msg.edit_text(f"✅ [{i}/{len(groups)}] Отправлено в {group}")
            except errors.FloodWaitError as e:
                await status_msg.edit_text(f"⏳ [{i}/{len(groups)}] Пауза {e.seconds}с...")
                await asyncio.sleep(e.seconds + 1)
                try:
                    await client.send_message(group, msg)
                    sent += 1
                    await status_msg.edit_text(f"✅ [{i}/{len(groups)}] Отправлено в {group}")
                except:
                    errors_count += 1
                    await status_msg.edit_text(f"❌ [{i}/{len(groups)}] Ошибка в {group}")
            except Exception as e:
                errors_count += 1
                await status_msg.edit_text(f"❌ [{i}/{len(groups)}] Ошибка: {str(e)[:30]}")
            
            await asyncio.sleep(3)  # Задержка между отправками
        
        user_spamming[user_id] = False
        await status_msg.edit_text(f"✅ Готово! Отправлено: {sent}, ошибок: {errors_count}")
    
    elif query.data == 'stop_spam':
        user_spamming[user_id] = False
        await query.edit_message_text("🛑 Рассылка остановлена")
    
    elif query.data == 'status':
        ready = await is_user_ready(user_id)
        blocked = ""
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                blocked = f"\n• Блокировка: {remaining//3600}ч {(remaining%3600)//60}мин"
        
        await query.edit_message_text(
            f"📊 *Статус:*\n"
            f"• Аккаунт: {'✅ Авторизован' if ready else '❌ Не авторизован'}{blocked}\n"
            f"• Групп: {len(user_groups.get(user_id, []))}\n"
            f"• Сообщение: {user_messages.get(user_id, '❌ Не задано')[:50]}\n"
            f"• Рассылка: {'🔄 Активна' if user_spamming.get(user_id, False) else '⏸ Остановлена'}",
            parse_mode='Markdown'
        )
    
    elif query.data == 'groups':
        groups = user_groups.get(user_id, [])
        if not groups:
            await query.edit_message_text("📭 Групп нет")
        else:
            await query.edit_message_text(f"📋 *Группы ({len(groups)}):*\n" + '\n'.join(groups), parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Обработка состояний логина
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
    
    # Обработка команд
    if text.startswith('/add_group'):
        args = text.split()
        if len(args) < 2:
            await update.message.reply_text("❌ Формат: /add_group @username")
            return
        group = args[1]
        if user_id not in user_groups:
            user_groups[user_id] = []
        if group not in user_groups[user_id]:
            user_groups[user_id].append(group)
            await update.message.reply_text(f"✅ Добавлено: {group}\nВсего групп: {len(user_groups[user_id])}")
        else:
            await update.message.reply_text(f"⚠️ Группа уже есть: {group}")
    
    elif text.startswith('/set_msg'):
        args = text.split()
        if len(args) < 2:
            await update.message.reply_text("❌ Формат: /set_msg Текст")
            return
        user_messages[user_id] = ' '.join(args[1:])
        await update.message.reply_text(f"✅ Сообщение сохранено:\n{user_messages[user_id][:200]}")
    
    elif text == '/login':
        if user_id in flood_wait_tracker:
            remaining = int(flood_wait_tracker[user_id] - time.time())
            if remaining > 0:
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                await update.message.reply_text(
                    f"🚫 Вход заблокирован!\n"
                    f"Осталось ждать: {hours}ч {minutes}мин\n\n"
                    f"Причина: слишком много попыток входа."
                )
                return
        
        ready = await is_user_ready(user_id)
        if ready:
            await update.message.reply_text("✅ Вы уже авторизованы!")
            return
        
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
                blocked = f"\n• Блокировка: {remaining//3600}ч {(remaining%3600)//60}мин"
        
        await update.message.reply_text(
            f"📊 *Статус:*\n"
            f"• Аккаунт: {'✅ Авторизован' if ready else '❌ Не авторизован'}{blocked}\n"
            f"• Групп: {len(user_groups.get(user_id, []))}\n"
            f"• Сообщение: {user_messages.get(user_id, '❌ Не задано')[:50]}\n"
            f"• Рассылка: {'🔄 Активна' if user_spamming.get(user_id, False) else '⏸ Остановлена'}",
            parse_mode='Markdown'
        )
    
    elif text == '/groups':
        groups = user_groups.get(user_id, [])
        if not groups:
            await update.message.reply_text("📭 Групп нет")
        else:
            await update.message.reply_text(
                f"📋 *Группы ({len(groups)}):*\n" + '\n'.join(groups),
                parse_mode='Markdown'
            )
    
    elif text == '/start_spam':
        ready = await is_user_ready(user_id)
        if not ready:
            await update.message.reply_text("❌ Сначала войдите: /login")
            return
        if user_id not in user_messages or not user_messages[user_id]:
            await update.message.reply_text("❌ Установите сообщение: /set_msg")
            return
        if user_id not in user_groups or not user_groups[user_id]:
            await update.message.reply_text("❌ Добавьте группы: /add_group")
            return
        if user_spamming.get(user_id, False):
            await update.message.reply_text("⚠️ Рассылка уже идет!")
            return
        
        user_spamming[user_id] = True
        client = user_clients[user_id]
        groups = user_groups[user_id][:]
        msg = user_messages[user_id]
        
        status_msg = await update.message.reply_text(f"🚀 Рассылка начата в {len(groups)} групп...")
        
        sent = 0
        errors_count = 0
        for i, group in enumerate(groups, 1):
            if not user_spamming.get(user_id, False):
                await status_msg.edit_text(f"🛑 Остановлено. Отправлено: {sent}")
                break
            
            try:
                await client.send_message(group, msg)
                sent += 1
                await status_msg.edit_text(f"✅ [{i}/{len(groups)}] Отправлено в {group}")
            except errors.FloodWaitError as e:
                await status_msg.edit_text(f"⏳ [{i}/{len(groups)}] Пауза {e.seconds}с...")
                await asyncio.sleep(e.seconds + 1)
                try:
                    await client.send_message(group, msg)
                    sent += 1
                except:
                    errors_count += 1
            except Exception as e:
                errors_count += 1
                await status_msg.edit_text(f"❌ [{i}/{len(groups)}] Ошибка: {str(e)[:30]}")
            
            await asyncio.sleep(3)
        
        user_spamming[user_id] = False
        await status_msg.edit_text(f"✅ Готово! Отправлено: {sent}, ошибок: {errors_count}")
    
    elif text == '/stop_spam':
        user_spamming[user_id] = False
        await update.message.reply_text("🛑 Рассылка остановлена")
    
    elif text == '/start':
        await start(update, context)
    
    elif text == '/help':
        await update.message.reply_text(
            "📚 *Доступные команды:*\n\n"
            "/start - Главное меню\n"
            "/login - Войти в аккаунт Telegram\n"
            "/add_group @user - Добавить группу\n"
            "/set_msg текст - Установить сообщение\n"
            "/start_spam - Запустить рассылку\n"
            "/stop_spam - Остановить рассылку\n"
            "/status - Проверить статус\n"
            "/groups - Список групп\n\n"
            "⚠️ *Важно:* Не пытайтесь входить слишком часто!",
            parse_mode='Markdown'
        )

# ===== ЗАПУСК =====
def main():
    # Очистка старых сессий при запуске
    for file in os.listdir('.'):
        if file.startswith('session_') and file.endswith('.session'):
            try:
                os.remove(file)
            except:
                pass
    
    # Запускаем веб-сервер для Render
    threading.Thread(target=run_webserver, daemon=True).start()
    
    # Создаем приложение
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", 
        lambda u, c: u.message.reply_text("Используйте /start")))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен! Используйте /start")
    app.run_polling()

if __name__ == "__main__":
    main()
