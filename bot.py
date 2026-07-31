import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, errors
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ===== ТВОИ ДАННЫЕ =====
API_ID = 36474738
API_HASH = '4dd8134517fc74300fe610a4d385eaa5'
BOT_TOKEN = '8868463698:AAE2C7pPOdyk7ouT64w_O3LMW-BScIqQSCg'

# Глобальное хранилище для клиентов разных пользователей
user_clients = {}  # {user_id: TelegramClient}
user_groups = {}   # {user_id: [groups]}
user_messages = {} # {user_id: str}
user_spamming = {} # {user_id: bool}
login_states = {}  # {user_id: {'step': 'phone'/'code', 'phone': str, 'hash': str}}

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

# ===== ФУНКЦИЯ ПОЛУЧЕНИЯ КЛИЕНТА ДЛЯ ПОЛЬЗОВАТЕЛЯ =====
def get_client(user_id):
    if user_id not in user_clients:
        # Создаем отдельную сессию для каждого пользователя
        user_clients[user_id] = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
    return user_clients[user_id]

async def is_user_ready(user_id):
    if user_id not in user_clients:
        return False
    client = user_clients[user_id]
    if not client.is_connected():
        await client.connect()
    return await client.is_user_authorized()

# ===== ЛОГИН ЧЕРЕЗ КОД (/login) =====
async def start_login(user_id, phone):
    try:
        client = get_client(user_id)
        await client.connect()
        result = await client.send_code_request(phone)
        login_states[user_id] = {
            'step': 'code',
            'phone': phone,
            'hash': result.phone_code_hash
        }
        return True, None
    except Exception as e:
        return False, str(e)

async def complete_login(user_id, code):
    if user_id not in login_states:
        return False, "Сначала используйте /login"
    
    data = login_states[user_id]
    client = get_client(user_id)
    
    try:
        await client.sign_in(data['phone'], code, phone_code_hash=data['hash'])
        del login_states[user_id]
        return True, None
    except errors.PhoneCodeExpiredError:
        # Автоматически отправляем новый код
        try:
            result = await client.send_code_request(data['phone'])
            login_states[user_id]['hash'] = result.phone_code_hash
            return False, "Код истек. Отправлен новый код. Введите его:"
        except Exception as e:
            return False, f"Ошибка: {str(e)}"
    except errors.PhoneCodeInvalidError:
        return False, "Неверный код. Попробуйте еще раз."
    except Exception as e:
        return False, str(e)

# ===== ЗАГРУЗКА СЕССИИ ИЗ ФАЙЛА (/auth) =====
async def load_session_from_file(user_id, file_path):
    try:
        # Перемещаем файл в сессию пользователя
        session_name = f'session_{user_id}'
        os.rename(file_path, f'{session_name}.session')
        client = get_client(user_id)
        await client.connect()
        if await client.is_user_authorized():
            return True
        else:
            return False
    except Exception as e:
        print(f"Ошибка загрузки сессии для {user_id}: {e}")
        return False

# ===== ОБРАБОТЧИК КОМАНД =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"🤖 Бот для рассылки\n\n"
        f"Ваш ID: `{user_id}`\n\n"
        "🔑 /login — войти по номеру и коду\n"
        "📤 /auth — войти через файл session.session\n"
        "➕ /add_group @chat — добавить группу\n"
        "📝 /set_msg Текст — установить сообщение\n"
        "🚀 /start_spam — запустить рассылку\n"
        "🛑 /stop_spam — остановить\n"
        "📊 /status — проверить статус\n"
        "📋 /groups — список групп",
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

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📤 Отправьте мне файл **session.session** как документ.\n\n"
        "Как получить:\n"
        "1. Скачайте login.py на ПК\n"
        "2. Запустите: python login.py\n"
        "3. Введите номер и код\n"
        "4. Отправьте получившийся файл сюда"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    document = update.message.document
    
    if document.file_name != 'session.session':
        await update.message.reply_text("❌ Отправьте файл с именем session.session")
        return
    
    file = await context.bot.get_file(document.file_id)
    file_path = f'temp_{user_id}.session'
    await file.download_to_drive(file_path)
    
    await update.message.reply_text("⏳ Загружаю сессию...")
    success = await load_session_from_file(user_id, file_path)
    
    if success:
        await update.message.reply_text("✅ Аккаунт авторизован! Теперь можно рассылать.")
    else:
        await update.message.reply_text("❌ Неверный файл сессии. Попробуйте снова.")
    
    if os.path.exists(file_path):
        os.remove(file_path)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if user_id not in login_states:
        await update.message.reply_text("ℹ️ Используйте /login для входа")
        return
    
    step = login_states[user_id]['step']
    
    if step == 'phone':
        success, error = await start_login(user_id, text)
        if success:
            await update.message.reply_text("✅ Код отправлен в Telegram!\nВведите код цифрами:")
        else:
            await update.message.reply_text(f"❌ Ошибка: {error}\nПопробуйте /login заново")
            del login_states[user_id]
    
    elif step == 'code':
        success, error = await complete_login(user_id, text)
        if success:
            await update.message.reply_text("✅ Аккаунт авторизован! Можно работать.")
            if user_id not in user_groups:
                user_groups[user_id] = []
            if user_id not in user_messages:
                user_messages[user_id] = ""
            if user_id not in user_spamming:
                user_spamming[user_id] = False
        else:
            if "Отправлен новый код" in error:
                await update.message.reply_text(f"⚠️ {error}")
            else:
                await update.message.reply_text(f"❌ Ошибка: {error}\nПопробуйте /login заново")
                del login_states[user_id]

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
    else:
        await update.message.reply_text(f"⚠️ Группа уже есть: {group}")

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
        await update.message.reply_text("❌ Сначала авторизуйтесь: /login или /auth")
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
        f"📊 Статус:\n"
        f"• Аккаунт: {'✅ Авторизован' if ready else '❌ Не авторизован'}\n"
        f"• Групп: {len(user_groups.get(user_id, []))}\n"
        f"• Сообщение: {user_messages.get(user_id, '❌ Не задано')[:50]}\n"
        f"• Рассылка: {'🔄 Активна' if user_spamming.get(user_id, False) else '⏸ Остановлена'}"
    )

async def groups_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    groups = user_groups.get(user_id, [])
    if not groups:
        await update.message.reply_text("📭 Групп нет")
    else:
        await update.message.reply_text(f"📋 Группы:\n" + '\n'.join(groups))

# ===== ЗАПУСК =====
def main():
    threading.Thread(target=run_webserver, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("add_group", add_group))
    app.add_handler(CommandHandler("set_msg", set_msg))
    app.add_handler(CommandHandler("start_spam", start_spam))
    app.add_handler(CommandHandler("stop_spam", stop_spam))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("groups", groups_list))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен! Мульти-пользовательский режим активен.")
    app.run_polling()

if __name__ == "__main__":
    main()
