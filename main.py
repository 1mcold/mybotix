import os
import logging
import time
from telegram import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)
from background import keep_alive  # если используешь Replit keep-alive

# ========= НАСТРОЙКИ =========
API_TOKEN = os.environ["Token"]          # токен бота
PAYMENT_PROVIDER_TOKEN = ""  # токен для Telegram Stars
CHANNEL_URL = os.environ.get("URL", "")  # ссылка на канал
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_ID", "0"))
ADMIN_CHAT_ID_2 = int(os.environ.get("ADMIN_ID_2", "0"))

logging.basicConfig(level=logging.INFO)
print("🤖 Бот запущен!")

# ========= ПАМЯТЬ =========
user_data: dict[int, dict] = {}
user_data_completed: set[int] = set()
user_blocked: dict[int, dict] = {}
transactions: dict[str, dict] = {}  # {id транзакции: {chat_id, amount, title}}

BLOCK_DURATION = 24 * 60 * 60
MAX_ATTEMPTS = 6

questions = [
    {"key": "name",  "question": "📝 Имя:"},
    {"key": "age",   "question": "🎂 Возраст:"},
    {"key": "skill", "question": "🎨 Скилл в рисовании (не обязательно):", "button": "Не хочу указывать"},
]

# ========= АНКЕТА =========
def validate_input(key: str, text: str) -> bool:
    if key == "name" and len(text) > 30:
        return False
    if key == "skill" and len(text) > 70:
        return False
    if key == "age" and not text.isdigit():
        return False
    return True

def is_block_active(chat_id: int, now: int) -> bool:
    b = user_blocked.get(chat_id)
    if not b:
        return False
    return (now - b.get("last_time", 0)) < BLOCK_DURATION

def reset_block_if_expired(chat_id: int, now: int):
    b = user_blocked.get(chat_id)
    if b and (now - b.get("last_time", 0)) >= BLOCK_DURATION:
        user_blocked[chat_id] = {"attempts": 0, "last_time": 0}

def note_attempt_and_maybe_block(chat_id: int, now: int) -> tuple[int, bool]:
    b = user_blocked.setdefault(chat_id, {"attempts": 0, "last_time": 0})
    b["attempts"] += 1
    blocked = False
    if b["attempts"] >= MAX_ATTEMPTS:
        b["last_time"] = now
        blocked = True
    return b["attempts"], blocked

async def ask_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    step = user_data[chat_id]["step"]
    q = questions[step]
    progress = f"Вопрос {step + 1}/{len(questions)}\n"

    if q.get("button") and q["key"] == "skill":
        kb = ReplyKeyboardMarkup([[q["button"]]], resize_keyboard=True, one_time_keyboard=True)
        await context.bot.send_message(chat_id, progress + q["question"], reply_markup=kb)
    else:
        await context.bot.send_message(chat_id, progress + q["question"])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    now = int(time.time())

    if is_block_active(chat_id, now):
        return
    reset_block_if_expired(chat_id, now)

    if chat_id in user_data_completed:
        attempts, blocked = note_attempt_and_maybe_block(chat_id, now)
        if not blocked:
            left = MAX_ATTEMPTS - attempts
            msg = "⚠ Вы уже заполнили анкету."
            if left > 0:
                msg += f"\n(Предупреждение {attempts}/{MAX_ATTEMPTS})"
            await context.bot.send_message(chat_id, msg)
        return

    user_data[chat_id] = {"step": 0, "answers": {}}
    await context.bot.send_message(chat_id, "👋 Добро пожаловать!\nДля начала заполните анкету.")
    await ask_question(chat_id, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    if chat_id not in user_data:
        return

    step = user_data[chat_id]["step"]
    q = questions[step]

    if q.get("button") and text == q["button"]:
        user_data[chat_id]["answers"][q["key"]] = "не указано"
        await context.bot.send_message(chat_id, "Вы пропустили этот вопрос", reply_markup=ReplyKeyboardRemove())
    else:
        if not validate_input(q["key"], text):
            await context.bot.send_message(chat_id, "⚠ Некорректный ввод.")
            return
        user_data[chat_id]["answers"][q["key"]] = text

    if step + 1 < len(questions):
        user_data[chat_id]["step"] += 1
        await ask_question(chat_id, context)
    else:
        answers = user_data[chat_id]["answers"]
        summary = (
            "✅ Спасибо за заполнение анкеты!\n\n"
            f"Имя: {answers['name']}\nВозраст: {answers['age']}\nСкилл: {answers['skill']}"
        )
        await context.bot.send_message(chat_id, summary)

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Перейти в канал", url=CHANNEL_URL or "https://t.me/")]])
        await context.bot.send_message(chat_id, "🎉 Добро пожаловать!", reply_markup=kb)

        if ADMIN_CHAT_ID:
            user = update.effective_user
            profile = f"<a href='tg://user?id={chat_id}'>Профиль</a>"
            log = f"📩 Новая анкета!\n👤 {profile}\n🆔 {chat_id}\nИмя: {answers['name']}\nВозраст: {answers['age']}\nСкилл: {answers['skill']}"
            await context.bot.send_message(ADMIN_CHAT_ID, log, parse_mode="HTML")

        user_data_completed.add(chat_id)
        del user_data[chat_id]

# ========= ДОНАТ =========
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[
        InlineKeyboardButton("✨ Благотворительный", callback_data="donate_charity"),
        InlineKeyboardButton("💎 Привилегии", callback_data="donate_privileges")
    ]]
    await update.message.reply_text("🌟 <b>Выберите тип доната</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "donate_charity":
        kb = [
            [InlineKeyboardButton("10 ⭐", callback_data="charity_amount_10"),
             InlineKeyboardButton("50 ⭐", callback_data="charity_amount_50")],
            [InlineKeyboardButton("100 ⭐", callback_data="charity_amount_100"),
             InlineKeyboardButton("500 ⭐", callback_data="charity_amount_500")],
            [InlineKeyboardButton("1000 ⭐", callback_data="charity_amount_1000")],
            [InlineKeyboardButton("💰 Другая сумма", callback_data="charity_custom")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        await q.edit_message_text("✨ <b>Выберите сумму доната</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("charity_amount_"):
        amount = int(q.data.split("_")[-1])
        await send_invoice(q, context, "Благотворительный донат", amount)

    elif q.data == "charity_custom":
        await q.edit_message_text("💰 Введите вашу сумму:", parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="donate_charity")]]))
        context.user_data["waiting_for_custom"] = True

    elif q.data == "donate_privileges":
        kb = [
            [InlineKeyboardButton("🛡 Страховка от мута — 10 ⭐", callback_data="privilege_mute_protect")],
            [InlineKeyboardButton("🔓 Размут — 15 ⭐", callback_data="privilege_unmute")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        await q.edit_message_text("💎 <b>Привилегии</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "privilege_mute_protect":
        await send_invoice(q, context, "Страховка от мута", 10)

    elif q.data == "privilege_unmute":
        await send_invoice(q, context, "Размут", 15)

    elif q.data == "main_menu":
        await donate(update, context)

async def handle_custom_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_custom"):
        try:
            amount = int(update.message.text)
            context.user_data["waiting_for_custom"] = False
            await send_invoice(update, context, "Благотворительный донат (кастом)", amount)
        except ValueError:
            await update.message.reply_text("⚠️ Введите число!")

async def send_invoice(target, context, title, amount):
    chat_id = target.from_user.id if hasattr(target, "from_user") else target.message.chat_id
    payload = f"{int(time.time())}_{chat_id}"
    transactions[payload] = {"chat_id": chat_id, "amount": amount, "title": title}

    prices = [LabeledPrice(label=title, amount=amount)]
    await context.bot.send_invoice(
        chat_id,
        title=title,
        description=f"Оплата: {title}",
        payload=payload,
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="XTR",
        prices=prices,
        start_parameter="donate"
    )

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = update.message.successful_payment
    tx_id = p.invoice_payload
    data = transactions.get(tx_id, {})
    amount = p.total_amount

    # Пользователю
    await update.message.reply_text(f"✅ Спасибо за поддержку!\nВы оплатили {amount} ⭐\n🆔 ID транзакции: `{tx_id}`", parse_mode="Markdown")

    # Админу
    user = update.effective_user
    profile = f"<a href='tg://user?id={user.id}'>{user.full_name}</a>"
    log = f"💰 Новый донат!\n👤 {profile}\n🆔 {user.id}\nСумма: {amount} ⭐\nID транзакции: <code>{tx_id}</code>"
    if ADMIN_CHAT_ID:
        await context.bot.send_message(ADMIN_CHAT_ID, log, parse_mode="HTML")

# ========= REFUND =========
async def refund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in [ADMIN_CHAT_ID, ADMIN_CHAT_ID_2]:
        return  # игнор неадминов

    if not context.args:
        await update.message.reply_text("⚠ Укажите ID транзакции")
        return

    tx_id = context.args[0]
    if tx_id not in transactions:
        await update.message.reply_text("❌ Транзакция не найдена")
        return

    tx = transactions[tx_id]
    user_id = tx["chat_id"]

    await update.message.reply_text(f"🔄 Рефанд выполнен для ID: {tx_id}")
    try:
        await context.bot.send_message(user_id, "❌ Ваша оплата была возвращена.")
    except Exception:
        pass
    del transactions[tx_id]

# ========= ЗАПУСК =========
def main():
    keep_alive()
    app = Application.builder().token(API_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", lambda u, c: None))
    app.add_handler(CommandHandler("donate", donate))
    app.add_handler(CommandHandler("refund", refund))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_amount))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    app.run_polling()

if __name__ == "__main__":
    main()

