import asyncio
from telegram import Bot
import os

# Use the same configuration as in main.py
BOT_TOKEN = os.getenv("BOT_TOKEN", "8377427445:AAE-H_EiGAjs4NKE20v9S8zFLOv2AiHKcpU")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Sustainability_Redistribution")

async def test_channel_access():
    print("🚀 Starting channel access test...")
    print(f"Bot Token: {BOT_TOKEN[:10]}...")
    print(f"Channel ID: {CHANNEL_ID}")
    
    bot = Bot(token=BOT_TOKEN)
    
    try:
        # Get bot info
        me = await bot.get_me()
        print(f"\n🤖 Bot Info:")
        print(f"Username: @{me.username}")
        print(f"ID: {me.id}")
        print(f"Name: {me.full_name}")
        
        # Test channel access
        print("\n🔍 Testing channel access...")
        try:
            chat = await bot.get_chat(chat_id=CHANNEL_ID)
            print(f"✅ Successfully accessed channel:")
            print(f"   Title: {chat.title}")
            print(f"   Type: {chat.type}")
            print(f"   ID: {chat.id}")
            
            # Check bot's admin status
            print("\n👑 Checking admin status...")
            try:
                member = await chat.get_member(me.id)
                print(f"   Status: {member.status}")
                if hasattr(member, 'can_post_messages'):
                    print(f"   Can post messages: {member.can_post_messages}")
                if hasattr(member, 'can_edit_messages'):
                    print(f"   Can edit messages: {member.can_edit_messages}")
            except Exception as e:
                print(f"❌ Could not get member status: {e}")
            
            # Test sending a message
            print("\n✉️  Testing message sending...")
            try:
                msg = await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text="🔧 This is a test message from the bot. Please ignore.",
                    parse_mode="HTML"
                )
                print(f"✅ Success! Message ID: {msg.message_id}")
                
                # Try to delete the test message
                try:
                    await bot.delete_message(chat_id=CHANNEL_ID, message_id=msg.message_id)
                    print("✅ Successfully deleted test message")
                except Exception as e:
                    print(f"⚠️ Could not delete test message: {e}")
                    print("This is normal if the bot doesn't have delete permissions.")
                    
            except Exception as e:
                print(f"❌ Failed to send message: {e}")
                print("\nPossible solutions:")
                print("1. Make sure the bot is an admin in the channel")
                print("2. Check that the bot has 'Post Messages' permission")
                print("3. Verify the channel username is correct (case-sensitive)")
                print("4. Try using the channel's numeric ID instead of the username")
                print("5. If you recently added the bot as admin, try removing and re-adding it")
                
        except Exception as e:
            print(f"❌ Failed to access channel: {e}")
            print("\nPossible solutions:")
            print("1. Make sure the channel is public")
            print("2. Check that the channel username is correct")
            print("3. Try using the channel's numeric ID instead of the username")
            print("4. Make sure the bot is added to the channel")
            
    except Exception as e:
        print(f"❌ General error: {e}")
    
    print("\nTest completed.")

# Run the test
if __name__ == "__main__":
    asyncio.run(test_channel_access())
