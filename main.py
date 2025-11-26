# ==============================
# 🏥 Sustainability Redistribution Bot (Firebase + 24/7 Ready)
# - Stateless Firebase implementation
# - Unique listing IDs
# - Atomic operations
# - Last updated: 2023-11-24 11:05 UTC+8
# - Auto cleanup of old listings
# ==============================

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, 
    ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters
)
import os, datetime, calendar, json, time
from pathlib import Path
from flask import Flask
from threading import Thread
import os
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
    # Use waitress as production server for better performance
    from waitress import serve
    serve(app_keepalive, host='0.0.0.0', port=port, threads=4)

# Global variable to track if the keep-alive thread is running
_keep_alive_thread = None

def keep_alive():
    global _keep_alive_thread
    # Only start the keep-alive server if not running in a worker process
    # and if the thread hasn't been started yet
    if os.environ.get('WORKER') != '1' and (_keep_alive_thread is None or not _keep_alive_thread.is_alive()):
        _keep_alive_thread = Thread(target=run, daemon=True)
        _keep_alive_thread.start()

# ========= CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN", "8377427445:AAE-H_EiGAjs4NKE20v9S8zFLOv2AiHKcpU")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Sustainability_Redistribution")  # Make sure to include the @ symbol

# Conversation states
(ITEM, QTY, SIZE, EXPIRY, LOCATION, PHOTO, CONFIRM, SUGGEST, CLAIM_QTY, CLAIM_DATE, CLAIM_CONFIRM) = range(11)

# ========= CHANNEL POST UPDATER =========
async def update_channel_post(context: ContextTypes.DEFAULT_TYPE, listing_id: str):
    """Update the channel post with current listing status."""
    try:
        listing = get_listing(listing_id)
        if not listing:
            print(f"Listing {listing_id} not found")
            return False
            
        # Calculate remaining quantity
        claimed = sum(claim.get('qty', 0) for claim in listing.get('claims', []))
        remaining = listing.get('qty', 1) - claimed
        
        # Prepare the message text
        text = (
            f"🧾 <b>{html.escape(listing['item'])}</b>\n"
            f"📦 Quantity: {listing['qty']} (Remaining: {remaining})\n"
            f"📏 Size: {html.escape(listing.get('size', 'N/A'))}\n"
            f"⏰ Expiry: {html.escape(listing.get('expiry', 'N/A'))}\n"
            f"📍 {html.escape(listing.get('location', 'N/A'))}"
        )
        
        # Add claim button if there are remaining items
        if remaining > 0:
            if listing.get('status') == 'available':
                keyboard = [
                    [InlineKeyboardButton("🤝 Claim", callback_data=f"claim|{listing_id}")]
                ]
            else:
                keyboard = []
        else:
            text += "\n\n✅ <b>Fully Claimed!</b>"
            keyboard = []
            
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        # Try to update the message
        try:
            await context.bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=int(listing_id),
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Failed to update caption: {e}")
            try:
                await context.bot.edit_message_text(
                    chat_id=CHANNEL_ID,
                    message_id=int(listing_id),
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            except Exception as e2:
                print(f"Failed to update message text: {e2}")
                
    except Exception as e:
        print(f"Error in update_channel_post: {e}")
        return False

# ========= CLAIM WORKFLOW =========
async def start_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the claim process when someone clicks the claim button."""
    try:
        query = update.callback_query
        await query.answer()
        
        # Extract listing ID from callback data (format: "claim|listing_id")
        _, listing_id = query.data.split('|')
        listing = get_listing(listing_id)
        
        if not listing:
            await query.edit_message_text("❌ This listing is no longer available.")
            return ConversationHandler.END
            
        if listing.get('status') not in ['available', 'open']:
            await query.answer("❌ This item has already been claimed.", show_alert=True)
            return ConversationHandler.END
        
        # Calculate remaining quantity
        claimed = sum(claim.get('qty', 0) for claim in listing.get('claims', []))
        remaining = listing['qty'] - claimed
        
        if remaining <= 0:
            await query.answer("❌ This item is no longer available.", show_alert=True)
            return ConversationHandler.END
        
        # Store listing ID and max quantity in user data
        context.user_data['claim_listing_id'] = listing_id
        context.user_data['max_qty'] = remaining
        context.user_data['listing_item'] = listing['item']  # Store item name for later use
        
        # Ask for quantity
        await query.message.reply_text(
            f"📦 You're claiming: {listing['item']}\n"
            f"How many units would you like to claim? (Max: {remaining})",
            reply_markup=ReplyKeyboardRemove()
        )
        return CLAIM_QTY
        
    except Exception as e:
        print(f"Error in start_claim: {e}")
        try:
            await query.answer("❌ An error occurred. Please try again.", show_alert=True)
        except:
            pass
        return ConversationHandler.END

async def claim_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the quantity input for the claim."""
    try:
        qty = int(update.message.text)
        max_qty = context.user_data.get('max_qty', 1)
        
        if qty < 1 or qty > max_qty:
            await update.message.reply_text(
                f"❌ Please enter a number between 1 and {max_qty}."
            )
            return CLAIM_QTY
            
        context.user_data['claim_qty'] = qty
        
        # Ask for preferred pickup date
        await update.message.reply_text(
            "📅 When would you like to pick up the item?\n"
            "Please enter your preferred date and time (e.g., \"2023-12-01 14:30\" or \"tomorrow 5pm\"):"
        )
        
        return CLAIM_DATE
        
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number.")
        return CLAIM_QTY

async def claim_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the pickup date input and send claim request to seller."""
    try:
        pickup_time = update.message.text
        listing_id = context.user_data.get('claim_listing_id')
        qty = context.user_data.get('claim_qty', 1)
        listing = get_listing(listing_id)
        
        if not listing:
            await update.message.reply_text("❌ This listing is no longer available.")
            return ConversationHandler.END
        
        # Store the proposed time in user data
        context.user_data['proposed_time'] = pickup_time
        
        # Ask if they want to propose a different quantity
        max_available = listing.get('remaining', 1)
        await update.message.reply_text(
            f"You've requested {qty} units with pickup time: {pickup_time}\n\n"
            f"Would you like to propose a different quantity? (Current: {qty} units, Max: {max_available})\n"
            f"Please enter a new quantity or click 'Done' to proceed with {qty} units.",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton('Done')]], 
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
        
        return CLAIM_CONFIRM
        
    except Exception as e:
        print(f"Error in claim_date: {e}")
        await update.message.reply_text("❌ An error occurred while processing your request. Please try again.")
        return ConversationHandler.END

async def confirm_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle quantity confirmation or update."""
    try:
        user_input = update.message.text
        listing_id = context.user_data.get('claim_listing_id')
        current_qty = context.user_data.get('claim_qty', 1)
        max_qty = context.user_data.get('max_qty', 1)
        proposed_time = context.user_data.get('proposed_time')
        
        listing = get_listing(listing_id)
        if not listing:
            await update.message.reply_text("❌ This listing is no longer available.")
            return ConversationHandler.END
        
        # If user entered a number, update the quantity
        if user_input.isdigit():
            new_qty = int(user_input)
            if 1 <= new_qty <= max_qty:
                context.user_data['claim_qty'] = new_qty
                current_qty = new_qty
                await update.message.reply_text(f"✅ Quantity updated to {new_qty} units.")
            else:
                await update.message.reply_text(
                    f"❌ Please enter a number between 1 and {max_qty} or click 'Done'."
                )
                return CLAIM_CONFIRM
        
        # Create claim request
        claim_data = {
            'user_id': update.effective_user.id,
            'username': update.effective_user.username or update.effective_user.full_name,
            'qty': current_qty,
            'pickup_time': proposed_time,
            'status': 'pending',
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'proposed_qty': current_qty,  # Store the proposed quantity
            'original_qty': listing.get('remaining', 1)  # Store the original available quantity
        }
        
        # Add claim to listing
        listing_ref = listings_ref.child(listing_id)
        listing = listing_ref.get()
        
        if not listing:
            await update.message.reply_text("❌ Error processing your claim. Please try again.")
            return ConversationHandler.END
            
        # Initialize claims list if it doesn't exist
        if 'claims' not in listing:
            listing['claims'] = []
            
        # Add new claim
        listing['claims'].append(claim_data)
        
        # Update listing in database
        listing_ref.update({
            'claims': listing['claims'],
            'remaining': listing.get('qty', 1) - sum(c.get('qty', 0) for c in listing['claims'] if c.get('status') == 'approved')
        })
        
        # Notify buyer
        await update.message.reply_text(
            "✅ Your claim request has been sent to the seller!\n"
            "The seller will review your request and get back to you soon."
        )
        
        # Notify seller
        try:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_claim|{listing_id}|{len(listing['claims']) - 1}"),
                    InlineKeyboardButton("🔄 Suggest New Time", callback_data=f"suggest_time|{listing_id}|{len(listing['claims']) - 1}")
                ],
                [
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_claim|{listing_id}|{len(listing['claims']) - 1}")
                ]
            ])
            
            await context.bot.send_message(
                chat_id=listing['user_id'],
                text=(
                    f"📨 New Claim Request!\n\n"
                    f"Item: {listing['item']}\n"
                    f"Quantity: {qty}\n"
                    f"Requested by: @{update.effective_user.username or update.effective_user.full_name}\n"
                    f"Preferred pickup time: {pickup_time}\n\n"
                    f"Please choose an action:"
                ),
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"Error notifying seller: {e}")
        
        return ConversationHandler.END
        
    except Exception as e:
        print(f"Error in claim_date: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again.")
        return ConversationHandler.END

# ========= CLAIM ACTIONS =========
async def handle_claim_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle claim actions (approve/reject/suggest time)."""
    query = update.callback_query
    await query.answer()
    
    action, listing_id, claim_idx = query.data.split('|')
    listing = get_listing(listing_id)
    
    if not listing or 'claims' not in listing or int(claim_idx) >= len(listing['claims']):
        await query.edit_message_text("❌ This claim request is no longer valid.")
        return
    
    claim = listing['claims'][int(claim_idx)]
    
    if action == 'approve_claim':
        # Update claim status
        listing['claims'][int(claim_idx)]['status'] = 'approved'
        listing['remaining'] = listing.get('qty', 1) - sum(
            c.get('qty', 0) for c in listing['claims'] 
            if c.get('status') == 'approved'
        )
        
        # Update listing in database
        listings_ref.child(listing_id).update({
            'claims': listing['claims'],
            'remaining': listing['remaining'],
            'status': 'available' if listing['remaining'] > 0 else 'claimed'
        })
        
        # Notify seller
        await query.edit_message_text(
            f"✅ You've approved the claim for {claim['qty']} units.\n"
            f"Pickup time: {claim['pickup_time']}"
        )
        
        # Notify buyer
        try:
            await context.bot.send_message(
                chat_id=claim['user_id'],
                text=(
                    f"✅ Your claim for {claim['qty']} units of '{listing['item']}' has been approved!\n\n"
                    f"📅 Pickup time: {claim['pickup_time']}\n"
                    f"📍 Location: {listing.get('location', 'N/A')}\n\n"
                    f"Please contact the seller if you have any questions."
                )
            )
        except Exception as e:
            print(f"Error notifying buyer: {e}")
            
    elif action == 'reject_claim':
        # Update claim status
        listing['claims'][int(claim_idx)]['status'] = 'rejected'
        listings_ref.child(listing_id).update({'claims': listing['claims']})
        
        # Notify seller
        await query.edit_message_text("❌ You've rejected the claim request.")
        
        # Notify buyer
        try:
            await context.bot.send_message(
                chat_id=claim['user_id'],
                text=f"❌ Your claim for {listing['item']} has been rejected by the seller."
            )
        except Exception as e:
            print(f"Error notifying buyer: {e}")
    
    # Update channel post
    await update_channel_post(context, listing_id)

# ========= SUGGEST TIME =========
async def suggest_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the suggest time conversation."""
    query = update.callback_query
    await query.answer()
    
    _, listing_id, claim_idx = query.data.split('|')
    context.user_data['suggest_listing_id'] = listing_id
    context.user_data['suggest_claim_idx'] = int(claim_idx)
    
    await query.edit_message_text(
        "⌛ Please suggest a new pickup time for the buyer:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Cancel", callback_data=f"cancel_suggest|{listing_id}|{claim_idx}")
        ]])
    )
    
    return SUGGEST

async def handle_suggest_time_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the suggested time input."""
    new_time = update.message.text
    listing_id = context.user_data.get('suggest_listing_id')
    claim_idx = context.user_data.get('suggest_claim_idx')
    
    if not listing_id or claim_idx is None:
        await update.message.reply_text("❌ Error processing your suggestion. Please try again.")
        return ConversationHandler.END
    
    listing = get_listing(listing_id)
    if not listing or 'claims' not in listing or claim_idx >= len(listing['claims']):
        await update.message.reply_text("❌ This claim request is no longer valid.")
        return ConversationHandler.END
    
    # Update the suggested time
    claim = listing['claims'][claim_idx]
    claim['suggested_time'] = new_time
    claim['status'] = 'time_suggested'
    
    # Update in database
    listing_ref = listings_ref.child(listing_id)
    listing_ref.update({'claims': listing['claims']})
    
    # Notify seller
    await update.message.reply_text("✅ Your suggested time has been sent to the buyer.")
    
    # Notify buyer
    try:
        await context.bot.send_message(
            chat_id=claim['user_id'],
            text=(
                f"🔄 The seller has suggested a new pickup time for your claim on '{listing['item']}':\n\n"
                f"📅 New suggested time: {new_time}\n\n"
                f"Please respond with either:\n"
                f"✅ 'Accept' - To accept the new time\n"
                f"❌ 'Reject' - To reject the suggestion"
            )
        )
    except Exception as e:
        print(f"Error notifying buyer: {e}")
    
    return ConversationHandler.END

# ========= CANCEL =========
async def cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the post creation operation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✅ Post creation cancelled.")
    return ConversationHandler.END

async def cancel_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the suggest time operation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Time suggestion cancelled.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allow the user to cancel the current operation."""
    await update.message.reply_text(
        'Operation cancelled. Type /start to begin again.',
        reply_markup=ReplyKeyboardRemove()
    )
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
        "👋 <b>Welcome to the Sustainability Redistribution Bot</b>\n\n"
        "This bot helps hospital staff share excess consumables easily.\n\n"
        "<b>Available Commands:</b>\n"
        "📦 /newitem - List an item for donation\n"
        "ℹ️ /instructions - How to use this bot\n\n"
        "<i>💡 Simply click the 'Claim' button under any item in the channel to request it.</i>"
    )
    
    await update.message.reply_text(msg, parse_mode="HTML")

async def channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📣 Open Channel", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")]])
    await update.message.reply_text("Open the redistribution channel:", reply_markup=keyboard)


async def instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instructions_text = (
        "<b>📋 How to List an Item for Donation</b>\n\n"
        "1. Type <b>/newitem</b> to start the listing process\n"
        "2. You'll be asked for the following details:\n"
        "   • <b>Item name</b>: What are you donating?\n"
        "   • <b>Quantity</b>: How many units/boxes?\n"
        "   • <b>Size/Volume</b>: (Type 'na' if not applicable)\n"
        "   • <b>Expiry date</b>: (If applicable, format: DD/MM/YYYY)\n"
        "   • <b>Location</b>: Where can it be picked up?\n"
        "   • <b>Photo</b>: Please provide a clear photo of the item\n\n"
        "3. Your item will be posted in the @Sustainability_Redistribution channel\n"
        "4. Others can claim items by clicking the 'Claim' button\n"
        "5. You'll be notified when someone claims your item\n\n"
        "<b>💡 Quick Start:</b> Just type <b>/newitem</b> to begin listing an item!\n\n"
        "<b>⚠️ Important Note:</b>\n"
        "• This bot may experience occasional technical difficulties.\n"
        "• If the bot is unresponsive, please post directly in the channel.\n"
        "• Manual coordination may be required if automated features fail.\n"
        "• Always verify pickup details with the other party."
    )
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            text=instructions_text,
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            text=instructions_text,
            parse_mode="HTML"
        )
    return ConversationHandler.END

# ========= NEW ITEM FLOW =========
# States are already defined at the top of the file

async def newitem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the new item listing flow."""
    # Clear any existing user data
    if 'user_data' in context.user_data:
        context.user_data.clear()
    
    # Get the message to reply to
    message = update.message
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    
    await message.reply_text(
        "📦 What item are you donating?\n"
        "Example: \"Gloves\" or \"Hand Sanitizer\"",
        parse_mode="Markdown"
    )
    return ITEM

async def ask_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store item name and ask for quantity."""
    context.user_data['item'] = update.message.text
    await update.message.reply_text(
        "🔢 How many boxes or units are available?\n"
        "Example: \"5\" or \"10\"",
        parse_mode="Markdown"
    )
    return QTY

async def ask_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store quantity and ask for size/description."""
    try:
        qty = int(update.message.text.strip())
        if qty <= 0:
            await update.message.reply_text("❌ Please enter a number greater than 0.")
            return QTY
        context.user_data['qty'] = qty
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number.")
        return QTY
    
    await update.message.reply_text(
        "📏 What is the size? (Type 'na' if not applicable)",
        parse_mode="Markdown"
    )
    return SIZE

async def ask_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store size/description and ask for expiry."""
    size = update.message.text.strip()
    context.user_data['size'] = size if size.lower() != 'na' else 'Not applicable'
    
    await update.message.reply_text(
        "📅 Enter expiry date (DD/MM/YYYY) or type 'na' if not applicable"
    )
    return EXPIRY

def _parse_expiry_text(text: str) -> str:
    """Parse and validate expiry date text."""
    t = text.strip()
    if t.upper() in ("NA", "N/A"):
        return "N/A"
    # Try DD/MM/YY then DD/MM/YYYY then YYYY-MM-DD
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(t, fmt).date()
            return dt.strftime("%d/%m/%y")
        except ValueError:
            continue
    raise ValueError("Invalid date format. Please use DD/MM/YY or YYYY-MM-DD")

async def handle_expiry_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store expiry and ask for location."""
    expiry_text = update.message.text.strip()
    try:
        context.user_data['expiry'] = _parse_expiry_text(expiry_text)
    except ValueError as e:
        await update.message.reply_text(f"❌ {str(e)}")
        return EXPIRY
    
    await update.message.reply_text(
        "📍 Where is the pickup location?"
    )
    return LOCATION

async def ask_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store location and ask for photo."""
    if update.message and update.message.text and update.message.text.strip().lower() == 'skip':
        # If user typed 'skip', go straight to confirmation
        return await skip_photo(update, context)
        
    location = update.message.text.strip() if update.message and update.message.text else context.user_data.get('location', '')
    if location:
        context.user_data['location'] = location
    
    keyboard = [[InlineKeyboardButton("⏩ Skip Photo", callback_data="skip_photo")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📸 Please send a photo of the item (or click 'Skip Photo' below)",
        reply_markup=reply_markup
    )
    return PHOTO

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle skipping the photo upload."""
    context.user_data['photo_id'] = None
    
    # Prepare the confirmation message with disclaimer
    item_info = (
        f"📝 *Confirm Your Listing*\n\n"
        f"*Item:* {context.user_data.get('item', 'N/A')}\n"
        f"*Quantity:* {context.user_data.get('qty', 'N/A')}\n"
        f"*Size/Weight:* {context.user_data.get('size', 'N/A')}\n"
        f"*Expiry:* {context.user_data.get('expiry', 'N/A')}\n"
        f"*Location:* {context.user_data.get('location', 'N/A')}\n"
        f"*Photo:* None\n\n"
        "⚠️ *Disclaimer:* By confirming, you agree that:\n"
        "• The item is in good condition and safe for use\n"
        "• You have the authority to donate this item\n"
        "• You'll arrange for pickup within 48 hours\n"
        "• You'll update the status if the item is no longer available\n\n"
        "*Please confirm if these details are correct:*"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data="confirm_post"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_post")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            text=item_info,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            text=item_info,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    return CONFIRM

async def save_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the photo and ask for confirmation."""
    photo = update.message.photo[-1]  # Get the highest resolution photo
    context.user_data['photo_id'] = photo.file_id
    
    # Prepare the confirmation message
    item_info = (
        f"📝 *Confirm Your Listing*\n\n"
        f"*Item:* {context.user_data.get('item', 'N/A')}\n"
        f"*Quantity:* {context.user_data.get('qty', 'N/A')}\n"
        f"*Size/Weight:* {context.user_data.get('size', 'N/A')}\n"
        f"*Expiry:* {context.user_data.get('expiry', 'N/A')}\n"
        f"*Location:* {context.user_data.get('location', 'N/A')}\n"
        f"*Photo:* ✅ (attached)\n\n"
        "Please confirm if these details are correct:"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data="confirm_post"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_post")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send the photo with the confirmation message
    await update.message.reply_photo(
        photo=photo.file_id,
        caption=item_info,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return CONFIRM

async def post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Post the listing to the channel."""
    query = update.callback_query
    await query.answer()
    
    user_data = context.user_data
    user = update.effective_user
    
    # Create the listing data
    listing_data = {
        'user_id': user.id,
        'user_name': user.full_name,
        'item': user_data.get('item'),
        'qty': user_data.get('qty'),
        'size': user_data.get('size'),
        'expiry': user_data.get('expiry'),
        'location': user_data.get('location'),
        'photo_id': user_data.get('photo_id'),
        'status': 'available',
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'claims': {}
    }
    
    try:
        # Save to Firebase
        listing_id = create_listing(listing_data)
        if not listing_id:
            await query.edit_message_text("❌ Failed to create listing. Please try again.")
            return ConversationHandler.END
        
        # Prepare the channel post
        post_text = (
            f"🆕 *New Item Available!*\n\n"
            f"*Item:* {listing_data['item']}\n"
            f"*Quantity:* {listing_data['qty']}\n"
            f"*Size/Weight:* {listing_data['size']}\n"
            f"*Expiry:* {listing_data['expiry']}\n"
            f"*Location:* {listing_data['location']}\n\n"
            f"Posted by: {user.full_name}"
        )
        
        # Create claim button
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤝 Claim", callback_data=f"claim|{listing_id}")]
        ])
        
        # Send to channel
        try:
            if 'photo_id' in listing_data and listing_data['photo_id']:
                message = await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=listing_data['photo_id'],
                    caption=post_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            else:
                message = await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=post_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            
            # Save the message ID to the listing
            update_listing(listing_id, {'channel_message_id': message.message_id})
            
        except Exception as e:
            print(f"Error posting to channel: {e}")
            await query.edit_message_text("❌ Failed to post to channel. Please try again.")
            return ConversationHandler.END
        
        await query.edit_message_text(
            "✅ Your item has been listed in the channel!\n\n"
            "Thank you for contributing to sustainability! ♻️"
        )
        return ConversationHandler.END
        
    except Exception as e:
        print(f"Error posting to channel: {e}")
        await query.edit_message_text(
            "❌ Sorry, there was an error posting your item. Please try again."
        )
        return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and handle them gracefully."""
    import traceback
    
    # Log the error before we try anything that might fail
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list)
    
    # Log the error
    print(f"An exception was raised: {context.error}")
    print(tb_string)
    
    # Try to notify the user
    try:
        if update and hasattr(update, 'effective_chat'):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ An error occurred while processing your request. Please try again."
            )
    except Exception as e:
        print(f"Error while sending error message: {e}")

# Conversation handler for new item listing
conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("newitem", newitem),
        CallbackQueryHandler(newitem, pattern="^newitem_btn$")
    ],
    states={
        ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_qty)],
        QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_size)],
        SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_expiry)],
        EXPIRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_expiry_text)],
        LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_photo)],
        PHOTO: [
            MessageHandler(filters.PHOTO, save_photo),
            CallbackQueryHandler(skip_photo, pattern="^skip_photo$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, ask_photo)
        ],
        CONFIRM: [
            CallbackQueryHandler(post_to_channel, pattern=r'^confirm_post$'),
            CallbackQueryHandler(cancel_post, pattern=r'^cancel_post$')
        ]
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False
)

async def suggest_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the suggest time conversation."""
    await update.message.reply_text(
        "⏰ Please suggest a new pickup time (e.g., 'Tomorrow at 2 PM' or 'Friday 3-5 PM'):"
    )
    return SUGGEST

async def handle_suggest_time_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the suggested time input."""
    suggested_time = update.message.text
    # In a real implementation, you would process the suggested time here
    # and notify the relevant users
    
    await update.message.reply_text(
        f"✅ Your suggested time '{suggested_time}' has been noted. The donor will be in touch!"
    )
    return ConversationHandler.END

# Conversation handler for suggesting pickup times
suggest_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(suggest_time, pattern=r'^suggest\|')
    ],
    states={
        SUGGEST: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_suggest_time_text)
        ]
    },
    fallbacks=[
        CallbackQueryHandler(cancel_post, pattern=r'^cancel_suggest\|')
    ],
    per_message=False
)

# ... (rest of the code remains the same)

# Initialize the application
app = (
    Application.builder()
    .token(BOT_TOKEN)
    .arbitrary_callback_data(True)  # Allow arbitrary callback data
    .build()
)

# Add all handlers
async def handle_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the claim button callback."""
    query = update.callback_query
    await query.answer()
    
    # Extract listing ID from callback data (format: "claim|listing_id")
    _, listing_id = query.data.split('|')
    user = update.effective_user
    
    try:
        # Get the listing from Firebase
        listing_ref = listings_ref.child(listing_id)
        listing = listing_ref.get()
        
        if not listing:
            await query.answer("❌ This listing no longer exists.", show_alert=True)
            return
            
        # Check if item is already claimed
        if listing.get('status') != 'available' and listing.get('status') != 'open':
            await query.answer("❌ This item has already been claimed.", show_alert=True)
            return
            
        # Add claim to the listing
        success = add_claim(
            listing_id=listing_id,
            user_id=user.id,
            qty=1,  # Default quantity to 1
            pickup_time="To be arranged"
        )
        
        if not success:
            await query.answer("❌ Failed to process claim. Please try again.", show_alert=True)
            return
            
        # Get updated listing
        updated_listing = get_listing(listing_id)
        if not updated_listing:
            await query.answer("❌ Error updating listing.", show_alert=True)
            return
        
        # Update the channel post
        await update_channel_post(context, listing_id)
        
        # Notify the user who claimed the item
        await query.answer("✅ You've claimed this item! The donor will contact you soon.", show_alert=True)
        
        # Notify the original poster
        try:
            await context.bot.send_message(
                chat_id=listing['user_id'],
                text=f"🎉 Your item '{listing['item']}' has been claimed by {user.full_name} ({user.id})! "
                     f"Please contact them to arrange for pickup."
            )
        except Exception as e:
            print(f"Failed to notify original poster: {e}")
            
        # Update the channel post to show it's claimed
        try:
            message_id = updated_listing.get('channel_message_id')
            if message_id:
                status_text = "✅ <b>Claimed by @" + (user.username or user.full_name) + "</b>"
                text = (
                    f"🧾 <b>{updated_listing.get('item', 'Item')}</b>\n"
                    f"{status_text}\n"
                    f"📏 Size: {updated_listing.get('size', 'N/A')}\n"
                    f"⏰ Expiry: {updated_listing.get('expiry', 'N/A')}\n"
                    f"📍 {updated_listing.get('location', 'N/A')}"
                )
                
                if 'photo_id' in updated_listing and updated_listing['photo_id']:
                    await context.bot.edit_message_caption(
                        chat_id=CHANNEL_ID,
                        message_id=message_id,
                        caption=text,
                        parse_mode="HTML"
                    )
                else:
                    await context.bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=message_id,
                        text=text,
                        parse_mode="HTML"
                    )
        except Exception as e:
            print(f"Error updating channel post after claim: {e}")
            
    except Exception as e:
        print(f"Error handling claim: {e}")
        await query.answer("❌ An error occurred while processing your claim. Please try again.", show_alert=True)

# Add all handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("instructions", instructions))
app.add_handler(CommandHandler("channel", channel))

# Handle claim workflow
app.add_handler(CallbackQueryHandler(instructions, pattern="^(help_info|back_to_start)$"))
app.add_handler(CallbackQueryHandler(handle_claim_action, pattern=r'^(approve_claim|reject_claim)\|'))
app.add_handler(CallbackQueryHandler(suggest_time, pattern=r'^suggest_time\|'))
app.add_handler(CallbackQueryHandler(cancel_suggest, pattern=r'^cancel_suggest\|'))

# Add direct handler for claim button
app.add_handler(CallbackQueryHandler(start_claim, pattern=r'^claim\|'))

# Claim conversation handler
claim_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_claim, pattern=r'^claim\|')
    ],
    states={
        CLAIM_QTY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, claim_quantity)
        ],
        CLAIM_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, claim_date)
        ],
        CLAIM_CONFIRM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_claim)
        ],
        SUGGEST: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_suggest_time_text)
        ]
    },
    fallbacks=[
        CommandHandler('cancel', cancel),
        CallbackQueryHandler(cancel_suggest, pattern=r'^cancel_suggest\|')
    ],
    per_message=False
)

# Add all conversation handlers
app.add_handler(conv_handler)  # Main conversation handler for listing items
app.add_handler(suggest_conv)  # For suggesting times
app.add_handler(claim_conv)    # For handling claims

# Handle channel posts
app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel))
async def private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle private messages that don't match any command."""
    await update.message.reply_text(
        "🤖 I'm the CGH Sustainability Bot! Here's what I can do:\n\n"
        "• /start - Show the main menu\n"
        "• /newitem - List a new item for donation\n"
        "• /instructions - Learn how to use the bot\n"
        "• /cancel - Cancel the current action"
    )

app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_message))
# Add error handler
app.add_error_handler(error_handler)

# Set up logging
import logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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
    
    # Start the keep-alive server in the main process
    keep_alive()
    
    # Run the bot in the main thread
    try:
        app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        print(f"Bot crashed with error: {e}")
        raise
    print("✅ Bot is now running!")
    app.run_polling()
