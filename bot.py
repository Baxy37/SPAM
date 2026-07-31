import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, errors
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ===== КОНФИГ =====
API_ID = 2040
API_HASH = 'b18441a1ff607e10a989891a5462e627'
BOT_TOKEN = '8868463698:AAE2C7pPOdyk7ouT64w_O3LMW-BScIqQSCg'

# ===== ХРАНИЛИЩЕ ДАННЫХ ПОЛЬЗОВАТЕЛЕЙ =====
user_sessions = {}  # {user_id: {'client': TelegramClient, 'phone': str, 'step': str, 'hash': str, 'ready': bool}}
user_groups = {}    # {user_id: [groups]}
user_messages = {}  # {user_id: str}
user_spamming = {}  # {user_id: bool}

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
    print(f"✅ Веб-сервер запущен на порту {port}")
    server.serve_forever()

# ===== ФУНКЦИИ ВХОДА =====
async def start_login(user_id, phone):
    """Начинает процесс входа для пользователя"""
    try:
        client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
        await client.connect()
        
        # Отправляем запрос кода
        result = await client.send_code_request(phone)
        
        # Сохраняем данные
        user_sessions[user_id] = {
            'client': client,
            'phone': phone,
            'step': 'code',
            'hash': result.phone_code_hash,
            'ready': False
        }
        return True, None
    except Exception as e:
        return False, str(e)

async def complete_login(user_id, code):
    """Завершает вход с кодом"""
    if user_id not in user_sessions:
        return False, "Сначала используйте /login"
    
    data = user_sessions[user_id]
    client = data['client']
    
    try:
        await client.sign_in(data['phone'], code, phone_code_hash=data['hash'])
        data['ready'] = True
        data['step'] = 'done'
        return True, None
    except errors.SessionPasswordNeededError:
        return False, "Включена двухфакторная авторизация (не поддерживается)"
    except Exception as e:
        return False, str(e)

# ===== КОМАНДЫ БОТА =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"🤖 Бот для рассылки\n\n"
        f"👤 Ваш ID: {user_id}\n\n"
        f"🔑 /login — войти в аккаунт\n"
        f"➕ /add_group @chat — добавить группу\n"
        f"📝 /set_msg Текст — установить сообщение\n"
        f"🚀 /start_spam — запустить рассылку\n"
        f"🛑 /stop_spam — остановить\n"
        f"📊 /status — проверить статус\n"
        f"📋 /groups — список групп"
    )

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in user_sessions and user_sessions[user_id].get('ready', False):
        await update.message.reply_text("✅ Вы уже авторизованы!")
        return
    
    user_sessions[user_id] = {'step': 'phone', 'ready': False}
    await update.message.reply_text(
        "📱 Введите номер телефона в формате:\n"
        "+79998887766"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Если пользователь не в процессе входа
    if user_id not in user_sessions or user_sessions[user_id].get('step') not in ['phone', 'code']:
        await update.message.reply_text("ℹ️ Используйте /login для входа")
        return
    
    step = user_sessions[user_id]['step']
    
    if step == 'phone':
        # Ввели номер телефона
        success, error = await start_login(user_id, text)
        if success:
            await update.message.reply_text(
                "✅ Код отправлен в Telegram!\n"
                "Введите код цифрами:"
            )
        else:
            await update.message.reply_text(f"❌ Ошибка: {error}\nПопробуйте /login заново")
            del user_sessions[user_id]
    
    elif step == 'code':
        # Ввели код
        success, error = await complete_login(user_id, text)
        if success:
            await update.message.reply_text("✅ Аккаунт авторизован! Можно работать.")
            # Инициализируем данные пользователя
            if user_id not in user_groups:
                user_groups[user_id] = []
            if user_id not in user_messages:
                user_messages[user_id] = ""
            if user_id not in user_spamming:
                user_spamming[user_id] = False
        else:
            await update.message.reply_text(f"❌ Ошибка: {error}\nПопробуйте /login заново")
            del user_sessions[user_id]

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
    
    # Проверки
    if user_id not in user_sessions or not user_sessions[user_id].get('ready', False):
        await update.message.reply_text("❌ Сначала войдите: /login")
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
    client = user_sessions[user_id]['client']
    groups = user_groups[user_id]
    msg = user_messages[user_id]
    
    await update.message.reply_text(f"🚀 Рассылка начата в {len(groups)} групп...")
    
    sent = 0
    for group in groups:
        if not user_spamming.get(user_id, False):
            await update.message.reply_text("🛑 Рассылка остановлена")
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
    await update.message.reply_text("🛑 Остановка рассылки...")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    is_ready = user_id in user_sessions and user_sessions[user_id].get('ready', False)
    groups_count = len(user_groups.get(user_id, []))
    msg = user_messages.get(user_id, "")
    spamming = user_spamming.get(user_id, False)
    
    await update.message.reply_text(
        f"📊 Статус:\n"
        f"• Аккаунт: {'✅ Авторизован' if is_ready else '❌ Не авторизован'}\n"
        f"• Групп: {groups_count}\n"
        f"• Сообщение: {msg[:50] + '...' if msg else '❌ Не задано'}\n"
        f"• Рассылка: {'🔄 Активна' if spamming else '⏸ Остановлена'}"
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
    # Запускаем веб-сервер в отдельном потоке
    thread = threading.Thread(target=run_webserver, daemon=True)
    thread.start()
    
    # Запускаем бота
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
    
    print("✅ Бот запущен! Могут подключаться несколько пользователей.")
    app.run_polling()

if __name__ == "__main__":
    main()
