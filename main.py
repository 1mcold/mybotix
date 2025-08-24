import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils import executor

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["Token"]
PAYMENT_PROVIDER_TOKEN = ""  # вставьте свой токен провайдера
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_ID", "0"))
CHANNEL_URL = os.environ.get("URL", "")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ========= ПАМЯТЬ/ХРАНИЛИЩЕ =========
user_data: dict[int, dict] = {}
user_data_completed: set[int] = set()

BLOCK_DURATION = 24 * 60 * 60
MAX_ATTEMPTS = 6
user_blocked: dict[int, dict] = {}

questions = [
    {"key": "name", "question": "📝 Имя:"},
    {"key": "age", "question": "🎂 Возраст:"},
    {"key": "skill", "question": "🎨 Скилл в рисовании (не обязательно):", "button": "Не хочу указывать"},
]

# ========= УТИЛИТЫ =========
def validate_input(key: str, text: str) -> bool:
    if key == "name" and len(text) > 30: return False
    if key == "skill" and len(text) > 70: return False
    if key == "age" and not text.isdigit(): return False
    return True

def is_block_active(chat_id: int, now: int) -> bool:
    b = user_blocked.get(chat_id)
    return b and b.get("last_time", 0) and (now - b["last_time"]) < BLOCK_DURATION

def reset_block_if_expired(chat_id: int, now: int):
    b = user_blocked.get(chat_id)
    if b and b.get("last_time", 0) and (now - b["last_time"]) >= BLOCK_DURATION:
        user_blocked[chat_id] = {"attempts": 0, "last_time": 0}

def note_attempt_and_maybe_block(chat_id: int, now: int) -> tuple[int, bool]:
    b = user_blocked.setdefault(chat_id, {"attempts": 0, "last_time": 0})
    b["attempts"] += 1
    blocked_now = False
    if b["attempts"] >= MAX_ATTEMPTS:
        b["last_time"] = now
        blocked_now = True
        logging.info(f"Пользователь {chat_id} заблокирован на 1 день за спам.")
    return b["attempts"], blocked_now

async def ask_question(chat_id: int):
    step = user_data[chat_id]["step"]
    q = questions[step]
    progress_text = f"Вопрос {step+1}/{len(questions)}\n{q['question']}"
    if q.get("button"):
        keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(q["button"])]], resize_keyboard=True, one_time_keyboard=True)
        await bot.send_message(chat_id, progress_text, reply_markup=keyboard)
    else:
        await bot.send_message(chat_id, progress_text, reply_markup=ReplyKeyboardRemove())

# ========= АНКЕТА =========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
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
            await bot.send_message(chat_id, msg)
        return

    user_data[chat_id] = {"step": 0, "answers": {}}
    await bot.send_message(chat_id, "👋 Добро пожаловать!\nДля начала заполните анкету.")
    await ask_question(chat_id)

@dp.message(F.text)
async def handle_answers(message: types.Message):
    chat_id = message.chat.id
    text = message.text
    if chat_id not in user_data: return

    step = user_data[chat_id]["step"]
    q = questions[step]

    if q.get("button") and text == q["button"]:
        user_data[chat_id]["answers"][q["key"]] = "не указано"
        await bot.send_message(chat_id, "Вы пропустили этот вопрос", reply_markup=ReplyKeyboardRemove())
    elif validate_input(q["key"], text):
        user_data[chat_id]["answers"][q["key"]] = text
    else:
        await bot.send_message(chat_id, "⚠ Некорректный ввод. Попробуйте снова:")
        return

    if step+1 < len(questions):
        user_data[chat_id]["step"] += 1
        await ask_question(chat_id)
    else:
        ans = user_data[chat_id]["answers"]
        summary = f"✅ Спасибо за заполнение анкеты!\n\nИмя: {ans['name']}\nВозраст: {ans['age']}\nСкилл: {ans['skill']}"
        await bot.send_message(chat_id, summary)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton("Перейти в канал", url=CHANNEL_URL)]])
        await bot.send_message(chat_id, "🎉 Добро пожаловать!", reply_markup=keyboard)

        if ADMIN_CHAT_ID != 0:
            profile_link = f"<a href='tg://user?id={chat_id}'>Профиль</a>"
            log_text = f"📩 Новая анкета!\n👤 {profile_link}\n🆔 {chat_id}\nИмя: {ans['name']}\nВозраст: {ans['age']}\nСкилл: {ans['skill']}"
            await bot.send_message(ADMIN_CHAT_ID, log_text, parse_mode="HTML")

        user_data_completed.add(chat_id)
        del user_data[chat_id]

@dp.message(Command("ping"))
async def cmd_ping(message: types.Message):
    chat_id = message.chat.id
    if False:  # ADMIN_CHAT_ID_2 всегда пустой
        await bot.send_message(chat_id, "🏓 Pong! Бот онлайн и работает.")

# ========= ДОНАТЫ =========
@dp.message(Command("donate"))
async def donate(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✨ Благотворительный", callback_data="donate_charity"),
         InlineKeyboardButton("💎 Привилегии", callback_data="donate_privileges")]
    ])
    await message.answer("🌟 Выберите тип доната:", reply_markup=keyboard)

@dp.callback_query()
async def donate_cb(query: types.CallbackQuery):
    data = query.data
    if data == "donate_charity":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("10 ⭐", callback_data="charity_amount_10"),
             InlineKeyboardButton("50 ⭐", callback_data="charity_amount_50")],
            [InlineKeyboardButton("100 ⭐", callback_data="charity_amount_100"),
             InlineKeyboardButton("500 ⭐", callback_data="charity_amount_500")],
            [InlineKeyboardButton("1000 ⭐", callback_data="charity_amount_1000")],
            [InlineKeyboardButton("💰 Другая сумма", callback_data="charity_custom")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ])
        await query.message.edit_text("✨ Выберите сумму:", reply_markup=keyboard)

    elif data.startswith("charity_amount_"):
        amount = int(data.split("_")[-1])
        await query.message.answer(f"Вы выбрали {amount} ⭐ (оплата через Telegram не реализована)")
    elif data == "donate_privileges":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🛡 Страховка от мута — 10 ⭐", callback_data="privilege_mute_protect")],
            [InlineKeyboardButton("🔓 Размут — 15 ⭐", callback_data="privilege_unmute")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ])
        await query.message.edit_text("💎 Привилегии", reply_markup=keyboard)
    await query.answer()

# ========= RUN =========
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
