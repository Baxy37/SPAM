import os
import asyncio
from telethon import TelegramClient
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ===== МОИ API (РАБОЧИЕ) =====
API_ID = 2040
API_HASH = 'b18441a1ff607e10a989891a5462e627'

# ===== ТВОИ ДАННЫЕ (ВСТАВЬ САМ ПРИ ЗАПУСКЕ) =====
BOT_TOKEN = '8868463698:AAE2C7pPOdyk7ouT64w_O3LMW-BScIqQSCg'  # Твой токен

# Временные данные для входа (ты вводишь их в боте, а не в коде!)
user_client = None
is_ready = False
login_data = {}  # Хранит телефон и этап входа

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
        "📊 /status — проверить статус"
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
        
        # Отправляем запрос кода
        client = TelegramClient('temp', API_ID, API_HASH)
        await client.connect()
        await client.send_code_request(text)
        await client.disconnect()
        
        await update.message.reply_text(
            "✅ Код отправлен в Telegram!\n"
            "Введите код цифрами:"
        )
    
    elif step == 'code':
        phone = login_data[user_id]['phone']
        result = await login_user(phone, text)
        
        if result is True:
            del login_data[user_id]
            await update.message.reply_text("✅ Аккаунт авторизован! Можно работать.")
        else:
            await update.message.reply_text(f"❌ Ошибка: {result}\nПопробуйте /login заново")
            del login_data[user_id]

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Статус: {'✅ Авторизован' if is_ready else '❌ Не авторизован'}")

async def add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажите группу: /add_group @chat")
        return
    # Здесь будет логика добавления (допишешь сам)
    await update.message.reply_text(f"✅ Добавлено: {context.args[0]}")

async def set_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажите текст: /set_msg Ваше сообщение")
        return
    await update.message.reply_text(f"✅ Сообщение сохранено: {' '.join(context.args)}")

async def start_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_ready:
        await update.message.reply_text("❌ Сначала войдите: /login")
        return
    await update.message.reply_text("🚀 Рассылка начата (заглушка)")

# ===== ЗАПУСК =====
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("add_group", add_group))
    app.add_handler(CommandHandler("set_msg", set_msg))
    app.add_handler(CommandHandler("start_spam", start_spam))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
