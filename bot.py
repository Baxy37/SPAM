import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ===== КОНФИГ =====
API_ID = 2040
API_HASH = 'b18441a1ff607e10a989891a5462e627'
BOT_TOKEN = '8868463698:AAE2C7pPOdyk7ouT64w_O3LMW-BScIqQSCg'

# ===== СОСТОЯНИЕ =====
user_client = None
is_ready = False
login_data = {}
groups = []
spam_message = ""
is_spamming = False

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

# ===== ФУНКЦИЯ ВХОДА =====
async def login_user(phone, code=None):
    global user_client, is_ready
    try:
        user_client = TelegramClient('session', API_ID, API_HASH)
        await user_client.start(phone=phone, code_callback=lambda: code)
        is_ready = True
        return True
    except Exception as e:
        return str(e)

# ===== КОМАНДЫ БОТА =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Бот готов!\n\n"
        "🔑 /login — начать вход в аккаунт\n"
        "➕ /add_group @chat — добавить группу\n"
        "📝 /set_msg Текст — установить сообщение\n"
        "🚀 /start_spam — запустить рассылку\n"
        "🛑 /stop_spam — остановить\n"
        "📊 /status — проверить статус\n"
        "📋 /groups — список групп"
    )

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login_data[update.effective_user.id] = {'step': 'phone'}
    await update.message.reply_text(
        "📱 Введите номер телефона в формате:\n"
        "+79998887766"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if user_id not in login_data:
        await update.message.reply_text("ℹ️ Используйте /login для входа")
        return
    
    step = login_data[user_id]['step']
    
    if step == 'phone':
        login_data[user_id]['phone'] = text
        login_data[user_id]['step'] = 'code'
        
        try:
            client = TelegramClient('temp', API_ID, API_HASH)
            await client.connect()
            await client.send_code_request(text)
            await client.disconnect()
            await update.message.reply_text(
                "✅ Код отправлен в Telegram!\n"
                "Введите код цифрами:"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)[:100]}\nПопробуйте /login заново")
            del login_data[user_id]
    
    elif step == 'code':
        phone = login_data[user_id]['phone']
        result = await login_user(phone, text)
        
        if result is True:
            del login_data[user_id]
            await update.message.reply_text("✅ Аккаунт авторизован! Можно работать.")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result}\nПопробуйте /login заново")
            del login_data[user_id]

async def add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажите группу: /add_group @chat")
        return
    group = context.args[0]
    if group not in groups:
        groups.append(group)
        await update.message.reply_text(f"✅ Добавлено: {group}")
    else:
        await update.message.reply_text(f"⚠️ Группа уже есть: {group}")

async def add_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажите группы: /add_groups @g1 @g2 @g3")
        return
    added = []
    for g in context.args:
        if g not in groups:
            groups.append(g)
            added.append(g)
    await update.message.reply_text(f"✅ Добавлено групп: {len(added)}\n{', '.join(added) if added else 'Ничего не добавлено'}")

async def set_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global spam_message
    if not context.args:
        await update.message.reply_text("❌ Укажите текст: /set_msg Ваше сообщение")
        return
    spam_message = ' '.join(context.args)
    await update.message.reply_text(f"✅ Сообщение сохранено:\n{spam_message}")

async def start_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_spamming
    if not is_ready:
        await update.message.reply_text("❌ Сначала войдите: /login")
        return
    if not spam_message:
        await update.message.reply_text("❌ Сначала установите сообщение: /set_msg")
        return
    if not groups:
        await update.message.reply_text("❌ Сначала добавьте группы: /add_group")
        return
    
    is_spamming = True
    await update.message.reply_text(f"🚀 Рассылка начата в {len(groups)} групп...")
    
    sent = 0
    for group in groups:
        if not is_spamming:
            await update.message.reply_text("🛑 Рассылка остановлена")
            break
        try:
            await user_client.send_message(group, spam_message)
            sent += 1
            await update.message.reply_text(f"✅ Отправлено в {group}")
            await asyncio.sleep(8)
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка в {group}: {str(e)[:50]}")
            await asyncio.sleep(15)
    
    is_spamming = False
    await update.message.reply_text(f"✅ Готово! Отправлено в {sent} групп")

async def stop_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_spamming
    is_spamming = False
    await update.message.reply_text("🛑 Остановка рассылки...")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 Статус:\n"
        f"• Аккаунт: {'✅ Авторизован' if is_ready else '❌ Не авторизован'}\n"
        f"• Групп: {len(groups)}\n"
        f"• Сообщение: {spam_message[:50] + '...' if spam_message else '❌ Не задано'}\n"
        f"• Рассылка: {'🔄 Активна' if is_spamming else '⏸ Остановлена'}"
    )

async def groups_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
