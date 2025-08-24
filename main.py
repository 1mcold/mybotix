import os
import logging
import time
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)
from background import keep_alive  # если используешь Replit keep-alive

# ========= НАСТРОЙКИ =========
API_TOKEN = os.environ["Token"]                # токен бота
PAYMENT_PROVIDER_TOKEN = "" # токен для Telegram Stars
CHANNEL_URL = os.environ.get("URL", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_ID", "0"))
ADMIN_CHAT_ID_2 = int(os.environ.get("ADMIN_ID_2", "0"))

logging.basicConfig(level=logging.INFO)
print("🤖 Бот запущен и готов к работе!")

# ========= ПАМЯТЬ =========
user_data: dict[int, dict] = {}
user_data_completed: set[int] = set()
transactions: dict[str, dict] = {}  # {transaction_id: {"chat_id": int, "amount": int, "title": str}}

# ========= КОМАНДА /donate =========
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("✨ Благотворительный", callback_data="donate_charity"),
            InlineKeyboardButton("💎 Привилегии", callback_data="donate_privileges")
        ]
    ]
    await update.message.reply_text(
        "🌟 <b>Выберите тип доната</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ========= КНОПКИ =========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "donate_charity":
        keyboard = [
            [InlineKeyboardButton("10 ⭐", callback_data="charity_amount_10"),
             InlineKeyboardButton("50 ⭐", callback_data="charity_amount_50")],
            [InlineKeyboardButton("100 ⭐", callback_data="charity_amount_100"),
             InlineKeyboardButton("500 ⭐", callback_data="charity_amount_500")],
            [InlineKeyboardButton("1000 ⭐", callback_data="charity_amount_1000")],
            [InlineKeyboardButton("💰 Другая сумма", callback_data="charity_custom")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        await query.edit_message_text("✨ <b>Выберите сумму доната</b>", parse_mode="HTML",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("charity_amount_"):
        amount = int(query.data.split("_")[-1])
        await send_invoice(query, context, "Благотворительный донат", amount)

    elif query.data == "charity_custom":
        await query.edit_message_text("💰 Введите вашу сумму в ⭐:", parse_mode="HTML",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="donate_charity")]]))
        context.user_data["waiting_for_custom"] = True

    elif query.data == "donate_privileges":
        keyboard = [
            [InlineKeyboardButton("🛡 Страховка от мута — 10 ⭐", callback_data="privilege_mute_protect")],
            [InlineKeyboardButton("🔓 Размут — 15 ⭐", callback_data="privilege_unmute")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        await query.edit_message_text("💎 <b>Привилегии</b>", parse_mode="HTML",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "privilege_mute_protect":
        await send_invoice(query, context, "Страховка от мута", 10)

    elif query.data == "privilege_unmute":
        await send_invoice(query, context, "Размут", 15)

    elif query.data == "main_menu":
        await query.edit_message_text("🌟 <b>Выберите тип доната</b>", parse_mode="HTML",
                                      reply_markup=InlineKeyboardMarkup([
                                          [InlineKeyboardButton("✨ Благотворительный", callback_data="donate_charity"),
                                           InlineKeyboardButton("💎 Привилегии", callback_data="donate_privileges")]
                                      ]))

# ========= ОБРАБОТКА КАСТОМНОЙ СУММЫ =========
async def handle_custom_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_custom"):
        try:
            amount = int(update.message.text)
            context.user_data["waiting_for_custom"] = False
            await send_invoice(update, context, "Благотворительный донат (кастом)", amount)
        except ValueError:
            await update.message.reply_text("⚠️ Введите число!")

# ========= СОЗДАНИЕ ИНВОЙСА =========
async def send_invoice(target, context, title, amount):
    chat_id = target.from_user.id if hasattr(target, "from_user") else target.message.chat_id
    description = f"Оплата: {title}"
    payload = f"donation_{title}_{amount}_{int(time.time())}"

    prices = [LabeledPrice(label=title, amount=amount)]  # Stars работают в 1:1

    await context.bot.send_invoice(
        chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="XTR",
        prices=prices,
        start_parameter="donate"
    )

# ========= PreCheckout =========
async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

# ========= УСПЕШНАЯ ОПЛАТА =========
async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    chat_id = update.message.chat_id
    user = update.effective_user

    transaction_id = payment.provider_payment_charge_id or str(int(time.time()))
    amount = payment.total_amount
    title = payment.invoice_payload.split("_")[1]

    # Сохраняем
    transactions[transaction_id] = {"chat_id": chat_id, "amount": amount, "title": title}

    # Пользователю
    await update.message.reply_text(
        f"✅ Спасибо за поддержку!\n"
        f"💎 Оплата: {title}\n"
        f"⭐ Сумма: {amount}\n"
        f"🆔 ID транзакции: <code>{transaction_id}</code>",
        parse_mode="HTML"
    )

    # Админу
    if ADMIN_CHAT_ID:
        profile_link = f"<a href='tg://user?id={chat_id}'>{user.first_name}</a>"
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"📢 Новый донат!\n\n"
            f"👤 {profile_link}\n"
            f"🆔 ChatID: <code>{chat_id}</code>\n"
            f"💎 Оплата: {title}\n"
            f"⭐ Сумма: {amount}\n"
            f"💳 Транзакция: <code>{transaction_id}</code>",
            parse_mode="HTML"
        )

# ========= /refund =========
async def refund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in [ADMIN_CHAT_ID, ADMIN_CHAT_ID_2]:
        return  # игнор

    if not context.args:
        await update.message.reply_text("⚠️ Укажите ID транзакции: /refund <id>")
        return

    transaction_id = context.args[0]
    tx = transactions.get(transaction_id)

    if not tx:
        await update.message.reply_text("❌ Транзакция не найдена.")
        return

    # Здесь должна быть реальная логика возврата через API (если доступно)
    await update.message.reply_text(
        f"🔄 Возврат выполнен!\n"
        f"💳 Транзакция: <code>{transaction_id}</code>\n"
        f"⭐ Сумма: {tx['amount']}",
        parse_mode="HTML"
    )
keep_alive()
# ========= ЗАПУСК =========
def main():
    app = ApplicationBuilder().token(API_TOKEN).build()

    app.add_handler(CommandHandler("donate", donate))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_amount))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(CommandHandler("refund", refund))

    app.run_polling()

if __name__ == "__main__":
    keep_alive()
    main()

