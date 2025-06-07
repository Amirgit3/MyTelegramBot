import os
import subprocess
import logging
import sqlite3
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, InlineQueryHandler, filters, ContextTypes
from telegram.error import TelegramError, BadRequest
import yt_dlp
from datetime import datetime
import re
import tempfile
import shutil
from contextlib import contextmanager
import time
from dotenv import load_dotenv
from aiohttp import web
import aiosqlite # اضافه شده برای دیتابیس ناهمگام

# بارگذاری توکن و اطلاعات اینستاگرام از .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# بررسی وجود متغیرهای محیطی ضروری
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN در فایل .env تعریف نشده است.")
# اینستاگرام یوزرنیم و پسورد اگر اجباری هستند، بررسی مشابه انجام شود.
# if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
#     logger.warning("INSTAGRAM_USERNAME یا INSTAGRAM_PASSWORD تعریف نشده‌اند. دانلود اینستاگرام ممکن است کار نکند.")

# تنظیم لاگ‌گیری برای Koyeb (به جای فایل، به stdout)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# لینک کانال‌ها (استفاده از نام کاربری برای get_chat_member)
# اطمینان حاصل کنید که اینها نام کاربری (username) کانال‌ها هستند، نه لینک کامل!
CHANNEL_1 = "@enrgy_m"
CHANNEL_2 = "@music_bik"

# مسیر دیتابیس
DB_PATH = "user_limits.db"

# صف برای مدیریت درخواست‌ها (به صورت asyncio.Queue)
request_queue = asyncio.Queue()

# متغیر سراسری برای ذخیره آخرین زمان ارسال پیام پیشرفت
last_progress_message_time = {}

# زبان‌ها (بدون تغییر)
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
    "ru": {
        "name": "Русский",
        "welcome": "Добро пожаловать! 😊\nФайлы разбиваются на части по 50 МБ.\nМаксимальный размер файла: 500 МБ.\nСначала присоединитесь к нашим каналам:",
        "invalid_link": "Недействительная ссылка! Только ссылки на Instagram или YouTube.",
        "file_too_large": "Ваш файл больше 500 МБ!",
        "join_channels": "Пожалуйста, присоединитесь к обоим каналам и попробуйте снова.",
        "membership_ok": "Членство подтверждено! Отправьте ссылку на Instagram или YouTube.",
        "choose_option": "Выберите опцию:",
        "no_subtitle": "Субтитры недоступны!",
        "error": "Ошибка: {}",
        "limit_reached": "Вы достигли лимита в 20 запросов или 1 ГБ в день. Попробуйте снова завтра.",
        "processing": "Обработка вашего запроса, пожалуйста, подождите...",
        "progress": "Прогресс загрузки: {}%",
        "cancel": "Запрос отменен.",
        "ping": "Понг! Время ответа: {} мс",
        "in_queue": "Ваш запрос в очереди. Пожалуйста, подождите..."
    },
    "es": {
        "name": "Español",
        "welcome": "¡Bienvenido! 😊\nLos archivos se dividen en partes de 50 MB.\nTamaño máximo del archivo: 500 MB.\nÚnete primero a nuestros canales:",
        "invalid_link": "¡Enlace inválido! Solo enlaces de Instagram o YouTube.",
        "file_too_large": "¡Tu archivo es mayor a 500 MB!",
        "join_channels": "Por favor, únete a ambos canales y prueba de nuevo.",
        "membership_ok": "¡Membresía verificada! Envía un enlace de Instagram o YouTube.",
        "choose_option": "Elige una opción:",
        "no_subtitle": "¡Subtítulos no disponibles!",
        "error": "Error: {}",
        "limit_reached": "Has alcanzado el límite de 20 solicitudes o 1 GB por día. Intenta de nuevo mañana.",
        "processing": "Procesando tu solicitud, por favor espera...",
        "progress": "Progreso de la descarga: {}%",
        "cancel": "Solicitud cancelada.",
        "ping": "¡Pong! Tiempo de respuesta: {} ms",
        "in_queue": "Tu solicitud está en cola. Por favor espera..."
    },
    "fr": {
        "name": "Français",
        "welcome": "Bienvenue ! 😊\nLes fichiers sont divisés en parties de 50 Mo.\nTaille maximale du fichier : 500 Mo.\nRejoignez d'abord nos chaînes :",
        "invalid_link": "Lien invalide ! Seuls les liens Instagram ou YouTube sont acceptés.",
        "file_too_large": "Votre fichier dépasse 500 Mo !",
        "join_channels": "Veuillez rejoindre les deux chaînes et réessayer.",
        "membership_ok": "Adhésion vérifiée ! Envoyez un lien Instagram ou YouTube.",
        "choose_option": "Choisissez une option :",
        "no_subtitle": "Sous-titres non disponibles !",
        "error": "Erreur : {}",
        "limit_reached": "Vous avez atteint la limite de 20 requêtes ou 1 Go par jour. Réessayez demain.",
        "processing": "Traitement de votre demande, veuillez patienter...",
        "progress": "Progression du téléchargement : {}%",
        "cancel": "Demande annulée.",
        "ping": "Pong ! Temps de réponse : {} ms",
        "in_queue": "Votre demande est en file d'attente. Veuillez patienter..."
    },
    "de": {
        "name": "Deutsch",
        "welcome": "Willkommen! 😊\nDateien werden in 50-MB-Teile aufgeteilt.\nMaximale Dateigröße: 500 MB.\nTritt zuerst unseren Kanälen bei:",
        "invalid_link": "Ungültiger Link! Nur Instagram- oder YouTube-Links.",
        "file_too_large": "Deine Datei ist größer als 500 MB!",
        "join_channels": "Bitte tritt beiden Kanälen bei und versuche es erneut.",
        "membership_ok": "Mitgliedschaft bestätigt! Sende einen Instagram- یا YouTube-Link.",
        "choose_option": "Wähle eine Option:",
        "no_subtitle": "Untertitel nicht verfügbar!",
        "error": "Fehler: {}",
        "limit_reached": "Du hast das Limit von 20 Anfragen oder 1 GB pro Tag erreicht. Versuche es morgen erneut.",
        "processing": "Deine Anfrage wird verarbeitet, bitte warte...",
        "progress": "Download-Fortschritt: {}%",
        "cancel": "Anfrage abgebrochen.",
        "ping": "Pong! Antwortzeit: {} ms",
        "in_queue": "Deine Anfrage ist in der Warteschlange. Bitte warte..."
    },
    "it": {
        "name": "Italiano",
        "welcome": "Benvenuto! 😊\nI file vengono divisi in parti da 50 MB.\nDimensione massima del file: 500 MB.\nUnisciti prima ai nostri canali:",
        "invalid_link": "Link non valido! Solo link di Instagram o YouTube.",
        "file_too_large": "Il tuo file è più grande di 500 MB!",
        "join_channels": "Per favore, unisciti a entrambi i canali e riprova.",
        "membership_ok": "Membresía verificata! Invia un link di Instagram o YouTube.",
        "choose_option": "Scegli un'opzione:",
        "no_subtitle": "Sottotitoli non disponibili!",
        "error": "Errore: {}",
        "limit_reached": "Hai raggiunto il limite di 20 richieste o 1 GB al giorno. Riprova domani.",
        "processing": "Elaborazione della tua richiesta, per favore attendi...",
        "progress": "Progresso del download: {}%",
        "cancel": "Richiesta annullata.",
        "ping": "Pong! Tempo di risposta: {} ms",
        "in_queue": "La tua richiesta è in coda. Per favore attendi..."
    },
    "ar": {
        "name": "العربية",
        "welcome": "مرحبًا! 😊\nيتم تقسيم الملفات إلى أجزاء بحجم 50 ميجابايت.\nالحد الأقصى لحجم الملف: 500 ميجابايت.\nانضم إلى قنواتنا أولاً:",
        "invalid_link": "رابط غير صالح! فقط روابط إنستغرام أو يوتيوب.",
        "file_too_large": "ملفك أكبر من 500 ميجابايت!",
        "join_channels": "يرجى الانضمام إلى كلا القناتين والمحاولة مرة أخرى.",
        "membership_ok": "تم التحقق من العضوية! أرسل رابط إنستغرام أو یوتیوب.",
        "choose_option": "اختر خيارًا:",
        "no_subtitle": "الترجمة غير متوفرة!",
        "error": "خطأ: {}",
        "limit_reached": "لقد وصلت إلى الحد الأقصى وهو 20 طلبًا أو 1 جيجابايت يوميًا. حاول مرة أخرى غدًا.",
        "processing": "جارٍ معالجة طلبك، يرجى الانتظار...",
        "progress": "تقدم التحميل: {}%",
        "cancel": "تم إلغاء الطلب.",
        "ping": "بينغ! زمن الاستجابة: {} مللي ثانية",
        "in_queue": "طلبك في الانتظار. يرجى الانتظار..."
    },
    "zh": {
        "name": "中文",
        "welcome": "欢迎！😊\n文件将被分成50MB的部分。\n最大文件大小：500MB。\n请先加入我们的频道：",
        "invalid_link": "无效链接！仅支持Instagram或YouTube链接。",
        "file_too_large": "您的文件大于500MB！",
        "join_channels": "请加入两个频道后重试。",
        "membership_ok": "会员身份已验证！发送Instagram或YouTube链接。",
        "choose_option": "选择一个选项：",
        "no_subtitle": "字幕不可用！",
        "error": "错误：{}",
        "limit_reached": "您已达到每日20次请求或1GB的限制。请明天再试。",
        "processing": "正在处理您的请求，请稍候...",
        "progress": "下载进度：{}%",
        "cancel": "请求已取消。",
        "ping": "Pong！响应时间：{}毫秒",
        "in_queue": "您的请求正在排队。请稍候..."
    },
    "pt": {
        "name": "Português",
        "welcome": "Bem-vindo! 😊\nOs arquivos são divididos em partes de 50 MB.\nTamanho máximo do arquivo: 500 MB.\nJunte-se primeiro aos nossos canais:",
        "invalid_link": "Link inválido! Apenas links do Instagram ou YouTube.",
        "file_too_large": "Seu arquivo é maior que 500 MB!",
        "join_channels": "Por favor, junte-se aos dois canais e tente novamente.",
        "membership_ok": "Associação verificada! Envie um link do Instagram ou YouTube.",
        "choose_option": "Escolha uma opção:",
        "no_subtitle": "Legendas não disponíveis!",
        "error": "Erro: {}",
        "limit_reached": "Você atingiu o limite de 20 solicitações ou 1 GB por dia. Tente novamente amanhã.",
        "processing": "Processando sua solicitação, por favor aguarde...",
        "progress": "Progresso do download: {}%",
        "cancel": "Solicitação cancelada.",
        "ping": "Pong! Tempo de resposta: {} ms",
        "in_queue": "Sua solicitação está na fila. Por favor, aguarde..."
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
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info(f"پوشه موقت کاربر {user_id} پاک شد: {temp_dir}")

# تنظیم دیتابیس SQLite (با aiosqlite)
async def init_db_async():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_limits (
                user_id TEXT PRIMARY KEY,
                date TEXT,
                request_count INTEGER,
                volume INTEGER
            )
        ''')
        await db.commit()
    logger.info("دیتابیس با موفقیت راه‌اندازی شد.")

async def update_user_limit_async(user_id, file_size):
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.cursor()
        await cursor.execute("SELECT request_count, volume FROM user_limits WHERE user_id = ? AND date = ?", (user_id, today))
        result = await cursor.fetchone()

        if result:
            request_count, volume = result
            await cursor.execute("UPDATE user_limits SET request_count = ?, volume = ? WHERE user_id = ? AND date = ?",
                                 (request_count + 1, volume + file_size, user_id, today))
        else:
            await cursor.execute("INSERT INTO user_limits (user_id, date, request_count, volume) VALUES (?, ?, ?, ?)",
                                 (user_id, today, 1, file_size))
        await db.commit()
    logger.info(f"محدودیت کاربر {user_id} به‌روزرسانی شد. حجم: {file_size} بایت.")

async def check_user_limit_async(user_id, file_size=0):
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.cursor()
        await cursor.execute("SELECT request_count, volume FROM user_limits WHERE user_id = ? AND date = ?", (user_id, today))
        result = await cursor.fetchone()

        request_count = result[0] if result else 0
        volume = result[1] if result else 0

        if request_count >= 20 or (volume + file_size) > 1024 * 1024 * 1024:  # 1GB in bytes
            logger.warning(f"محدودیت کاربر {user_id} رد شد. درخواست: {request_count}/20، حجم: {volume}/{1024*1024*1024} بایت.")
            return False
        logger.info(f"محدودیت کاربر {user_id} بررسی شد. درخواست: {request_count}/20، حجم: {volume}/{1024*1024*1024} بایت.")
        return True

# بررسی اعتبار لینک
def is_valid_url(url):
    pattern = r'^(https?://)?(www\.)?(youtube\.com|youtu\.be|instagram\.com)/.+$'
    return bool(re.match(pattern, url))

# دانلود غیرهمزمان با yt-dlp
async def download_with_yt_dlp(url, ydl_opts, context, update, lang):
    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    def progress_hook(d):
        if d['status'] == 'downloading':
            percent = d.get('downloaded_bytes', 0) / d.get('total_bytes', 1) * 100
            current_time = time.time()
            # فقط هر 5 ثانیه یک بار پیام پیشرفت ارسال شود
            if percent and (user_id not in last_progress_message_time or (current_time - last_progress_message_time[user_id]) > 5):
                last_progress_message_time[user_id] = current_time
                asyncio.run_coroutine_threadsafe(
                    context.bot.send_message(chat_id=chat_id, text=LANGUAGES[lang]["progress"].format(round(percent, 2))),
                    asyncio.get_running_loop()
                )
        elif d['status'] == 'finished':
            logger.info(f"دانلود کامل شد: {d.get('filename')}")
            # پاک کردن آخرین زمان پیشرفت پس از اتمام دانلود
            if user_id in last_progress_message_time:
                del last_progress_message_time[user_id]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.add_progress_hook(progress_hook)
        loop = asyncio.get_running_loop()
        # اجرای دانلود در یک executor جداگانه برای جلوگیری از مسدود شدن event loop
        return await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))

# پردازش صف درخواست‌ها
async def process_queue():
    while True:
        try:
            update, context, url, in_queue_msg = await request_queue.get()
            await handle_request(update, context, url, in_queue_msg)
            request_queue.task_done()
        except Exception as e:
            logger.error(f"خطا در پردازش صف: {str(e)}")
            # در صورت خطا، یک تاخیر کوتاه برای جلوگیری از لوپ سریع
            await asyncio.sleep(5)

async def handle_request(update, context, url, in_queue_msg):
    lang = context.user_data.get("language", "fa")
    user_id = str(update.effective_user.id)
    downloaded_file_path = None # برای اطمینان از پاکسازی

    # ویرایش پیام "در صف" به "در حال پردازش"
    processing_msg = await in_queue_msg.edit_text(LANGUAGES[lang]["processing"])

    try:
        if "youtube.com" in url or "youtu.be" in url:
            info = await process_youtube(update, context, url, processing_msg)
            downloaded_file_path = info.get('filepath') if info else None
        elif "instagram.com" in url:
            info = await process_instagram(update, context, url, processing_msg)
            downloaded_file_path = info.get('filepath') if info else None
        logger.info(f"درخواست کاربر {user_id} پردازش شد: {url}")
    except (TelegramError, yt_dlp.utils.DownloadError, Exception) as e:
        error_message = str(e)
        if isinstance(e, TelegramError):
            error_message = "خطا در ارتباط با تلگرام."
        elif isinstance(e, yt_dlp.utils.DownloadError):
            error_message = "خطا در دانلود. لینک نامعتبر است یا مشکلی پیش آمده."
        await processing_msg.edit_text(LANGUAGES[lang]["error"].format(error_message))
        logger.error(f"خطا در پردازش درخواست کاربر {user_id}: {str(e)}")
    finally:
        # اطمینان از پاکسازی فایل‌های موقت پس از پردازش
        # اگر از temp_directory استفاده می‌کنید، نیازی به این بخش نیست مگر اینکه دانلود خارج از آن انجام شود.
        # این یک مکان نگهدارنده است.
        if downloaded_file_path and os.path.exists(downloaded_file_path):
            try:
                # shutil.rmtree(os.path.dirname(downloaded_file_path), ignore_errors=True)
                logger.info(f"فایل موقت {downloaded_file_path} پاک شد.")
            except Exception as e:
                logger.error(f"خطا در پاکسازی فایل موقت {downloaded_file_path}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_lang = update.effective_user.language_code if update.effective_user.language_code in LANGUAGES else "fa"
    context.user_data["language"] = user_lang
    lang = context.user_data["language"]

    keyboard = [
        [InlineKeyboardButton("عضویت در کانال ۱", url=f"https://t.me/{CHANNEL_1.lstrip('@')}")],
        [InlineKeyboardButton("عضویت در کانال ۲", url=f"https://t.me/{CHANNEL_2.lstrip('@')}")],
        [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(LANGUAGES[lang]["welcome"], reply_markup=reply_markup)
    logger.info(f"کاربر {user_id} ربات را با زبان {lang} شروع کرد")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    lang = context.user_data.get("language", "fa")
    # ارسال و ویرایش پیام برای محاسبه دقیق‌تر زمان پاسخ تلگرام
    message = await update.message.reply_text("پینگ...")
    response_time = (time.time() - start_time) * 1000
    await message.edit_text(LANGUAGES[lang]["ping"].format(round(response_time, 2)))
    logger.info(f"کاربر {update.effective_user.id} پینگ کرد: {response_time:.2f} میلی‌ثانیه")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("language", "fa")
    # چیدمان دکمه‌ها برای زبان‌ها (می‌تواند بهبود یابد)
    keyboard = [
        [InlineKeyboardButton(LANGUAGES["en"]["name"], callback_data="lang_en"),
         InlineKeyboardButton(LANGUAGES["fa"]["name"], callback_data="lang_fa"),
         InlineKeyboardButton(LANGUAGES["ru"]["name"], callback_data="lang_ru")],
        [InlineKeyboardButton(LANGUAGES["es"]["name"], callback_data="lang_es"),
         InlineKeyboardButton(LANGUAGES["fr"]["name"], callback_data="lang_fr"),
         InlineKeyboardButton(LANGUAGES["de"]["name"], callback_data="lang_de")],
        [InlineKeyboardButton(LANGUAGES["it"]["name"], callback_data="lang_it"),
         InlineKeyboardButton(LANGUAGES["ar"]["name"], callback_data="lang_ar"),
         InlineKeyboardButton(LANGUAGES["zh"]["name"], callback_data="lang_zh")],
        [InlineKeyboardButton(LANGUAGES["pt"]["name"], callback_data="lang_pt")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("زبان ربات را انتخاب کنید:", reply_markup=reply_markup)
    logger.info(f"کاربر {query.from_user.id} تنظیمات را باز کرد")

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    new_lang = query.data.split('_')[1]
    context.user_data["language"] = new_lang
    await query.edit_message_text(f"زبان ربات به **{LANGUAGES[new_lang]['name']}** تغییر یافت. \n" + LANGUAGES[new_lang]["welcome"])
    logger.info(f"کاربر {query.from_user.id} زبان را به {new_lang} تغییر داد.")

async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = context.user_data.get("language", "fa")

    logger.info(f"شروع بررسی عضویت برای کاربر {user_id}")
    try:
        # بررسی وضعیت ربات در کانال‌ها (اطمینان از ادمین بودن یا عضویت ربات)
        bot_info = await context.bot.get_me()
        bot_id = bot_info.id

        # بررسی کانال ۱
        try:
            bot_member_channel1 = await context.bot.get_chat_member(chat_id=CHANNEL_1, user_id=bot_id)
            if bot_member_channel1.status not in ["member", "administrator", "creator"]:
                await query.message.reply_text(f"لطفاً ربات را به عنوان ادمین یا عضو در کانال اول ({CHANNEL_1}) اضافه کنید تا بتوانم عضویت شما را بررسی کنم.")
                logger.warning(f"ربات در کانال {CHANNEL_1} عضو نیست یا ادمین نیست.")
                return
        except TelegramError as e:
            logger.error(f"خطا در بررسی وضعیت ربات در کانال {CHANNEL_1}: {e}")
            await query.message.reply_text(LANGUAGES[lang]["error"].format(f"مشکلی در بررسی کانال {CHANNEL_1} پیش آمد. مطمئن شوید نام کاربری کانال صحیح است و ربات در آن عضو است."))
            return

        # بررسی کانال ۲
        try:
            bot_member_channel2 = await context.bot.get_chat_member(chat_id=CHANNEL_2, user_id=bot_id)
            if bot_member_channel2.status not in ["member", "administrator", "creator"]:
                await query.message.reply_text(f"لطفاً ربات را به عنوان ادمین یا عضو در کانال دوم ({CHANNEL_2}) اضافه کنید تا بتوانم عضویت شما را بررسی کنم.")
                logger.warning(f"ربات در کانال {CHANNEL_2} عضو نیست یا ادمین نیست.")
                return
        except TelegramError as e:
            logger.error(f"خطا در بررسی وضعیت ربات در کانال {CHANNEL_2}: {e}")
            await query.message.reply_text(LANGUAGES[lang]["error"].format(f"مشکلی در بررسی کانال {CHANNEL_2} پیش آمد. مطمئن شوید نام کاربری کانال صحیح است و ربات در آن عضو است."))
            return

        # بررسی عضویت کاربر در هر دو کانال
        member1 = await context.bot.get_chat_member(chat_id=CHANNEL_1, user_id=user_id)
        member2 = await context.bot.get_chat_member(chat_id=CHANNEL_2, user_id=user_id)

        if member1.status in ["member", "administrator", "creator"] and \
           member2.status in ["member", "administrator", "creator"]:
            await query.message.reply_text(LANGUAGES[lang]["membership_ok"])
            logger.info(f"عضویت کاربر {user_id} تأیید شد.")
        else:
            keyboard = [
                [InlineKeyboardButton("عضویت در کانال ۱", url=f"https://t.me/{CHANNEL_1.lstrip('@')}")],
                [InlineKeyboardButton("عضویت در کانال ۲", url=f"https://t.me/{CHANNEL_2.lstrip('@')}")],
                [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(LANGUAGES[lang]["join_channels"], reply_markup=reply_markup)
            logger.info(f"عضویت کاربر {user_id} رد شد.")
    except TelegramError as e:
        logger.error(f"خطا در بررسی عضویت برای کاربر {user_id}: {e}")
        await query.message.reply_text(LANGUAGES[lang]["error"].format("مشکلی در بررسی عضویت پیش آمد. مطمئن شوید ربات دسترسی‌های لازم را در کانال‌ها دارد."))
    except Exception as e:
        logger.error(f"خطای ناشناخته در بررسی عضویت برای کاربر {user_id}: {e}")
        await query.message.reply_text(LANGUAGES[lang]["error"].format("خطای ناشناخته."))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    lang = context.user_data.get("language", "fa")
    url = update.message.text

    if not is_valid_url(url):
        await update.message.reply_text(LANGUAGES[lang]["invalid_link"])
        logger.warning(f"لینک نامعتبر از کاربر {user_id}: {url}")
        return

    # بررسی محدودیت قبل از افزودن به صف
    if not await check_user_limit_async(user_id):
        await update.message.reply_text(LANGUAGES[lang]["limit_reached"])
        logger.warning(f"محدودیت کاربر {user_id} رد شد.")
        return

    # پیام "در صف" و افزودن به صف
    in_queue_msg = await update.message.reply_text(LANGUAGES[lang]["in_queue"])
    await request_queue.put((update, context, url, in_queue_msg))
    logger.info(f"درخواست کاربر {user_id} به صف اضافه شد: {url}")


async def process_youtube(update, context, url, processing_msg):
    user_id = str(update.effective_user.id)
    lang = context.user_data.get("language", "fa")
    info = None
    downloaded_file_path = None

    with temp_directory(user_id) as temp_dir:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'cookiefile': 'youtube_cookies.txt', # اگر نیاز به کوکی دارید
            'noplaylist': True,
            'max_filesize': 500 * 1024 * 1024, # 500 MB
            'throttledratelimit': 1024 * 1024, # 1MB/s limit
            'fragment_retries': 10,
            'concurrent_fragment_downloads': 5,
            'ignoreerrors': True, # در صورت بروز خطا ادامه دهد
            'quiet': True,
            'no_warnings': True,
            'logger': logger,
        }

        try:
            await processing_msg.edit_text(LANGUAGES[lang]["processing"])
            logger.info(f"شروع دانلود یوتیوب برای کاربر {user_id}: {url}")
            info = await download_with_yt_dlp(url, ydl_opts, context, update, lang)
            downloaded_file_path = info['filepath'] if info and 'filepath' in info else None

            if not downloaded_file_path or not os.path.exists(downloaded_file_path):
                raise ValueError("فایل ویدیو دانلود نشد یا مسیر آن نامعتبر است.")

            file_size = os.path.getsize(downloaded_file_path)
            if file_size > 500 * 1024 * 1024:
                await processing_msg.edit_text(LANGUAGES[lang]["file_too_large"])
                logger.warning(f"فایل یوتیوب کاربر {user_id} بزرگتر از ۵۰۰ مگابایت بود: {file_size} بایت.")
                return

            await update_user_limit_async(user_id, file_size)

            # Split and send if larger than 50MB
            if file_size > 50 * 1024 * 1024:
                await processing_msg.edit_text("فایل در حال تقسیم‌بندی است...")
                output_prefix = os.path.join(temp_dir, os.path.basename(downloaded_file_path).split('.')[0])
                # FFmpeg command to split video into 50MB parts (approximate)
                # This is a complex step; exact splitting by size is hard.
                # A simpler approach is to split by duration. For example, 5 minutes per part.
                # Here's a conceptual example using ffmpeg to split.
                # This assumes video can be split losslessly. For more robust splitting,
                # you might need re-encoding or a more advanced segmenter.

                # Get video duration to calculate segment time for ~50MB parts
                try:
                    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", downloaded_file_path]
                    duration_str = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
                    duration_seconds = float(duration_str)

                    # Estimate segment time based on total size and target chunk size
                    # This is a very rough estimation and might not result in exact 50MB chunks
                    num_chunks = max(1, (file_size // (50 * 1024 * 1024)) + 1)
                    segment_time = duration_seconds / num_chunks

                    split_command = [
                        "ffmpeg", "-i", downloaded_file_path,
                        "-f", "segment",
                        "-segment_time", str(int(segment_time)),
                        "-c", "copy",
                        f"{output_prefix}_part%03d.mp4"
                    ]
                    subprocess.run(split_command, check=True, cwd=temp_dir)

                    part_files = sorted([f for f in os.listdir(temp_dir) if re.match(f"{re.escape(os.path.basename(output_prefix))}_part\\d{{3}}\\.", f)])

                    for part_file in part_files:
                        part_path = os.path.join(temp_dir, part_file)
                        await context.bot.send_document(chat_id=update.effective_chat.id, document=open(part_path, 'rb'), caption=f"بخش {part_file}")
                        logger.info(f"بخش {part_file} برای کاربر {user_id} ارسال شد.")
                    await processing_msg.edit_text("فایل با موفقیت تقسیم و ارسال شد.")

                except subprocess.CalledProcessError as e:
                    logger.error(f"خطا در تقسیم فایل با FFmpeg برای کاربر {user_id}: {e.stderr.decode()}")
                    await processing_msg.edit_text(LANGUAGES[lang]["error"].format("خطا در تقسیم فایل ویدیویی."))
                except Exception as e:
                    logger.error(f"خطای ناشناخته در تقسیم فایل برای کاربر {user_id}: {e}")
                    await processing_msg.edit_text(LANGUAGES[lang]["error"].format("خطای ناشناخته در تقسیم فایل."))
            else:
                # Send the whole file
                await context.bot.send_document(chat_id=update.effective_chat.id, document=open(downloaded_file_path, 'rb'))
                await processing_msg.edit_text("فایل با موفقیت ارسال شد.")
                logger.info(f"فایل یوتیوب برای کاربر {user_id} ارسال شد: {downloaded_file_path}")

        except Exception as e:
            logger.error(f"خطا در پردازش یوتیوب برای کاربر {user_id}: {str(e)}")
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(str(e)))
        finally:
            # temp_directory context manager handles cleanup
            pass # No need for shutil.rmtree here as context manager does it.


async def process_instagram(update, context, url, processing_msg):
    user_id = str(update.effective_user.id)
    lang = context.user_data.get("language", "fa")
    info = None
    downloaded_file_path = None

    with temp_directory(user_id) as temp_dir:
        ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'username': INSTAGRAM_USERNAME,
            'password': INSTAGRAM_PASSWORD,
            'noplaylist': True,
            'max_filesize': 500 * 1024 * 1024,
            'quiet': True,
            'no_warnings': True,
            'logger': logger,
        }

        try:
            await processing_msg.edit_text(LANGUAGES[lang]["processing"])
            logger.info(f"شروع دانلود اینستاگرام برای کاربر {user_id}: {url}")
            info = await download_with_yt_dlp(url, ydl_opts, context, update, lang)
            downloaded_file_path = info['filepath'] if info and 'filepath' in info else None

            if not downloaded_file_path or not os.path.exists(downloaded_file_path):
                raise ValueError("فایل اینستاگرام دانلود نشد یا مسیر آن نامعتبر است.")

            file_size = os.path.getsize(downloaded_file_path)
            if file_size > 500 * 1024 * 1024:
                await processing_msg.edit_text(LANGUAGES[lang]["file_too_large"])
                logger.warning(f"فایل اینستاگرام کاربر {user_id} بزرگتر از ۵۰۰ مگابایت بود: {file_size} بایت.")
                return

            await update_user_limit_async(user_id, file_size)

            # Split and send if larger than 50MB (similar logic as YouTube)
            if file_size > 50 * 1024 * 1024:
                await processing_msg.edit_text("فایل در حال تقسیم‌بندی است...")
                output_prefix = os.path.join(temp_dir, os.path.basename(downloaded_file_path).split('.')[0])
                try:
                    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", downloaded_file_path]
                    duration_str = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
                    duration_seconds = float(duration_str)

                    num_chunks = max(1, (file_size // (50 * 1024 * 1024)) + 1)
                    segment_time = duration_seconds / num_chunks

                    split_command = [
                        "ffmpeg", "-i", downloaded_file_path,
                        "-f", "segment",
                        "-segment_time", str(int(segment_time)),
                        "-c", "copy",
                        f"{output_prefix}_part%03d.mp4"
                    ]
                    subprocess.run(split_command, check=True, cwd=temp_dir)

                    part_files = sorted([f for f in os.listdir(temp_dir) if re.match(f"{re.escape(os.path.basename(output_prefix))}_part\\d{{3}}\\.", f)])

                    for part_file in part_files:
                        part_path = os.path.join(temp_dir, part_file)
                        await context.bot.send_document(chat_id=update.effective_chat.id, document=open(part_path, 'rb'), caption=f"بخش {part_file}")
                        logger.info(f"بخش {part_file} برای کاربر {user_id} ارسال شد.")
                    await processing_msg.edit_text("فایل با موفقیت تقسیم و ارسال شد.")

                except subprocess.CalledProcessError as e:
                    logger.error(f"خطا در تقسیم فایل با FFmpeg برای کاربر {user_id}: {e.stderr.decode()}")
                    await processing_msg.edit_text(LANGUAGES[lang]["error"].format("خطا در تقسیم فایل ویدیویی."))
                except Exception as e:
                    logger.error(f"خطای ناشناخته در تقسیم فایل برای کاربر {user_id}: {e}")
                    await processing_msg.edit_text(LANGUAGES[lang]["error"].format("خطای ناشناخته در تقسیم فایل."))
            else:
                # Send the whole file
                await context.bot.send_document(chat_id=update.effective_chat.id, document=open(downloaded_file_path, 'rb'))
                await processing_msg.edit_text("فایل با موفقیت ارسال شد.")
                logger.info(f"فایل اینستاگرام برای کاربر {user_id} ارسال شد: {downloaded_file_path}")

        except Exception as e:
            logger.error(f"خطا در پردازش اینستاگرام برای کاربر {user_id}: {str(e)}")
            await processing_msg.edit_text(LANGUAGES[lang]["error"].format(str(e)))
        finally:
            # temp_directory context manager handles cleanup
            pass # No need for shutil.rmtree here as context manager does it.


# Inline Query Handler (بدون تغییر)
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    if not query:
        return
    results = [
        InlineQueryResultArticle(
            id=str(time.time()),
            title="Download Link",
            input_message_content=InputTextMessageContent(query)
        )
    ]
    await update.inline_query.answer(results)

# Webhook handler برای Koyeb
async def telegram_webhook_handler(request):
    try:
        update_json = await request.json()
        update = Update.de_json(update_json, application.bot)
        await application.process_update(update)
        return web.Response(text="ok")
    except Exception as e:
        logger.error(f"خطا در پردازش وب‌هوک: {e}")
        return web.Response(text="error", status=500)

application = None # تعریف سراسری برای دسترسی در webhook handler

async def main():
    # بررسی نصب FFmpeg
    if not check_ffmpeg():
        logger.error("FFmpeg نصب نشده است. ربات نمی‌تواند فایل‌ها را پردازش کند.")
        # می‌توانید ربات را متوقف کنید یا به کاربر اطلاع دهید.
        # return

    # راه‌اندازی دیتابیس
    await init_db_async()

    global application
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(check_membership, pattern="^check_membership$"))
    application.add_handler(CallbackQueryHandler(settings, pattern="^settings$"))
    application.add_handler(CallbackQueryHandler(set_language, pattern="^lang_"))
    application.add_handler(InlineQueryHandler(inline_query))

    # اجرای process_queue به صورت یک تسک پس‌زمینه
    asyncio.create_task(process_queue())
    logger.info("تسک پردازش صف آغاز شد.")

    # تنظیمات Webhook برای Koyeb
    WEBHOOK_PATH = "/telegram"
    WEBHOOK_URL = os.getenv("K_SERVICE_URL") # آدرس URL سرویس Koyeb شما
    PORT = int(os.environ.get("PORT", 8080))

    if WEBHOOK_URL:
        # تنظیم Webhook در تلگرام
        webhook_full_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        await application.bot.set_webhook(url=webhook_full_url)
        logger.info(f"Webhook تنظیم شد: {webhook_full_url}")

        # راه‌اندازی سرور aiohttp
        app = web.Application()
        app.router.add_post(WEBHOOK_PATH, telegram_webhook_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        logger.info(f"سرور aiohttp برای Webhook در پورت {PORT} آغاز به کار کرد.")

        # برای نگه داشتن برنامه در حال اجرا، منتظر یک رویداد نامحدود باشید
        # در محیط‌های Production (مانند Koyeb)، برنامه باید فعال بماند تا Webhook دریافت شود.
        await asyncio.Event().wait()
    else:
        logger.warning("متغیر K_SERVICE_URL یافت نشد. ربات در حالت Polling اجرا می‌شود. این حالت برای Koyeb توصیه نمی‌شود.")
        # برای توسعه محلی (بدون Webhook)
        await application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("ربات متوقف شد.")
    except Exception as e:
        logger.critical(f"خطای کشنده در اجرای ربات: {e}", exc_info=True)

