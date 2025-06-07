import os
import logging
import asyncio
import aiosqlite
from datetime import datetime

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
from aiohttp import web
from yt_dlp import YoutubeDL, DownloadError, ExtractorError # Import specific yt-dlp exceptions

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Environment Variables (Fetched from Koyeb or OS) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

WEBHOOK_URL = "https://particular-capybara-amirgit3-bbc0dbbd.koyeb.app"
WEBHOOK_PATH = "/telegram"
PORT = int(os.environ.get("PORT", 8080))

# --- Channel Configuration ---
REQUIRED_CHANNEL_ID_1 = -1001137065230
REQUIRED_CHANNEL_ID_2 = -1002284196638

CHANNEL_LINK_1 = "https://t.me/enrgy_m"
CHANNEL_LINK_2 = "https://t.me/music_bik"

# --- Database Management ---
DATABASE_NAME = "user_limits.db"
DAILY_LIMIT = 50

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
    logger.info("Database initialized successfully.")

async def get_user_download_count(user_id):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        cursor = await db.execute("SELECT download_count, last_reset_date FROM user_downloads WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()

        today_str = datetime.now().strftime("%Y-%m-%d")

        if result:
            count, last_reset_date = result
            if last_reset_date != today_str:
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
    if chat_id == 0:
        return True
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Error checking membership for user {user_id} in chat {chat_id}: {e}")
        return False

async def check_all_memberships(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if a user is a member of all required channels."""
    is_member_1 = await is_member(user_id, REQUIRED_CHANNEL_ID_1, context)
    is_member_2 = True
    if REQUIRED_CHANNEL_ID_2 != 0:
        is_member_2 = await is_member(user_id, REQUIRED_CHANNEL_ID_2, context)
    return is_member_1 and is_member_2

async def get_membership_buttons(is_all_member: bool = False):
    """Returns inline keyboard for membership check and channel links."""
    if is_all_member:
        return None

    buttons = []
    if REQUIRED_CHANNEL_ID_1 != 0 and CHANNEL_LINK_1:
        buttons.append([InlineKeyboardButton("کانال نگرش مثبت ✨", url=CHANNEL_LINK_1)])
    if REQUIRED_CHANNEL_ID_2 != 0 and CHANNEL_LINK_2:
        buttons.append([InlineKeyboardButton("کانال Music 🎶", url=CHANNEL_LINK_2)])

    buttons.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")])

    return InlineKeyboardMarkup(buttons)

async def check_membership_and_proceed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name

    logger.info(f"کاربر {user_id} ({username}/{first_name}) درخواست بررسی عضویت را کلیک کرد.")

    is_all_member = await check_all_memberships(user_id, context)
    if is_all_member:
        message_text = (
            "✅ عضویت شما در کانال‌ها تایید شد! 🎉\n\n"
            "حالا می‌توانید لینک پست‌های **یوتیوب (YouTube)**، **شورت (Shorts)**، **ریلز (Reels)** یا **IGTV اینستاگرام (Instagram IGTV)** را برای من ارسال کنید تا ویدیو یا عکس مربوطه را دریافت کنید."
        )
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
            reply_markup=None
        )
        await update.effective_message.reply_text(message_text)
    else:
        await update.callback_query.answer("هنوز عضویت شما تایید نشده است. لطفاً ابتدا در کانال‌ها عضو شوید.")
        message_text = (
            "⚠️ برای استفاده از ربات، ابتدا باید در کانال‌های زیر عضو شوید:\n\n"
            "لطفاً با کلیک روی دکمه‌های زیر، وارد کانال‌ها شوید و سپس دکمه «✅ بررسی عضویت» را دوباره فشار دهید."
        )
        await update.effective_message.reply_text(message_text, reply_markup=await get_membership_buttons(False))


# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message on /start with membership check."""
    user = update.effective_user
    logger.info(f"کاربر {user.id} ربات را با زبان {user.language_code} شروع کرد")

    is_all_member = await check_all_memberships(user.id, context)
    if is_all_member:
        await update.message.reply_html(
            rf"سلام {user.mention_html()}! خوش آمدید. 👋\n\n"
            "می‌توانید لینک پست‌های **یوتیوب (YouTube)**، **شورت (Shorts)**، **ریلز (Reels)** یا **IGTV اینستاگرام (Instagram IGTV)** را برای من ارسال کنید تا ویدیو یا عکس مربوطه را دریافت کنید."
        )
    else:
        await update.message.reply_html(
            rf"سلام {user.mention_html()}! ⚠️ برای استفاده از ربات، ابتدا باید در کانال‌های زیر عضو شوید:\n\n"
            "لطفاً با کلیک روی دکمه‌های زیر، وارد کانال‌ها شوید و سپس دکمه «✅ بررسی عضویت» را فشار دهید.",
            reply_markup=await get_membership_buttons(False)
        )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages containing URLs for download."""
    user_id = update.effective_user.id
    user_message = update.message.text
    chat_id = update.effective_chat.id

    is_all_member = await check_all_memberships(user_id, context)
    if not is_all_member:
        await update.message.reply_text(
            "⚠️ برای استفاده از ربات، ابتدا باید در کانال‌های زیر عضو شوید:\n\n"
            "لطفاً با کلیک روی دکمه‌های زیر، وارد کانال‌ها شوید و سپس دکمه «✅ بررسی عضویت» را فشار دهید.",
            reply_markup=await get_membership_buttons(False)
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

    sent_message = None
    try:
        sent_message = await update.message.reply_text("در حال پردازش لینک شما... لطفا صبر کنید.")
        file_path = None
        info = None

        # --- First attempt: Try with Instagram credentials (if it's an Instagram link) ---
        if "instagram.com" in user_message and INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD:
            logger.info("تلاش اول: دانلود اینستاگرام با اعتبارنامه کاربری.")
            ydl_opts_with_auth = {
                'format': 'best',
                'outtmpl': os.path.join(temp_dir_path, '%(title)s.%(ext)s'),
                'noplaylist': True,
                'ignoreerrors': True, # Important for trying public if login fails
                'max_downloads': 1,
                'usenetrc': False,
                'cookiefile': None,
                'username': INSTAGRAM_USERNAME,
                'password': INSTAGRAM_PASSWORD,
                'quiet': True,
                'no_warnings': True
            }
            try:
                with YoutubeDL(ydl_opts_with_auth) as ydl:
                    info = ydl.extract_info(user_message, download=False) # Just extract info first
                    if info:
                        # If info is successfully extracted, download it
                        ydl.download([user_message])
                        file_path = ydl.prepare_filename(info)
                    else:
                        # If info is None even with credentials, something is wrong
                        raise ExtractorError("Failed to extract info with credentials.")
            except ExtractorError as ee:
                logger.warning(f"تلاش با اعتبارنامه اینستاگرام شکست خورد: {ee}. (ممکن است به دلیل نیاز به تایید لاگین باشد)")
                # If login fails, info will be None, so we move to the public attempt
                info = None # Reset info to None so the second attempt is triggered
            except DownloadError as de:
                logger.warning(f"خطا در دانلود با اعتبارنامه اینستاگرام: {de}. (ممکن است به دلیل نیاز به تایید لاگین باشد)")
                info = None
            except Exception as e:
                logger.warning(f"خطای نامشخص در تلاش با اعتبارنامه اینستاگرام: {e}. (تلاش عمومی انجام می‌شود)")
                info = None

        # --- Second attempt (or first if not Instagram or no credentials): Try without authentication ---
        if info is None: # Only try public if previous attempt failed or wasn't Instagram
            logger.info("تلاش دوم: دانلود به صورت عمومی (بدون اعتبارنامه).")
            ydl_opts_public = {
                'format': 'best',
                'outtmpl': os.path.join(temp_dir_path, '%(title)s.%(ext)s'),
                'noplaylist': True,
                'ignoreerrors': True, # Allow continuing if some parts fail
                'max_downloads': 1,
                'usenetrc': False,
                'cookiefile': None,
                'quiet': True,
                'no_warnings': True
            }
            try:
                with YoutubeDL(ydl_opts_public) as ydl:
                    info = ydl.extract_info(user_message, download=True)
                    if info:
                        file_path = ydl.prepare_filename(info)
            except Exception as e:
                logger.error(f"خطا در دانلود عمومی برای لینک {user_message}: {e}", exc_info=True)
                info = None # Ensure info is None on public attempt error

        # --- Process downloaded file or report failure ---
        if file_path and os.path.exists(file_path) and info:
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            logger.info(f"فایل دانلود شد: {file_path}, حجم: {file_size_mb:.2f} MB")

            if file_size_mb > 50:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent_message.message_id,
                    text="متاسفانه، فایل دانلود شد اما حجم آن (بیش از 50 مگابایت) برای ارسال در تلگرام بسیار زیاد است."
                )
            else:
                try:
                    if info.get('ext') in ['mp4', 'mov', 'avi', 'mkv', 'webm']:
                        with open(file_path, 'rb') as video_file:
                            await context.bot.send_video(chat_id, video_file, caption="ویدیوی شما آماده است! 🎬")
                    elif info.get('ext') in ['jpg', 'jpeg', 'png', 'webp']:
                        with open(file_path, 'rb') as photo_file:
                            await context.bot.send_photo(chat_id, photo_file, caption="عکس شما آماده است! 📸")
                    else:
                        with open(file_path, 'rb') as doc_file:
                            await context.bot.send_document(chat_id, doc_file, caption="فایل شما آماده است! 📄")

                    await context.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
                    await increment_user_download_count(user_id)
                    await update.message.reply_text(
                        f"فایل با موفقیت ارسال شد! 🚀 شما امروز {await get_user_download_count(user_id)} از {DAILY_LIMIT} دانلود مجاز را انجام داده‌اید."
                    )
                except Exception as e:
                    logger.error(f"Error sending file to Telegram: {e}")
                    if sent_message:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=sent_message.message_id,
                            text=f"متاسفانه، در ارسال فایل به تلگرام مشکلی پیش آمد. لطفاً دوباره تلاش کنید. (خطا: {e})"
                        )
        else:
            if sent_message:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent_message.message_id,
                    text="⚠️ متاسفانه، فایلی از این لینک پیدا نشد یا دانلود با مشکل مواجه شد.\nلطفاً از لینک صحیح، عمومی و فعال استفاده کنید و دوباره امتحان کنید."
                )
    except Exception as e: # Catch any other unexpected errors
        logger.error(f"General error processing URL {user_message}: {e}", exc_info=True)
        if sent_message:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text=f"متاسفانه، در پردازش لینک شما مشکلی پیش آمد: {e}\nلطفاً از لینک صحیح و عمومی استفاده کنید و دوباره امتحان کنید."
            )
    finally:
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

# Health Check function for aiohttp
async def health_check_route(request):
    """Simple endpoint for Koyeb Health Check."""
    return web.Response(text="OK")

async def main() -> None:
    """Starts the bot."""
    await init_db()

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set. Bot cannot start.")
        if hasattr(os.environ, 'BOT_TOKEN'):
             logger.warning("BOT_TOKEN was found in os.environ but not explicitly fetched. Please ensure it's set as a Koyeb environment variable.")
        return

    global application
    application = Application.builder().token(BOT_TOKEN).build()

    await application.initialize()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(check_membership_and_proceed, pattern="^check_membership$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    app = web.Application()
    app.router.add_get("/", health_check_route)

    async def telegram_webhook_handler(request):
        update_data = await request.json()
        update = Update.de_json(update_data, application.bot)
        await application.process_update(update)
        return web.Response()

    app.router.add_post(WEBHOOK_PATH, telegram_webhook_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)

    try:
        await application.bot.delete_webhook()
        logger.info("Webhook با موفقیت حذف شد")
    except Exception as e:
        logger.warning(f"Failed to delete webhook (might not be set): {e}")

    webhook_full_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
    await application.bot.set_webhook(url=webhook_full_url)
    logger.info(f"Webhook تنظیم شد: {webhook_full_url}")

    await site.start()
    logger.info(f"سرور aiohttp برای Webhook در پورت {PORT} آغاز به کار کرد.")

    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"خطای کلی در اجرای ربات: {e}", exc_info=True)

