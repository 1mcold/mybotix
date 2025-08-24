import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import LabeledPrice

API_TOKEN = os.environ.get("BOT_TOKEN")  # токен от BotFather
logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Команда /buy
@dp.message(commands=["buy"])
async def buy(message: types.Message):
    prices = [LabeledPrice(label="Тестовая оплата", amount=100)]  # 100 = 1⭐
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Тест Stars",
        description="Оплата через Telegram Stars",
        provider_token="STARS",   # нативно для Telegram
        currency="XTR",
        prices=prices,
        start_parameter="stars-test",
        payload="test-payload"
    )

# Перед оплатой
@dp.pre_checkout_query()
async def checkout(pre_checkout_query: types.PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

# После успешной оплаты
@dp.message(content_types=types.ContentType.SUCCESSFUL_PAYMENT)
async def got_payment(message: types.Message):
    payment = message.successful_payment
    await message.answer(f"✅ Оплата принята!\nСумма: {payment.total_amount / 100} ⭐")

if __name__ == "__main__":
    import asyncio
    asyncio.run(dp.start_polling(bot))
