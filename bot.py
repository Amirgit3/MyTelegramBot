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
        except Exception as e:
            logger.error(f"ربات نمی‌تواند وضعیت خودش را در کانال‌ها چک کند: {str(e)}")
            await query.message.reply_text("خطا: ربات به کانال‌ها دسترسی ندارد. لطفاً ربات را ادمین کنید.")
            return

        # چک کردن عضویت کاربر با timeout کمتر
        try:
            chat_member1 = await context.bot.get_chat_member("@enrgy_m", user_id)
            chat_member2 = await context.bot.get_chat_member("@music_bik", user_id)
            if chat_member1.status in ["member", "administrator", "creator"] and \
               chat_member2.status in ["member", "administrator", "creator"]:
                context.user_data["is_member"] = True
                await query.message.reply_text(LANGUAGES[lang]["membership_ok"])
            else:
                await query.message.reply_text(LANGUAGES[lang]["join_channels"])
        except Exception as e:
            logger.error(f"خطا در بررسی عضویت کاربر {user_id}: {str(e)}")
            await query.message.reply_text(LANGUAGES[lang]["error"].format("نمی‌توان عضویت را چک کرد. لطفاً دوباره امتحان کنید."))

    except Exception as e:
        logger.error(f"خطای کلی در check_membership برای کاربر {user_id}: {str(e)}")
        await query.message.reply_text(LANGUAGES[lang]["error"].format("خطای ناشناخته رخ داد."))
