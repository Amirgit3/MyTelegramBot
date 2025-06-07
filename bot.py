import os
import logging
from telegram import Update, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# --- Basic Configuration ---
# Replace with your actual bot token
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Optional: Set your Telegram Channel ID for forced subscription
# Example: CHANNEL_ID = -1001234567890 (Make sure your bot is an admin in the channel)
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# Optional: Set Instagram username and password for older authentication methods if cookies fail.
# For better security and reliability, cookies are now preferred.
# INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
# INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# Create a temporary directory for downloads
TEMP_DIR = 'downloads'
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)
temp_dir_path = os.path.abspath(TEMP_DIR)

# --- Logging Configuration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET/POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Helper Functions ---

async def is_member(user_id: int) -> bool:
    if not CHANNEL_ID:
        return True  # If no channel is set, all users are considered members
    try:
        chat_member = await Application.builder().token(TOKEN).build().bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Error checking channel membership: {e}")
        return False

def get_subscribe_keyboard():
    keyboard = [[InlineKeyboardButton("عضویت در کانال", url=f"https://t.me/your_channel_username")]] # Replace 'your_channel_username'
    return InlineKeyboardMarkup(keyboard)

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"User {user.id} started the bot.")

    if not await is_member(user.id):
        reply_markup = get_subscribe_keyboard()
        await update.message.reply_text(
            f"سلام {user.mention_html()}!\n\n"
            "برای استفاده از ربات، ابتدا باید در کانال ما عضو شوید:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return

    await update.message.reply_html(
        rf"سلام {user.mention_html()}! من یه ربات دانلودر هستم.",
        reply_markup=ForceReply(selective=True),
    )
    await update.message.reply_text(
        "برای دانلود از یوتیوب و اینستاگرام، فقط کافیه لینک رو برام بفرستی.",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not await is_member(user.id):
        reply_markup = get_subscribe_keyboard()
        await update.message.reply_text(
            f"سلام {user.mention_html()}!\n\n"
            "برای استفاده از ربات، ابتدا باید در کانال ما عضو شوید:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return

    await update.message.reply_text(
        "من میتونم ویدیوها رو از یوتیوب و اینستاگرام دانلود کنم.\n"
        "فقط کافیه لینک ویدیو رو برام بفرستی. 😎",
        parse_mode='Markdown'
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_message = update.message.text
    logger.info(f"User {user.id} sent a URL: {user_message}")

    if not await is_member(user.id):
        reply_markup = get_subscribe_keyboard()
        await update.message.reply_text(
            f"سلام {user.mention_html()}!\n\n"
            "برای استفاده از ربات، ابتدا باید در کانال ما عضو شوید:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return

    sent_message = None
    try:
        sent_message = await update.message.reply_text("در حال پردازش لینک شما... لطفا صبر کنید.")
        file_path = None
        info = None

        # --- First attempt: Try with cookies for Instagram (if it's an Instagram link) ---
        if "instagram.com" in user_message:
            logger.info("تلاش اول: دانلود اینستاگرام با کوکی‌ها.")
            ydl_opts_with_cookies = {
                'format': 'best',
                'outtmpl': os.path.join(temp_dir_path, '%(title)s.%(ext)s'),
                'noplaylist': True,
                'max_downloads': 1,
                'usenetrc': False,
                'cookiefile': 'www.instagram.com_cookies.txt', # --- IMPORTANT: Use Instagram cookies file ---
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                # 'username': INSTAGRAM_USERNAME, # Remove these if you're using cookiefile
                # 'password': INSTAGRAM_PASSWORD, # Remove these if you're using cookiefile
            }
            try:
                with YoutubeDL(ydl_opts_with_cookies) as ydl:
                    info = ydl.extract_info(user_message, download=False) # Extract info first
                    if info:
                        ydl.download([user_message]) # Then download
                        file_path = ydl.prepare_filename(info)
                    else:
                        logger.warning("اطلاعاتی با کوکی‌های اینستاگرام استخراج نشد. تلاش عمومی انجام می‌شود.")
                        info = None
            except DownloadError as de:
                logger.warning(f"خطا در دانلود با کوکی‌های اینستاگرام: {de}. (تلاش عمومی انجام می‌شود)")
                info = None
            except Exception as e:
                logger.warning(f"خطای نامشخص در تلاش با کوکی‌های اینستاگرام: {e}. (تلاش عمومی انجام می‌شود)")
                info = None

        # --- Second attempt (or first if not Instagram): Try without authentication, but with YouTube cookies if applicable ---
        if info is None:
            logger.info("تلاش دوم: دانلود به صورت عمومی (بدون اعتبارنامه مستقیم) یا با کوکی‌های یوتیوب.")
            ydl_opts_public_or_youtube_cookies = {
                'format': 'best',
                'outtmpl': os.path.join(temp_dir_path, '%(title)s.%(ext)s'),
                'noplaylist': True,
                'max_downloads': 1,
                'usenetrc': False,
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
            }
            if "youtube.com" in user_message or "youtu.be" in user_message:
                ydl_opts_public_or_youtube_cookies['cookiefile'] = 'www.youtube.com_cookies.txt' # --- IMPORTANT: Use YouTube cookies file ---
                logger.info("لینک یوتیوب است، از کوکی‌های یوتیوب استفاده می‌شود.")

            try:
                with YoutubeDL(ydl_opts_public_or_youtube_cookies) as ydl:
                    info = ydl.extract_info(user_message, download=True)
                    if info:
                        file_path = ydl.prepare_filename(info)
            except DownloadError as e:
                logger.error(f"خطا در دانلود عمومی (یا با کوکی‌های یوتیوب) برای لینک {user_message}: {e}", exc_info=True)
                if "Sign in to confirm you’re not a bot" in str(e) or "Login required" in str(e):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=sent_message.message_id,
                        text="⚠️ متاسفانه، یوتیوب برای دانلود این ویدیو نیاز به ورود به حساب کاربری دارد یا شما را به عنوان ربات شناسایی کرده است. لطفاً اطمینان حاصل کنید که کوکی‌های یوتیوب شما در سرور به‌روز هستند یا با یک لینک عمومی‌تر امتحان کنید."
                    )
                    return
                elif "Requested content is not available" in str(e) or "empty media response" in str(e):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=sent_message.message_id,
                        text="⚠️ اینستاگرام اجازه دانلود این پست را نمی‌دهد. (ممکن است پست خصوصی باشد یا به دلیل محدودیت‌های امنیتی اینستاگرام باشد). لطفاً اطمینان حاصل کنید که کوکی‌های اینستاگرام شما در سرور به‌روز هستند یا از یک لینک عمومی و فعال استفاده کنید."
                    )
                    return
                info = None
            except Exception as e:
                logger.error(f"خطای نامشخص در دانلود عمومی (یا با کوکی‌های یوتیوب) برای لینک {user_message}: {e}", exc_info=True)
                info = None

        if not info:
            logger.warning(f"Could not extract info for {user_message}. No file to send.")
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text="❌ متاسفانه نتونستم این لینک رو پردازش کنم یا فایلی پیدا کنم. لطفا مطمئن بشید لینک درسته."
            )
            return

        if file_path and os.path.exists(file_path):
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            logger.info(f"File found: {file_path}, size: {file_size_mb:.2f} MB")

            if file_size_mb > 50: # Telegram bot API limit is 50MB for general files, 20MB for photos
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent_message.message_id,
                    text=f"فایل با حجم {file_size_mb:.2f} مگابایت، متاسفانه بزرگتر از محدودیت تلگرام (50MB) است."
                )
                logger.warning(f"File {file_path} is too large ({file_size_mb:.2f} MB).")
            else:
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=sent_message.message_id,
                        text="فایل آماده آپلود است. لطفا صبر کنید... 🚀"
                    )
                    await context.bot.send_document(chat_id=chat_id, document=file_path)
                    await context.bot.send_message(chat_id=chat_id, text="✅ فایل با موفقیت ارسال شد!")
                    logger.info(f"Successfully sent {file_path} to user {user.id}.")
                except Exception as e:
                    logger.error(f"Error sending file {file_path}: {e}", exc_info=True)
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=sent_message.message_id,
                        text="❌ متاسفانه در ارسال فایل به تلگرام مشکلی پیش آمد."
                    )
                finally:
                    # Clean up the downloaded file
                    os.remove(file_path)
                    logger.info(f"Cleaned up file: {file_path}")
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text="❌ متاسفانه فایل دانلود نشد یا پیدا نشد. لینک شما ممکن است پشتیبانی نشود یا مشکلی پیش آمده باشد."
            )
            logger.warning(f"File not found or downloaded for {user_message}.")

    except Exception as e:
        logger.error(f"Unhandled error in handle_url for {user_message}: {e}", exc_info=True)
        if sent_message:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text="❌ یک خطای ناشناخته رخ داد. لطفا دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
            )
        else:
            await update.message.reply_text("❌ یک خطای ناشناخته رخ داد. لطفا دوباره تلاش کنید.")
    finally:
        # Ensure cleanup in case of partial download or error
        if 'file_path' in locals() and file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Ensured cleanup of file: {file_path}")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # A simple echo for any non-command, non-URL message
    user = update.effective_user
    logger.info(f"User {user.id} sent: {update.message.text}")

    if not await is_member(user.id):
        reply_markup = get_subscribe_keyboard()
        await update.message.reply_text(
            f"سلام {user.mention_html()}!\n\n"
            "برای استفاده از ربات، ابتدا باید در کانال ما عضو شوید:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return

    await update.message.reply_text(
        "من فقط می‌تونم لینک‌های یوتیوب و اینستاگرام رو پردازش کنم. 🧐"
        "لطفا لینک صحیح رو برام بفرست.",
        parse_mode='Markdown'
    )

# --- Main Application Setup ---
def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # Handles URLs (messages that contain 'http://' or 'https://')
    application.add_handler(MessageHandler(filters.TEXT & (filters.Regex(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+') | filters.Regex(r'www\.(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')), handle_url))

    # Handles other text messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

