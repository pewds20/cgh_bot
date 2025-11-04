# ==============================
# 🏥 Sustainability Redistribution Bot (Firebase + 24/7 Ready)
# - Firebase persistent listings
# - Calendar date selector
# - Manual pickup time
# - Live Remaining counter
# - Auto archive + channel notification
# - Flask keep-alive (for Koyeb)
# ==============================

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters
)
import os, datetime, calendar, json
from pathlib import Path
from flask import Flask
from threading import Thread
import firebase_admin
from firebase_admin import credentials, db

# ========= FIREBASE SETUP =========
# ========= FIREBASE SETUP (ENVIRONMENT VARIABLE) =========
import json
from firebase_admin import credentials, db

# Load Firebase credentials from environment variable instead of file
firebase_creds = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
cred = credentials.Certificate(firebase_creds)
firebase_admin.initialize_app(cred, {
    "databaseURL": "https://cgh-telebot-default-rtdb.asia-southeast1.firebasedatabase.app/"
})

ref = db.reference("listings")
LISTINGS = ref.get() or {}

def save_listings():
    try:
        ref.set(LISTINGS)
        print(f"💾 Saved {len(LISTINGS)} listings to Firebase.")
    except Exception as e:
        print(f"⚠️ Failed to save listings: {e}")


ref = db.reference("listings")

# Load data if any
LISTINGS = ref.get() or {}

def save_listings():
    """Save current LISTINGS dictionary to Firebase."""
    try:
        ref.set(LISTINGS)
        print(f"💾 Saved {len(LISTINGS)} listings to Firebase.")
    except Exception as e:
        print(f"⚠️ Failed to save listings: {e}")

# ========= KEEP-ALIVE SERVER =========
app_keepalive = Flask(__name__)

@app_keepalive.route('/')
def home():
    return "Bot is alive!"

def run():
    app_keepalive.run(host='0.0.0.0', port=8000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ========= CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN", "8377427445:AAE-H_EiGAjs4NKE20v9S8zFLOv2AiHKcpU")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@sustainability_redistribution")

ITEM, QTY, SIZE, EXPIRY, LOCATION, PHOTO, CONFIRM, SUGGEST = range(8)

# ========= CALENDAR =========
def make_month_calendar(year=None, month=None):
    today = datetime.date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month
    month_name = datetime.date(year, month, 1).strftime("%B %Y")
    cal = calendar.Calendar()
    days = [d for d in cal.itermonthdates(year, month)]

    rows, row = [], []
    for day in days:
        if day.month == month:
            row.append(InlineKeyboardButton(str(day.day), callback_data=f"date_{day.isoformat()}"))
        else:
            row.append(InlineKeyboardButton(" ", callback_data="noop"))
        if len(row) == 7:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    prev_month = 12 if month == 1 else month - 1
    next_month = 1 if month == 12 else month + 1
    prev_year = year - 1 if month == 1 else year
    next_year = year + 1 if month == 12 else year

    nav = [
        InlineKeyboardButton("<<", callback_data=f"nav_{prev_year}_{prev_month}"),
        InlineKeyboardButton(month_name, callback_data="noop"),
        InlineKeyboardButton(">>", callback_data=f"nav_{next_year}_{next_month}")
    ]
    rows.insert(0, nav)
    return InlineKeyboardMarkup(rows)

# ========= UPDATE CHANNEL POST =========
async def update_channel_post(context: ContextTypes.DEFAULT_TYPE, msg_id: int):
    l = LISTINGS.get(msg_id)
    if not l:
        return

    try:
        if l["remaining"] <= 0:
            text = (
                f"🧾 <b>{l['item']}</b>\n"
                f"✅ <b>Fully Claimed</b>\n"
                f"📏 Size: {l['size']}\n"
                f"⏰ Expiry: {l['expiry']}\n"
                f"📍 {l['location']}"
            )
            try:
                await context.bot.edit_message_caption(
                    chat_id=CHANNEL_ID,
                    message_id=msg_id,
                    caption=text,
                    parse_mode="HTML"
                )
            except Exception:
                await context.bot.edit_message_text(
                    chat_id=CHANNEL_ID,
                    message_id=msg_id,
                    text=text,
                    parse_mode="HTML"
                )

            await context.bot.send_message(
                CHANNEL_ID,
                f"✅ <b>{l['item']}</b> is now fully claimed! 🎉\nThank you for participating ♻️",
                parse_mode="HTML"
            )
            await context.bot.send_message(
                l["poster_id"],
                f"✅ Your item <b>{l['item']}</b> has been fully claimed and archived.",
                parse_mode="HTML"
            )
            return

        text = (
            f"🧾 <b>{l['item']}</b>\n"
            f"📦 Remaining: {l['remaining']} of {l['qty']}\n"
            f"📏 Size: {l['size']}\n"
            f"⏰ Expiry: {l['expiry']}\n"
            f"📍 {l['location']}"
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🤝 Claim", url=f"https://t.me/{context.bot.username}?start=claim_{msg_id}")
        ]])

        try:
            await context.bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=msg_id,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=msg_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except Exception as e:
        print(f"⚠️ Error updating post: {e}")

# ========= CANCEL =========
async def cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.edit_message_text("❌ Cancelled. Start again with /start.")
    else:
        await update.message.reply_text("❌ Cancelled. Start again with /start.")
    return ConversationHandler.END

# ========= BASIC COMMANDS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0].startswith("claim_"):
        msg_id = int(args[0].split("_")[1])
        l = LISTINGS.get(msg_id)
        if not l:
            await update.message.reply_text("❌ This listing is no longer available.")
            return
        if l["remaining"] <= 0:
            await update.message.reply_text("❌ This listing has been fully claimed.")
            return
        context.user_data["claiming_msg_id"] = msg_id
        context.user_data["claim_step"] = "qty"
        await update.message.reply_text(
            f"You’re claiming <b>{l['item']}</b>.\n\n"
            "📦 How many boxes would you like to collect?",
            parse_mode="HTML"
        )
        return

    # Handle deep-link payloads for quick actions
    if args:
        if args[0].lower() == "instructions":
            await instructions(update, context)
            return
        if args[0].lower() == "channel":
            await channel(update, context)
            return

    keyboard = None
    msg = (
        "👋 <b>Welcome to the Sustainability Redistribution Bot!</b>\n\n"
        "This bot helps hospital staff donate excess consumables easily.\n\n"
        "Use the commands below to get started:\n"
        f"• <a href=\"https://t.me/{context.bot.username}?start=newitem\">/newitem</a> – Donate items\n"
        f"• <a href=\"https://t.me/{context.bot.username}?start=instructions\">/instructions</a> – Learn how it works\n"
        f"• <a href=\"https://t.me/{CHANNEL_ID.lstrip('@')}\">/channel</a> – Open the redistribution channel"
    )
    sent = await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="HTML")
    context.chat_data["menu_msg_id"] = sent.message_id

async def channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📣 Open Channel", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")]])
    await update.message.reply_text("Open the redistribution channel:", reply_markup=keyboard)

async def instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        target = q.message
    else:
        target = update.message
    await target.reply_text(
        "ℹ️ <b>How It Works</b>\n\n"
        "• Staff post excess items using /newitem.\n"
        "• Items appear in the Redistribution Channel.\n"
        "• Others click Claim and coordinate pickup.\n"
        "• Seller can approve, reject, or suggest new pickup times.\n\n"
        f"This ensures efficient reuse and minimizes hospital waste ♻️\n\n"
        f"<b>Quick start:</b> <a href=\"https://t.me/{context.bot.username}?start=newitem\">Start donating</a> (opens a chat with the bot)",
        parse_mode="HTML"
    )

# ========= NEW ITEM FLOW =========
async def newitem(update, context):
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.message.reply_text("🧾 What item are you donating?")
    else:
        await update.message.reply_text("🧾 What item are you donating?")
    return ITEM

async def deprecate_old_donate_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("This button is no longer used. Please use /newitem or /start.", show_alert=False)
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

async def start_newitem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0].lower() == "newitem":
        # Begin the donate flow from a deep-link like /start newitem
        await update.message.reply_text("🧾 What item are you donating?")
        return ITEM
    return ConversationHandler.END

async def ask_qty(update, context):
    context.user_data["item"] = update.message.text
    await update.message.reply_text("📦 How many boxes or units are available?")
    return QTY

async def ask_size(update, context):
    context.user_data["qty"] = update.message.text
    await update.message.reply_text("📏 What is the size? (Type 'NA' if not applicable)")
    return SIZE

async def ask_expiry(update, context):
    context.user_data["size"] = update.message.text
    await update.message.reply_text(
        "⏰ Enter the expiry date in DD/MM/YY format, or type 'NA' if not applicable.\n"
        "Examples: 05/11/25, 15/01/26, NA"
    )
    return EXPIRY

def _parse_expiry_text(text: str) -> str:
    t = text.strip()
    if t.upper() == "NA":
        return "NA"
    # Try DD/MM/YY then DD/MM/YYYY
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            dt = datetime.datetime.strptime(t, fmt).date()
            return dt.strftime("%d/%m/%y")
        except Exception:
            continue
    raise ValueError("Invalid date")

async def handle_expiry_text(update, context):
    try:
        parsed = _parse_expiry_text(update.message.text)
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid date as DD/MM/YY (e.g., 05/11/25) or 'NA'.")
        return EXPIRY
    context.user_data["expiry"] = parsed
    await update.message.reply_text("📍 Where is the pickup location?")
    return LOCATION

async def calendar_handler(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith("nav_"):
        _, y, m = data.split("_")
        await q.edit_message_reply_markup(reply_markup=make_month_calendar(int(y), int(m)))
        return EXPIRY
    elif data.startswith("date_"):
        picked = data.replace("date_", "")
        context.user_data["expiry"] = datetime.date.fromisoformat(picked).strftime("%d/%m/%y")
        await q.edit_message_text(f"✅ Expiry date: {context.user_data['expiry']}")
        await q.message.reply_text("📍 Where is the pickup location?")
        return LOCATION
    elif data == "noop":
        await q.answer("Select a valid day.")
        return EXPIRY

async def ask_photo(update, context):
    context.user_data["location"] = update.message.text
    await update.message.reply_text("📸 Send a photo of the item or type 'Skip' if none.")
    return PHOTO

async def save_photo(update, context):
    photo = update.message.photo[-1]
    file = await photo.get_file()
    context.user_data["photo"] = file.file_id
    await confirm_post(update, context)
    return CONFIRM

async def skip_photo(update, context):
    context.user_data["photo"] = None
    await confirm_post(update, context)
    return CONFIRM

async def confirm_post(update, context):
    d = context.user_data
    preview = (
        f"🧾 <b>{d['item']}</b>\n"
        f"📦 Quantity: {d['qty']}\n"
        f"📏 Size: {d['size']}\n"
        f"⏰ Expiry: {d['expiry']}\n"
        f"📍 Location: {d['location']}\n\n"
        "Would you like to post this to the channel?"
    )
    buttons = [[
        InlineKeyboardButton("✅ Post", callback_data="confirm_post"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_post")
    ]]
    await update.message.reply_text(preview, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
    return CONFIRM

async def post_to_channel(update, context):
    q = update.callback_query
    await q.answer()
    d = context.user_data

    text = (
        f"🧾 <b>{d['item']}</b>\n"
        f"📦 Quantity: {d['qty']}\n"
        f"📏 Size: {d['size']}\n"
        f"⏰ Expiry: {d['expiry']}\n"
        f"📍 {d['location']}"
    )

    photo = d.get("photo")
    if photo:
        msg = await context.bot.send_photo(CHANNEL_ID, photo=photo, caption=text, parse_mode="HTML")
    else:
        msg = await context.bot.send_message(CHANNEL_ID, text, parse_mode="HTML")

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🤝 Claim", url=f"https://t.me/{context.bot.username}?start=claim_{msg.message_id}")
    ]])

    try:
        await context.bot.edit_message_caption(
            chat_id=CHANNEL_ID, message_id=msg.message_id,
            caption=text, reply_markup=keyboard, parse_mode="HTML"
        )
    except Exception:
        await context.bot.edit_message_text(
            chat_id=CHANNEL_ID, message_id=msg.message_id,
            text=text, reply_markup=keyboard, parse_mode="HTML"
        )

    LISTINGS[msg.message_id] = {
        "poster_id": q.from_user.id,
        "poster_name": q.from_user.username,
        "item": d["item"],
        "qty": int(d["qty"]),
        "remaining": int(d["qty"]),
        "size": d["size"],
        "expiry": d["expiry"],
        "location": d["location"],
        "claims": []
    }
    save_listings()
    await q.edit_message_text("✅ Posted to channel!")
    return ConversationHandler.END

# ========= CLAIM FLOW =========
async def private_message(update, context):
    if "claim_step" not in context.user_data:
        return
    msg_id = context.user_data.get("claiming_msg_id")
    if msg_id is None or msg_id not in LISTINGS:
        await update.message.reply_text("⚠️ I can’t find that listing. Please tap Claim again.")
        context.user_data.clear()
        return

    l = LISTINGS[msg_id]
    step = context.user_data["claim_step"]
    user = update.effective_user

    if step == "qty":
        context.user_data["claim_qty"] = int(update.message.text)
        context.user_data["claim_step"] = "time"
        await update.message.reply_text("🕓 When can you collect? (e.g. 10 Oct 2025, 3–5 pm)")
    elif step == "time":
        pickup_time = update.message.text
        qty = context.user_data["claim_qty"]
        seller_id = l["poster_id"]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve|{msg_id}|{user.id}|{qty}|{pickup_time}"),
            InlineKeyboardButton("🕓 Suggest New Date/Time", callback_data=f"suggest|{msg_id}|{user.id}|{qty}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject|{msg_id}|{user.id}|{qty}|{pickup_time}")
        ]])
        await context.bot.send_message(
            seller_id,
            f"📨 <b>Claim Request</b>\n\n"
            f"👤 @{user.username or user.first_name} wants to claim:\n"
            f"• <b>{qty}</b> of <b>{l['item']}</b>\n"
            f"• Collection: {pickup_time}",
            reply_markup=kb, parse_mode="HTML"
        )
        await update.message.reply_text("📨 Request sent to the seller for approval.")
        context.user_data.clear()

# ========= APPROVE / REJECT HANDLER =========
async def handle_claim_decision(update, context):
    q = update.callback_query
    await q.answer()
    action, msg_id, user_id, qty, pickup_time = q.data.split("|")
    msg_id, user_id, qty = int(msg_id), int(user_id), int(qty)
    l = LISTINGS.get(msg_id)
    if not l:
        await q.edit_message_text("⚠️ Listing no longer exists.")
        return

    buyer = await context.bot.get_chat(user_id)

    if action == "approve":
        if l["remaining"] < qty:
            await q.edit_message_text("⚠️ Not enough remaining stock to approve.")
            return
        l["remaining"] -= qty
        l["claims"].append({"user_id": user_id, "qty": qty, "time": pickup_time})
        save_listings()
        await update_channel_post(context, msg_id)
        await context.bot.send_message(
            user_id,
            f"✅ Your claim for <b>{l['item']}</b> has been approved!\n\n"
            f"📦 Quantity: <b>{qty}</b>\n"
            f"⏰ Pickup: <b>{pickup_time}</b>\n"
            f"📍 Location: <b>{l['location']}</b>",
            parse_mode="HTML"
        )
        await q.edit_message_text(f"✅ Approved claim for @{buyer.username or buyer.first_name} ({qty}× {l['item']})")

    elif action == "reject":
        await context.bot.send_message(
            user_id,
            f"❌ Your claim for <b>{l['item']}</b> has been rejected.",
            parse_mode="HTML"
        )
        await q.edit_message_text(f"❌ Rejected claim for @{buyer.username or buyer.first_name}.")

# ========= SUGGEST NEW DATE/TIME FLOW =========
async def suggest_time(update, context):
    q = update.callback_query
    await q.answer()
    _, msg_id, uid, qty = q.data.split("|")
    context.user_data["suggest_info"] = (int(msg_id), int(uid), int(qty))
    await q.message.reply_text("📅 Please choose a new pickup date:", reply_markup=make_month_calendar())
    return SUGGEST

async def handle_suggest_calendar(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith("nav_"):
        _, y, m = data.split("_")
        await q.edit_message_reply_markup(reply_markup=make_month_calendar(int(y), int(m)))
        return SUGGEST
    elif data.startswith("date_"):
        picked = data.replace("date_", "")
        context.user_data["new_date"] = datetime.date.fromisoformat(picked).strftime("%d %b %Y")
        await q.edit_message_text(f"✅ Date selected: {context.user_data['new_date']}")
        await q.message.reply_text("⏰ Please type the exact pickup time (e.g. 14:30):")
        return SUGGEST

async def handle_suggest_time_text(update, context):
    user_time = update.message.text.strip()
    msg_id, uid, qty = context.user_data["suggest_info"]
    new_date = context.user_data["new_date"]
    l = LISTINGS[msg_id]
    proposed_time = f"{new_date}, {user_time}"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept", callback_data=f"accept_newtime|{msg_id}|{qty}|{proposed_time}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"decline_newtime|{msg_id}")
    ]])
    msg = (
        "📌 <b>IMPORTANT – SAVE THIS MESSAGE</b>\n\n"
        "🕓 <b>Seller proposed new pickup:</b>\n"
        f"📦 Quantity: <b>{qty}</b>\n"
        f"📅 Pickup: <b>{proposed_time}</b>\n"
        f"📍 Location: <b>{l['location']}</b>\n\n"
        "Do you accept this proposal?"
    )
    await context.bot.send_message(uid, msg, reply_markup=kb, parse_mode="HTML")
    await update.message.reply_text("✅ Sent your proposed new date/time to the buyer.")
    context.user_data.clear()
    return ConversationHandler.END

async def handle_newtime_reply(update, context):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("|")
    action, msg_id = parts[0], int(parts[1])
    l = LISTINGS.get(msg_id)
    buyer = q.from_user
    if not l:
        await q.edit_message_text("⚠️ Listing no longer available.")
        return

    if action == "accept_newtime":
        qty, proposed_time = int(parts[2]), parts[3]
        l["remaining"] -= qty
        l["claims"].append({"user_id": buyer.id, "qty": qty, "time": proposed_time})
        save_listings()
        await update_channel_post(context, msg_id)
        await context.bot.send_message(
            l["poster_id"],
            f"✅ Buyer @{buyer.username or buyer.first_name} accepted your new pickup timing:\n{proposed_time} ({qty} boxes)."
        )
        await q.edit_message_text(f"✅ Pickup confirmed for {qty} of {l['item']} at {proposed_time}.")
    elif action == "decline_newtime":
        await context.bot.send_message(l["poster_id"], f"❌ Buyer @{buyer.username or buyer.first_name} declined your new timing.")
        await q.edit_message_text("❌ You declined the new timing. Claim cancelled.")

# ========= HANDLER CONFIG =========
conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("newitem", newitem),
        CommandHandler("start", start_newitem, filters=filters.Regex(r"^/start(?:@\\w+)?\\s+newitem(\b|$)"))
    ],
    states={
        ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_qty)],
        QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_size)],
        SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_expiry)],
        EXPIRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_expiry_text)],
        LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_photo)],
        PHOTO: [
            MessageHandler(filters.PHOTO, save_photo),
            MessageHandler(filters.Regex("^(Skip|skip)$"), skip_photo)
        ],
        CONFIRM: [
            CallbackQueryHandler(post_to_channel, pattern="confirm_post"),
            CallbackQueryHandler(cancel_post, pattern="cancel_post")
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_post)],
)

suggest_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(suggest_time, pattern="^suggest")],
    states={
        SUGGEST: [
            CallbackQueryHandler(handle_suggest_calendar, pattern="^(date_|nav_|noop)"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_suggest_time_text)
        ]
    },
    fallbacks=[CommandHandler("cancel", cancel_post)],
)

# ========= APP SETUP =========
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(conv_handler)
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(deprecate_old_donate_button, pattern="^help_newitem$"))
app.add_handler(CommandHandler("channel", channel))
app.add_handler(CommandHandler("instructions", instructions))
app.add_handler(CallbackQueryHandler(instructions, pattern="^help_info$"))
app.add_handler(suggest_conv)
app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, private_message))
app.add_handler(CallbackQueryHandler(handle_newtime_reply, pattern="^(accept_newtime|decline_newtime)"))
app.add_handler(CallbackQueryHandler(handle_claim_decision, pattern="^(approve|reject)"))
app.add_handler(CommandHandler("cancel", cancel_post))

async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Show main menu"),
        BotCommand("newitem", "Donate an excess item"),
        BotCommand("instructions", "How the bot works"),
        BotCommand("cancel", "Cancel current action"),
    ])
app.post_init = set_commands

print("🤖 Bot running with Firebase persistence + keep-alive + auto-archive ...")
if __name__ == "__main__":
    keep_alive()
    app.run_polling()
