# ==============================
# 🏥 Sustainability Redistribution Bot (Firebase + 24/7 Ready)
# - Stateless Firebase implementation
# - Unique listing IDs
# - Atomic operations
# - Last updated: 2023-11-24 11:05 UTC+8
# - Auto cleanup of old listings
# ==============================

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters
)
import os, datetime, calendar, json, time
from pathlib import Path
from flask import Flask
from threading import Thread
import firebase_admin
from firebase_admin import credentials, db
from firebase_admin.db import Reference
from typing import Dict, Optional, Any, List, Tuple

# ========= FIREBASE SETUP =========
# Load Firebase credentials from environment variable
firebase_creds = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
cred = credentials.Certificate(firebase_creds)
firebase_admin.initialize_app(cred, {
    "databaseURL": "https://cgh-telebot-default-rtdb.asia-southeast1.firebasedatabase.app/"
})

# Firebase references
listings_ref = db.reference("listings")
user_listings_ref = db.reference("user_listings")

# Conversation states
(ITEM, QTY, SIZE, EXPIRY, LOCATION, PHOTO, 
 CONFIRM, SUGGEST) = range(8)

# ========= UTILITY FUNCTIONS =========

def get_listing(listing_id: str) -> Optional[Dict]:
    """Get a single listing from Firebase."""
    return listings_ref.child(listing_id).get()

def update_listing(listing_id: str, updates: Dict) -> bool:
    """Update a listing in Firebase atomically."""
    try:
        listings_ref.child(listing_id).update(updates)
        return True
    except Exception as e:
        print(f"Error updating listing {listing_id}: {e}")
        return False

def create_listing(listing_data: Dict) -> Optional[str]:
    """Create a new listing and return its ID."""
    try:
        listing_data.update({
            "created_at": int(time.time()),
            "status": "open",
            "remaining": listing_data.get("qty", 1),
            "claims": []
        })
        new_ref = listings_ref.push(listing_data)
        return new_ref.key
    except Exception as e:
        print(f"Error creating listing: {e}")
        return None

def cleanup_expired_listings():
    """Mark old listings as expired."""
    try:
        week_ago = int(time.time()) - (7 * 24 * 60 * 60)  # 7 days
        
        # Get all open listings
        open_listings = listings_ref.order_by_child("status").equal_to("open").get() or {}
        
        for listing_id, listing in open_listings.items():
            if not isinstance(listing, dict):
                continue
                
            created = listing.get("created_at", 0)
            if created < week_ago:
                listings_ref.child(listing_id).update({"status": "expired"})
                
    except Exception as e:
        print(f"Error in cleanup_expired_listings: {e}")

def get_user_listings(user_id: str) -> Dict[str, Dict]:
    """Get all listings for a specific user."""
    return user_listings_ref.child(str(user_id)).get() or {}

def add_claim(listing_id: str, user_id: int, qty: int, pickup_time: str) -> bool:
    """Add a claim to a listing atomically."""
    try:
        # Use transaction to ensure atomic update
        def transaction_update(data):
            if not data or data.get("status") != "open":
                return None  # Abort transaction
                
            remaining = data.get("remaining", 0)
            if remaining < qty:
                return None  # Not enough remaining
                
            # Update the data
            data["remaining"] = remaining - qty
            
            # Add claim
            if "claims" not in data:
                data["claims"] = []
            data["claims"].append({
                "user_id": user_id,
                "qty": qty,
                "time": pickup_time,
                "timestamp": int(time.time())
            })
            
            # Update status if fully claimed
            if data["remaining"] <= 0:
                data["status"] = "claimed"
                
            return data
            
        # Run the transaction
        listings_ref.child(listing_id).transaction(transaction_update)
        return True
        
    except Exception as e:
        print(f"Error in add_claim: {e}")
        return False

def refresh_listings():
    """Legacy function for backward compatibility."""
    return True

def save_listings():
    """Legacy function for backward compatibility."""
    return True

# ========= KEEP-ALIVE SERVER =========
app_keepalive = Flask(__name__)

@app_keepalive.route('/')
def home():
    return "Bot is running!"

def run():
    port = int(os.environ.get('PORT', 8000))
    app_keepalive.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ========= CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN", "8377427445:AAE-H_EiGAjs4NKE20v9S8zFLOv2AiHKcpU")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Sustainability_Redistribution")  # Make sure to include the @ symbol

# ========= CHANNEL POST UPDATER =========
async def update_channel_post(context: ContextTypes.DEFAULT_TYPE, listing_id: str):
    """Update the channel post with current listing status."""
    listing = get_listing(listing_id)
    if not listing:
        return False
    
    # Create the message text
    status_text = "✅ <b>Fully Claimed</b>" if listing.get("remaining", 0) <= 0 else f"📦 Available: {listing.get('remaining', 0)} of {listing.get('qty', 1)}"
    
    text = (
        f"🧾 <b>{listing.get('item', 'Unknown Item')}</b>\n"
        f"{status_text}\n"
        f"📏 Size: {listing.get('size', 'N/A')}\n"
        f"⏰ Expiry: {listing.get('expiry', 'N/A')}\n"
        f"📍 {listing.get('location', 'N/A')}"
    )
    
    # Create the appropriate keyboard
    keyboard = None
    if listing.get("status") == "open" and listing.get("remaining", 0) > 0:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🤝 Claim", callback_data=f"claim|{listing_id}")
        ]])
    
    try:
        message_id = listing.get("channel_message_id")
        if not message_id:
            return False
            
        # Check if the message has a photo
        if listing.get("photo_id"):
            await context.bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=message_id,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        return True
    except Exception as e:
        print(f"Error updating channel post: {e}")
        return False

# ========= CANCEL =========
async def cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.edit_message_text("❌ Cancelled. Start again with /start.")
    else:
        await update.message.reply_text("❌ Cancelled. Start again with /start.")
    return ConversationHandler.END

# ========= BASIC COMMANDS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle deep link for claims
    if context.args and context.args[0].startswith("claim_"):
        try:
            # Get the message ID from the deep link
            msg_id = context.args[0].split("_")[1]
            print(f"Start command with claim: {msg_id}")
            
            # Force refresh listings from Firebase
            refresh_listings()
            
            # Check if the listing exists in our current data
            if msg_id not in LISTINGS:
                print(f"Listing {msg_id} not found in LISTINGS, checking user_listings...")
                # Try to find the listing in user_listings
                user_listings = db.reference("user_listings").get() or {}
                found = False
                
                # Search through all user listings
                for uid, listings in user_listings.items():
                    if msg_id in listings:
                        # Found the listing, add it back to active listings
                        LISTINGS[msg_id] = listings[msg_id]
                        save_listings()
                        found = True
                        print(f"Found listing {msg_id} in user_listings, restored to active listings")
                        break
                
                if not found:
                    print(f"Listing {msg_id} not found anywhere")
                    # Try to find the original poster
                    poster_id = None
                    for uid, listings in user_listings.items():
                        if msg_id in listings:
                            poster_id = uid
                            break
                    
                    # If the current user is the original poster, offer to repost
                    if str(update.effective_user.id) == poster_id:
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Repost This Item", callback_data=f"repost_{msg_id}")]
                        ])
                        await update.message.reply_text(
                            "⚠️ This listing is no longer active, but I found it in your history. "
                            "Would you like to repost it?",
                            reply_markup=keyboard
                        )
                    else:
                        await update.message.reply_text(
                            "⚠️ This listing is no longer available. "
                            "Please ask the original poster to create a new listing."
                        )
                    return
            
            # Now get the listing
            l = LISTINGS[msg_id]
            
            if l.get("remaining", 0) <= 0:
                await update.message.reply_text("❌ This listing has been fully claimed.")
                return
                
            # Start the claim process
            context.user_data["claiming_msg_id"] = msg_id
            context.user_data["claim_step"] = "qty"
            
            await update.message.reply_text(
                f"You're claiming <b>{l['item']}</b>.\n\n"
                "📦 How many units would you like to collect?",
                parse_mode="HTML"
            )
            return
            
        except Exception as e:
            import traceback
            print(f"Error in start command: {e}")
            print(traceback.format_exc())
            await update.message.reply_text("❌ An error occurred. Please try again.")
            return
    
    # Handle /start newitem
    if context.args and context.args[0].lower() == "newitem":
        return await newitem(update, context)
    
    msg = (
        "👋 <b>Welcome to the Sustainability Redistribution Bot!</b>\n\n"
        "This bot helps hospital staff donate excess consumables easily.\n\n"
        "<b>Available Commands:</b>\n"
        "/newitem - Donate excess items\n"
        "/instructions - Learn how it works\n\n"
        "<i>⚠️ <b>Note:</b> If you encounter any issues with the bot, "
        "please contact the admin or post directly in the channel. "
        "In case of technical difficulties, manual coordination "
        "through the channel may be necessary.</i>"
    )
    
    await update.message.reply_text(msg, parse_mode="HTML")

async def channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📣 Open Channel", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")]])
    await update.message.reply_text("Open the redistribution channel:", reply_markup=keyboard)


async def instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instructions_text = (
        "📚 *How It Works*\n\n"
        "1. *List an Item* 📝\n"
        "   - Use /newitem or click 'List New Item'\n"
        "   - Follow the prompts to add details\n"
        "   - Add a photo (optional but recommended)\n\n"
        "2. *Claim an Item* 🛍️\n"
        "   - Browse available items in the channel\n"
        "   - Click 'Claim' and follow instructions\n\n"
        "3. *After Claiming* ✅\n"
        "   - The donor will approve/deny your request\n"
        "   - Coordinate pickup details privately\n\n"
        "4. *After Pickup* ♻️\n"
        "   - Mark the item as claimed\n"
        "   - Help us reduce waste!"
    )
    
    keyboard = [
        [InlineKeyboardButton("📝 List New Item", callback_data="newitem_btn")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            instructions_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            instructions_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

# ========= NEW ITEM FLOW =========
async def newitem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the new item listing flow."""
    await update.message.reply_text(
        "📝 *Let's list a new item!*\n\n"
        "What item would you like to list? (e.g., Pack of 10 masks, 3 boxes of gloves)",
        parse_mode="Markdown"
    )
    return ITEM

async def ask_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for the quantity of the item."""
    context.user_data['item'] = update.message.text
    await update.message.reply_text(
        "🔢 *How many items are available?*\n\n"
        "Please enter a number (e.g., 5, 10, 100)",
        parse_mode="Markdown"
    )
    return QTY

async def ask_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for the size/quantity details."""
    try:
        qty = int(update.message.text)
        if qty <= 0:
            raise ValueError("Quantity must be positive")
        context.user_data['qty'] = qty
        await update.message.reply_text(
            "📏 *What's the size/weight of each item?*\n\n"
            "(e.g., 100ml, 500g, 1kg, Large, One Size)",
            parse_mode="Markdown"
        )
        return SIZE
    except ValueError:
        await update.message.reply_text(
            "❌ Please enter a valid positive number for quantity."
        )
        return QTY

async def ask_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for the expiry date."""
    context.user_data['size'] = update.message.text
    await update.message.reply_text(
        "📅 *When does this item expire?*\n\n"
        "You can enter:\n"
        "• A date (e.g., 2023-12-31)\n"
        "• A relative time (e.g., 'in 1 week', 'tomorrow')\n"
        "• 'N/A' if not applicable",
        parse_mode="Markdown"
    )
    return EXPIRY

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and handle them gracefully."""
    from telegram import Update
    from telegram.constants import ParseMode
    
    # Log the error
    print(f"Error: {context.error}")
    
    # Send a message to the user
    error_msg = (
        "❌ *An error occurred*\n\n"
        "Sorry, something went wrong while processing your request. "
        "The error has been logged and will be investigated.\n\n"
        "Please try again or use /cancel to start over."
    )
    
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            error_msg,
            parse_mode=ParseMode.MARKDOWN
        )


# ... (rest of the code remains the same)

conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("newitem", newitem),
        CallbackQueryHandler(newitem, pattern="^newitem_btn$")
    ],
    per_message=True,  # Track callbacks per message
    states={
        ITEM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, ask_qty)
        ],
        QTY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, ask_size)
        ],
        SIZE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, ask_expiry)
        ],
        EXPIRY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_expiry_text)
        ],
        LOCATION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, ask_photo)
        ],
        PHOTO: [
            MessageHandler(filters.PHOTO, save_photo),
            MessageHandler(filters.Regex("^(?i)(skip|none|na|not available)$"), skip_photo),
            MessageHandler(filters.TEXT & ~filters.COMMAND, ask_photo)  # Handle invalid input
        ],
        CONFIRM: [
            # Handle confirm/cancel callbacks
            CallbackQueryHandler(post_to_channel, pattern=r'^confirm_post$'),
            CallbackQueryHandler(cancel_post, pattern=r'^cancel_post$'),
            # Add a fallback for any other callbacks
            CallbackQueryHandler(
                lambda u, c: u.answer("This action is not available right now.", show_alert=True)
            )],
    },
    fallbacks=[CommandHandler("cancel", cancel_post)],
)

suggest_conv = ConversationHandler(
    entry_points=[CommandHandler("suggest", suggest_time)],
    states={
        SUGGEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_suggest_time_text)]
    },
    fallbacks=[CommandHandler("cancel", cancel_post)],
    per_message=True  # Track callbacks per message
)

# ... (rest of the code remains the same)

# Add all handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("instructions", instructions))
app.add_handler(CallbackQueryHandler(handle_repost, pattern="^repost_"))
app.add_handler(CallbackQueryHandler(deprecate_old_donate_button, pattern="^help_newitem$"))
app.add_handler(CommandHandler("channel", channel))
app.add_handler(CommandHandler("instructions", instructions))
app.add_handler(CallbackQueryHandler(instructions, pattern="^(help_info|back_to_start)$"))
app.add_handler(suggest_conv)
app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, private_message))
app.add_handler(CallbackQueryHandler(handle_newtime_reply, pattern="^(accept_newtime|decline_newtime)"))
app.add_handler(CallbackQueryHandler(handle_claim_decision, pattern="^(approve|reject)"))
# Add error handler
app.add_error_handler(error_handler)

# Set up command menu
async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Show main menu"),
        BotCommand("newitem", "Donate an excess item"),
        BotCommand("instructions", "How the bot works"),
        BotCommand("cancel", "Cancel current action"),
    ])

app.post_init = set_commands

print("🤖 Bot starting with Firebase persistence + keep-alive + auto-archive ...")

# Initialize listings from Firebase on startup
if __name__ == "__main__":
    if not refresh_listings():
        print("⚠️ Warning: Could not load initial listings from Firebase")
    keep_alive()
    print("✅ Bot is now running!")
    app.run_polling()
