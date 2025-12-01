# ==============================
# 🏥 Sustainability Redistribution Bot (CLEAN, FIREBASE)
# - /newitem to list items
# - Deep-link "Claim" button → DM with bot
# - Simple approve / reject flow
# - Firebase persistence (stateless, survives restart)
# - Inline keyboards only (no reply keyboard)
# ==============================

from __future__ import annotations

import os
import json
import time
import datetime
import html
import logging
from typing import Dict, Any, Optional, List

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.constants import ParseMode, ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import firebase_admin
from firebase_admin import credentials, db

# ========= LOGGING =========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========= CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN", "8377427445:AAGrnwxTcyQvF2IpEwBTL6AeqR6ux5ulhOY")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Sustainability_Redistribution")
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL", "https://cgh-telebot-default-rtdb.asia-southeast1.firebasedatabase.app/")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not FIREBASE_DB_URL:
    raise RuntimeError("FIREBASE_DB_URL is not set")

# ========= FIREBASE INIT =========
firebase_creds_raw = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_creds_raw:
    raise RuntimeError("FIREBASE_CREDENTIALS is not set")

firebase_creds_dict = json.loads(firebase_creds_raw)
cred = credentials.Certificate(firebase_creds_dict)

firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})

# References
listings_ref = db.reference("listings")

# ========= CONVERSATION STATES =========
ITEM, QTY, SIZE, EXPIRY, LOCATION, PHOTO, CONFIRM = range(7)

# ========= DATA HELPERS =========


def create_listing(data: Dict[str, Any]) -> Optional[str]:
    """Create a new listing in Firebase and return its ID."""
    try:
        now_ts = int(time.time())
        data = {
            **data,
            "created_at": now_ts,
            "status": "available",
            "remaining": int(data.get("qty", 0) or 0),
            "claims": [],  # list of {user_id, username, qty, pickup_time, status}
        }
        new_ref = listings_ref.push(data)
        return new_ref.key
    except Exception as e:
        logger.error(f"Error creating listing: {e}")
        return None


def get_listing(listing_id: str) -> Optional[Dict[str, Any]]:
    try:
        l = listings_ref.child(listing_id).get()
        return l or None
    except Exception as e:
        logger.error(f"Error getting listing {listing_id}: {e}")
        return None


def save_listing(listing_id: str, data: Dict[str, Any]) -> bool:
    try:
        listings_ref.child(listing_id).update(data)
        return True
    except Exception as e:
        logger.error(f"Error saving listing {listing_id}: {e}")
        return False


async def update_channel_post(
    context: ContextTypes.DEFAULT_TYPE, listing_id: str
) -> None:
    """Update the channel message (remaining qty or fully claimed)."""
    listing = get_listing(listing_id)
    if not listing:
        logger.warning(f"update_channel_post: listing {listing_id} not found")
        return

    message_id = listing.get("channel_message_id")
    if not message_id:
        logger.warning(f"update_channel_post: no channel_message_id for {listing_id}")
        return

    total_qty = int(listing.get("qty", 0) or 0)
    remaining = int(listing.get("remaining", 0) or 0)

    item = html.escape(str(listing.get("item", "Item")))
    size = html.escape(str(listing.get("size", "N/A")))
    expiry = html.escape(str(listing.get("expiry", "N/A")))
    location = html.escape(str(listing.get("location", "N/A")))

    text = (
        f"🧾 <b>{item}</b>\n"
        f"📦 Quantity: {total_qty} (Remaining: {remaining})\n"
        f"📏 Size: {size}\n"
        f"⏰ Expiry: {expiry}\n"
        f"📍 {location}"
    )

    # Keyboard: Claim only if remaining > 0
    reply_markup = None
    if remaining > 0 and listing.get("status") == "available":
        claim_url = f"https://t.me/{context.bot.username}?start=claim_{listing_id}"
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🤝 Claim", url=claim_url)]]
        )
    else:
        text += "\n\n✅ <b>Fully claimed!</b>"

    try:
        if listing.get("photo_id"):
            await context.bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=message_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        else:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        logger.error(f"Error editing channel message: {e}")


# ========= BASIC COMMANDS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start and deep-link claim flow."""
    args = context.args or []

    # --- Deep link: start claim flow ---
    if args and args[0].startswith("claim_"):
        listing_id = args[0].split("_", 1)[1]
        listing = get_listing(listing_id)

        if not listing:
            await update.message.reply_text("❌ This listing is no longer available.")
            return

        remaining = int(listing.get("remaining", 0) or 0)
        status = listing.get("status", "unknown")

        if remaining <= 0 or status != "available":
            await update.message.reply_text("❌ This listing has been fully claimed.")
            return

        context.user_data.clear()
        context.user_data["claim_listing_id"] = listing_id
        context.user_data["claim_step"] = "qty"
        context.user_data["max_qty"] = remaining

        await update.message.reply_text(
            f"You’re claiming <b>{html.escape(listing.get('item', 'Item'))}</b>.\n\n"
            f"📦 Available: {remaining}\n"
            "How many units would you like to claim?",
            parse_mode=ParseMode.HTML,
        )
        return

    # --- Normal /start menu ---
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 List New Item", callback_data="newitem_btn")],
            [InlineKeyboardButton("📚 Instructions", callback_data="help_info")],
        ]
    )

    msg = (
        "👋 <b>Welcome to the Sustainability Redistribution Bot</b>\n\n"
        "This bot helps hospital staff share excess consumables easily.\n\n"
        "<b>Commands</b>\n"
        "• /newitem – List an item for donation\n"
        "• /instructions – How it works\n\n"
        "Or use the buttons below."
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>📋 How to List an Item for Donation</b>\n\n"
        "1. Type <b>/newitem</b> to start the listing process\n"
        "2. You’ll be asked for:\n"
        "   • Item name\n"
        "   • Quantity\n"
        "   • Size/Volume (or 'na')\n"
        "   • Expiry date (DD/MM/YYYY or 'na')\n"
        "   • Pickup location\n"
        "   • Optional photo\n\n"
        "3. Your item will be posted in the channel\n"
        "4. Others can claim by tapping the <b>‘Claim’</b> button\n"
        "5. You’ll receive a request to approve or reject\n\n"
        "💡 Quick start: type <b>/newitem</b>."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 List New Item", callback_data="newitem_btn")],
        ]
    )

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_text(
            text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )


# ========= NEW ITEM FLOW =========
def parse_expiry(text: str) -> str:
    t = text.strip()
    if not t:
        raise ValueError("Empty date")
    if t.lower() in ("na", "n/a", "none"):
        return "N/A"

    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            d = datetime.datetime.strptime(t, fmt).date()
            return d.strftime("%d/%m/%y")
        except ValueError:
            continue

    raise ValueError("Invalid date. Use DD/MM/YYYY or 'na'.")


async def newitem_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new item conversation (via /newitem or button)."""
    # if started from button, use the callback's message
    msg = update.message
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        msg = q.message

    context.user_data.clear()
    await msg.reply_text(
        "🧾 What item are you donating?\n"
        "Example: 'Gloves' or 'Hand Sanitiser'."
    )
    return ITEM


async def ask_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["item"] = update.message.text.strip()
    await update.message.reply_text(
        "📦 How many boxes or units are available?\nExample: 5"
    )
    return QTY


async def ask_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    try:
        qty = int(txt)
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a positive whole number.")
        return QTY

    context.user_data["qty"] = qty
    await update.message.reply_text(
        "📏 What is the size/volume?\n"
        "Type 'na' if not applicable."
    )
    return SIZE


async def ask_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    size_txt = update.message.text.strip()
    context.user_data["size"] = (
        size_txt if size_txt.lower() not in ("na", "n/a") else "Not applicable"
    )

    await update.message.reply_text(
        "⏰ Enter expiry date (DD/MM/YYYY) or type 'na' if not applicable."
    )
    return EXPIRY


async def handle_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    try:
        context.user_data["expiry"] = parse_expiry(txt)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return EXPIRY

    await update.message.reply_text("📍 Where is the pickup location?")
    return LOCATION


async def ask_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["location"] = update.message.text.strip()
    await update.message.reply_text(
        "📸 Please send a photo of the item, or type 'skip' to continue without a photo."
    )
    return PHOTO


async def save_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    context.user_data["photo_id"] = photo.file_id
    return await confirm_post(update, context)


async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["photo_id"] = None
    return await confirm_post(update, context)


async def confirm_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    caption = (
        "📝 <b>Confirm Your Listing</b>\n\n"
        f"🧾 <b>Item:</b> {html.escape(str(d.get('item')))}\n"
        f"📦 <b>Quantity:</b> {d.get('qty')}\n"
        f"📏 <b>Size:</b> {html.escape(str(d.get('size')))}\n"
        f"⏰ <b>Expiry:</b> {html.escape(str(d.get('expiry')))}\n"
        f"📍 <b>Location:</b> {html.escape(str(d.get('location')))}\n"
        f"📸 <b>Photo:</b> {'Attached' if d.get('photo_id') else 'None'}\n\n"
        "Post this to the channel?"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Post", callback_data="confirm_post"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_post"),
            ]
        ]
    )

    if update.message:  # came from text or photo
        if d.get("photo_id") and update.message.photo:
            # Already sent as photo; just send text preview
            await update.message.reply_text(
                caption, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
        else:
            await update.message.reply_text(
                caption, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
    else:
        # from callback
        q = update.callback_query
        await q.message.reply_text(
            caption, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )

    return CONFIRM


async def cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_text("❌ Listing cancelled. Start again with /newitem.")
    else:
        await update.message.reply_text("❌ Listing cancelled. Start again with /newitem.")
    context.user_data.clear()
    return ConversationHandler.END


async def do_post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize listing and post to channel."""
    q = update.callback_query
    await q.answer()

    d = context.user_data
    user = update.effective_user

    listing_data = {
        "user_id": user.id,
        "user_name": user.full_name,
        "item": d.get("item"),
        "qty": int(d.get("qty")),
        "size": d.get("size"),
        "expiry": d.get("expiry"),
        "location": d.get("location"),
        "photo_id": d.get("photo_id"),
    }

    listing_id = create_listing(listing_data)
    if not listing_id:
        await q.edit_message_text("❌ Failed to create listing. Please try again.")
        return ConversationHandler.END

    # Build channel text
    text = (
        f"🆕 <b>New Item Available</b>\n\n"
        f"🧾 <b>Item:</b> {html.escape(str(listing_data['item']))}\n"
        f"📦 <b>Quantity:</b> {listing_data['qty']}\n"
        f"📏 <b>Size:</b> {html.escape(str(listing_data['size']))}\n"
        f"⏰ <b>Expiry:</b> {html.escape(str(listing_data['expiry']))}\n"
        f"📍 <b>Location:</b> {html.escape(str(listing_data['location']))}\n\n"
        f"Posted by: {html.escape(user.full_name)}"
    )

    claim_url = f"https://t.me/{context.bot.username}?start=claim_{listing_id}"
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🤝 Claim", url=claim_url)]]
    )

    try:
        if listing_data["photo_id"]:
            msg = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=listing_data["photo_id"],
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            msg = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

        # Save channel message id
        save_listing(
            listing_id,
            {
                "channel_message_id": msg.message_id,
            },
        )

        await q.edit_message_text(
            "✅ Your item has been listed in the channel!\n\n"
            "Thank you for contributing to sustainability ♻️"
        )
    except Exception as e:
        logger.error(f"Error posting to channel: {e}")
        await q.edit_message_text(
            "❌ Failed to post to channel. Please try again later."
        )

    context.user_data.clear()
    return ConversationHandler.END


# ========= CLAIM FLOW =========
async def private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle DM text – mainly claim qty & time."""
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    # If user is in a claim flow
    step = context.user_data.get("claim_step")
    if not step:
        # Generic help
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📝 List New Item", callback_data="newitem_btn")],
                [InlineKeyboardButton("📚 Instructions", callback_data="help_info")],
            ]
        )
        await update.message.reply_text(
            "Hi! Use /newitem to list items, or tap a Claim button in the channel to request an item.",
            reply_markup=keyboard,
        )
        return

    text = update.message.text.strip()

    # --- Step 1: quantity ---
    if step == "qty":
        try:
            qty = int(text)
            if qty <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Please enter a positive whole number for the quantity."
            )
            return

        max_qty = context.user_data.get("max_qty", 0)
        if qty > max_qty:
            await update.message.reply_text(
                f"❌ Only {max_qty} units are available. Please enter a number between 1 and {max_qty}."
            )
            return

        context.user_data["claim_qty"] = qty
        context.user_data["claim_step"] = "time"

        await update.message.reply_text(
            "🕓 When can you collect?\n"
            "Example: 'Tomorrow 3–5 pm' or '25 Nov, 10 am'."
        )
        return

    # --- Step 2: pickup time ---
    if step == "time":
        pickup_time = text
        listing_id = context.user_data.get("claim_listing_id")
        qty = context.user_data.get("claim_qty")

        listing = get_listing(listing_id) if listing_id else None
        if not listing:
            await update.message.reply_text(
                "❌ This listing is no longer available. Please try another item."
            )
            context.user_data.clear()
            return

        # Check remaining again (in case someone else claimed)
        remaining = int(listing.get("remaining", 0) or 0)
        if remaining < qty or listing.get("status") != "available":
            await update.message.reply_text(
                "❌ Not enough remaining stock to fulfil your request."
            )
            context.user_data.clear()
            return

        buyer = update.effective_user
        seller_id = listing.get("user_id")

        # Build claim object (pending)
        claim = {
            "user_id": buyer.id,
            "username": buyer.username or buyer.full_name,
            "qty": qty,
            "pickup_time": pickup_time,
            "status": "pending",
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }

        claims: List[Dict[str, Any]] = listing.get("claims") or []
        claims.append(claim)
        claim_index = len(claims) - 1

        # Save to Firebase
        save_listing(
            listing_id,
            {
                "claims": claims,
            },
        )

        # Notify seller
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Approve",
                        callback_data=f"approve|{listing_id}|{buyer.id}|{qty}|{pickup_time}",
                    ),
                    InlineKeyboardButton(
                        "❌ Reject",
                        callback_data=f"reject|{listing_id}|{buyer.id}|{qty}|{pickup_time}",
                    ),
                ]
            ]
        )

        item_name = listing.get("item", "Item")
        try:
            await context.bot.send_message(
                chat_id=seller_id,
                text=(
                    "📨 <b>New Claim Request</b>\n\n"
                    f"🧾 <b>Item:</b> {html.escape(str(item_name))}\n"
                    f"🔢 <b>Quantity:</b> {qty}\n"
                    f"👤 <b>From:</b> @{buyer.username or buyer.full_name}\n"
                    f"⏰ <b>Pickup:</b> {html.escape(pickup_time)}\n\n"
                    "Please approve or reject:"
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        except Exception as e:
            logger.error(f"Error notifying seller: {e}")

        await update.message.reply_text(
            "✅ Your request has been sent to the donor. "
            "You’ll be notified once they approve or reject."
        )
        context.user_data.clear()
        return


async def handle_claim_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seller approves or rejects a claim."""
    q = update.callback_query
    await q.answer()

    try:
        action, listing_id, user_id_str, qty_str, pickup_time = q.data.split("|", 4)
        user_id = int(user_id_str)
        qty = int(qty_str)
    except Exception:
        await q.edit_message_text("❌ Invalid action.")
        return

    listing = get_listing(listing_id)
    if not listing:
        await q.edit_message_text("❌ Listing no longer exists.")
        return

    remaining = int(listing.get("remaining", 0) or 0)
    item_name = listing.get("item", "Item")

    if action == "approve":
        if remaining < qty:
            await q.edit_message_text(
                "⚠️ Not enough remaining stock to approve this claim."
            )
            return

        remaining -= qty
        status = "available" if remaining > 0 else "claimed"

        # Append an approved claim entry
        claims: List[Dict[str, Any]] = listing.get("claims") or []
        claims.append(
            {
                "user_id": user_id,
                "qty": qty,
                "pickup_time": pickup_time,
                "status": "approved",
                "timestamp": datetime.datetime.utcnow().isoformat(),
            }
        )

        save_listing(
            listing_id,
            {
                "remaining": remaining,
                "status": status,
                "claims": claims,
            },
        )

        # Update channel post
        await update_channel_post(context, listing_id)

        # Notify buyer
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"✅ Your claim for <b>{html.escape(str(item_name))}</b> "
                    f"({qty} units) has been <b>approved</b>!\n\n"
                    f"⏰ Pickup: {html.escape(pickup_time)}\n"
                    f"📍 Location: {html.escape(str(listing.get('location', 'N/A')))}"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Error notifying buyer: {e}")

        await q.edit_message_text(
            f"✅ Approved {qty} × {item_name} for user ID {user_id}."
        )

    elif action == "reject":
        # Append a rejected claim entry (optional)
        claims: List[Dict[str, Any]] = listing.get("claims") or []
        claims.append(
            {
                "user_id": user_id,
                "qty": qty,
                "pickup_time": pickup_time,
                "status": "rejected",
                "timestamp": datetime.datetime.utcnow().isoformat(),
            }
        )
        save_listing(listing_id, {"claims": claims})

        # Notify buyer
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"❌ Your claim for <b>{html.escape(str(item_name))}</b> "
                    f"({qty} units) was rejected by the donor."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Error notifying buyer: {e}")

        await q.edit_message_text("❌ Claim rejected.")


# ========= ERROR HANDLER =========
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update:", exc_info=context.error)


# ========= CONVERSATION HANDLER =========
conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("newitem", newitem_entry),
        CallbackQueryHandler(newitem_entry, pattern="^newitem_btn$"),
    ],
    states={
        ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_qty)],
        QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_size)],
        SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_expiry)],
        EXPIRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_expiry)],
        LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_photo)],
        PHOTO: [
            MessageHandler(filters.PHOTO, save_photo),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.Regex("(?i)^skip$"),
                skip_photo,
            ),
        ],
        CONFIRM: [
            CallbackQueryHandler(do_post_to_channel, pattern="^confirm_post$"),
            CallbackQueryHandler(cancel_post, pattern="^cancel_post$"),
        ],
    },
    fallbacks=[CallbackQueryHandler(cancel_post, pattern="^cancel_post$")],
)


# ========= APP SETUP =========
async def set_commands(app: Application):
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Show main menu"),
            BotCommand("newitem", "List a new item"),
            BotCommand("instructions", "How the bot works"),
        ]
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("instructions", instructions))
    app.add_handler(conv_handler)

    # DM text handler (claim flow & generic help)
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_message
        )
    )

    # Claim decision buttons
    app.add_handler(
        CallbackQueryHandler(handle_claim_decision, pattern="^(approve|reject)\|")
    )

    # Inline buttons for help/newitem
    app.add_handler(CallbackQueryHandler(instructions, pattern="^help_info$"))
    app.add_handler(CallbackQueryHandler(newitem_entry, pattern="^newitem_btn$"))

    app.add_error_handler(error_handler)
    app.post_init = set_commands

    logger.info("🤖 Bot starting with Firebase persistence (clean version)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
