import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, errors
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

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

# ===== ЛОГИН ТОЛЬКО ПО ПАРОЛЮ (С ПРАВИЛЬНОЙ ИНИЦИАЛИЗАЦИЕЙ) =====
async def login_with_password(user_id, phone, password):
    try:
        client = get_client(user_id)
        await client.connect()
        
        # 1. ОТПРАВЛЯЕМ ЗАПРОС КОДА (это нужно, чтобы Telegram "узнал" аккаунт)
        try:
            await client.send_code_request(phone)
        except:
            pass  # Нам не важно, пришёл код или нет
        
        # 2. СРАЗУ ПРОБУЕМ ВОЙТИ ПО ПАРОЛЮ
        await client.sign_in(password=password)
        return True, None
    except errors.PasswordHashInvalidError:
        return False, "❌ Неверный пароль. Проверьте раскладку и попробуйте еще раз."
    except errors.SessionPasswordNeededError:
        return False, "❌ У вас не включен облачный пароль. Включите в настройках Telegram."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

# ===== КОМАНДЫ БОТА =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Бот для рассылки*\n\n"
        "🔑 `/login` — *войти по номеру и облачному паролю*\n"
        "➕ `/add_group @chat` — *добавить группу*\n"
        "📝 `/set_msg Текст` — *установить сообщение*\n"
        "🚀 `/start_spam` — *запустить рассылку*\n"
        "🛑 `/stop_spam` — *остановить*\n"
        "📊 `/status` — *проверить статус*\n"
        "📋 `/groups` — *список групп*",
        parse_mode='Markdown'
    )

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ready = await is_user_ready(user_id)
    if ready:
        await update.message.reply_text("✅ Вы уже авторизованы!")
        return
    
    login_states[user_id] = {'step': 'phone'}
    await update.message.reply_text(
        "📱 Введите номер телефона в формате:\n"
        "+79998887766"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if user_id not in login_states:
        await update.message.reply_text("ℹ️ Используйте /login для входа")
        return
    
    step = login_states[user_id]['step']
    
    if step == 'phone':
        # Сохраняем номер и сразу переключаемся на пароль
        login_states[user_id]['phone'] = text
        login_states[user_id]['step'] = 'password'
        await update.message.reply_text(
            "🔐 **Введите ваш облачный пароль (2FA)**\n\n"
            "Код из СМС не нужен. Только пароль, который вы установили в настройках Telegram.\n"
            "Если у вас нет облачного пароля — включите его: Настройки → Конфиденциальность → Облачный пароль."
        )
    
    elif step == 'password':
        phone = login_states[user_id]['phone']
        password = text
        
        success, error = await login_with_password(user_id, phone, password)
        
        if success:
            await update.message.reply_text("✅ Аккаунт успешно авторизован по облачному паролю! 🎉")
            del login_states[user_id]
            if user_id not in user_groups:
                user_groups[user_id] = []
            if user_id not in user_messages:
                user_messages[user_id] = ""
            if user_id not in user_spamming:
                user_spamming[user_id] = False
        else:
            await update.message.reply_text(error)

# ===== ОСТАЛЬНЫЕ КОМАНДЫ =====
async def add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Укажите группу: /add_group @chat")
        return
    if user_id not in user_groups:
        user_groups[user_id] = []
    group = context.args[0]
    if group not in user_groups[user_id]:
        user_groups[user_id].append(group)
        await update.message.reply_text(f"✅ Добавлено: {group}")

async def add_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Укажите группы: /add_groups @g1 @g2 @g3")
        return
    if user_id not in user_groups:
        user_groups[user_id] = []
    added = []
    for g in context.args:
        if g not in user_groups[user_id]:
            user_groups[user_id].append(g)
            added.append(g)
    await update.message.reply_text(f"✅ Добавлено групп: {len(added)}\n{', '.join(added) if added else 'Ничего не добавлено'}")

async def set_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Укажите текст: /set_msg Ваше сообщение")
        return
    user_messages[user_id] = ' '.join(context.args)
    await update.message.reply_text(f"✅ Сообщение сохранено:\n{user_messages[user_id]}")

async def start_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ready = await is_user_ready(user_id)
    
    if not ready:
        await update.message.reply_text("❌ Сначала авторизуйтесь: /login")
        return
    if user_id not in user_messages or not user_messages[user_id]:
        await update.message.reply_text("❌ Сначала установите сообщение: /set_msg")
        return
    if user_id not in user_groups or not user_groups[user_id]:
        await update.message.reply_text("❌ Сначала добавьте группы: /add_group")
        return
    if user_spamming.get(user_id, False):
        await update.message.reply_text("⚠️ Рассылка уже идёт!")
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

async def stop_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_spamming[user_id] = False
    await update.message.reply_text("🛑 Остановка...")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ready = await is_user_ready(user_id)
    await update.message.reply_text(
        f"📊 *Статус:*\n"
        f"• Аккаунт: {'✅ Авторизован' if ready else '❌ Не авторизован'}\n"
        f"• Групп: {len(user_groups.get(user_id, []))}\n"
        f"• Сообщение: {user_messages.get(user_id, '❌ Не задано')[:50]}\n"
        f"• Рассылка: {'🔄 Активна' if user_spamming.get(user_id, False) else '⏸ Остановлена'}",
        parse_mode='Markdown'
    )

async def groups_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    groups = user_groups.get(user_id, [])
    if not groups:
        await update.message.reply_text("📭 Групп нет")
    else:
        await update.message.reply_text(f"📋 *Группы:*\n" + '\n'.join(groups), parse_mode='Markdown')

# ===== ЗАПУСК =====
def main():
    threading.Thread(target=run_webserver, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("add_group", add_group))
    app.add_handler(CommandHandler("add_groups", add_groups))
    app.add_handler(CommandHandler("set_msg", set_msg))
    app.add_handler(CommandHandler("start_spam", start_spam))
    app.add_handler(CommandHandler("stop_spam", stop_spam))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("groups", groups_list))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен! Вход ТОЛЬКО по облачному паролю.")
    app.run_polling()

if __name__ == "__main__":
    main()
