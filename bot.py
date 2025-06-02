import os
import subprocess
import logging
import sqlite3
import asyncio
import psutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, InlineQueryHandler, filters, ContextTypes
from telegram.error import TelegramError
import yt_dlp
from datetime import datetime, timedelta
import re
import tempfile
import shutil
from contextlib import contextmanager
import time
from dotenv import load_dotenv
from aiohttp import web

# بارگذاری توکن و اطلاعات اینستاگرام از .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# تنظیم لاگ‌گیری برای Koyeb (به stdout)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# لینک کانال‌ها (به فرمت HTTPS)
CHANNEL_1 = "https://t.me/enrgy_m"
CHANNEL_2 = "https://t.me/music_bik"

# مسیر دیتابیس
DB_PATH = "user_limits.db"

# صف برای مدیریت درخواست‌ها
request_queue = asyncio.Queue()

# Semaphore برای محدود کردن دانلودهای همزمان
download_semaphore = asyncio.Semaphore(2)  # حداکثر ۲ دانلود همزمان

# زبان‌ها
LANGUAGES = {
    "en": {
        "name": "English",
        "welcome": "Welcome! 😊\nFiles are split into 50MB parts.\nMax file size: 500MB.\nJoin our channels first:",
        "invalid_link": "Invalid link! Only Instagram or YouTube links.",
        "file_too_large": "Your file is larger than 500MB!",
        "join_channels": "Please join both channels and try again.",
        "membership_ok": "Membership verified! Send an Instagram or YouTube link.",
        "choose_option": "Choose an option:",
        "no_subtitle": "Subtitles not available!",
        "error": "Error: {}",
        "limit_reached": "You've reached the limit of 20 requests or 1GB per day. Try again tomorrow.",
        "processing": "Processing your request, please wait...",
        "progress": "Download progress: {}%",
        "cancel": "Request cancelled.",
        "ping": "Pong! Response time: {}ms",
        "in_queue": "Your request is in queue. Please wait...",
        "estimated_time": "Download started. Estimated time: {} seconds",
        "checking_membership": "Checking membership...",
        "bot_not_admin": "Bot must be an admin in both channels. Please make it an admin.",
        "membership_check_failed": "Could not check membership. Please try again."
    },
    "fa": {
        "name": "فارسی",
        "welcome": "به ربات خوش اومدید! 😊\nفایل‌ها به تکه‌های ۵۰ مگابایتی تقسیم می‌شن.\nحداکثر حجم فایل: ۵۰۰ مگابایت.\nلطفاً ابتدا در کانال‌ها عضو بشید:",
        "invalid_link": "لینک نامعتبره! فقط لینک اینستاگرام یا یوتیوب.",
        "file_too_large": "فایل شما بزرگتر از ۵۰۰ مگابایته!",
        "join_channels": "لطفاً در هر دو کانال عضو بشید و دوباره امتحان کنید.",
        "membership_ok": "عضویت تأیید شد! لینک اینستاگرام یا یوتیوب بفرستید.",
        "choose_option": "گزینه رو انتخاب کنید:",
        "no_subtitle": "زیرنویس در دسترس نیست!",
        "error": "خطا: {}",
        "limit_reached": "شما به محدودیت ۲۰ درخواست یا ۱ گیگ در روز رسیدید. فردا دوباره امتحان کنید.",
        "processing": "در حال پردازش درخواست شما، لطفاً منتظر بمانید...",
        "progress": "پیشرفت دانلود: {}%",
        "cancel": "درخواست لغو شد.",
        "ping": "پینگ! زمان پاسخ: {} میلی‌ثانیه",
        "in_queue": "درخواست شما در صف قرار داره. لطفاً صبر کنید...",
        "estimated_time": "دانلود شروع شد. زمان تقریبی: {} ثانیه",
        "checking_membership": "در حال بررسی عضویت...",
        "bot_not_admin": "ربات باید در هر دو کانال ادمین باشد. لطفاً ادمین کنید.",
        "membership_check_failed": "نمی‌توان عضویت را چک کرد. لطفاً دوباره امتحان کنید."
    }
}

# بررسی نصب FFmpeg
def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("FFmpeg نصب نشده یا پیدا نشد.")
        return False

# مدیریت دایرکتوری موقت
@contextmanager
def temp_directory(user_id):
    temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_")
    logger.info(f"پوشه موقت برای کاربر {user_id} ساخته شد: {temp_dir}")
    try:
        yield temp_dir
    finally:
        # حذف پوشه به توابع process_youtube و process_instagram منتقل شده
        pass

# پاک‌سازی دوره‌ای پوشه‌های موقت قدیمی
async def clean_temp_directories():
    while True:
        current_time = datetime.now()
        temp_dir_prefix = tempfile.gettempdir() + "/user_"
        for folder in os.listdir(tempfile.gettempdir()):
            if folder.startswith("user_"):
                folder_path = os.path.join(tempfile.gettempdir(), folder)
                try:
                    creation_time = datetime.fromtimestamp(os.path.getctime(folder_path))
                    if current_time - creation_time > timedelta(hours=1):
                        shutil.rmtree(folder_path, ignore_errors=True)
                        logger.info(f"پوشه موقت قدیمی حذف شد: {folder_path}")
                except Exception as e:
                    logger.error(f"خطا در پاک‌سازی پوشه {folder_path}: {str(e)}")
        await asyncio.sleep(3600)  # بررسی هر یک ساعت

# تنظیم دیتابیس SQLite
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_limits (
            user_id TEXT,
            date TEXT,
            request_count INTEGER,
            volume INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def update_user_limit(user_id, file_size):
    today = datetime.now().date().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT request_count, volume FROM user_limits WHERE user_id = ? AND date = ?", (user_id, today))
    result = cursor.fetchone()

    if result:
        request_count, volume = result
        cursor.execute("UPDATE user_limits SET request_count = ?, volume = ? WHERE user_id = ? AND date = ?",
                       (request_count + 1, volume + file_size, user_id, today))
    else:
        cursor.execute("INSERT INTO user_limits (user_id, date, request_count, volume) VALUES (?, ?, ?, ?)",
                       (user_id, today, 1, file_size))

    conn.commit()
    conn.close()

def check_user_limit(user_id, file_size=0):
    today = datetime.now().date().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT request_count, volume FROM user_limits WHERE user_id = ? AND date = ?", (user_id, today))
    result = cursor.fetchone()

    request_count = result[0] if result else 0
    volume = result[1] if result else 0

    conn.close()

    if request_count >= 20 or (volume + file_size) > 1024 * 1024 * 1024:
        return False
    return True

# بررسی اعتبار لینک
def is_valid_url(url):
    pattern = r'^(https?://)?(www\.)?(youtube\.com|youtu\.be|instagram\.com)/.+$'
    return bool(re.match(pattern, url))

# دانلود غیرهمزمان با yt-dlp
async def download_with_yt_dlp(url, ydl_opts, context, update, lang):
    def progress_hook(d):
        if d['status'] == 'downloading':
            percent = d.get('downloaded_bytes', 0) / d.get('total_bytes', 1) * 100
            if percent:
                asyncio.ensure_future(
                    update.message.reply_text(LANGUAGES[lang]["progress"].format(round(percent, 2)))
                )
        elif d['status'] == 'error':
            asyncio.ensure_future(
                update.message.reply_text(LANGUAGES[lang]["error"].format("خطا در دانلود فایل"))
            )

    memory = psutil.virtual_memory()
    if memory.available < 100 * 1024 * 1024:
        await update.message.reply_text(LANGUAGES[lang]["error"].format("حافظه سرور کافی نیست."))
        logger.error(f"حافظه ناکافی: {memory.available / (1024 * 1024):.2f} MB")
        return False

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        file_size = info.get('filesize', 0) or 0
        if file_size > 500 * 1024 * 1024:
            await update.message.reply_text(LANGUAGES[lang]["file_too_large"])
            return False

    estimated_time = file_size / (1024 * 1024) / 2
    await update.message.reply_text(LANGUAGES[lang]["estimated_time"].format(round(estimated_time)))

    ydl_opts.update({'buffer_size': 1024 * 1024})

    async with download_semaphore:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.add_progress_hook(progress_hook)
            loop = asyncio.get_running_loop()
            try:
                start_time = time.time()
                await loop.run_in_executor(None, lambda: ydl.download([url]))
                duration = time.time() - start_time
                logger.info(f"دانلود برای کاربر {update.effective_user.id} در {duration:.2f} ثانیه کامل شد")
                return True
            except yt_dlp.DownloadError as e:
                logger.error(f"خطای دانلود: {str(e)}")
                await update.message.reply_text(LANGUAGES[lang]["error"].format("خطا در دانلود فایل"))
                return False

# پردازش صف درخواست‌ها
async def process_queue():
    while True:
        try:
            update, context, url, processing_msg = await request_queue.get()
            lang = context.user_data.get("language", "fa")
            user_id = str(update.effective_user.id)
            max_retries = 3
            retry_count = 0

            while retry_count < max_retries:
                try:
                    await handle_request(update, context, url, processing_msg)
                    logger.info(f"درخواست کاربر {user_id} با موفقیت پردازش شد: {url}")
                    break
                except Exception as e:
                    retry_count += 1
                    if retry_count == max_retries:
                        await processing_msg.edit_text(LANGUAGES[lang]["error"].format("تلاش‌ها برای پردازش درخواست ناموفق بود."))
                        logger.error(f"شکست نهایی در پردازش درخواست کاربر {user_id}: {str(e)}")
                        break
                    await asyncio.sleep(5)
                    logger.warning(f"تلاش مجدد ({retry_count}/{max_retries}) برای کاربر {user_id}: {str(e)}")
            request_queue.task_done()
        except Exception as e:
            logger.error(f"خطای کلی در پردازش صف: {str(e)}")
            await asyncio.sleep(10)

async def handle_request(update, context, url, processing_msg):
    lang = context.user_data.get("language", "fa")
    user_id = str(update.effective_user.id)

    try:
        if "youtube.com" in url or "youtu.be" in url:
            await process_youtube(update, context, url, processing_msg)
        elif "instagram.com" in url:
            if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
                await processing_msg.edit_text(LANGUAGES[lang]["error"].format("اطلاعات ورود به اینستاگرام تنظیم نشده است."))
                logger.error(f"اطلاعات اینستاگرام برای کاربر {user_id} تنظیم نشده است.")
                return
            await process_instagram(update, context, url, processing_msg)
        logger.info(f"درخواست کاربر {user_id} پردازش شد: {url}")
    except Exception as e:
        await processing_msg.edit_text(LANGUAGES[lang]["error"].format(str(e)))
        logger.error(f"خطا در پردازش درخواست کاربر {user_id}: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_lang = update.effective_user.language_code if update.effective_user.language_code in LANGUAGES else "fa"
    context.user_data["language"] = user_lang
    lang = context.user_data["language"]

    keyboard = [
        [InlineKeyboardButton("عضویت در کانال ۱", url=CHANNEL_1)],
        [InlineKeyboardButton("عضویت در کانال ۲", url=CHANNEL_2)],
        [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(LANGUAGES[lang]["welcome"], reply_markup=reply_markup)
    logger.info(f"کاربر {user_id} ربات را با زبان {lang} شروع کرد")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    lang = context.user_data.get("language", "fa")
    response_time = (time.time() - start_time) * 1000
    await update.message.reply_text(LANGUAGES[lang]["ping"].format(round(response_time, 2)))
    logger.info(f"کاربر {update.effective_user.id} پینگ کرد: {response_time:.2f} میلی‌ثانیه")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "fa")
    keyboard = [
        [InlineKeyboardButton(LANGUAGES[lang]["name"], callback_data=f"lang_{lang}") for lang in ["en", "fa", "ru"]],
        [InlineKeyboardButton(LANGUAGES[lang]["name"], callback_data=f"lang_{lang}") for lang in ["es", "fr", "de"]],
        [InlineKeyboardButton(LANGUAGES[lang]["name"], callback_data=f"lang_{lang}") for lang in ["it", "ar", "zh"]],
        [InlineKeyboardButton(LANGUAGES["pt"]["name"], callback_data="lang_pt")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("زبان ربات را انتخاب کنید:", reply_markup=reply_markup)
    logger.info(f"کاربر {query.from_user.id} تنظیمات را باز کرد")

async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = context.user_data.get("language", "fa")

    logger.info(f"شروع بررسی عضویت برای کاربر {user_id}")
    try:
        await query.message.reply_text(LANGUAGES[lang]["checking_membership"])

        # چک کردن وضعیت ربات در کانال‌ها
        bot_id = (await context.bot.get_me()).id
        try:
            bot_member1 = await context.bot.get_chat_member("@enrgy_m", bot_id)
            bot_member2 = await context.bot.get_chat_member("@music_bik", bot_id)
            logger.info(f"وضعیت ربات - کانال ۱: {bot_member1.status}, کانال ۲: {bot_member2.status}")
            if bot_member1.status not in ["administrator", "creator"] or bot_member2.status not in ["administrator", "creator"]:
                await query.message.reply_text(LANGUAGES[lang]["bot_not_admin"])
                logger.error(f"ربات در کانال‌ها ادمین نیست. کانال ۱: {bot_member1.status}, کانال ۲: {bot_member2.status}")
                return
        except TelegramError as e:
            logger.error(f"خطا در بررسی وضعیت ربات در کانال‌ها: {str(e)}")
            await query.message.reply_text(LANGUAGES[lang]["membership_check_failed"])
            return

        # چک کردن عضویت کاربر
        try:
            chat_member1 = await context.bot.get_chat_member("@enrgy_m", user_id)
            chat_member2 = await context.bot.get_chat_member("@music_bik", user_id)
            logger.info(f"وضعیت کاربر {user_id} - کانال ۱: {chat_member1.status}, کانال ۲: {chat_member2.status}")
            if chat_member1.status in ["member", "administrator", "creator"] and \
               chat_member2.status in ["member", "administrator", "creator"]:
                context.user_data["is_member"] = True
                await query.message.reply_text(LANGUAGES[lang]["membership_ok"])
                logger.info(f"عضویت کاربر {user_id} تأیید شد")
            else:
                await query.message.reply_text(LANGUAGES[lang]["join_channels"])
                logger.warning(f"کاربر {user_id} در هر دو کانال عضو نیست")
        except TelegramError as e:
            logger.error(f"خطا در بررسی عضویت کاربر {user_id}: {str(e)}")
            await query.message.reply_text(LANGUAGES[lang]["membership_check_failed"])

    except Exception as e:
        logger.error(f"خطای کلی در بررسی عضویت برای کاربر {user_id}: {str(e)}")
        await query.message.reply_text(LANGUAGES[lang]["error"].format(str(e)))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    lang = context.user_data.get("language", "fa")

    if not context.user_data.get("is_member", False):
        await update.message.reply_text(LANGUAGES[lang]["join_channels"])
        logger.warning(f"کاربر {user_id} بدون عضویت پیام فرستاد")
        return

    url = update.message.text
    if not is_valid_url(url):
        await update.message.reply_text(LANGUAGES[lang]["invalid_link"])
        logger.warning(f"کاربر {user_id} لینک نامعتبر فرستاد: {url}")
        return

    if not check_user_limit(user_id):
        await update.message.reply_text(LANGUAGES[lang]["limit_reached"])
        logger.warning(f"کاربر {user_id} به محدودیت روزانه رسید")
        return

    context.user_data["cancel"] = False
    processing_msg = await update.message.reply_text(
        LANGUAGES[lang]["in_queue"],
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("لغو", callback_data=f"cancel_{url}")
        ]])
    )

    await request_queue.put((update, context, url, processing_msg))
    logger.info(f"درخواست کاربر {user_id} به صف اضافه شد: {url}")

async def process_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE, url, processing_msg):
    lang = context.user_data.get("language", "fa")
    user_id = str(update.effective_user.id)

    with temp_directory(user_id) as temp_dir:
        success = False
        try:
            ydl_opts = {"quiet": True, "outtmpl": f"{temp_dir}/%(id)s.%(ext)s"}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get("formats", [])
                subtitles = info.get("subtitles", {})
                description = info.get("description", LANGUAGES[lang]["no_subtitle"])

            context.user_data["yt_description"] = description
            keyboard = []
            for fmt in formats:
                if fmt.get("ext") in ["mp4", "webm"] and fmt.get("vcodec") != "none":
                    quality = fmt.get("format_note", "unknown")
                    file_size = fmt.get("filesize", 0) or 0
                    if file_size > 500 * 1024 * 1024:
                        continue
                    size_mb = f"~{file_size // (1024 * 1024)}MB" if file_size else "نامشخص"
                    keyboard.append([InlineKeyboardButton(
                        f"کیفیت {quality} ({size_mb})", callback_data=f"yt_{url}_{fmt['format_id']}"
                    )])
            keyboard.append([InlineKeyboardButton("صوت (mp3)", callback_data=f"yt_audio_{url}_mp3")])
            keyboard.append([InlineKeyboardButton("صوت (m4a)", callback_data=f"yt_audio_{url}_m4a")])
            for sub_lang in subtitles:
                keyboard.append([InlineKeyboardButton(
                    f"زیرنویس ({sub_lang})", callback_data=f"yt_sub_{url}_{sub_lang}"
                )])
            keyboard.append([InlineKeyboardButton("توضیحات ویدئو", callback_data=f"yt_desc_{url}")])
            keyboard.append([InlineKeyboardButton("لغو", callback_data=f"cancel_{url}")])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await processing_msg.edit_text(LANGUAGES[lang]["choose_option"], reply_markup=reply_markup)
            logger.info(f"کاربر {user_id} لینک یوتیوب را پردازش کرد: {url}")
            success = True
        except yt_dlp.DownloadError as e:
            error_msg = "لینک خصوصی است یا دسترسی محدود دارد."
            if "403" in str(e):
                error_msg = "دسترسی ممنوع (403)."
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(error_msg))
            logger.error(f"خطای دانلود یوتیوب برای کاربر {user_id}: {str(e)}")
        except Exception as e:
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(str(e)))
            logger.error(f"خطای غیرمنتظره برای کاربر {user_id}: {str(e)}")
        finally:
            if success:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"پوشه موقت کاربر {user_id} پس از موفقیت پاک شد: {temp_dir}")
            else:
                logger.info(f"پوشه موقت کاربر {user_id} به دلیل خطا نگه داشته شد: {temp_dir}")

async def process_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE, url, processing_msg):
    lang = context.user_data.get("language", "fa")
    user_id = str(update.effective_user.id)

    with temp_directory(user_id) as temp_dir:
        success = False
        try:
            ydl_opts = {
                "outtmpl": f"{temp_dir}/media.%(ext)s",
                "quiet": True,
                "username": INSTAGRAM_USERNAME,
                "password": INSTAGRAM_PASSWORD
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                media_type = info.get("ext", "mp4")
                caption = info.get("description", LANGUAGES[lang]["no_subtitle"])
                file_size = info.get("filesize", 0) or 0

            if file_size > 500 * 1024 * 1024:
                await processing_msg.edit_text(LANGUAGES[lang]["file_too_large"])
                logger.warning(f"فایل برای کاربر {user_id} بیش از حد بزرگ است: {file_size} بایت")
                return

            context.user_data["ig_caption"] = caption
            keyboard = []
            if media_type in ["jpg", "jpeg", "png"]:
                keyboard.append([InlineKeyboardButton("دریافت عکس", callback_data=f"ig_media_{url}_{media_type}")])
            else:
                keyboard.append([InlineKeyboardButton("دریافت ویدئو", callback_data=f"ig_media_{url}_{media_type}")])
            keyboard.append([InlineKeyboardButton("دریافت کپشن", callback_data=f"ig_caption_{url}")])
            keyboard.append([InlineKeyboardButton("لغو", callback_data=f"cancel_{url}")])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await processing_msg.edit_text(LANGUAGES[lang]["choose_option"], reply_markup=reply_markup)
            logger.info(f"کاربر {user_id} لینک اینستاگرام را پردازش کرد: {url}")
            success = True
        except yt_dlp.DownloadError as e:
            error_msg = "لینک خصوصی است یا دسترسی محدود دارد."
            if "403" in str(e):
                error_msg = "دسترسی ممنوع (403)."
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(error_msg))
            logger.error(f"خطای دانلود اینستاگرام برای کاربر {user_id}: {str(e)}")
        except Exception as e:
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(str(e)))
            logger.error(f"خطای غیرمنتظره برای کاربر {user_id}: {str(e)}")
        finally:
            if success:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"پوشه موقت کاربر {user_id} پس از موفقیت پاک شد: {temp_dir}")
            else:
                logger.info(f"پوشه موقت کاربر {user_id} به دلیل خطا نگه داشته شد: {temp_dir}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    lang = context.user_data.get("language", "fa")
    user_id = str(query.from_user.id)

    if data[0] == "cancel":
        context.user_data["cancel"] = True
        new_queue = asyncio.Queue()
        while not request_queue.empty():
            req = await request_queue.get()
            if req[0].effective_user.id != user_id or req[2] != data[1]:
                await new_queue.put(req)
            else:
                logger.info(f"درخواست کاربر {user_id} برای لینک {data[1]} از صف حذف شد")
            request_queue.task_done()
        global request_queue
        request_queue = new_queue
        await query.message.reply_text(LANGUAGES[lang]["cancel"])
        logger.info(f"کاربر {user_id} درخواست را برای لینک لغو کرد: {data[1]}")
        return

    if data[0] == "check_membership":
        await check_membership(update, context)
        return
    elif data[0] == "settings":
        await settings(update, context)
        return
    elif data[0] == "lang":
        context.user_data["language"] = data[1]
        await query.message.reply_text(f"زبان به {LANGUAGES[data[1]]['name']} تغییر کرد")
        logger.info(f"کاربر {user_id} زبان را به {data[1]} تغییر داد")
        return

    if not check_user_limit(user_id):
        await query.message.reply_text(LANGUAGES[lang]["limit_reached"])
        logger.warning(f"کاربر {user_id} در callback به محدودیت روزانه رسید")
        return

    url = data[1]
    processing_msg = await query.message.reply_text(LANGUAGES[lang]["processing"])

    with temp_directory(user_id) as temp_dir:
        success = False
        try:
            if not check_ffmpeg():
                await processing_msg.edit_text(LANGUAGES[lang]["error"].format("FFmpeg نصب نشده است."))
                return

            if data[0] == "yt":
                if data[2] == "desc":
                    description = context.user_data.get("yt_description", LANGUAGES[lang]["no_subtitle"])
                    await processing_msg.edit_text(f"توضیحات ویدئو:\n{description}")
                    logger.info(f"کاربر {user_id} توضیحات یوتیوب را درخواست کرد")
                    success = True
                elif data[2] == "audio":
                    audio_format = data[3]
                    ydl_opts = {
                        "format": "bestaudio",
                        "outtmpl": f"{temp_dir}/audio.%(ext)s",
                        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": audio_format}],
                        "quiet": True,
                    }
                    if await download_with_yt_dlp(url, ydl_opts, context, query, lang):
                        file_path = f"{temp_dir}/audio.{audio_format}"
                        file_size = os.path.getsize(file_path)
                        if not check_user_limit(user_id, file_size):
                            await processing_msg.edit_text(LANGUAGES[lang]["limit_reached"])
                            logger.warning(f"کاربر {user_id} در دانلود صوت به محدودیت رسید")
                            return
                        update_user_limit(user_id, file_size)
                        await query.message.reply_audio(audio=open(file_path, "rb"))
                        logger.info(f"کاربر {user_id} صوت یوتیوب ({audio_format}) را دانلود کرد")
                        success = True
                elif data[2] == "sub":
                    sub_lang = data[3]
                    ydl_opts = {
                        "writesubtitles": True,
                        "subtitleslangs": [sub_lang],
                        "outtmpl": f"{temp_dir}/subtitle.%(ext)s",
                        "quiet": True,
                    }
                    if await download_with_yt_dlp(url, ydl_opts, context, query, lang):
                        subtitle_file = f"{temp_dir}/subtitle.{sub_lang}.vtt"
                        if os.path.exists(subtitle_file):
                            file_size = os.path.getsize(subtitle_file)
                            update_user_limit(user_id, file_size)
                            await query.message.reply_document(document=open(subtitle_file, "rb"))
                            logger.info(f"کاربر {user_id} زیرنویس ({sub_lang}) را دانلود کرد")
                            success = True
                        else:
                            await processing_msg.edit_text(LANGUAGES[lang]["no_subtitle"])
                            logger.warning(f"زیرنویس برای کاربر {user_id} در دسترس نیست")
                else:
                    format_id = data[2]
                    ydl_opts = {
                        "format": format_id,
                        "outtmpl": f"{temp_dir}/video.%(ext)s",
                        "quiet": True,
                    }
                    if await download_with_yt_dlp(url, ydl_opts, context, query, lang):
                        input_file = f"{temp_dir}/video.mp4" if os.path.exists(f"{temp_dir}/video.mp4") else f"{temp_dir}/video.webm"
                        file_size = os.path.getsize(input_file)
                        if file_size > 500 * 1024 * 1024:
                            await processing_msg.edit_text(LANGUAGES[lang]["file_too_large"])
                            logger.warning(f"فایل برای کاربر {user_id} بیش از حد بزرگ است: {file_size} بایت")
                            return
                        if not check_user_limit(user_id, file_size):
                            await processing_msg.edit_text(LANGUAGES[lang]["limit_reached"])
                            logger.warning(f"کاربر {user_id} در دانلود ویدئو به محدودیت رسید")
                            return

                        update_user_limit(user_id, file_size)
                        if file_size > 49 * 1024 * 1024:
                            output_template = f"{temp_dir}/part_%03d.mp4"
                            subprocess.run([
                                "ffmpeg", "-i", input_file, "-c", "copy", "-f", "segment",
                                "-segment_time", "60", "-segment_size", "49000000", output_template
                            ], check=True, capture_output=True)
                            for part_file in sorted([f for f in os.listdir(temp_dir) if f.startswith("part_")]):
                                part_path = os.path.join(temp_dir, part_file)
                                await query.message.reply_video(video=open(part_path, "rb"))
                                await asyncio.sleep(1)
                                logger.info(f"کاربر {user_id} بخش ویدئو را فرستاد: {part_file}")
                            logger.info(f"کاربر {user_id} ویدئوی یوتیوب را به‌صورت تکه‌تکه دانلود کرد")
                        else:
                            await query.message.reply_video(video=open(input_file, "rb"))
                            logger.info(f"کاربر {user_id} ویدئوی یوتیوب را دانلود کرد")
                        success = True

            elif data[0] == "ig":
                if data[2] == "caption":
                    caption = context.user_data.get("ig_caption", LANGUAGES[lang]["no_subtitle"])
                    await processing_msg.edit_text(f"کپشن:\n{caption}")
                    logger.info(f"کاربر {user_id} کپشن اینستاگرام را درخواست کرد")
                    success = True
                else:
                    media_type = data[2]
                    ydl_opts = {
                        "outtmpl": f"{temp_dir}/media.%(ext)s",
                        "quiet": True,
                        "username": INSTAGRAM_USERNAME,
                        "password": INSTAGRAM_PASSWORD
                    }
                    if await download_with_yt_dlp(url, ydl_opts, context, query, lang):
                        file_path = f"{temp_dir}/media.{media_type}"
                        file_size = os.path.getsize(file_path)
                        if file_size > 500 * 1024 * 1024:
                            await processing_msg.edit_text(LANGUAGES[lang]["file_too_large"])
                            logger.warning(f"فایل برای کاربر {user_id} بیش از حد بزرگ است: {file_size} بایت")
                            return
                        if not check_user_limit(user_id, file_size):
                            await processing_msg.edit_text(LANGUAGES[lang]["limit_reached"])
                            logger.warning(f"کاربر {user_id} در دانلود اینستاگرام به حداقل رسید")
                            return

                        update_user_limit(user_id, file_size)
                        if file_size > 49 * 1024 * 1024:
                            output_template = f"{temp_dir}/part_%03d.mp4"
                            subprocess.run([
                                "ffmpeg", "-i", file_path, "-c", "copy", "-f", "segment",
                                "-segment_time", "60", "-segment_size", "49000000", output_template
                            ], check=True, capture_output=True)
                            for part_file in sorted([f for f in os.listdir(temp_dir) if f.startswith("part_")]):
                                part_path = os.path.join(temp_dir, part_file)
                                if media_type in ["jpg", "jpeg", "png"]:
                                    await query.message.reply_photo(photo=open(part_path, "rb"))
                                else:
                                    await query.message.reply_video(video=open(part_path, "rb"))
                                await asyncio.sleep(1)
                                logger.info(f"کاربر {user_id} بخش اینستاگرام را فرستاد: {part_file}")
                            logger.info(f"کاربر {user_id} مدیای اینستاگرام را به‌صورت تکه‌تکه دانلود کرد")
                        else:
                            if media_type in ["jpg", "jpeg", "png"]:
                                await query.message.reply_photo(photo=open(file_path, "rb"))
                            else:
                                await query.message.reply_video(video=open(file_path, "rb"))
                            logger.info(f"کاربر {user_id} مدیای اینستاگرام را دانلود کرد")
                        success = True

        except yt_dlp.DownloadError as e:
            error_msg = "لینک خصوصی است یا دسترسی محدود دارد."
            if "403" in str(e):
                error_msg = "دسترسی ممنوع (403)."
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(error_msg))
            logger.error(f"خطای دانلود برای کاربر {user_id}: {str(e)}")
        except subprocess.CalledProcessError as e:
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format("خطا در تقسیم فایل"))
            logger.error(f"خطای FFmpeg برای کاربر {user_id}: {str(e)}")
        except Exception as e:
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(str(e)))
            logger.error(f"خطای غیرمنتظره برای کاربر {user_id}: {str(e)}")
        finally:
            if success:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"پوشه موقت کاربر {user_id} پس از موفقیت پاک شد: {temp_dir}")
            else:
                logger.info(f"پوشه موقت کاربر {user_id} به دلیل خطا نگه داشته شد: {temp_dir}")

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    lang = context.user_data.get("language", "fa")
    user_id = str(update.inline_query.from_user.id)

    if not query:
        results = [
            InlineQueryResultArticle(
                id="welcome",
                title="دانلودر YouTube Instagram Download",
                input_message_content=InputTextMessageContent(
                    "لینک را وارد کنید Enter link"
                )
            )
        ]
        await update.inline_query.answer(results)
        return

    try:
        chat_member1 = await context.bot.get_chat_member("@enrgy_m", user_id)
        chat_member2 = await context.bot.get_chat_member("@music_bik", user_id)
        if not (chat_member1.status in ["member", "administrator", "creator"] and
                chat_member2.status in ["member", "administrator", "creator"]):
            results = [
                InlineQueryResultArticle(
                    id="membership",
                    title="لطفاً در کانال‌ها عضو شوید",
                    input_message_content=InputTextMessageContent(
                        LANGUAGES[lang]["join_channels"]
                    )
                )
            ]
            await update.inline_query.answer(results)
            logger.info(f"کاربر {user_id} بدون عضویت درخواست inline کرد")
            return
    except TelegramError as e:
        logger.error(f"خطا در بررسی عضویت برای inline query: {str(e)}")
        return

    if not is_valid_url(query):
        results = [
            InlineQueryResultArticle(
                id="invalid",
                title="لینک نامعتبر",
                input_message_content=InputTextMessageContent(
                    LANGUAGES[lang]["invalid_link"]
                )
            )
        ]
        await update.inline_query.answer(results)
        logger.warning(f"کاربر {user_id} لینک نامعتبر در inline فرستاد: {query}")
        return

    results = [
        InlineQueryResultArticle(
            id="download",
            title="دانلود ویدئو یا صوت",
            input_message_content=InputTextMessageContent(
                f"لینک دریافت شد! برای دانلود به چت ربات بروید: {query}"
            )
        )
    ]
    await update.inline_query.answer(results)
    logger.info(f"کاربر {user_id} لینک معتبر در inline فرستاد: {query}")

# تنظیم سرور aiohttp برای health check و webhook
async def health_check(request):
    memory = psutil.virtual_memory()
    queue_size = request_queue.qsize()
    return web.Response(text=f"OK - Queue: {queue_size}, Free Memory: {memory.available / (1024 * 1024):.2f} MB")

async def webhook(request):
    application = request.app['application']
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return web.Response(text="OK")

async def run_bot(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(MessageHandler(filters.Text() & ~filters.Command(), handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(InlineQueryHandler(inline_query))
    asyncio.create_task(process_queue())
    asyncio.create_task(clean_temp_directories())  # شروع پاک‌سازی دوره‌ای
    await application.initialize()
    logger.info("Application initialized")
    await application.start()
    logger.info("Application started")

async def shutdown(application, runner):
    logger.info("در حال متوقف کردن ربات...")
    await application.stop()
    await application.shutdown()
    await runner.cleanup()
    logger.info("ربات متوقف شد")

async def setup_and_run():
    if not BOT_TOKEN:
        logger.error("توکن ربات مشخص نشده است.")
        raise ValueError("لطفاً BOT_TOKEN را تنظیم کنید.")

    init_db()
    application = Application.builder().token(BOT_TOKEN).read_timeout(1200).write_timeout(1200).connect_timeout(120Republic).build()
    app = web.Application()
    app['application'] = application
    app.router.add_get('/', health_check)
    app.router.add_post('/webhook', webhook)

    webhook_url = "https://particular-capybara-amirgit3-bbc0dbbd.koyeb.app/webhook"
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook تنظیم شد: {webhook_url}")
    except TelegramError as e:
        logger.error(f"خطا در تنظیم Webhook: {str(e)}. به حالت Polling سوئیچ می‌شود.")
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        logger.info("Polling started")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("سرور aiohttp برای health check و webhook روی پورت ۸۰۸۰ شروع شد")
    await run_bot(application)
    return application, runner

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        application, runner = loop.run_until_complete(setup_and_run())
        loop.run_forever()
    except KeyboardInterrupt:
        loop.run_until_complete(shutdown(application, runner))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    except Exception as e:
        logger.error(f"خطای غیرمنتظره: {str(e)}")
        loop.run_until_complete(shutdown(application, runner))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
