import os
import subprocess
import logging
import sqlite3
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, InlineQueryHandler, filters, ContextTypes
from telegram.error import BadRequest
import yt_dlp
from datetime import datetime
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

# تنظیم لاگ‌گیری برای Koyeb
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
        "in_queue": "Your request is in queue. Please wait..."
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
        "in_queue": "درخواست شما در صف قرار داره. لطفاً صبر کنید..."
    },
    # سایر زبان‌ها رو می‌تونی اضافه کنی اگه نیاز داری
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
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info(f"پوشه موقت کاربر {user_id} پاک شد: {temp_dir}")

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

# دانلود غیرهمزمان با yt_dlp
async def download_with_yt_dlp(url, ydl_opts, context, update, lang):
    def progress_hook(d):
        if d['status'] == 'downloading':
            percent = d.get('downloaded_bytes', 0) / d.get('total_bytes', 1) * 100
            if percent:
                asyncio.ensure_future(
                    update.message.reply_text(LANGUAGES[lang]["progress"].format(round(percent, 2)))
                )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.add_progress_hook(progress_hook)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: ydl.download([url]))

# پردازش صف درخواست‌ها
async def process_queue():
    while True:
        try:
            update, context, url, processing_msg = await request_queue.get()
            await handle_request(update, context, url, processing_msg)
            request_queue.task_done()
        except Exception as e:
            logger.error(f"خطا در پردازش صف: {str(e)}")
            await asyncio.sleep(5)

async def handle_request(update, context, url, processing_msg):
    lang = context.user_data.get("language", "fa")
    user_id = str(update.effective_user.id)

    try:
        if "youtube.com" in url or "youtu.be" in url:
            await process_youtube(update, context, url, processing_msg)
        elif "instagram.com" in url:
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
        [InlineKeyboardButton(LANGUAGES[lang]["name"], callback_data=f"lang_{lang}") for lang in LANGUAGES]
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
        bot_id = (await context.bot.get_me()).id
        timeout = 15
        bot_member1 = await asyncio.wait_for(context.bot.get_chat_member("@enrgy_m", bot_id), timeout)
        bot_member2 = await asyncio.wait_for(context.bot.get_chat_member("@music_bik", bot_id), timeout)

        if bot_member1.status not in ["administrator", "creator"] or bot_member2.status not in ["administrator", "creator"]:
            await query.message.reply_text("ربات باید در هر دو کانال ادمین باشد. لطفاً ادمین کنید.")
            return

        chat_member1 = await asyncio.wait_for(context.bot.get_chat_member("@enrgy_m", user_id), timeout)
        chat_member2 = await asyncio.wait_for(context.bot.get_chat_member("@music_bik", user_id), timeout)

        if chat_member1.status in ["member", "administrator", "creator"] and \
           chat_member2.status in ["member", "administrator", "creator"]:
            context.user_data["is_member"] = True
            await query.message.reply_text(LANGUAGES[lang]["membership_ok"])
        else:
            await query.message.reply_text(LANGUAGES[lang]["join_channels"])
    except Exception as e:
        logger.error(f"خطا در بررسی عضویت: {str(e)}")
        await query.message.reply_text(LANGUAGES[lang]["error"].format(str(e)))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    lang = context.user_data.get("language", "fa")

    if not context.user_data.get("is_member", False):
        await update.message.reply_text(LANGUAGES[lang]["join_channels"])
        return

    url = update.message.text
    if not is_valid_url(url):
        await update.message.reply_text(LANGUAGES[lang]["invalid_link"])
        return

    if not check_user_limit(user_id):
        await update.message.reply_text(LANGUAGES[lang]["limit_reached"])
        return

    context.user_data["cancel"] = False
    processing_msg = await update.message.reply_text(
        LANGUAGES[lang]["in_queue"],
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data=f"cancel_{url}")]])
    )
    await request_queue.put((update, context, url, processing_msg))

async def process_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE, url, processing_msg):
    lang = context.user_data.get("language", "fa")
    user_id = str(update.effective_user.id)

    with temp_directory(user_id) as temp_dir:
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
                    keyboard.append([InlineKeyboardButton(f"کیفیت {quality} ({size_mb})", callback_data=f"yt_{url}_{fmt['format_id']}")])
            keyboard.append([InlineKeyboardButton("صوت (mp3)", callback_data=f"yt_audio_{url}_mp3")])
            keyboard.append([InlineKeyboardButton("صوت (m4a)", callback_data=f"yt_audio_{url}_m4a")])
            for sub_lang in subtitles:
                keyboard.append([InlineKeyboardButton(f"زیرنویس ({sub_lang})", callback_data=f"yt_sub_{url}_{sub_lang}")])
            keyboard.append([InlineKeyboardButton("توضیحات ویدئو", callback_data=f"yt_desc_{url}")])
            keyboard.append([InlineKeyboardButton("لغو", callback_data=f"cancel_{url}")])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await processing_msg.edit_text(LANGUAGES[lang]["choose_option"], reply_markup=reply_markup)
        except Exception as e:
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(str(e)))
            logger.error(f"خطا در پردازش یوتیوب: {str(e)}")

async def process_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE, url, processing_msg):
    lang = context.user_data.get("language", "fa")
    user_id = str(update.effective_user.id)

    with temp_directory(user_id) as temp_dir:
        try:
            ydl_opts = {"outtmpl": f"{temp_dir}/media.%(ext)s", "quiet": True, "username": INSTAGRAM_USERNAME, "password": INSTAGRAM_PASSWORD}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                media_type = info.get("ext", "mp4")
                caption = info.get("description", LANGUAGES[lang]["no_subtitle"])
                file_size = info.get("filesize", 0) or 0

            if file_size > 500 * 1024 * 1024:
                await processing_msg.edit_text(LANGUAGES[lang]["file_too_large"])
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
        except Exception as e:
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(str(e)))
            logger.error(f"خطا در پردازش اینستاگرام: {str(e)}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    lang = context.user_data.get("language", "fa")
    user_id = str(query.from_user.id)

    if data[0] == "cancel":
        context.user_data["cancel"] = True
        await query.message.reply_text(LANGUAGES[lang]["cancel"])
        return

    if data[0] in ["check_membership", "settings"]:
        if data[0] == "check_membership":
            await query.message.reply_text("در حال بررسی...")
            await check_membership(update, context)
        elif data[0] == "settings":
            await settings(update, context)
        return

    if not check_user_limit(user_id):
        await query.message.reply_text(LANGUAGES[lang]["limit_reached"])
        return

    url = data[1]
    processing_msg = await query.message.reply_text(LANGUAGES[lang]["processing"])

    with temp_directory(user_id) as temp_dir:
        try:
            if not check_ffmpeg():
                await processing_msg.edit_text(LANGUAGES[lang]["error"].format("FFmpeg نصب نشده است."))
                return

            if data[0] == "yt":
                if data[2] == "desc":
                    description = context.user_data.get("yt_description", LANGUAGES[lang]["no_subtitle"])
                    await processing_msg.edit_text(f"توضیحات ویدئو:\n{description}")
                elif data[2] == "audio":
                    audio_format = data[3]
                    ydl_opts = {"format": "bestaudio", "outtmpl": f"{temp_dir}/audio.%(ext)s", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": audio_format}], "quiet": True}
                    await download_with_yt_dlp(url, ydl_opts, context, query, lang)
                    file_path = f"{temp_dir}/audio.{audio_format}"
                    file_size = os.path.getsize(file_path)
                    if file_size > 500 * 1024 * 1024 or not check_user_limit(user_id, file_size):
                        await processing_msg.edit_text(LANGUAGES[lang]["limit_reached"])
                        return
                    update_user_limit(user_id, file_size)
                    await query.message.reply_audio(audio=open(file_path, "rb"))
                elif data[2] == "sub":
                    sub_lang = data[3]
                    ydl_opts = {"writesubtitles": True, "subtitleslangs": [sub_lang], "outtmpl": f"{temp_dir}/subtitle.%(ext)s", "quiet": True}
                    await download_with_yt_dlp(url, ydl_opts, context, query, lang)
                    subtitle_file = f"{temp_dir}/subtitle.{sub_lang}.vtt"
                    if os.path.exists(subtitle_file):
                        file_size = os.path.getsize(subtitle_file)
                        if file_size > 500 * 1024 * 1024 or not check_user_limit(user_id, file_size):
                            await processing_msg.edit_text(LANGUAGES[lang]["limit_reached"])
                            return
                        update_user_limit(user_id, file_size)
                        await query.message.reply_document(document=open(subtitle_file, "rb"))
                    else:
                        await processing_msg.edit_text(LANGUAGES[lang]["no_subtitle"])
                else:
                    format_id = data[2]
                    ydl_opts = {"format": format_id, "outtmpl": f"{temp_dir}/video.%(ext)s", "quiet": True}
                    await download_with_yt_dlp(url, ydl_opts, context, query, lang)
                    input_file = f"{temp_dir}/video.mp4" if os.path.exists(f"{temp_dir}/video.mp4") else f"{temp_dir}/video.webm"
                    file_size = os.path.getsize(input_file)
                    if file_size > 500 * 1024 * 1024 or not check_user_limit(user_id, file_size):
                        await processing_msg.edit_text(LANGUAGES[lang]["file_too_large" if file_size > 500 * 1024 * 1024 else "limit_reached"])
                        return
                    update_user_limit(user_id, file_size)
                    if file_size > 49 * 1024 * 1024:
                        output_template = f"{temp_dir}/part_%03d.mp4"
                        subprocess.run(["ffmpeg", "-i", input_file, "-c", "copy", "-f", "segment", "-segment_time", "60", "-segment_size", "49000000", output_template], check=True)
                        for part_file in sorted([f for f in os.listdir(temp_dir) if f.startswith("part_")]):
                            part_path = os.path.join(temp_dir, part_file)
                            await query.message.reply_video(video=open(part_path, "rb"))
                            await asyncio.sleep(1)
                    else:
                        await query.message.reply_video(video=open(input_file, "rb"))

            elif data[0] == "ig":
                if data[2] == "caption":
                    caption = context.user_data.get("ig_caption", LANGUAGES[lang]["no_subtitle"])
                    await processing_msg.edit_text(f"کپشن:\n{caption}")
                else:
                    media_type = data[2]
                    ydl_opts = {"outtmpl": f"{temp_dir}/media.%(ext)s", "quiet": True, "username": INSTAGRAM_USERNAME, "password": INSTAGRAM_PASSWORD}
                    await download_with_yt_dlp(url, ydl_opts, context, query, lang)
                    file_path = f"{temp_dir}/media.{media_type}"
                    file_size = os.path.getsize(file_path)
                    if file_size > 500 * 1024 * 1024 or not check_user_limit(user_id, file_size):
                        await processing_msg.edit_text(LANGUAGES[lang]["file_too_large" if file_size > 500 * 1024 * 1024 else "limit_reached"])
                        return
                    update_user_limit(user_id, file_size)
                    if file_size > 49 * 1024 * 1024:
                        output_template = f"{temp_dir}/part_%03d.mp4"
                        subprocess.run(["ffmpeg", "-i", file_path, "-c", "copy", "-f", "segment", "-segment_time", "60", "-segment_size", "49000000", output_template], check=True)
                        for part_file in sorted([f for f in os.listdir(temp_dir) if f.startswith("part_")]):
                            part_path = os.path.join(temp_dir, part_file)
                            if media_type in ["jpg", "jpeg", "png"]:
                                await query.message.reply_photo(photo=open(part_path, "rb"))
                            else:
                                await query.message.reply_video(video=open(part_path, "rb"))
                            await asyncio.sleep(1)
                    else:
                        if media_type in ["jpg", "jpeg", "png"]:
                            await query.message.reply_photo(photo=open(file_path, "rb"))
                        else:
                            await query.message.reply_video(video=open(file_path, "rb"))

        except Exception as e:
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(str(e)))
            logger.error(f"خطا در پردازش دکمه: {str(e)}")

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    lang = context.user_data.get("language", "fa")
    user_id = str(update.inline_query.from_user.id)

    if not query:
        results = [InlineQueryResultArticle(id="welcome", title="دانلودر YouTube Instagram", input_message_content=InputTextMessageContent("لینک را وارد کنید"))]
        await update.inline_query.answer(results)
        return

    try:
        chat_member1 = await context.bot.get_chat_member("@enrgy_m", user_id)
        chat_member2 = await context.bot.get_chat_member("@music_bik", user_id)
        if not (chat_member1.status in ["member", "administrator", "creator"] and
                chat_member2.status in ["member", "administrator", "creator"]):
            results = [InlineQueryResultArticle(id="membership", title="عضویت در کانال", input_message_content=InputTextMessageContent(LANGUAGES[lang]["join_channels"]))]
            await update.inline_query.answer(results)
            return
    except Exception:
        return

    if not is_valid_url(query):
        results = [InlineQueryResultArticle(id="invalid", title="لینک نامعتبر", input_message_content=InputTextMessageContent(LANGUAGES[lang]["invalid_link"]))]
        await update.inline_query.answer(results)
        return

    results = [InlineQueryResultArticle(id="download", title="دانلود", input_message_content=InputTextMessageContent(f"لینک دریافت شد: {query}"))]
    await update.inline_query.answer(results)

# تنظیم سرور aiohttp
async def health_check(request):
    return web.Response(text="OK")

async def run_bot():
    if not BOT_TOKEN:
        logger.error("توکن ربات مشخص نشده است.")
        raise ValueError("لطفاً BOT_TOKEN را تنظیم کنید.")

    init_db()
    application = Application.builder().token(BOT_TOKEN).read_timeout(20).write_timeout(20).connect_timeout(20).build()

    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(MessageHandler(filters.Text() & ~filters.Command(), handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(InlineQueryHandler(inline_query))

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
