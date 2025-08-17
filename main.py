import os
import logging
import time
from telegram import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from background import keep_alive  # если используешь Replit keep-alive

# ========= НАСТРОЙКИ =========
API_TOKEN = os.environ["Token"]          # токен бота (переменная окружения)
CHANNEL_URL = os.environ.get("URL", "")  # ссылка на канал
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_ID", "0"))  # ID админа для логов
ADMIN_CHAT_ID_2 = int(os.environ.get("ADMIN_ID_2", "0"))  # ID админа для логов

logging.basicConfig(level=logging.INFO)
print("🤖 Бот запущен и готов к работе!")

# ========= ПАМЯТЬ/ХРАНИЛИЩЕ =========
user_data: dict[int, dict] = {}           # временное состояние анкеты {chat_id: {"step": int, "answers": dict}}
user_data_completed: set[int] = set()     # кто уже заполнил анкету
user_blocked: dict[int, dict] = {}        # {chat_id: {"attempts": int, "last_time": int}}

BLOCK_DURATION = 24 * 60 * 60  # 24 часа в секундах
MAX_ATTEMPTS = 6               # после 6-й попытки — блок на 24ч

# ========= ВОПРОСЫ =========
questions = [
    {"key": "name",  "question": "📝 Имя:"},
    {"key": "age",   "question": "🎂 Возраст:"},
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
            [[current_question["button"]]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await context.bot.send_message(chat_id, progress_text + current_question["question"], reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id, progress_text + current_question["question"])


# ========= ХЭНДЛЕРЫ =========
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
                msg += f"\n(Предупреждение {attempts}/{MAX_ATTEMPTS}. После {MAX_ATTEMPTS} попыток будет игнор на 24 часа.)"
            await context.bot.send_message(chat_id, msg)
        return

    user_data[chat_id] = {"step": 0, "answers": {}}
    await context.bot.send_message(chat_id, "👋 Добро пожаловать!\nДля начала заполните анкету.")
    await ask_question(chat_id, context)

# ========= СЕКРЕТНАЯ КОМАНДА =========
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Разрешаем только админу
    if chat_id != ADMIN_CHAT_ID_2:
        return  # просто игнорируем остальных

    await context.bot.send_message(chat_id, "🏓 Pong! Бот онлайн и работает.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    text = update.message.text or ""

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
            f"Скилл в рисовании: {answers['skill']}"
        )
        await context.bot.send_message(chat_id, summary)

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Перейти в канал", url=CHANNEL_URL or "https://t.me/")]]
        )
        await context.bot.send_message(chat_id, "🎉 Добро пожаловать!", reply_markup=keyboard)

        # ===== ОТПРАВКА АДМИНУ =====
        if ADMIN_CHAT_ID != 0:
            user = update.effective_user
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
        
keep_alive()

# ========= ЗАПУСК =========
if __name__ == "__main__":
    keep_alive()  # запускаем Flask для "пинга" (на Replit/Render)
    app = ApplicationBuilder().token(API_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling()
