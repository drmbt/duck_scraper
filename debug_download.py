"""
Debug script to download a single Telegram message and show all relevant info.
Usage: python debug_download.py https://t.me/channelname/123
"""

import os
from dotenv import load_dotenv
import argparse
from telethon import TelegramClient
import asyncio
import re

# Parse arguments
parser = argparse.ArgumentParser(description='Download a single Telegram message and show debug info')
parser.add_argument('url', help='Telegram message URL (e.g., https://t.me/channelname/123)')
args = parser.parse_args()

# Load environment variables
load_dotenv()
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')

# Parse URL
match = re.match(r'https?://t\.me/([^/]+)/(\d+)', args.url)
if not match:
    raise ValueError("Invalid Telegram URL format. Expected: https://t.me/channelname/123")
channel_username, message_id = match.groups()
message_id = int(message_id)

async def main():
    print(f"Attempting to download message {message_id} from {channel_username}")
    
    # Initialize client
    async with TelegramClient('debug_session', api_id, api_hash) as client:
        try:
            # Get the channel
            channel = await client.get_entity(channel_username)
            print(f"\nChannel info:")
            print(f"ID: {channel.id}")
            print(f"Title: {channel.title}")
            print(f"Username: {channel.username}")
            
            # Get the message
            message = await client.get_messages(channel, ids=message_id)
            if not message:
                print(f"Message {message_id} not found!")
                return
                
            print(f"\nMessage info:")
            print(f"ID: {message.id}")
            print(f"Date: {message.date}")
            print(f"Has media: {bool(message.media)}")
            print(f"Media type: {type(message.media).__name__ if message.media else None}")
            
            if message.photo:
                print(f"\nPhoto info:")
                print(f"Photo ID: {message.photo.id}")
                print(f"Access hash: {message.photo.access_hash}")
                print(f"File reference: {message.photo.file_reference}")
                print(f"DC ID: {message.photo.dc_id}")
                
                print("\nAvailable sizes:")
                for size in message.photo.sizes:
                    print(f"- Type: {size.type}, Dimensions: {getattr(size, 'w', '?')}x{getattr(size, 'h', '?')}, Size: {getattr(size, 'size', '?')} bytes")
            
            if message.media:
                # Try to download
                print("\nAttempting download...")
                filename = f"debug_download_{message_id}.jpg"
                result = await client.download_media(message.media, filename)
                
                if result:
                    print(f"Successfully downloaded to: {result}")
                    file_size = os.path.getsize(result)
                    print(f"File size: {file_size} bytes")
                else:
                    print("Download failed!")
            
            # Show reactions if any
            if hasattr(message, 'reactions') and message.reactions:
                print("\nReactions:")
                for reaction in message.reactions.results:
                    print(f"- {reaction.reaction.emoticon}: {reaction.count}")
                
        except Exception as e:
            print(f"\nError: {str(e)}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 