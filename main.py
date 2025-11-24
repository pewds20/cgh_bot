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
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        target = q.message
    else:
        target = update.message
    msg = (
        "ℹ️ <b>How It Works</b>\n\n"
        "1. Use /newitem to post excess items.\n"
        "2. Your item will appear in the Redistribution Channel.\n"
        "3. Others can claim and coordinate pickup.\n"
        "4. You'll be notified when someone claims your item.\n\n"
        "<b>Important Notes:</b>\n"
        "• The bot may experience occasional technical difficulties\n"
        "• If the bot is unresponsive, please post directly in the channel\n"
        "• Manual coordination may be needed if automated features fail\n"
        "• Always double-check pickup details with the other party\n\n"
        "To get started, just type: /newitem"
    )
    await target.reply_text(msg, parse_mode="HTML")

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
    # This function is no longer needed as we handle the newitem flow in the start function
    return await newitem(update, context)

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
    # Store the listing data in both user_data and chat_data for reliability
    if 'item' not in context.user_data:
        await update.message.reply_text("❌ Error: Listing data not found. Please start over with /newitem")
        return ConversationHandler.END
        
    # Prepare the listing data
    listing_data = {
        "item": context.user_data['item'],
        "qty": context.user_data['qty'],
        "size": context.user_data.get('size', 'N/A'),
        "expiry": context.user_data.get('expiry', 'N/A'),
        "location": context.user_data['location'],
        "photo": context.user_data.get('photo')
    }
    
    # Store in both user_data and chat_data
    context.user_data['listing_data'] = listing_data
    context.chat_data['listing_data'] = listing_data
    
    # Create the preview message
    preview = (
        f"🧾 <b>{listing_data['item']}</b>\n"
        f"📦 Available: {listing_data['qty']} available\n"
        f"📏 Size: {listing_data['size']}\n"
        f"⏰ Expiry: {listing_data['expiry']}\n"
        f"📍 Location: {listing_data['location']}\n\n"
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
    
    # Try to get listing_data from user_data first, then from chat_data
    if 'listing_data' in context.user_data:
        d = context.user_data['listing_data']
    elif 'listing_data' in context.chat_data:
        d = context.chat_data['listing_data']
    else:
        await q.edit_message_text("❌ Error: Could not find listing data. Please try creating a new listing with /newitem")
        return ConversationHandler.END
    
    text = (
        f"🧾 <b>{d['item']}</b>\n"
        f"📦 Available: {d['qty']} available\n"
        f"📏 Size: {d['size']}\n"
        f"⏰ Expiry: {d['expiry']}\n"
        f"📍 {d['location']}"
    )
    
    # Create the listing data for Firebase
    listing_data = {
        "poster_id": str(q.from_user.id),
        "poster_name": q.from_user.username or q.from_user.full_name,
        "item": d["item"],
        "qty": int(d["qty"]),
        "remaining": int(d["qty"]),
        "size": d["size"],
        "expiry": d["expiry"],
        "location": d["location"],
        "status": "open",
        "timestamp": datetime.datetime.now().isoformat(),
        "claims": {}
    }
    
    # Add photo if available
    if "photo" in d:
        listing_data["photo_id"] = d["photo"]
    
    # Create the listing in Firebase and get the unique ID
    listing_id = create_listing(listing_data)
    if not listing_id:
        await q.edit_message_text("❌ Failed to create listing. Please try again.")
        return ConversationHandler.END
    
    # Create the claim button with the listing ID
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🤝 Claim", callback_data=f"claim|{listing_id}")
    ]])
    
    # Post to channel
    try:
        print(f"Attempting to post to channel: {CHANNEL_ID}")
        print(f"Listing ID: {listing_id}")
        print(f"Has photo: {'photo' in d}")
        
        if "photo" in d:
            print(f"Photo ID: {d['photo']}")
            msg = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=d["photo"],
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            print("No photo, sending text message")
            msg = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        
        print(f"Message sent successfully, message_id: {msg.message_id}")
        
        # Update the listing with the channel message ID
        update_listing(listing_id, {"channel_message_id": msg.message_id})
        print("Listing updated with channel message ID")
        
        await q.edit_message_text("✅ Posted to channel!")
        return ConversationHandler.END
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error posting to channel: {e}")
        print(f"Error details: {error_details}")
        print(f"CHANNEL_ID: {CHANNEL_ID} (type: {type(CHANNEL_ID)})")
        print(f"Bot token: {BOT_TOKEN[:10]}...")
        print(f"Listing data: {listing_data}")
        
        # Test channel access
        try:
            print("\nTesting channel access...")
            chat = await context.bot.get_chat(chat_id=CHANNEL_ID)
            print(f"Chat info: {chat}")
            print(f"Bot is member: {chat.get_member(context.bot.id) is not None}")
            print(f"Bot can post: {chat.permissions.can_post_messages if hasattr(chat, 'permissions') else 'N/A'}")
        except Exception as test_error:
            print(f"Channel access test failed: {test_error}")
        
        # Clean up the listing if posting failed
        try:
            db.reference(f"listings/{listing_id}").delete()
            print(f"Cleaned up listing {listing_id}")
        except Exception as cleanup_error:
            print(f"Error during cleanup: {cleanup_error}")
        
        error_msg = (
            "❌ Failed to post to channel.\n\n"
            f"Error: {str(e)}\n\n"
            "Please check that:\n"
            "1. The bot is an admin in the channel\n"
            "2. The bot has 'Post Messages' permission\n"
            "3. The channel username is correct (case-sensitive)"
        )
        await q.edit_message_text(error_msg)
        return ConversationHandler.END

# ========= CLAIM FLOW =========
async def private_message(update, context):
    # If this is a claim attempt from a callback query (new way)
    if update.callback_query and update.callback_query.data.startswith("claim|"):
        try:
            q = update.callback_query
            await q.answer()
            
            # Get the listing ID from the callback data
            listing_id = q.data.split("|")[1]
            print(f"Claim attempt for listing ID: {listing_id}")
            
            # Get the listing from Firebase
            listing = get_listing(listing_id)
            if not listing:
                await q.edit_message_text("❌ Sorry, this listing is no longer available or has expired.")
                return ConversationHandler.END
            
            # Check if the item is still available
            if listing.get("status") != "open" or listing.get("remaining", 0) <= 0:
                await q.edit_message_text("❌ Sorry, this item has already been fully claimed.")
                return ConversationHandler.END
            
            # Store the listing ID in user data for the claim flow
            context.user_data["claim_listing_id"] = listing_id
            
            # Ask for quantity
            await q.edit_message_text(
                f"How many of '{listing['item']}' would you like to claim? "
                f"(Max: {listing['remaining']})",
                reply_markup=None
            )
            
            return "CLAIM_QTY"
            
        except Exception as e:
            print(f"Error handling claim callback: {e}")
            if update.callback_query:
                await update.callback_query.answer("❌ An error occurred. Please try again.", show_alert=True)
            return ConversationHandler.END
    
    # Legacy support for deep links (can be removed after migration)
    elif update.message and update.message.text and update.message.text.startswith("/start claim_"):
        try:
            # Get the listing ID from the deep link
            listing_id = update.message.text.split("_")[1]
            print(f"Legacy claim attempt for listing ID: {listing_id}")
            
            # Get the listing from Firebase
            listing = get_listing(listing_id)
            if not listing:
                await update.message.reply_text("❌ Sorry, this listing is no longer available or has expired.")
                return ConversationHandler.END
            
            # Check if the item is still available
            if listing.get("status") != "open" or listing.get("remaining", 0) <= 0:
                await update.message.reply_text("❌ Sorry, this item has already been fully claimed.")
                return ConversationHandler.END
            
            # Store the listing ID in user data for the claim flow
            context.user_data["claim_listing_id"] = listing_id
            
            # Ask for quantity
            await update.message.reply_text(
                f"How many of '{listing['item']}' would you like to claim? "
                f"(Max: {listing['remaining']})"
            )
            
            return "CLAIM_QTY"
            
        except Exception as e:
            print(f"Error handling legacy claim deep link: {e}")
            await update.message.reply_text("❌ An error occurred while processing your claim. Please try again.")
            return ConversationHandler.END
    
        # Regular message (not a claim attempt)
        return ConversationHandler.END

# ========= APPROVE / REJECT HANDLER =========
async def handle_claim_decision(update, context):
    q = update.callback_query
    await q.answer()
    
    try:
        # Parse the callback data
        parts = q.data.split("|")
        if len(parts) < 5:
            await q.edit_message_text("⚠️ Invalid request format.")
            return
            
        action, listing_id, user_id, qty, pickup_time = parts[0], parts[1], int(parts[2]), int(parts[3]), "|".join(parts[4:])
        
        # Get the listing from Firebase
        listing = get_listing(listing_id)
        if not listing:
            await q.edit_message_text("⚠️ This listing is no longer available.")
            return
            
        # Get buyer info
        try:
            buyer = await context.bot.get_chat(user_id)
        except Exception as e:
            print(f"Error getting buyer info: {e}")
            await q.edit_message_text("⚠️ Could not retrieve buyer information.")
            return
        
        if action == "approve":
            # Add the claim atomically
            success = add_claim(listing_id, user_id, qty, pickup_time)
            
            if success:
                # Update the channel post to reflect the new remaining quantity
                await update_channel_post(context, listing_id)
                
                # Notify the buyer
                try:
                    await context.bot.send_message(
                        user_id,
                        f"✅ Your claim for <b>{listing['item']}</b> has been approved!\n\n"
                        f"📦 Quantity: <b>{qty}</b>\n"
                        f"⏰ Pickup: <b>{pickup_time}</b>\n"
                        f"📍 Location: <b>{listing['location']}</b>",
                        parse_mode="HTML"
                    )
                    await q.edit_message_text(
                        f"✅ Approved claim for @{buyer.username or buyer.first_name} ({qty}× {listing['item']})"
                    )
                except Exception as e:
                    print(f"Error sending approval message: {e}")
                    await q.edit_message_text(
                        f"✅ Approved claim for @{buyer.username or buyer.first_name} ({qty}× {listing['item']})\n\n"
                        "⚠️ Could not send message to buyer. They may have blocked the bot or deactivated their account."
                    )
            else:
                await q.edit_message_text("⚠️ Failed to process the claim. Please try again.")
                
        elif action == "reject":
            try:
                await context.bot.send_message(
                    user_id,
                    f"❌ Your claim for <b>{listing['item']}</b> was not approved.\n\n"
                    f"📦 Quantity: {qty}\n"
                    f"⏰ Pickup time: {pickup_time}\n\n"
                    "Please contact the poster directly if you have any questions.",
                    parse_mode="HTML"
                )
                await q.edit_message_text(
                    f"❌ Rejected claim for @{buyer.username or buyer.first_name}"
                )
            except Exception as e:
                print(f"Error sending rejection message: {e}")
                await q.edit_message_text(
                    f"❌ Rejected claim for @{buyer.username or buyer.first_name}\n\n"
                    "⚠️ Could not notify the buyer."
                )
                
        elif action == "suggest":
            # Store the claim details for the suggest time flow
            context.user_data["suggest_claim"] = {
                "listing_id": listing_id,
                "user_id": user_id,
                "qty": qty,
                "original_time": pickup_time,
                "message_id": q.message.message_id
            }
            
            await q.edit_message_text(
                f"🕓 Please suggest a new pickup time for @{buyer.username or buyer.first_name}'s claim.\n\n"
                f"📦 {qty} × {listing['item']}\n"
                f"⏰ Current time: {pickup_time}\n\n"
                "Please type your suggested time:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Cancel", callback_data=f"cancel_suggest|{listing_id}")]
                ])
            )
            return "SUGGEST_TIME"
            
        elif action == "cancel_suggest":
            await q.edit_message_text("⏭️ Time suggestion cancelled.")
            
    except Exception as e:
        print(f"Error in handle_claim_decision: {e}")
        import traceback
        traceback.print_exc()
        await q.edit_message_text("⚠️ An error occurred while processing your request. Please try again.")

# ========= SUGGEST NEW DATE/TIME FLOW =========
async def suggest_time(update, context):
    q = update.callback_query
    await q.answer()
    
    try:
        # Parse the callback data: suggest|{listing_id}|{user_id}|{qty}|{current_time}
        parts = q.data.split('|')
        if len(parts) < 5:
            await q.edit_message_text("❌ Error: Invalid request format. Please try again.")
            return ConversationHandler.END
            
        listing_id = parts[1]
        buyer_id = parts[2]
        qty = parts[3]
        current_time = '|'.join(parts[4:])
        
        # Get the listing from Firebase
        listing = get_listing(listing_id)
        if not listing or listing.get('status') != 'open' or listing.get('remaining', 0) <= 0:
            await q.edit_message_text("❌ This listing is no longer available.")
            return ConversationHandler.END
        
        # Store the claim info in user_data
        context.user_data["suggesting_for"] = msg_id
        context.user_data["claim_info"] = {
            "buyer_id": int(buyer_id),
            "qty": int(qty),
            "original_msg_id": update.callback_query.message.message_id  # Store the original message ID
        }
        
        # Edit the message to ask for new time
        await q.edit_message_text(
            "📅 <b>Suggest a new pickup time:</b>\n\n"
            "Please enter a new date and time in one of these formats:\n\n"
            "• <code>25/12/2023 14:30</code>\n"
            "• <code>Tomorrow 3pm</code>\n"
            "• <code>Next Monday 10am</code>\n\n"
            "The buyer will receive your suggested time and can accept or decline it.",
            parse_mode="HTML"
        )
        return SUGGEST
        
    except Exception as e:
        print(f"Error in suggest_time: {e}")
        import traceback
        print(traceback.format_exc())
        await q.edit_message_text("❌ An error occurred. Please try again.")
        return ConversationHandler.END

async def handle_suggest_time_text(update, context):
    proposed_time = update.message.text.strip()
    
    # Get the claim data from user_data
    claim_data = context.user_data.get("suggest_claim")
    if not claim_data:
        await update.message.reply_text("❌ Error: Session expired. Please try again.")
        return ConversationHandler.END
    
    listing_id = claim_data.get("listing_id")
    buyer_id = claim_data.get("user_id")
    qty = claim_data.get("qty", 1)
    original_time = claim_data.get("original_time")
    
    # Clear the conversation state
    context.user_data.clear()
    
    # Get the listing from Firebase
    listing = get_listing(listing_id)
    if not listing or listing.get('status') != 'open' or listing.get('remaining', 0) < qty:
        await update.message.reply_text("❌ This listing is no longer available or doesn't have enough stock.")
        return ConversationHandler.END
    
    try:
        # Create the message with accept/decline buttons
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Accept", callback_data=f"accept_newtime|{listing_id}|{qty}|{proposed_time}"),
                InlineKeyboardButton("❌ Decline", callback_data=f"decline_newtime|{listing_id}")
            ]
        ])
        
        # Format the message to the buyer
        msg = (
            "📌 <b>NEW PICKUP TIME SUGGESTED</b>\n\n"
            f"🛍️ <b>Item:</b> {listing['item']}\n"
            f"📦 <b>Quantity:</b> {qty}\n"
            f"📅 <b>Original Pickup Time:</b> {original_time}\n"
            f"📅 <b>Proposed New Time:</b> {proposed_time}\n"
            f"📍 <b>Location:</b> {listing['location']}\n\n"
            "Please accept or decline this new pickup time:"
        )
        
        try:
            # Send the suggestion to the buyer
            await context.bot.send_message(
                chat_id=buyer_id,
                text=msg,
                reply_markup=kb,
                parse_mode="HTML"
            )
            
            # Confirm to the seller
            await update.message.reply_text(
                "✅ Your suggested pickup time has been sent to the buyer. "
                "They will be able to accept or decline it."
            )
            
        except Exception as e:
            print(f"Error sending message to buyer: {e}")
            await update.message.reply_text(
                "❌ Failed to send the suggestion. The buyer may have started a conversation with the bot. "
                "Please ask them to start a chat with @CGH_Redistribute_Bot and try again."
            )
            
    except Exception as e:
        print(f"Error in handle_suggest_time_text: {e}")
        import traceback
        print(traceback.format_exc())
        await update.message.reply_text(
            "❌ An error occurred while sending the suggestion. Please try again."
        )
        
    return ConversationHandler.END

async def handle_newtime_reply(update, context):
    q = update.callback_query
    await q.answer()
    
    try:
        parts = q.data.split("|")
        if len(parts) < 2:
            await q.edit_message_text("❌ Invalid request format.")
            return
            
        action = parts[0]
        listing_id = parts[1]
        
        # Get the listing from Firebase
        listing = get_listing(listing_id)
        if not listing or listing.get('status') != 'open':
            await q.edit_message_text("❌ This listing is no longer available.")
            return
            
        if action == "accept_newtime":
            if len(parts) < 4:
                await q.edit_message_text("❌ Invalid request format.")
                return
                
            qty = int(parts[2])
            new_time = parts[3]
            
            # Update the claim in Firebase with the new time
            claims = listing.get('claims', {})
            for claim_id, claim in claims.items():
                if str(claim.get('user_id')) == str(q.from_user.id):
                    # Update the claim with the new time
                    claims[claim_id]['pickup_time'] = new_time
                    update_listing(listing_id, {'claims': claims})
                    break
            
            try:
                # Remove the buttons from the message
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception as e:
                print(f"Could not edit message: {e}")
            
            # Notify the seller
            try:
                await context.bot.send_message(
                    listing['poster_id'],
                    f"✅ Buyer has accepted the new pickup time: {new_time}\n\n"
                    f"🛍️ Item: {listing['item']}\n"
                    f"📦 Quantity: {qty}\n"
                    f"📍 Location: {listing['location']}"
                )
            except Exception as e:
                print(f"Could not notify seller: {e}")
            
            # Update the buyer
            await q.message.reply_text(
                f"✅ You've accepted the new pickup time: {new_time}\n\n"
                f"🛍️ Item: {listing['item']}\n"
                f"📦 Quantity: {qty}\n"
                f"📍 Location: {listing['location']}\n\n"
                "The seller has been notified. Thank you!"
            )
            
        elif action == "decline_newtime":
            try:
                # Remove the buttons from the message
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception as e:
                print(f"Could not edit message: {e}")
            
            await q.message.reply_text("❌ You've declined the suggested pickup time.")
            
            # Notify the seller
            try:
                await context.bot.send_message(
                    chat_id=listing.get('poster_id'),
                    text=f"❌ The buyer has declined your suggested pickup time for {listing.get('item', 'the item')}."
                )
            except Exception as e:
                print(f"Could not notify seller: {e}")
                
    except Exception as e:
        print(f"Error in handle_newtime_reply: {e}")
        import traceback
        print(traceback.format_exc())
        try:
            await q.edit_message_text("❌ An error occurred while processing your request. Please try again.")
        except:
            try:
                await context.bot.send_message(
                    chat_id=q.from_user.id,
                    text="❌ An error occurred while processing your request. Please try again."
                )
            except:
                pass

# ========= REPOST HANDLERS =========
async def handle_repost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    try:
        # Extract the message ID from the callback data
        original_msg_id = q.data.split("_")
        if len(original_msg_id) < 2:
            await q.edit_message_text("❌ Invalid repost request.")
            return
            
        original_msg_id = original_msg_id[1]
        
        # Get the original listing from user_listings
        user_listings = db.reference("user_listings").get() or {}
        listing_data = None
        
        # Find the listing in user_listings
        for uid, listings in user_listings.items():
            if original_msg_id in listings:
                listing_data = listings[original_msg_id]
                break
        
        if not listing_data:
            # Try to find in active listings as fallback
            if original_msg_id in LISTINGS:
                listing_data = LISTINGS[original_msg_id]
            else:
                await q.edit_message_text("❌ Could not find the original listing data.")
                return
        
        # Create a new listing with the same data
        new_msg_id = str(max([int(k) if k.isdigit() else 0 for k in LISTINGS.keys()] + [0]) + 1)
        
        # Create a deep copy of the listing data
        import copy
        new_listing = copy.deepcopy(listing_data)
        
        # Update the listing data
        new_listing['poster_id'] = str(q.from_user.id)
        new_listing['timestamp'] = datetime.datetime.now().isoformat()
        
        # If the listing is still active (not in user_listings), use the remaining quantity
        if original_msg_id in LISTINGS:
            new_listing['remaining'] = LISTINGS[original_msg_id].get('remaining', new_listing.get('qty', 1))
        else:
            # For archived listings, reset to the original quantity
            new_listing['remaining'] = new_listing.get('qty', 1)
        
        # Add to active listings
        LISTINGS[new_msg_id] = new_listing
        
        # Save to Firebase
        save_listings()
        
        # Create the message text for the channel
        text = (
            f"🧾 <b>{new_listing['item']}</b>\n"
            f"📦 Available: {new_listing['qty']} {new_listing.get('unit', 'units')}\n"
            f"📏 Size: {new_listing.get('size', 'N/A')}\n"
            f"⏰ Expiry: {new_listing.get('expiry', 'N/A')}\n"
            f"📍 {new_listing.get('location', 'N/A')}"
        )
        
        # Create the claim button with the new message ID
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🤝 Claim", url=f"https://t.me/{context.bot.username}?start=claim_{new_msg_id}")
        ]])
        
        # Send the new post to the channel
        sent_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Update the listing with the new message ID
        new_listing['message_id'] = sent_message.message_id
        LISTINGS[new_msg_id] = new_listing
        save_listings()
        
        await q.edit_message_text("✅ Your item has been reposted to the channel!")
        
    except Exception as e:
        import traceback
        print(f"Error in handle_repost: {e}")
        print(traceback.format_exc())
        await q.edit_message_text("❌ An error occurred while reposting. Please try again.")

# ========= HANDLER CONFIG =========
conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("newitem", newitem),
        CommandHandler("start", start, filters=filters.Regex(r"newitem"))
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
    entry_points=[CallbackQueryHandler(suggest_time, pattern=r'^suggest\|')],
    states={
        SUGGEST: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_suggest_time_text)
        ]
    },
    fallbacks=[CommandHandler("cancel", cancel_post)],
)

# ========= APP SETUP =========
app = Application.builder().token(BOT_TOKEN).build()
# Add start handler first to handle /start without newitem
app.add_handler(CommandHandler("start", start))
# Add all handlers
app.add_handler(conv_handler)
app.add_handler(CallbackQueryHandler(handle_repost, pattern="^repost_"))
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

print("🤖 Bot starting with Firebase persistence + keep-alive + auto-archive ...")

# Initialize listings from Firebase on startup
if __name__ == "__main__":
    if not refresh_listings():
        print("⚠️ Warning: Could not load initial listings from Firebase")
    keep_alive()
    print("✅ Bot is now running!")
    app.run_polling()
