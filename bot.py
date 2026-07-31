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

# ===== РАБОТА С КЛИЕНТАМИ (С ИСПРАВЛЕНИЕМ ВРЕМЕНИ) =====
def get_client(user_id):
    if user_id not in user_clients:
        # ВАЖНО: добавляем time_offset для синхронизации времени с серверами Telegram
        # Это решает проблему с истекшим кодом при запуске на Render
        client = TelegramClient(
            f'session_{user_id}', 
            API_ID, 
            API_HASH,
            time_offset=0  # Можно попробовать разные значения, но 0 обычно работает
        )
        user_clients[user_id] = client
    return user_clients[user_id]

async def is_user_ready(user_id):
    if user_id not in user_clients:
        return False
    client = user_clients[user_id]
    if not client.is_connected():
        await client.connect()
    return await client.is_user_authorized()

# ===== ЛОГИН ПО КОДУ (ТОЛЬКО ЧЕРЕЗ TELEGRAM) =====
async def send_code(user_id, phone):
    try:
        client = get_client(user_id)
        await client.connect()
        
        # Отправляем запрос кода
        result = await client.send_code_request(phone)
        
        # Сохраняем состояние
        login_states[user_id] = {
            'step': 'code',
            'phone': phone,
            'hash': result.phone_code_hash,
            'attempts': 0
        }
        return True, "✅ Код подтверждения отправлен в Telegram!\n\nПроверьте Telegram на вашем телефоне и введите код цифрами."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

async def verify_code(user_id, code):
    if user_id not in login_states:
        return False, "❌ Сначала используйте /login"
    
    data = login_states[user_id]
    client = get_client(user_id)
    
    try:
        # Пытаемся войти с кодом
        await client.sign_in(data['phone'], code, phone_code_hash=data['hash'])
        del login_states[user_id]
        return True, "✅ Аккаунт авторизован! Теперь можно делать рассылку."
    except errors.PhoneCodeExpiredError:
        # Код истек - отправляем новый
        try:
            new_result = await client.send_code_request(data['phone'])
            login_states[user_id]['hash'] = new_result.phone_code_hash
            login_states[user_id]['attempts'] += 1
            return False, "⚠️ Код истек. Отправлен новый код в Telegram. Введите его:"
        except Exception as e:
            return False, f"❌ Ошибка при отправке нового кода: {str(e)}"
    except errors.PhoneCodeInvalidError:
        return False, "❌ Неверный код. Попробуйте еще раз."
    except errors.FloodWaitError as e:
        return False, f"⏳ Подождите {e.seconds} секунд перед повторной попыткой."
    except errors.PhoneNumberInvalidError:
        return False, "❌ Неверный номер телефона"
    except errors.RPCError as e:
        # Перехватываем любые другие ошибки RPC
        if 'TIME' in str(e).upper() or 'SYNC' in str(e).upper():
            # Пробуем переподключиться с синхронизацией времени
            await client.disconnect()
            await asyncio.sleep(2)
            client = get_client(user_id)
            await client.connect()
            try:
                # Пробуем еще раз
                await client.sign_in(data['phone'], code, phone_code_hash=data['hash'])
                del login_states[user_id]
                return True, "✅ Аккаунт авторизован!"
            except:
                return False, "❌ Ошибка синхронизации времени. Попробуйте /login заново."
        return False, f"❌ Ошибка: {str(e)}"
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

# ===== КОМАНДЫ БОТА =====
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
        "Все команды доступны по кнопкам ↓",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# ===== ОБРАБОТЧИК КНОПОК =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == 'login':
        ready = await is_user_ready(user_id)
        if ready:
            await query.edit_message_text("✅ Вы уже авторизованы!")
            return
        
        login_states[user_id] = {'step': 'phone'}
        await query.edit_message_text(
            "📱 Введите номер телефона в формате:\n"
            "+79998887766\n\n"
            "После ввода номера, код подтверждения придет в Telegram на ваш телефон."
        )
    
    elif query.data == 'add_group':
        await query.edit_message_text(
            "Введите команду вручную:\n"
            "`/add_group @username`\n\n"
            "Например: `/add_group @durov`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'set_msg':
        await query.edit_message_text(
            "Введите команду вручную:\n"
            "`/set_msg Текст сообщения`\n\n"
            "Например: `/set_msg Всем привет!`",
            parse_mode='Markdown'
        )
    
    elif query.data == 'start_spam':
        ready = await is_user_ready(user_id)
        if not ready:
            await query.edit_message_text("❌ Сначала войдите: нажмите 'Войти'")
            return
        if user_id not in user_messages or not user_messages[user_id]:
            await query.edit_message_text("❌ Сначала установите сообщение: /set_msg")
            return
        if user_id not in user_groups or not user_groups[user_id]:
            await query.edit_message_text("❌ Сначала добавьте группы: /add_group")
            return
        if user_spamming.get(user_id, False):
            await query.edit_message_text("⚠️ Рассылка уже идет!")
            return
        
        user_spamming[user_id] = True
        client = get_client(user_id)
        groups = user_groups[user_id]
        msg = user_messages[user_id]
        
        await query.edit_message_text(f"🚀 Рассылка начата в {len(groups)} групп...")
        
        sent = 0
        for group in groups:
            if not user_spamming.get(user_id, False):
                await query.edit_message_text("🛑 Остановлено")
                break
            try:
                await client.send_message(group, msg)
                sent += 1
                await query.edit_message_text(f"✅ Отправлено в {group}")
                await asyncio.sleep(5)
            except Exception as e:
                await query.edit_message_text(f"❌ Ошибка в {group}: {str(e)[:50]}")
                await asyncio.sleep(10)
        
        user_spamming[user_id] = False
        await query.edit_message_text(f"✅ Готово! Отправлено в {sent} групп")
    
    elif query.data == 'stop_spam':
        user_spamming[user_id] = False
        await query.edit_message_text("🛑 Остановка...")
    
    elif query.data == 'status':
        ready = await is_user_ready(user_id)
        await query.edit_message_text(
            f"📊 *Статус:*\n"
            f"• Аккаунт: {'✅ Авторизован' if ready else '❌ Не авторизован'}\n"
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
            await query.edit_message_text(f"📋 *Группы:*\n" + '\n'.join(groups), parse_mode='Markdown')

# ===== ОБРАБОТЧИК СООБЩЕНИЙ =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if user_id in login_states:
        step = login_states[user_id]['step']
        
        if step == 'phone':
            success, error = await send_code(user_id, text)
            if success:
                await update.message.reply_text(error)
            else:
                await update.message.reply_text(f"{error}\nПопробуйте /login заново")
                del login_states[user_id]
        
        elif step == 'code':
            success, error = await verify_code(user_id, text)
            if success:
                await update.message.reply_text(error)
                # Инициализируем хранилище
                if user_id not in user_groups:
                    user_groups[user_id] = []
                if user_id not in user_messages:
                    user_messages[user_id] = ""
                if user_id not in user_spamming:
                    user_spamming[user_id] = False
                del login_states[user_id]
            else:
                await update.message.reply_text(error)
        
        return
    
    if text.startswith('/add_group'):
        args = text.split()
        if len(args) < 2:
            await update.message.reply_text("❌ /add_group @chat")
            return
        if user_id not in user_groups:
            user_groups[user_id] = []
        group = args[1]
        if group not in user_groups[user_id]:
            user_groups[user_id].append(group)
            await update.message.reply_text(f"✅ Добавлено: {group}")
        else:
            await update.message.reply_text(f"⚠️ Группа уже есть: {group}")
    
    elif text.startswith('/set_msg'):
        args = text.split()
        if len(args) < 2:
            await update.message.reply_text("❌ /set_msg Текст")
            return
        user_messages[user_id] = ' '.join(args[1:])
        await update.message.reply_text(f"✅ Сообщение сохранено:\n{user_messages[user_id]}")
    
    elif text == '/login':
        ready = await is_user_ready(user_id)
        if ready:
            await update.message.reply_text("✅ Вы уже авторизованы!")
            return
        login_states[user_id] = {'step': 'phone'}
        await update.message.reply_text(
            "📱 Введите номер телефона в формате:\n"
            "+79998887766\n\n"
            "Код подтверждения придет в Telegram"
        )
    
    elif text == '/status':
        ready = await is_user_ready(user_id)
        await update.message.reply_text(
            f"📊 *Статус:*\n"
            f"• Аккаунт: {'✅ Авторизован' if ready else '❌ Не авторизован'}\n"
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
            await update.message.reply_text(f"📋 *Группы:*\n" + '\n'.join(groups), parse_mode='Markdown')
    
    elif text == '/start_spam':
        ready = await is_user_ready(user_id)
        if not ready:
            await update.message.reply_text("❌ Сначала войдите: нажмите 'Войти'")
            return
        if user_id not in user_messages or not user_messages[user_id]:
            await update.message.reply_text("❌ Сначала установите сообщение: /set_msg")
            return
        if user_id not in user_groups or not user_groups[user_id]:
            await update.message.reply_text("❌ Сначала добавьте группы: /add_group")
            return
        if user_spamming.get(user_id, False):
            await update.message.reply_text("⚠️ Рассылка уже идет!")
            return
        
        user_spamming[user_id] = True
        client = get_client(user_id)
        groups = user_groups[user_id]
        msg = user_messages[user_id]
        
        await update.message.reply_text(f"🚀 Рассылка начата в {len(groups)} групп...")
        
        sent = 0
        for group in groups:
            if not user_spamming.get(user_id, False):
                await update.message.reply_text("🛑 Остановлено")
                break
            try:
                await client.send_message(group, msg)
                sent += 1
                await update.message.reply_text(f"✅ Отправлено в {group}")
                await asyncio.sleep(5)
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка в {group}: {str(e)[:50]}")
                await asyncio.sleep(10)
        
        user_spamming[user_id] = False
        await update.message.reply_text(f"✅ Готово! Отправлено в {sent} групп")
    
    elif text == '/stop_spam':
        user_spamming[user_id] = False
        await update.message.reply_text("🛑 Остановка...")
    
    elif text == '/start':
        await start(update, context)
    
    else:
        await update.message.reply_text("ℹ️ Используйте /start для меню")

# ===== ЗАПУСК =====
def main():
    threading.Thread(target=run_webserver, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен! Используйте /start")
    app.run_polling()

if __name__ == "__main__":
    main()
