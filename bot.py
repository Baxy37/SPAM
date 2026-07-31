import os
import asyncio
import threading
import ntplib
import time
from datetime import datetime, timezone
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

# ===== СИНХРОНИЗАЦИЯ ВРЕМЕНИ (без прав администратора) =====
def sync_time():
    """Синхронизирует время через NTP (не требует прав root)"""
    try:
        client = ntplib.NTPClient()
        response = client.request('pool.ntp.org', version=3)
        # Просто выводим точное время — это помогает Telethon
        # Telethon использует системное время, но если мы его не меняем,
        # то хотя бы знаем расхождение
        ntp_time = datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
        local_time = datetime.now(timezone.utc)
        diff = (ntp_time - local_time).total_seconds()
        print(f"🕐 NTP время: {ntp_time.strftime('%H:%M:%S')}")
        print(f"🕐 Локальное время: {local_time.strftime('%H:%M:%S')}")
        print(f"📊 Расхождение: {diff:.2f} секунд")
        
        # Если расхождение больше 2 секунд — Telethon может не работать
        if abs(diff) > 2:
            print("⚠️ ВНИМАНИЕ: Большое расхождение времени!")
            print("💡 Рекомендуем переключиться на вход по QR-коду (/qr)")
        return diff
    except Exception as e:
        print(f"⚠️ Ошибка синхронизации: {e}")
        return None

# ===== ВЕБ-СЕРВЕР =====
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

# ===== ЛОГИН =====
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
        sync_time()
        try:
            new_result = await client.send_code_request(data['phone'])
            login_states[user_id]['hash'] = new_result.phone_code_hash
            return False, "⏰ Код истек. Отправлен новый код. Введите его:"
        except Exception as e:
            return False, f"Ошибка: {str(e)}"
    except errors.PhoneCodeInvalidError:
        return False, "❌ Неверный код. Попробуйте еще раз."
    except Exception as e:
        return False, str(e)

# ===== КОМАНДЫ БОТА =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"🤖 Бот для рассылки\n\n"
        "🔑 /login — войти по номеру и коду\n"
        "📱 /qr — войти по QR-коду (рекомендуется, если код не работает)\n"
        "➕ /add_group @chat — добавить группу\n"
        "📝 /set_msg Текст — установить сообщение\n"
        "🚀 /start_spam — запустить рассылку\n"
        "🛑 /stop_spam — остановить\n"
        "📊 /status — проверить статус\n"
        "📋 /groups — список групп"
    )

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ready = await is_user_ready(user_id)
    if ready:
        await update.message.reply_text("✅ Вы уже авторизованы!")
        return
    
    sync_time()
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
            if "Код истек" in error:
                await update.message.reply_text(f"⚠️ {error}")
            else:
                await update.message.reply_text(f"❌ {error}\nПопробуйте /login заново")
                del login_states[user_id]

# ===== QR-ВХОД (на случай, если код не работает) =====
async def qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    ready = await is_user_ready(user_id)
    if ready:
        await update.message.reply_text("✅ Вы уже авторизованы!")
        return
    
    await update.message.reply_text("⏳ Генерирую QR-код...")
    
    try:
        client = get_client(user_id)
        await client.connect()
        qr_login_obj = await client.qr_login()
        
        img = await qr_login_obj.qr_code()
        img_path = f'qr_{user_id}.png'
        img.save(img_path)
        
        with open(img_path, 'rb') as f:
            await update.message.reply_photo(
                photo=f,
                caption=(
                    "📸 **Отсканируйте QR-код**\n\n"
                    "1️⃣ Откройте Telegram на телефоне\n"
                    "2️⃣ Настройки → Устройства → Сканировать QR\n"
                    "3️⃣ Наведите на этот код\n"
                    "4️⃣ Нажмите 'Подтвердить'\n\n"
                    "⏳ Код действует 60 секунд."
                ),
                parse_mode='Markdown'
            )
        
        os.remove(img_path)
        
        try:
            await qr_login_obj.wait(60)
            await update.message.reply_text("✅ Аккаунт успешно авторизован! 🎉")
            if user_id not in user_groups:
                user_groups[user_id] = []
            if user_id not in user_messages:
                user_messages[user_id] = ""
            if user_id not in user_spamming:
                user_spamming[user_id] = False
        except asyncio.TimeoutError:
            await update.message.reply_text("⏰ Время истекло. Попробуйте /qr заново.")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}\nПопробуйте /login.")

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
        await update.message.reply_text("❌ Сначала авторизуйтесь: /login или /qr")
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
    sync_time()
    threading.Thread(target=run_webserver, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("qr", qr))
    app.add_handler(CommandHandler("add_group", add_group))
    app.add_handler(CommandHandler("add_groups", add_groups))
    app.add_handler(CommandHandler("set_msg", set_msg))
    app.add_handler(CommandHandler("start_spam", start_spam))
    app.add_handler(CommandHandler("stop_spam", stop_spam))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("groups", groups_list))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен!")
    print("💡 Если код не работает — используйте /qr для входа по QR-коду.")
    app.run_polling()

if __name__ == "__main__":
    main()
