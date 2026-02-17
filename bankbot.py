# bankbot.py (نسخه نهایی با ورود نقش‌ها و مالیات 10%)

import os
import asyncio
import aiosqlite
from datetime import datetime
from passlib.hash import sha256_crypt
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------- Environment Variables ----------
TOKEN = os.environ.get("TOKEN")
GROUP_CHAT_ID = int(os.environ.get("GROUP_CHAT_ID", 0))

DB_PATH = "bank.db"
sessions = {}  # {user_id: role} برای ذخیره نقش پس از لاگین

# ---------- Helper Functions ----------
async def get_account(username):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM accounts WHERE username=?", (username,)) as cur:
            return await cur.fetchone()

async def get_account_id(username):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM accounts WHERE username=?", (username,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def get_balance(account_id, currency):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT amount FROM balances WHERE account_id=? AND currency=?",
            (account_id, currency)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0.0

async def set_balance(account_id, currency, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO balances(account_id, currency, amount) VALUES(?,?,?)",
            (account_id, currency, amount)
        )
        await db.commit()

async def add_transaction(from_id, to_id, currency, amount, type_):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO transactions(from_acc,to_acc,currency,amount,ts,type) VALUES(?,?,?,?,?,?)",
            (from_id, to_id, currency, amount, datetime.utcnow().isoformat(), type_)
        )
        await db.commit()

async def get_role(username):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role FROM accounts WHERE username=?", (username,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

# ---------- Admin Functions ----------
async def create_account(username, password, role):
    async with aiosqlite.connect(DB_PATH) as db:
        hashed = sha256_crypt.hash(password)
        await db.execute(
            "INSERT INTO accounts(owner_tg,username,password,role) VALUES(0,?,?,?)",
            (username, hashed, role)
        )
        await db.commit()

async def add_currency(currency):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO currencies(name) VALUES(?)", (currency,))
        await db.commit()

async def apply_monthly_tax():
    party_acc = await get_account_id("party")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT account_id, currency, amount FROM balances") as cur:
            rows = await cur.fetchall()
            for account_id, currency, amount in rows:
                tax = amount * 0.10  # 10% مالیات
                if tax > 0:
                    await set_balance(account_id, currency, amount - tax)
                    party_balance = await get_balance(party_acc, currency)
                    await set_balance(party_acc, currency, party_balance + tax)
                    await add_transaction(account_id, party_acc, currency, tax, "MONTHLY_TAX")

# ---------- Telegram Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ربات بانک با موفقیت وصل شد ✅\nبرای ورود، از /login <username> <password> استفاده کنید.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "دستورها:\n/start\n/help\n/login <username> <password>\n/balance\n/transfer\n"
        "(دستورات ادمین: /create_account /add_currency /apply_tax)"
    )

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("استفاده صحیح: /login <username> <password>")
        return

    username, password = args
    acc = await get_account(username)
    if not acc:
        await update.message.reply_text("کاربر پیدا نشد!")
        return

    hashed = acc[2]  # ستون password
    if sha256_crypt.verify(password, hashed):
        user_id = update.message.from_user.id
        role = acc[4]  # ستون role
        sessions[user_id] = role
        await update.message.reply_text(f"ورود موفق! نقش شما: {role}")
    else:
        await update.message.reply_text("رمز اشتباه است!")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in sessions:
        await update.message.reply_text("ابتدا با /login وارد شوید!")
        return

    username = update.message.from_user.username
    acc = await get_account(username)
    if not acc:
        await update.message.reply_text("حساب شما پیدا نشد!")
        return

    account_id = acc[0]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT currency, amount FROM balances WHERE account_id=?", (account_id,)) as cur:
            balances = await cur.fetchall()

    if not balances:
        await update.message.reply_text("موجودی شما صفر است.")
        return

    msg = "موجودی شما:\n"
    for cur, amt in balances:
        msg += f"{cur}: {amt}\n"
    await update.message.reply_text(msg)

async def transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in sessions:
        await update.message.reply_text("ابتدا با /login وارد شوید!")
        return

    username = update.message.from_user.username
    args = context.args
    if len(args) != 3:
        await update.message.reply_text("استفاده صحیح: /transfer <recipient> <currency> <amount>")
        return

    recipient_name, currency, amount = args[0], args[1], float(args[2])
    sender_acc = await get_account(username)
    recipient_acc = await get_account(recipient_name)

    if not sender_acc or not recipient_acc:
        await update.message.reply_text("یکی از حساب‌ها پیدا نشد!")
        return

    sender_id = sender_acc[0]
    recipient_id = recipient_acc[0]

    sender_balance = await get_balance(sender_id, currency)
    if sender_balance < amount:
        await update.message.reply_text("موجودی کافی نیست!")
        return

    fee = amount * 0.05
    net_amount = amount - fee

    await set_balance(sender_id, currency, sender_balance - amount)
    rec_balance = await get_balance(recipient_id, currency)
    await set_balance(recipient_id, currency, rec_balance + net_amount)

    await add_transaction(sender_id, recipient_id, currency, net_amount, "TRANSFER")
    await update.message.reply_text(f"تراکنش موفق: {net_amount} {currency} به {recipient_name} (کارمزد: {fee})")

    if GROUP_CHAT_ID != 0:
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=f"{username} به {recipient_name} {net_amount} {currency} انتقال داد (کارمزد: {fee})"
        )

# ---------- Admin Commands ----------
async def admin_create_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if sessions.get(user_id) != "ADMIN":
        await update.message.reply_text("شما اجازه این کار را ندارید!")
        return

    args = context.args
    if len(args) != 3:
        await update.message.reply_text("استفاده صحیح: /create_account <username> <password> <role>")
        return

    await create_account(args[0], args[1], args[2])
    await update.message.reply_text(f"حساب {args[0]} ساخته شد.")

async def admin_add_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if sessions.get(user_id) != "ADMIN":
        await update.message.reply_text("شما اجازه این کار را ندارید!")
        return

    if len(context.args) != 1:
        await update.message.reply_text("استفاده صحیح: /add_currency <currency>")
        return

    await add_currency(context.args[0])
    await update.message.reply_text(f"ارز {context.args[0]} اضافه شد.")

async def admin_apply_tax(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if sessions.get(user_id) != "ADMIN":
        await update.message.reply_text("شما اجازه این کار را ندارید!")
        return

    await apply_monthly_tax()
    await update.message.reply_text("مالیات ماهیانه ۱۰٪ اعمال شد.")

# ---------- Main ----------
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Basic Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("transfer", transfer))

    # Admin Commands
    app.add_handler(CommandHandler("create_account", admin_create_account))
    app.add_handler(CommandHandler("add_currency", admin_add_currency))
    app.add_handler(CommandHandler("apply_tax", admin_apply_tax))

    print("🟢 ربات شروع شد")
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "already running" in str(e):
            loop = asyncio.get_running_loop()
            loop.create_task(main())
        else:
            raise
