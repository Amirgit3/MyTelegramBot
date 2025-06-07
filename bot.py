import os
import logging
import asyncio
import aiosqlite
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from aiohttp import web # aiohttp را برای Health Check برمی‌گردانیم
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# Use the directly provided Koyeb URL
WEBHOOK_URL = "https://particular-capybara-amirgit3-bbc0dbbd.koyeb.app"
WEBHOOK_PATH = "/telegram"
PORT = int(os.environ.get("PORT", 8080))

# Channel IDs (example - replace with your actual channel IDs)
REQUIRED_CHANNEL_ID_1 = -1002198083864  # Replace with your first channel ID
REQUIRED_CHANNEL_ID_2 = -1002167086815  # Replace with your second channel ID (if any)

# --- Database Management ---
DATABASE_NAME = "user_limits.db"
DAILY_LIMIT = 50  # Max downloads per user per day

async def init_db():
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_downloads (
                user_id INTEGER PRIMARY KEY,
                download_count INTEGER DEFAULT 0,
                last_reset_date TEXT
            )
            """
        )
        await db.commit()
    logger.info("Database initialized successfully.") # Add log for clarity

async def get_user_download_count(user_id):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        cursor = await db.execute("SELECT download_count, last_reset_date FROM user_downloads WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()

        today_str = datetime.now().strftime("%Y-%m-%d")

        if result:
            count, last_reset_date = result
            if last_reset_date != today_str:
                # Reset count for a new day
                await db.execute("UPDATE user_downloads SET download_count = 0, last_reset_date = ? WHERE user_id = ?", (today_str, user_id))
                await db.commit()
                return 0
            return count
        else:
            await db.execute("INSERT INTO user_downloads (user_id, download_count, last_reset_date) VALUES (?, ?, ?)", (user_id, 0, today_str))
            await db.commit()
            return 0

async def increment_user_download_count(user_id):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        today_str = datetime.now().strftime("%Y-%m-%d")
        await db.execute(
            "INSERT OR REPLACE INTO user_downloads (user_id, download_count, last_reset_date) VALUES (?, COALESCE((SELECT download_count FROM user_downloads WHERE user_id = ? AND last_reset_date = ?), 0) + 1, ?)",
            (user_id, user_id, today_str, today_str)
        )
        await db.commit()

# --- Helper Functions ---
async def is_member(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if a user is a member of a specific channel."""
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Error checking membership for user {user_id} in chat {chat_id}: {e}")
        return False

async def check_all_memberships(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if a user is a member of all required channels."""
    is_member_1 = await is_member(user_id, REQUIRED_CHANNEL_ID_1, context)
    is_member_2 = True # Default to True if no second channel is required
    if REQUIRED_CHANNEL_ID_2: # Only check if a second channel is defined
        is_member_2 = await is_member(user_id, REQUIRED_CHANNEL_ID_2, context)
    return is_member_1 and is_member_2

async def get_membership_buttons():
    """Returns inline keyboard for membership check."""
    buttons = [
        [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")]
    ]
    return InlineKeyboardMarkup(buttons)

async def check_membership_and_proceed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name

    logger.info(f"کاربر {user_id} ({username}/{first_name}) درخواست بررسی عضویت را کلیک کرد.")

    is_all_member = await check_all_memberships(user_id, context)
    if is_all_member:
        message_text = "✅ عضویت شما در کانال‌ها تایید شد! حالا می‌توانید لینک یوتیوب، شورت، ریلز یا IGTV را ارسال کنید."
        # Remove the "check membership" button after successful check
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            reply_markup=None # Remove keyboard
        )
    else:
        channel_links_text = (
            f"- کانال اول: {os.getenv('CHANNEL_LINK_1', 'لینک کانال اول را در .env تنظیم کنید')}\n"
        )
        if REQUIRED_CHANNEL_ID_2:
            channel_links_text += (
                f"- کانال دوم: {os.getenv('CHANNEL_LINK_2', 'لینک کانال دوم را در .env تنظیم کنید')}"
            )

        message_text = (
            "⚠️ برای استفاده از ربات، ابتدا باید در کانال‌های زیر عضو شوید:\n\n"
            f"{channel_links_text}\n\n"
            "پس از عضویت، دکمه «✅ بررسی عضویت» را دوباره فشار دهید."
        )

    await update.callback_query.answer()
    await update.effective_message.reply_text(message_text, reply_markup=await get_membership_buttons() if not is_all_member else None)


# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message on /start with membership check."""
    user = update.effective_user
    logger.info(f"کاربر {user.id} ربات را با زبان {user.language_code} شروع کرد")

    is_all_member = await check_all_memberships(user.id, context)
    if is_all_member:
        await update.message.reply_html(
            rf"سلام {user.mention_html()}! خوش آمدید. 👋",
            reply_markup=None # No need for membership button
        )
        await update.message.reply_text(
            "لطفاً لینک یوتیوب، شورت، ریلز یا IGTV اینستاگرام را برای دانلود ارسال کنید."
        )
    else:
        channel_links_text = (
            f"- کانال اول: {os.getenv('CHANNEL_LINK_1', 'لینک کانال اول را در .env تنظیم کنید')}\n"
        )
        if REQUIRED_CHANNEL_ID_2:
            channel_links_text += (
                f"- کانال دوم: {os.getenv('CHANNEL_LINK_2', 'لینک کانال دوم را در .env تنظیم کنید')}"
            )

        await update.message.reply_html(
            rf"سلام {user.mention_html()}! ⚠️ برای استفاده از ربات، ابتدا باید در کانال‌های زیر عضو شوید:\n\n"
            f"{channel_links_text}\n\n"
            "پس از عضویت، دکمه «✅ بررسی عضویت» را فشار دهید.",
            reply_markup=await get_membership_buttons()
        )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages containing URLs for download."""
    user_id = update.effective_user.id
    user_message = update.message.text
    chat_id = update.effective_chat.id

    is_all_member = await check_all_memberships(user_id, context)
    if not is_all_member:
        channel_links_text = (
            f"- کانال اول: {os.getenv('CHANNEL_LINK_1', 'لینک کانال اول را در .env تنظیم کنید')}\n"
        )
        if REQUIRED_CHANNEL_ID_2:
            channel_links_text += (
                f"- کانال دوم: {os.getenv('CHANNEL_LINK_2', 'لینک کانال دوم را در .env تنظیم کنید')}"
            )
        await update.message.reply_text(
            "⚠️ برای استفاده از ربات، ابتدا باید در کانال‌های زیر عضو شوید:\n\n"
            f"{channel_links_text}\n\n"
            "پس از عضویت، دکمه «✅ بررسی عضویت» را فشار دهید.",
            reply_markup=await get_membership_buttons()
        )
        return

    # Check daily download limit
    current_downloads = await get_user_download_count(user_id)
    if current_downloads >= DAILY_LIMIT:
        await update.message.reply_text(
            f"متاسفانه، سهمیه روزانه شما ({DAILY_LIMIT} دانلود) به پایان رسیده است. لطفاً فردا مجدداً تلاش کنید."
        )
        return

    # Create a temporary directory for the user
    temp_dir_path = f"/tmp/user_{user_id}_{os.urandom(4).hex()}"
    os.makedirs(temp_dir_path, exist_ok=True)
    logger.info(f"پوشه موقت برای کاربر {user_id} ساخته شد: {temp_dir_path}")

    try:
        sent_message = await update.message.reply_text("در حال پردازش لینک شما... لطفا صبر کنید.")
        file_path = None

        ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(temp_dir_path, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'ignoreerrors': True,
            'max_downloads': 1,
            'usenetrc': False,
            'cookiefile': None, # Ensure no cookie file is used by default
        }

        # Add Instagram credentials if available
        if "instagram.com" in user_message and INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD:
            ydl_opts['username'] = INSTAGRAM_USERNAME
            ydl_opts['password'] = INSTAGRAM_PASSWORD
            logger.info("Instagram credentials added to yt-dlp options.")

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(user_message, download=True)
            file_path = ydl.prepare_filename(info)

        if file_path and os.path.exists(file_path):
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            logger.info(f"فایل دانلود شد: {file_path}, حجم: {file_size_mb:.2f} MB")

            if file_size_mb > 50: # Telegram bot API limit is 50MB for general files
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent_message.message_id,
                    text="فایل دانلود شد، اما حجم آن بالای 50 مگابایت است. ربات نمی‌تواند فایل‌های با این حجم را ارسال کند."
                )
            else:
                try:
                    # Determine if it's a video or photo
                    if info.get('ext') in ['mp4', 'mov', 'avi', 'mkv', 'webm']:
                        with open(file_path, 'rb') as video_file:
                            await context.bot.send_video(chat_id, video_file, caption="فایل ویدیویی شما:")
                    elif info.get('ext') in ['jpg', 'jpeg', 'png', 'webp']:
                        with open(file_path, 'rb') as photo_file:
                            await context.bot.send_photo(chat_id, photo_file, caption="فایل تصویری شما:")
                    else:
                        with open(file_path, 'rb') as doc_file:
                            await context.bot.send_document(chat_id, doc_file, caption="فایل شما:")

                    await context.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
                    await increment_user_download_count(user_id) # Increment count only on successful send
                except Exception as e:
                    logger.error(f"Error sending file to Telegram: {e}")
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=sent_message.message_id,
                        text=f"متاسفانه، در ارسال فایل به تلگرام مشکلی پیش آمد: {e}"
                    )
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text="متاسفانه، فایلی از این لینک یافت نشد یا دانلود با مشکل مواجه شد. لطفاً از لینک صحیح و عمومی استفاده کنید."
            )
    except Exception as e:
        logger.error(f"Error processing URL {user_message}: {e}", exc_info=True)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_message.message_id,
            text=f"متاسفانه، در پردازش لینک شما مشکلی پیش آمد: {e}\nلطفاً از لینک صحیح و عمومی استفاده کنید و دوباره امتحان کنید."
        )
    finally:
        # Clean up temporary directory
        if os.path.exists(temp_dir_path):
            for file_name in os.listdir(temp_dir_path):
                file_path_to_delete = os.path.join(temp_dir_path, file_name)
                try:
                    if os.path.isfile(file_path_to_delete):
                        os.remove(file_path_to_delete)
                except Exception as e:
                    logger.error(f"Error deleting file {file_path_to_delete}: {e}")
            try:
                os.rmdir(temp_dir_path)
                logger.info(f"پوشه موقت کاربر {user_id} پاک شد: {temp_dir_path}")
            except Exception as e:
                logger.error(f"Error deleting temporary directory {temp_dir_path}: {e}")

# تابع Health Check جداگانه برای aiohttp
async def health_check_route(request):
    """Simple endpoint for Koyeb Health Check."""
    return web.Response(text="OK")

async def main() -> None:
    """Starts the bot."""
    # Initialize the database
    await init_db()

    global application
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(check_membership_and_proceed, pattern="^check_membership$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    # Initialize the aiohttp web application for handling both webhook and health check
    app = web.Application()
    app.router.add_get("/", health_check_route) # Health check route

    # We need to pass the webhook handler for telegram-bot updates
    async def telegram_webhook_handler(request):
        update = Update.de_json(await request.json(), application.bot)
        await application.process_update(update)
        return web.Response()

    app.router.add_post(WEBHOOK_PATH, telegram_webhook_handler) # Telegram webhook route

    # Run the aiohttp server as part of the application setup
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)

    # Set webhook with Telegram API
    await application.bot.delete_webhook()
    logger.info("Webhook با موفقیت حذف شد")
    webhook_full_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
    await application.bot.set_webhook(url=webhook_full_url)
    logger.info(f"Webhook تنظیم شد: {webhook_full_url}")

    # Start the aiohttp server
    await site.start()
    logger.info(f"سرور aiohttp برای Webhook در پورت {PORT} آغاز به کار کرد.")

    # Keep the application running indefinitely
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"خطای کلی در اجرای ربات: {e}", exc_info=True)

