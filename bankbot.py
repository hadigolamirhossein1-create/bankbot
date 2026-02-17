from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = "8148713218:AAGR9y3KRSLVgtSDFWmt_iwA1VHwgRjSB6E"

# ---------- commands ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات با موفقیت وصل شد ✅")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("دستورها:\n/start\n/help")

# ---------- main ----------

def main():
    print("🟢 ربات شروع شد")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    app.run_polling()


if __name__ == "__main__":
    main()
