import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["TOKEN"]
PAYMENT_PROVIDER_TOKEN = os.environ.get("PAYMENT_PROVIDER_TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_ID", "0"))
CHANNEL_URL = os.environ.get("URL", "https://t.me/")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ===== ПАМЯТЬ =====
user_data = {}
user_data_completed = set()

questions = [
    {"key": "name", "question": "📝 Имя:"},
    {"key": "age", "question": "🎂 Возраст:"},
    {"key": "skill", "question": "🎨 Скилл в рисовании (не обязательно):", "button": "Не хочу указывать"},
]

# ===== УТИЛИТЫ =====
def validate_input(key, text):
    if key == "name" and len(text) > 30: return False
    if key == "skill" and len(text) > 70: return False
    if key == "age" and not text.isdigit(): return False
    return True

# ===== АНКЕТА =====
async def ask_question(chat_id):
    step = user_data[chat_id]["step"]
    q = questions[step]
    text = f"Вопрос {step+1}/{len(questions)}\n{q['question']}"
    if q.get("button"):
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(q["button"])]], resize_keyboard=True, one_time_keyboard=True
        )
        await bot.send_message(chat_id, text, reply_markup=keyboard)
    else:
        await bot.send_message(chat_id, text, reply_markup=None)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    if chat_id in user_data_completed:
        await message.answer("⚠ Вы уже заполнили анкету.")
        return
    user_data[chat_id] = {"step": 0, "answers": {}}
    await message.answer("👋 Добро пожаловать! Для начала заполните анкету.")
    await ask_question(chat_id)

@dp.message(F.text)
async def handle_answers(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in user_data: return

    step = user_data[chat_id]["step"]
    q = questions[step]
    text = message.text

    if q.get("button") and text == q["button"]:
        user_data[chat_id]["answers"][q["key"]] = "не указано"
    elif validate_input(q["key"], text):
        user_data[chat_id]["answers"][q["key"]] = text
    else:
        await message.answer("⚠ Некорректный ввод. Попробуйте снова:")
        return

    if step+1 < len(questions):
        user_data[chat_id]["step"] += 1
        await ask_question(chat_id)
    else:
        ans = user_data[chat_id]["answers"]
        summary = f"✅ Спасибо за заполнение анкеты!\n\nИмя: {ans['name']}\nВозраст: {ans['age']}\nСкилл: {ans['skill']}"
        await message.answer(summary)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("Перейти в канал", url=CHANNEL_URL)]
        ])
        await message.answer("🎉 Добро пожаловать!", reply_markup=keyboard)

        # Админ уведомление
        if ADMIN_CHAT_ID:
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"📩 Новая анкета!\n👤 {message.from_user.full_name}\n🆔 {chat_id}\nИмя: {ans['name']}\nВозраст: {ans['age']}\nСкилл: {ans['skill']}"
            )

        user_data_completed.add(chat_id)
        del user_data[chat_id]

# ===== ДОНАТЫ =====
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
            [InlineKeyboardButton("10 ⭐", callback_data="charity_10"),
             InlineKeyboardButton("50 ⭐", callback_data="charity_50")],
            [InlineKeyboardButton("100 ⭐", callback_data="charity_100")],
        ])
        await query.message.edit_text("✨ Выберите сумму:", reply_markup=keyboard)
    elif data.startswith("charity_"):
        amount = int(data.split("_")[1])
        await bot.send_message(query.from_user.id, f"✅ Вы выбрали {amount} ⭐ (оплата через Telegram не реализована в этом примере)")
    await query.answer()

# ===== RUN =====
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
