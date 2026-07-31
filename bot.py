import os
import asyncio
import threading
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

# ===== РАБОТА С КЛИЕНТАМИ =====
def get_client(user_id):
    if user_id not in user_clients:
        user_clients[user_id] = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
    return user_clients[user_id]

async def is_user_ready(user_id):
    if user_id not in user_clients:
        return False
    client = user_clients[user_id]
    if not client.is_connected():
        await client.connect()
    return await client.is_user_authorized()

# ===== ЛОГИН С ПАРОЛЕМ (ПРАВИЛЬНАЯ ИНИЦИАЛИЗАЦИЯ) =====
async def login_with_password(user_id, phone, password):
    try:
        client = get_client(user_id)
        await client.connect()
        
        # ОТПРАВЛЯЕМ ЗАПРОС КОДА (ЭТО ОБЯЗАТЕЛЬНО!)
        try:
            await client.send_code_request(phone)
        except Exception as e:
            print(f"Код не отправился, но похуй: {e}")
        
        # ПРОБУЕМ ВОЙТИ ПО ПАРОЛЮ
        await client.sign_in(password=password)
        return True, None
    except errors.PasswordHashInvalidError:
        return False, "❌ Неверный пароль. Проверь раскладку."
    except errors.SessionPasswordNeededError:
        return False, "❌ У тебя НЕТ облачного пароля! Включи в настройках Telegram."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

# ===== КОМАНДЫ БОТА (С КНОПКАМИ) =====
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
        "🤖 *ЕБАНУТЫЙ БОТ ДЛЯ РАССЫЛКИ*\n\n"
        "Жми на кнопки, не еби мозги!",
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
            await query.edit_message_text("✅ Ты уже залогинен, ебанат!")
            return
        
        login_states[user_id] = {'step': 'phone'}
        await query.edit_message_text(
            "📱 Введи номер телефона в формате:\n"
            "+79998887766"
        )
    
    elif query.data == 'add_group':
        await query.edit_message_text("❌ Введи команду вручную:\n/add_group @chat")
    
    elif query.data == 'set_msg':
        await query.edit_message_text("❌ Введи команду вручную:\n/set_msg Текст сообщения")
    
    elif query.data == 'start_spam':
        ready = await is_user_ready(user_id)
        if not ready:
            await query.edit_message_text("❌ Сначала залогинься! /login")
            return
        if user_id not in user_messages or not user_messages[user_id]:
            await query.edit_message_text("❌ Сначала установи сообщение! /set_msg")
            return
        if user_id not in user_groups or not user_groups[user_id]:
            await query.edit_message_text("❌ Сначала добавь группы! /add_group")
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
                await asyncio.sleep(8)
            except Exception as e:
                await query.edit_message_text(f"❌ Ошибка в {group}: {str(e)[:50]}")
                await asyncio.sleep(15)
        
        user_spamming[user_id] = False
        await query.edit_message_text(f"✅ Готово! Отправлено в {sent} групп")
    
    elif query.data == 'stop_spam':
        user_spamming[user_id] = False
        await query.edit_message_text("🛑 Остановка рассылки...")
    
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
    
    # Если пользователь в процессе входа
    if user_id in login_states:
        step = login_states[user_id]['step']
        
        if step == 'phone':
            login_states[user_id]['phone'] = text
            login_states[user_id]['step'] = 'password'
            await update.message.reply_text(
                "🔐 *Введи свой облачный пароль (2FA)*\n\n"
                "Код не нужен! Только пароль.",
                parse_mode='Markdown'
            )
        
        elif step == 'password':
            phone = login_states[user_id]['phone']
            password = text
            
            success, error = await login_with_password(user_id, phone, password)
            
            if success:
                await update.message.reply_text("✅ **Аккаунт залогинен!**")
                del login_states[user_id]
                if user_id not in user_groups:
                    user_groups[user_id] = []
                if user_id not in user_messages:
                    user_messages[user_id] = ""
                if user_id not in user_spamming:
                    user_spamming[user_id] = False
            else:
                await update.message.reply_text(f"{error}\nПопробуй еще раз.")
        
        return
    
    # Обычные команды
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
            await update.message.reply_text("✅ Ты уже залогинен!")
            return
        login_states[user_id] = {'step': 'phone'}
        await update.message.reply_text(
            "📱 Введи номер телефона:\n"
            "+79998887766"
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
            await update.message.reply_text("❌ Сначала залогинься! /login")
            return
        if user_id not in user_messages or not user_messages[user_id]:
            await update.message.reply_text("❌ Сначала установи сообщение! /set_msg")
            return
        if user_id not in user_groups or not user_groups[user_id]:
            await update.message.reply_text("❌ Сначала добавь группы! /add_group")
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
                await asyncio.sleep(8)
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка в {group}: {str(e)[:50]}")
                await asyncio.sleep(15)
        
        user_spamming[user_id] = False
        await update.message.reply_text(f"✅ Готово! Отправлено в {sent} групп")
    
    elif text == '/stop_spam':
        user_spamming[user_id] = False
        await update.message.reply_text("🛑 Остановка...")
    
    else:
        await update.message.reply_text("ℹ️ Используй /start для меню")

# ===== ЗАПУСК =====
def main():
    threading.Thread(target=run_webserver, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен! Жми кнопки, не еби мозги!")
    app.run_polling()

if __name__ == "__main__":
    main()
