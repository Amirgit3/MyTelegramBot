import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import TelegramError
from aiohttp import web

# تنظیم لاگ‌گیری برای Koyeb
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# توکن ربات (باید توی Koyeb به عنوان متغیر محیطی تنظیم شده باشه)
import os
BOT_TOKEN = os.getenv("BOT_TOKEN")

# زبان‌ها
LANGUAGES = {
    "en": {
        "welcome": "Welcome! 😊\nJoin our channels first:",
        "join_channels": "Please join both channels and try again.",
        "membership_ok": "Membership verified!",
        "error": "Error: {}",
    },
    "fa": {
        "welcome": "به ربات خوش اومدید! 😊\nلطفاً ابتدا در کانال‌ها عضو بشید:",
        "join_channels": "لطفاً در هر دو کانال عضو بشید و دوباره امتحان کنید.",
        "membership_ok": "عضویت تأیید شد!",
        "error": "خطا: {}",
    }
}

# لینک کانال‌ها
CHANNEL_1 = "https://t.me/enrgy_m"
CHANNEL_2 = "https://t.me/music_bik"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_lang = update.effective_user.language_code if update.effective_user.language_code in LANGUAGES else "fa"
    context.user_data["language"] = user_lang
    lang = context.user_data["language"]

    keyboard = [
        [InlineKeyboardButton("عضویت در کانال ۱", url=CHANNEL_1)],
        [InlineKeyboardButton("عضویت در کانال ۲", url=CHANNEL_2)],
        [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(LANGUAGES[lang]["welcome"], reply_markup=reply_markup)
    logger.info(f"کاربر {user_id} ربات را با زبان {lang} شروع کرد")

async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = context.user_data.get("language", "fa")

    logger.info(f"شروع بررسی عضویت برای کاربر {user_id}")
    try:
        # چک کردن وضعیت ربات توی کانال‌ها
        bot_id = (await context.bot.get_me()).id
        try:
            bot_member1 = await context.bot.get_chat_member("@enrgy_m", bot_id)
            bot_member2 = await context.bot.get_chat_member("@music_bik", bot_id)
            if bot_member1.status not in ["administrator", "creator"] or bot_member2.status not in ["administrator", "creator"]:
                await query.message.reply_text("ربات باید در هر دو کانال ادمین باشد. لطفاً ادمین کنید.")
                return
        except TelegramError as e:
            logger.error(f"ربات نمی‌تواند وضعیت خودش را در کانال‌ها چک کند: {str(e)}")
            await query.message.reply_text("خطا: ربات به کانال‌ها دسترسی ندارد. لطفاً ربات را ادمین کنید.")
            return

        # چک کردن عضویت کاربر
        try:
            chat_member1 = await context.bot.get_chat_member("@enrgy_m", user_id)
            chat_member2 = await context.bot.get_chat_member("@music_bik", user_id)
            if chat_member1.status in ["member", "administrator", "creator"] and \
               chat_member2.status in ["member", "administrator", "creator"]:
                context.user_data["is_member"] = True
                await query.message.reply_text(LANGUAGES[lang]["membership_ok"])
            else:
                await query.message.reply_text(LANGUAGES[lang]["join_channels"])
        except TelegramError as e:
            logger.error(f"خطا در بررسی عضویت کاربر {user_id}: {str(e)}")
            await query.message.reply_text(LANGUAGES[lang]["error"].format("نمی‌توان عضویت را چک کرد. لطفاً دوباره امتحان کنید."))

    except Exception as e:
        logger.error(f"خطای کلی در check_membership برای کاربر {user_id}: {str(e)}")
        await query.message.reply_text(LANGUAGES[lang]["error"].format("خطای ناشناخته رخ داد."))

# تنظیم سرور aiohttp برای health check
async def health_check(request):
    return web.Response(text="OK")

async def run_bot():
    if not BOT_TOKEN:
        logger.error("توکن ربات مشخص نشده است.")
        raise ValueError("لطفاً BOT_TOKEN را تنظیم کنید.")

    application = Application.builder().token(BOT_TOKEN).read_timeout(20).write_timeout(20).connect_timeout(20).build()

    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(check_membership))

    # تنظیم سرور aiohttp
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("سرور aiohttp برای health check روی پورت 8080 شروع شد")

    # شروع ربات
    await application.initialize()
    logger.info("Application initialized")
    await application.start()
    logger.info("Application started")
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    logger.info("Polling started")

    # نگه داشتن برنامه در حال اجرا
    while True:
        await asyncio.sleep(3600)

async def shutdown(application, runner):
    logger.info("در حال متوقف کردن ربات...")
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    await runner.cleanup()
    logger.info("ربات متوقف شد")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_bot())
    except KeyboardInterrupt:
        loop.run_until_complete(shutdown(application, runner))
        loop.close()
    except Exception as e:
        logger.error(f"خطای غیرمنتظره: {str(e)}")
        loop.run_until_complete(shutdown(application, runner))
        loop.close()
