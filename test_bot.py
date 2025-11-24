import asyncio
from telegram import Bot

async def test_bot():
    bot = Bot(token='8377427445:AAE-H_EiGAjs4NKE20v9S8zFLOv2AiHKcpU')
    
    try:
        # Get bot info
        me = await bot.get_me()
        print(f"Bot username: @{me.username}")
        print(f"Bot ID: {me.id}")
        
        # Test channel access
        channel_username = "@Sustainability_Redistribution"
        print(f"\nTesting access to channel: {channel_username}")
        
        try:
            # Try to get chat info
            chat = await bot.get_chat(channel_username)
            print(f"Channel title: {chat.title}")
            print(f"Channel ID: {chat.id}")
            print(f"Channel type: {chat.type}")
            
            # Try to get bot's member status
            try:
                member = await chat.get_member(me.id)
                print(f"\nBot's member status:")
                print(f"Status: {member.status}")
                print(f"Can post messages: {member.can_post_messages if hasattr(member, 'can_post_messages') else 'N/A'}")
            except Exception as e:
                print(f"\nError getting member status: {e}")
                print("The bot might not be an admin in the channel")
            
            # Try to send a test message
            try:
                print("\nAttempting to send a test message...")
                msg = await bot.send_message(
                    chat_id=channel_username,
                    text="🔧 This is a test message from the bot. You can delete this message."
                )
                print(f"✅ Success! Message ID: {msg.message_id}")
                
                # Try to delete the test message
                try:
                    await bot.delete_message(chat_id=channel_username, message_id=msg.message_id)
                    print("✅ Successfully deleted test message")
                except Exception as e:
                    print(f"⚠️ Could not delete test message: {e}")
                    
            except Exception as e:
                print(f"❌ Failed to send test message: {e}")
                print("\nPossible reasons:")
                print("1. The bot is not an admin in the channel")
                print("2. The bot doesn't have 'Post Messages' permission")
                print("3. The channel username is incorrect")
                print("4. The bot was recently added as admin - try removing and re-adding it")
                
        except Exception as e:
            print(f"❌ Error accessing channel: {e}")
            print("\nPossible solutions:")
            print("1. Make sure the channel is public")
            print("2. Make sure you're using the correct channel username (case-sensitive)")
            print("3. Try using the channel ID instead of username")
            
    except Exception as e:
        print(f"❌ General error: {e}")
    
    print("\nTest completed.")

# Run the test
if __name__ == "__main__":
    asyncio.run(test_bot())
