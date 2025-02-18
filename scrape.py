"""
Telegram Media Scraper

This script downloads media from a specified Telegram channel based on reactions.
It can download:
- All media that has any reactions
- Only media that you have personally reacted to
- Both of the above

Requirements:
- Python 3.6+
- Telegram API credentials (API_ID and API_HASH) in .env file
- Channel username in .env file

First Time Setup:
1. Get your Telegram API credentials:
   - Visit https://my.telegram.org/auth
   - Log in with your phone number
   - Go to 'API development tools'
   - Create a new application
   - Copy your API_ID and API_HASH

2. Create a .env file with your credentials:
   API_ID=your_api_id
   API_HASH=your_api_hash
   CHANNEL_USERNAME=target_channel_username
   
   Note: CHANNEL_USERNAME should be without the @ symbol

Usage:
    python scrape.py [options]

Options:
    --skip-all-reactions     Skip downloading media with any reactions
    --skip-my-reactions      Skip downloading media you reacted to
    --force-redownload       Force redownload of all files, even if they exist
                            (by default, existing files are skipped)
    --limit N               Limit downloads to N items (useful for testing)
    --clean                Delete all existing downloads and logs before starting

Examples:
    # Download both all-reacted and personally-reacted media (skipping existing files)
    python scrape.py

    # Download only 5 items for testing
    python scrape.py --limit 5

    # Download only media you reacted to (skipping existing files)
    python scrape.py --skip-all-reactions

    # Download only media with any reactions (skipping existing files)
    python scrape.py --skip-my-reactions

    # Force redownload of all files, even if they exist
    python scrape.py --force-redownload

    # Skip all downloads (useful for testing)
    python scrape.py --skip-all-reactions --skip-my-reactions

    # Delete all existing downloads and logs before starting
    python scrape.py --clean

Output Structure:
    downloads/
        all_reactions/      # Media with any reactions
        my_reactions/       # Media you personally reacted to
"""

import json
import os
from datetime import datetime, timezone
import time
from dotenv import load_dotenv
import argparse
import traceback
import asyncio
import re
from telethon import TelegramClient, events, errors
from telethon.tl.types import MessageMediaPhoto

# Constants
DOWNLOAD_DIRS = {
    'all_reactions': 'downloads/all_reactions',
    'my_reactions': 'downloads/my_reactions'
}

LOG_FILE = 'download_log.json'

# Argument parser
parser = argparse.ArgumentParser(description='Download media from Telegram channel based on reactions')
parser.add_argument('--skip-all-reactions', action='store_true', 
                   help='Skip downloading media with any reactions')
parser.add_argument('--skip-my-reactions', action='store_true',
                   help='Skip downloading media you reacted to')
parser.add_argument('--force-redownload', action='store_true',
                   help='Force redownload of all files, even if they exist')
parser.add_argument('--limit', type=int, 
                   help='Limit the number of downloads (useful for testing)')
parser.add_argument('--clean', action='store_true',
                   help='Delete all existing downloads and logs before starting')
args = parser.parse_args()

# Load environment variables
load_dotenv()

# Get credentials from environment variables
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
channel_username = os.getenv('CHANNEL_USERNAME')

# Validate environment variables
if not all([api_id, api_hash, channel_username]):
    raise ValueError("Please ensure all required environment variables are set in .env file")

def clean_workspace():
    """Delete all downloads and logs"""
    print("Cleaning workspace...")
    
    # Delete log files
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
        print(f"Deleted {LOG_FILE}")
    if os.path.exists(f"{LOG_FILE}.bak"):
        os.remove(f"{LOG_FILE}.bak")
        print(f"Deleted {LOG_FILE}.bak")
    
    # Clean download directories
    for dir_name, dir_path in DOWNLOAD_DIRS.items():
        if os.path.exists(dir_path):
            import shutil
            shutil.rmtree(dir_path)
            print(f"Cleaned {dir_path}")
        # Always create the directory
        os.makedirs(dir_path, exist_ok=True)
        print(f"Created {dir_path}")

# Clean if requested
if args.clean:
    clean_workspace()
else:
    # Create download directories if they don't exist
    for directory in DOWNLOAD_DIRS.values():
        if not os.path.exists(directory):
            os.makedirs(directory)

# Initialize the client
client = TelegramClient('session_name', api_id, api_hash)

def load_log_file():
    """Load existing log file if it exists"""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'messages' in data:
                    return data
        except (json.JSONDecodeError, KeyError):
            print("Invalid log file found, starting fresh")
    
    return {
        'last_scan_time': None,
        'messages': {},
        'last_successful_id': None  # Track last successfully downloaded message
    }

def save_log_file(log_data):
    """Save log file with download information"""
    # Create backup of existing log
    if os.path.exists(LOG_FILE):
        import shutil
        backup_name = f"{LOG_FILE}.bak"
        shutil.copy2(LOG_FILE, backup_name)
    
    # Save new log
    with open(LOG_FILE, 'w') as f:
        json.dump(log_data, f, indent=2)

def sanitize_filename(text, max_length=50):
    """
    Sanitize text for use in filenames:
    - Handle None values
    - Remove invalid characters
    - Replace spaces with underscores
    - Truncate to reasonable length
    - Remove newlines and extra spaces
    """
    if text is None:
        return 'unnamed'
        
    # Remove newlines and collapse multiple spaces
    text = ' '.join(str(text).split())
    # Remove invalid characters
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    # Replace spaces and other characters
    text = re.sub(r'[\s,]', '_', text)
    # Remove any resulting double underscores
    text = re.sub(r'_+', '_', text)
    # Truncate to max_length
    return text[:max_length] if text else 'untitled'

def debug_print_message(message):
    """Print all available attributes of a message object"""
    print("\nFull Message Debug Info:")
    print("=" * 50)
    for attr in dir(message):
        if not attr.startswith('_'):  # Skip private attributes
            try:
                value = getattr(message, attr)
                if not callable(value):  # Skip methods
                    print(f"{attr}: {value}")
            except Exception as e:
                print(f"{attr}: Error accessing - {e}")
    print("=" * 50)

async def get_qualified_messages(channel):
    log_data = load_log_file()
    
    # Initialize collection structures
    qualified = {
        'all_reactions': [],
        'my_reactions': []
    }
    
    # Initialize counters
    processed = 0
    found_qualifying = 0
    
    # Get total message count
    total_messages = await client.get_messages(channel, limit=0)
    print(f"Found {total_messages.total} total messages")
    
    # Find the most recent successful download
    last_id = None
    if log_data['messages']:
        successful_msgs = [
            int(msg_id) for msg_id, msg in log_data['messages'].items()
            if msg.get('downloaded', False)
        ]
        if successful_msgs:
            last_id = max(successful_msgs)
            print(f"Resuming scan from message ID: {last_id}")
        else:
            print("No previously downloaded messages found, starting fresh scan")
    
    print("\nScanning messages from oldest to newest...")
    
    # Get messages in chronological order (oldest first)
    async for message in client.iter_messages(channel, reverse=True):
        processed += 1
        if processed % 100 == 0:
            print(f"Scanning: {processed}/{total_messages.total} messages")
        
        # Skip already downloaded messages unless force redownload
        if not args.force_redownload and last_id and message.id <= last_id:
            continue
            
        if hasattr(message, 'reactions') and message.reactions and message.media:
            if isinstance(message.media, MessageMediaPhoto):
                # Get reply information
                reply_text = None
                reply_user_id = None
                reply_username = None
                reply_name = None
                
                if message.reply_to:
                    reply = await message.get_reply_message()
                    if reply:
                        reply_text = reply.text
                        if reply.sender:
                            reply_user_id = reply.sender.id
                            reply_username = getattr(reply.sender, 'username', None)
                            # Get the most readable name available
                            reply_name = (
                                getattr(reply.sender, 'first_name', '') + 
                                ' ' + 
                                getattr(reply.sender, 'last_name', '')
                            ).strip() or reply_username or str(reply_user_id)
                
                # Ensure we have valid text
                if not reply_text:
                    reply_text = "no_reply_text"
                
                # Format date without '20' prefix in year and only to minute precision
                msg_time = message.date.strftime("%y%m%d_%H%M")
                
                # Get reaction details and total
                reaction_details = []
                total_reactions = 0
                if hasattr(message.reactions, 'results'):
                    for reaction in message.reactions.results:
                        reaction_details.append({
                            'emoji': reaction.reaction.emoticon,
                            'count': reaction.count
                        })
                        total_reactions += reaction.count
                
                # Create base filename with proper text
                base_filename = (
                    f"{msg_time}_"
                    f"{sanitize_filename(reply_name or 'unnamed')}_"
                    f"r{total_reactions}_"
                    f"{sanitize_filename(reply_text)}"
                )
                
                message_info = {
                    'id': message.id,
                    'timestamp': msg_time,
                    'date_iso': message.date.isoformat(),
                    'url': f"https://t.me/{channel_username}/{message.id}",
                    # Reply information
                    'reply_text': reply_text,
                    'reply_user_id': reply_user_id,
                    'reply_username': reply_username,
                    'reply_name': reply_name,
                    # Reaction information
                    'has_reactions': bool(reaction_details),
                    'my_reaction': has_my_reaction(message),
                    'total_reactions': total_reactions,
                    'reactions': reaction_details,
                    # File information
                    'base_filename': base_filename
                }
                
                # Initialize download status
                message_info['downloaded'] = False
                
                # Store in log by message ID
                log_data['messages'][str(message.id)] = message_info
                
                if message_info['has_reactions'] and not args.skip_all_reactions:
                    qualified['all_reactions'].append(message_info)
                if message_info['my_reaction'] and not args.skip_my_reactions:
                    qualified['my_reactions'].append(message_info)
                
                if message_info['has_reactions'] or message_info['my_reaction']:
                    found_qualifying += 1
                    print(f"\nFound qualifying message ({found_qualifying}): {message.id}")
                    print(f"Has reactions: {message_info['has_reactions']}")
                    print(f"Has my reaction: {message_info['my_reaction']}")
                    print(f"Reply from: {message_info['reply_username'] or message_info['reply_user_id']}")
                    print(f"Reply text: {message_info['reply_text'][:100]}...")
                    # New way to format reactions
                    reaction_strings = [f"{r['emoji']}({r['count']})" for r in reaction_details]
                    print(f"Reactions: {', '.join(reaction_strings)}")
                    print(f"URL: {message_info['url']}")
                
                # Check download limit
                if args.limit and (len(qualified['all_reactions']) + len(qualified['my_reactions'])) >= args.limit:
                    print(f"\nReached download limit of {args.limit} items")
                    break
    
    # Update log file with new timestamp and messages
    log_data['last_scan_time'] = datetime.now(timezone.utc).isoformat()
    save_log_file(log_data)
    
    print(f"\nScan complete!")
    print(f"Processed {processed} messages")
    print(f"Found {found_qualifying} qualifying messages")
    print(f"- With any reactions: {len(qualified['all_reactions'])}")
    print(f"- With your reactions: {len(qualified['my_reactions'])}")
    
    return qualified

def has_my_reaction(message):
    """Check if the user has reacted to this message"""
    if hasattr(message, 'reactions') and message.reactions:
        if hasattr(message.reactions, 'recent_reactions'):
            return any(
                getattr(reaction, 'my', False)
                for reaction in message.reactions.recent_reactions
            )
    return False

async def download_reacted_media():
    # Connect to the channel
    channel = await client.get_entity(channel_username)
    
    # Load existing log if available
    log_data = load_log_file()
    
    # Get pre-scan of new messages
    qualified_messages = await get_qualified_messages(channel)
    
    print("\n=== Download Queue ===")
    print(f"Messages with reactions: {len(qualified_messages['all_reactions'])}")
    print(f"Messages with your reactions: {len(qualified_messages['my_reactions'])}")
    
    # Add limit warning if set
    if args.limit:
        print(f"\nNote: Download limit set to {args.limit} items")
        # Trim qualified messages to respect limit
        if not args.skip_all_reactions:
            qualified_messages['all_reactions'] = qualified_messages['all_reactions'][:args.limit]
        if not args.skip_my_reactions:
            qualified_messages['my_reactions'] = qualified_messages['my_reactions'][:args.limit]
    
    # Store results
    media_data = {
        'all_reactions': [],
        'my_reactions': []
    }
    
    failed_downloads = []
    processed_messages = 0
    skipped_existing = 0
    
    # Track downloaded files to avoid duplicates
    downloaded_files = {}
    
    # Track attempted downloads instead of failures
    attempted_downloads = []
    
    if not args.skip_all_reactions:
        print("\nProcessing messages with any reactions...")
        for msg_info in qualified_messages['all_reactions']:
            processed_messages += 1
            path = f'{DOWNLOAD_DIRS["all_reactions"]}/{msg_info["base_filename"]}.jpg'
            
            if os.path.exists(path) and not args.force_redownload:
                skipped_existing += 1
                print(f"Skipping existing file: {path}")
                downloaded_files[msg_info['id']] = path
                media_data['all_reactions'].append(msg_info)
                continue
                
            try:
                message = await client.get_messages(channel, ids=msg_info['id'])
                if not message:
                    raise Exception(f"Message {msg_info['id']} not found")
                
                if not message.media:
                    raise Exception("Message has no media")
                
                if not message.photo:
                    raise Exception("Message has no photo")
                
                # Print photo info for debugging
                print(f"\nFound photo in message {msg_info['id']}:")
                print(f"Photo ID: {message.photo.id}")
                print(f"DC ID: {message.photo.dc_id}")
                largest_size = max(message.photo.sizes, key=lambda x: getattr(x, 'size', 0))
                print(f"Using size: {largest_size.type} ({getattr(largest_size, 'w', '?')}x{getattr(largest_size, 'h', '?')}, {getattr(largest_size, 'size', '?')} bytes)")
                
                # Download using same method as debug script
                result = await client.download_media(
                    message.media,
                    file=path
                )
                
                if not result:
                    raise Exception("Download failed - no media returned")
                
                print(f"Downloaded ({processed_messages}/{len(qualified_messages['all_reactions'])}): {path}")
                file_size = os.path.getsize(path)
                print(f"File size: {file_size} bytes")
                
                # Track the attempt and ensure message info is in log_data
                log_data['messages'][str(msg_info['id'])] = msg_info
                attempted_downloads.append({
                    **msg_info,
                    'path': path,
                    'expected_size': file_size
                })
                
            except errors.FloodWaitError as e:
                wait_time = e.seconds
                print(f"Rate limit hit. Waiting {wait_time} seconds...")
                await asyncio.sleep(wait_time)
                continue  # Retry this message
                
            except Exception as e:
                print(f"Error during download of message {msg_info['id']}: {str(e)}")
                continue

    # Process my reactions - only copy if the file exists
    if not args.skip_my_reactions:
        print("\nProcessing messages with your reactions...")
        for msg_info in qualified_messages['my_reactions']:
            processed_messages += 1
            target_path = f'{DOWNLOAD_DIRS["my_reactions"]}/{msg_info["base_filename"]}.jpg'
            
            # Only try to copy if we successfully downloaded the file
            if msg_info['id'] in downloaded_files:
                source_path = downloaded_files[msg_info['id']]
                if os.path.exists(source_path):  # Verify source exists
                    if not os.path.exists(target_path) or args.force_redownload:
                        import shutil
                        try:
                            shutil.copy2(source_path, target_path)
                            print(f"Copied to my reactions: {target_path}")
                            media_data['my_reactions'].append(msg_info)
                        except Exception as e:
                            print(f"Failed to copy file: {str(e)}")
                    else:
                        skipped_existing += 1
                        print(f"Skipping existing file: {target_path}")
                        media_data['my_reactions'].append(msg_info)
                continue
            
            # If not already downloaded, try to download directly
            if os.path.exists(target_path) and not args.force_redownload:
                skipped_existing += 1
                print(f"Skipping existing file: {target_path}")
                media_data['my_reactions'].append(msg_info)
                continue
                
            try:
                message = await client.get_messages(channel, ids=msg_info['id'])
                
                while True:
                    try:
                        await client.download_media(message, target_path)
                        downloaded_files[msg_info['id']] = target_path
                        break
                    except errors.FloodWaitError as e:
                        wait_time = e.seconds
                        print(f"Rate limit hit. Waiting {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
                    except Exception as e:
                        raise e
                
                media_data['my_reactions'].append(msg_info)
                print(f"Downloaded ({processed_messages}/{len(qualified_messages['my_reactions'])}): {target_path}")
                
                # After successful download:
                log_data['messages'][str(msg_info['id'])]['downloaded'] = True
                if msg_info['id'] > log_data.get('last_successful_id', 0):
                    log_data['last_successful_id'] = msg_info['id']
                save_log_file(log_data)
                
            except Exception as e:
                error_msg = f"Failed to download message {msg_info['id']}: {str(e)}"
                failed_downloads.append({**msg_info, 'error': error_msg})
                print(f"Error: {error_msg}")
                continue

    # Verify downloads at the end
    print("\nVerifying downloads...")
    successful_downloads = []
    failed_downloads = []
    
    # Single delay before verification - only place we need a delay
    await asyncio.sleep(1)
    
    for attempt in attempted_downloads:
        msg_id = str(attempt['id'])
        path = attempt['path']
        
        if not os.path.exists(path):
            print(f"File not found: {path}")
            failed_downloads.append({
                **attempt,
                'error': "File not found after download"
            })
            continue
            
        current_size = os.path.getsize(path)
        if current_size == attempt['expected_size']:
            print(f"Verified: {path}")
            successful_downloads.append(attempt)
            if msg_id not in log_data['messages']:
                log_data['messages'][msg_id] = attempt
            log_data['messages'][msg_id]['downloaded'] = True
            last_id = log_data.get('last_successful_id')
            if last_id is None or attempt['id'] > last_id:
                log_data['last_successful_id'] = attempt['id']
        else:
            print(f"Size mismatch for {path}")
            failed_downloads.append({
                **attempt,
                'error': f"File size mismatch: expected {attempt['expected_size']}, got {current_size}"
            })
            os.remove(path)

    # Update log file
    save_log_file(log_data)
    
    # Return results without printing report
    return media_data, successful_downloads, failed_downloads

async def main():
    # Start the client
    await client.start()
    
    try:
        print("Starting download process...")
        media_data, successful_downloads, failed_downloads = await download_reacted_media()
        
        # Single final report
        print("\n=== FINAL REPORT ===")
        print(f"Total files downloaded: {len(successful_downloads)}")
        print(f"- Files with any reactions: {len([d for d in successful_downloads if d['has_reactions']])}")
        print(f"- Files with your reactions: {len([d for d in successful_downloads if d['my_reaction']])}")
        print(f"Failed downloads: {len(failed_downloads)}")
        
        if failed_downloads:
            print("\nFailed URLs:")
            for fail in failed_downloads:
                print(f"- {fail['url']}")
                print(f"  Error: {fail['error']}")
        
        print("\nProcess complete!")
    
    finally:
        await client.disconnect()

# Run the script
if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())