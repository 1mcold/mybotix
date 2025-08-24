import os
import logging
import time
from telegram import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
    LabeledPrice
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters
)
from background import keep_alive  # можно удалить, если не используешь

# ========= НАСТРОЙКИ =========
API_TOKEN = os.environ["Token"]          # токен бота
CHANNEL_URL = os.environ.get("URL", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_ID", "0"))
ADMIN_CHAT_ID_2 = int(os.environ.get("ADMIN_ID_2", "0"))

PAYMENT_PROVIDER_TOKEN = ""  # вставь токен платежей

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
print("🤖 Бот стартует...")

# ========= ПАМЯТЬ =========
user_data: dict[int, dict] = {}
user_data_completed: set[int] = set()
user_blocked: dict[int, dict] = {}

BLOCK_DURATION = 24 * 60 * 60
MAX_ATTEMPTS = 6

questions = [
    {"key": "name", "question": "📝 Имя:"},
    {"key": "age", "question": "🎂 Возраст:"},
    {"key": "skill", "question": "🎨 Скилл в рисовании (не обязательно):", "button": "Не хочу указывать"},
]

# ========= УТИЛИТЫ =========
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
    if b.get("last_time", 0) == 0:
        return False
    return (now - b["last_time"]) < BLOCK_DURATION

def reset_block_if_expired(chat_id: int, now: int) -> None:
    b = user_blocked.get(chat_id)
    if not b:
        return
    if b.get("last_time", 0) and (now - b["last_time"]) >= BLOCK_DURATION:
        user_blocked[chat_id] = {"attempts": 0, "last_time": 0}

def note_attempt_and_maybe_block(chat_id: int, now: int) -> tuple[int, bool]:
    b = user_blocked.get(chat_id)
    if not b:
        b = {"attempts": 0, "last_time": 0}
        user_blocked[chat_id] = b
    b["attempts"] += 1
    blocked_now = False
    if b["attempts"] >= MAX_ATTEMPTS:
        b["last_time"] = now
        blocked_now = True
        logging.info(f"Пользователь {chat_id} заблокирован на 1 день за спам.")
    return b["attempts"], blocked_now

async def ask_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    step = user_data[chat_id]["step"]
    current_question = questions[step]
    progress_text = f"Вопрос {step + 1}/{len(questions)}\n"
    if current_question.get("button") and current_question["key"] == "skill":
        keyboard = ReplyKeyboardMarkup(
            [[current_question["button"]]], resize_keyboard=True, one_time_keyboard=True
        )
        await context.bot.send_message(chat_id, progress_text + current_question["question"], reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id, progress_text + current_question["question"])

# ========= АНКЕТА =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    now = int(time.time())

    if is_block_active(chat_id, now):
        return
    reset_block_if_expired(chat_id, now)

    if chat_id in user_data_completed:
        attempts, blocked_now = note_attempt_and_maybe_block(chat_id, now)
        if not blocked_now:
            left = max(0, MAX_ATTEMPTS - attempts)
            msg = "⚠ Вы уже заполнили анкету. Новая анкета невозможна."
            if left > 0:
                msg += f"\n(Предупреждение {attempts}/{MAX_ATTEMPTS}. После {MAX_ATTEMPTS} попыток игнор на 24 часа.)"
            await context.bot.send_message(chat_id, msg)
        return

    user_data[chat_id] = {"step": 0, "answers": {}}
    await context.bot.send_message(chat_id, "👋 Добро пожаловать!\nДля начала заполните анкету.")
    await ask_question(chat_id, context)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_CHAT_ID_2:
        return
    await context.bot.send_message(chat_id, "🏓 Pong! Бот онлайн и работает.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    text = update.message.text or ""

    # кастомная сумма доната
    if context.user_data.get("waiting_for_custom"):
        try:
            amount = int(text)
            context.user_data["waiting_for_custom"] = False
            await send_invoice(update, context, "Благотворительный донат (кастом)", amount)
        except ValueError:
            await update.message.reply_text("⚠️ Введите число!")
        return

    if chat_id not in user_data:
        return

    step = user_data[chat_id]["step"]
    current_question = questions[step]

    if current_question.get("button") and text == current_question["button"]:
        user_data[chat_id]["answers"][current_question["key"]] = "не указано"
        await context.bot.send_message(chat_id, "Вы пропустили этот вопрос", reply_markup=ReplyKeyboardRemove())
    else:
        if not validate_input(current_question["key"], text):
            await context.bot.send_message(chat_id, "⚠ Некорректный ввод. Попробуйте снова:")
            return
        user_data[chat_id]["answers"][current_question["key"]] = text

    if step + 1 < len(questions):
        user_data[chat_id]["step"] += 1
        await ask_question(chat_id, context)
    else:
        answers = user_data[chat_id]["answers"]
        summary = (
            "✅ Спасибо за заполнение анкеты!\n\n"
            f"Имя: {answers['name']}\n"
            f"Возраст: {answers['age']}\n"
            f"Скилл: {answers['skill']}"
        )
        await context.bot.send_message(chat_id, summary)

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Перейти в канал", url=CHANNEL_URL or "https://t.me/")]])
        await context.bot.send_message(chat_id, "🎉 Добро пожаловать!", reply_markup=keyboard)

        # лог админу
        if ADMIN_CHAT_ID != 0:
            profile_link = f"<a href='tg://user?id={chat_id}'>Профиль</a>"
            log_text = (
                f"📩 Новая анкета!\n\n"
                f"👤 {profile_link}\n"
                f"🆔 ChatID: <code>{chat_id}</code>\n\n"
                f"Имя: {answers['name']}\n"
                f"Возраст: {answers['age']}\n"
                f"Скилл: {answers['skill']}"
            )
            try:
                await context.bot.send_message(ADMIN_CHAT_ID, log_text, parse_mode="HTML")
            except Exception as e:
                logging.error(f"Не удалось отправить админу: {e}")

        user_data_completed.add(chat_id)
        del user_data[chat_id]

# ========= ДОНАТЫ =========
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    keyboard = [
        [InlineKeyboardButton("✨ Благотворительный", callback_data="donate_charity"),
         InlineKeyboardButton("💎 Привилегии", callback_data="donate_privileges")]
    ]
    await context.bot.send_message(chat_id, "🌟 <b>Выберите тип доната</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.from_user.id

    # Благотворительный
    if query.data == "donate_charity":
        keyboard = [
            [InlineKeyboardButton("10 ⭐", callback_data="charity_amount_10"),
             InlineKeyboardButton("50 ⭐", callback_data="charity_amount_50")],
            [InlineKeyboardButton("100 ⭐", callback_data="charity_amount_100"),
             InlineKeyboardButton("500 ⭐", callback_data="charity_amount_500")],
            [InlineKeyboardButton("1000 ⭐", callback_data="charity_amount_1000")],
            [InlineKeyboardButton("💰 Другая сумма", callback_data="charity_custom")]
        ]
        await context.bot.send_message(chat_id, "✨ <b>Выберите сумму доната</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("charity_amount_"):
        amount = int(query.data.split("_")[-1])
        await send_invoice(query, context, "Благотворительный донат", amount)

    elif query.data == "charity_custom":
        await context.bot.send_message(chat_id, "💰 Введите вашу сумму в звёздах:", parse_mode="HTML")
        context.user_data["waiting_for_custom"] = True

    elif query.data == "donate_privileges":
        keyboard = [
            [InlineKeyboardButton("🛡 Страховка от мута — 10 ⭐", callback_data="privilege_mute_protect")],
            [InlineKeyboardButton("🔓 Размут — 15 ⭐", callback_data="privilege_unmute")]
        ]
        await context.bot.send_message(chat_id, "💎 <b>Привилегии</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "privilege_mute_protect":
        await send_invoice(query, context, "Страховка от мута", 10)

    elif query.data == "privilege_unmute":
        await send_invoice(query, context, "Размут", 15)

# ========= ИНВОЙС =========
async def send_invoice(target, context, title, amount):
    chat_id = target.from_user.id if hasattr(target, "from_user") else target.message.chat_id
    description = f"Оплата: {title}"
    prices = [LabeledPrice(label=title, amount=amount * 1)]
    await context.bot.send_invoice(
        chat_id,
        title=title,
        description=description,
        payload=f"donation_{title}_{amount}",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="XTR",
        prices=prices,
        start_parameter="donate"
    )

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    await update.message.reply_text(f"✅ Спасибо за оплату {payment.total_amount // 100} ⭐ ({payment.invoice_payload})!")

# ========= ЗАПУСК =========
if __name__ == "__main__":
    app = ApplicationBuilder().token(API_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("donate", donate))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    app.run_polling()
