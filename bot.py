import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, InlineQueryHandler, filters, ContextTypes
from dotenv import load_dotenv
from aiohttp import web

# بارگذاری توکن از .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# تنظیم لاگ‌گیری برای Koyeb
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# زبان‌ها (فقط موارد ضروری)
LANGUAGES = {
    "fa": {
        "welcome": "به ربات خوش اومدید! 😊\nلطفاً ابتدا در کانال‌ها عضو بشید:",
        "join_channels": "لطفاً در هر دو کانال عضو بشید و دوباره امتحان کنید.",
    },
    "en": {
        "welcome": "Welcome! 😊\nPlease join our channels first:",
        "join_channels": "Please join both channels and try again.",
    }
}

# هندلر ساده برای تست
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang = update.effective_user.language_code if update.effective_user.language_code in LANGUAGES else "fa"
    await update.message.reply_text(LANGUAGES[user_lang]["welcome"])
    logger.info(f"کاربر {update.effective_user.id} ربات را شروع کرد")

# تنظیم سرور aiohttp برای health check
async def health_check(request):
    return web.Response(text="OK")

async def run_bot():
    if not BOT_TOKEN:
        logger.error("توکن ربات مشخص نشده است.")
        raise ValueError("لطفاً BOT_TOKEN را تنظیم کنید.")

    # ساخت اپلیکیشن تلگرام
    application = Application.builder().token(BOT_TOKEN).read_timeout(20).write_timeout(20).connect_timeout(20).build()

    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))

    # تنظیم سرور aiohttp
    app = web.Application()
    app.router.add_get('/', health_check)

    # اجرای aiohttp
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("سرور aiohttp برای health check روی پورت 8080 شروع شد")

    # شروع Polling
    await application.initialize()
    logger.info("Application initialized")
    await application.start()
    logger.info("Application started")
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    logger.info("Polling started")

    # نگه داشتن برنامه در حال اجرا
    while True:
        await asyncio.sleep(3600)  # خوابیدن به مدت 1 ساعت برای جلوگیری از خروج

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
