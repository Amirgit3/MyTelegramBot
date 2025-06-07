# از یک ایمیج پایتون کوچک و پایدار استفاده کنید
FROM python:3.9-slim-buster

# به‌روزرسانی پکیج‌ها و نصب FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# تنظیم دایرکتوری کاری در کانتینر
WORKDIR /app

# کپی کردن فایل requirements.txt و نصب پکیج‌های پایتون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی کردن بقیه فایل‌های پروژه (مثل bot.py، .env و ...)
COPY . .

# اعلام پورت مورد استفاده (کویب به طور پیش‌فرض پورت 8080 را استفاده می‌کند)
EXPOSE 8080

# دستوری که هنگام شروع کانتینر اجرا می‌شود
CMD ["python", "bot.py"]
