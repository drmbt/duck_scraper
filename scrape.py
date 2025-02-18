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
   TOPIC_ID=0  # Default to 0 for main channel
   
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
    --resume-from          Resume from message ID
    --max-retries          Maximum retry attempts for failed downloads
    --checkpoint-interval  Save log every N successful downloads
    --verify-only          Only verify existing downloads
    --dry-run              Scan without downloading
    --output-dir           Custom download directory
    --user-id              Filter for specific user ID
    --username             Filter for specific username
    --reacted-by           Get messages that the specified user reacted to
    --replied-to           Get messages that are replies to the specified user

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
        {username}_results/ # Replies to specific user
        {username}_reacted/ # Messages reacted to by specific user
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
    'all_reactions': 'downloads/all_reactions'
}

LOG_FILE = 'download_log.json'
CHECKPOINT_INTERVAL = 10  # Save log every 10 successful downloads
BATCH_SIZE = 100  # Number of messages to fetch at once
MAX_CONCURRENT_DOWNLOADS = 5  # Balance between speed and rate limits
DEFAULT_CHECKPOINT_INTERVAL = 10

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
parser.add_argument('--resume-from', type=int, help='Resume from message ID')
parser.add_argument('--max-retries', type=int, default=3, 
                   help='Maximum retry attempts for failed downloads')
parser.add_argument('--checkpoint-interval', type=int, 
                   help=f'Save log every N successful downloads (default: {DEFAULT_CHECKPOINT_INTERVAL})')
parser.add_argument('--verify-only', action='store_true',
                   help='Only verify existing downloads')
parser.add_argument('--dry-run', action='store_true',
                   help='Scan without downloading')
parser.add_argument('--output-dir', type=str,
                   help='Custom download directory')
parser.add_argument('--user-id', type=int,
                   help='Filter for specific user ID')
parser.add_argument('--username', type=str,
                   help='Filter for specific username')
parser.add_argument('--reacted-by', action='store_true',
                   help='Get messages that the specified user reacted to')
parser.add_argument('--replied-to', action='store_true',
                   help='Get messages that are replies to the specified user')
args = parser.parse_args()

# Load environment variables
load_dotenv()

# Get credentials from environment variables
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
channel_username = os.getenv('CHANNEL_USERNAME')
topic_id = int(os.getenv('TOPIC_ID', 0))  # Default to 0 for main channel

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

def save_checkpoint(log_data, force=False, is_final=False):
    """Save log data based on checkpoint conditions"""
    # Get the count of downloaded files
    downloaded_count = sum(1 for msg in log_data['messages'].values() 
                         if msg.get('downloaded', False))
    
    # Save if:
    # 1. This is a forced save, or
    # 2. This is the final save, or
    # 3. We've hit our checkpoint interval
    if force or is_final or (downloaded_count % CHECKPOINT_INTERVAL == 0):
        # Only create backup on first save
        if not hasattr(save_checkpoint, 'has_backup'):
            if os.path.exists(LOG_FILE):
                import shutil
                backup_name = f"{LOG_FILE}.bak"
                shutil.copy2(LOG_FILE, backup_name)
            save_checkpoint.has_backup = True
        
        # Save current state
        with open(LOG_FILE, 'w') as f:
            json.dump(log_data, f, indent=2)
        
        if is_final:
            print("Final log save completed")
        elif force:
            print("Forced log checkpoint saved")
        else:
            print(f"Checkpoint saved at {downloaded_count} downloads")

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
    """Get messages that qualify for download based on reactions and user filters"""
    log_data = load_log_file()
    qualified = {
        'all_reactions': [],
        'user_interactions': []
    }
    
    # Get target user info if specified
    target_user = None
    if args.user_id or args.username:
        try:
            target_user = await client.get_entity(
                args.user_id if args.user_id else args.username
            )
            print(f"Filtering for user: {target_user.first_name} {target_user.last_name} (@{target_user.username})")
        except Exception as e:
            print(f"Warning: Could not find specified user: {e}")
            return qualified, log_data

    # First, check what's already downloaded
    latest_msg_id = 0
    for msg_id, msg in log_data['messages'].items():
        msg_id = int(msg_id)
        latest_msg_id = max(latest_msg_id, msg_id)
        
        # Skip if already downloaded (unless force redownload)
        if msg.get('downloaded', False) and not args.force_redownload:
            continue
            
        # Add to appropriate categories based on existing data
        if msg['has_reactions'] and not args.skip_all_reactions:
            qualified['all_reactions'].append(msg)
            
        if target_user:
            if args.replied_to and msg['reply_user_id'] == target_user.id:
                qualified['user_interactions'].append(msg)
            elif args.reacted_by:
                # Check reactions from log data
                for reaction in msg.get('reactions', []):
                    if any(reactor.id == target_user.id for reactor in getattr(reaction, 'recent_reactors', [])):
                        qualified['user_interactions'].append(msg)
                        break

    # Then only scan for messages newer than what we have
    print(f"\nScanning for new messages after ID {latest_msg_id}...")
    
    async for message in client.iter_messages(
        channel,
        min_id=latest_msg_id,
        reverse=True,
        reply_to=topic_id
    ):
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
                            # Get the most readable name available, handling None values
                            first_name = getattr(reply.sender, 'first_name', '') or ''
                            last_name = getattr(reply.sender, 'last_name', '') or ''
                            reply_name = (
                                f"{first_name} {last_name}"
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
                
                # Create message info
                msg_info = {
                    'id': message.id,
                    'timestamp': msg_time,
                    'date_iso': message.date.isoformat(),
                    'url': f"https://t.me/{channel_username}/{message.id}",
                    'reply_text': reply_text,
                    'reply_user_id': reply_user_id,
                    'reply_username': reply_username,
                    'reply_name': reply_name,
                    'has_reactions': bool(reaction_details),
                    'total_reactions': total_reactions,
                    'reactions': reaction_details,
                    'base_filename': base_filename,
                    'downloaded': False
                }
                
                # Store in log by message ID
                log_data['messages'][str(message.id)] = msg_info
                
                # Check user-specific conditions
                is_user_interaction = False
                if target_user:
                    if args.replied_to and reply_user_id == target_user.id:
                        is_user_interaction = True
                    elif args.reacted_by:
                        # Check if target user reacted using the reactions attribute
                        try:
                            if hasattr(message, 'reactions') and message.reactions:
                                for reaction in message.reactions.results:
                                    if hasattr(reaction, 'recent_reactors'):
                                        for reactor in reaction.recent_reactors:
                                            if reactor.id == target_user.id:
                                                is_user_interaction = True
                                                break
                        except Exception as e:
                            print(f"Error checking reactions: {e}")

                # Add to appropriate categories
                if msg_info['has_reactions'] and not args.skip_all_reactions:
                    qualified['all_reactions'].append(msg_info)
                if is_user_interaction:
                    qualified['user_interactions'].append(msg_info)
                
                if msg_info['has_reactions']:
                    print(f"\nFound qualifying message ({len(qualified['all_reactions'])}): {message.id}")
                    print(f"Has reactions: {msg_info['has_reactions']}")
                    print(f"Reply from: {msg_info['reply_username'] or msg_info['reply_user_id']}")
                    print(f"Reply text: {msg_info['reply_text'][:100]}...")
                    # New way to format reactions
                    reaction_strings = [f"{r['emoji']}({r['count']})" for r in reaction_details]
                    print(f"Reactions: {', '.join(reaction_strings)}")
                    print(f"URL: {msg_info['url']}")
                
                # Check download limit
                if args.limit and (len(qualified['all_reactions']) + len(qualified['user_interactions'])) >= args.limit:
                    print(f"\nReached download limit of {args.limit} items")
                    break
    
    # Update log file with new timestamp and messages
    log_data['last_scan_time'] = datetime.now(timezone.utc).isoformat()
    save_checkpoint(log_data)
    
    print(f"\nScan complete!")
    print(f"Processed {len(qualified['all_reactions'])} messages")
    print(f"Found {len(qualified['user_interactions'])} qualifying messages")
    print(f"- With any reactions: {len(qualified['all_reactions'])}")
    print(f"- With user interactions: {len(qualified['user_interactions'])}")
    
    return qualified, log_data

# Add progress tracking class
class ProgressTracker:
    def __init__(self, total_items):
        self.total = total_items
        self.completed = 0
        self.start_time = time.time()
        
    def update(self, items_completed=1):
        self.completed += items_completed
        elapsed = time.time() - self.start_time
        rate = self.completed / elapsed if elapsed > 0 else 0
        remaining = (self.total - self.completed) / rate if rate > 0 else 0
        
        return {
            'percent': (self.completed / self.total) * 100,
            'elapsed': elapsed,
            'remaining': remaining,
            'rate': rate
        }
        
    def format_time(self, seconds):
        return time.strftime('%H:%M:%S', time.gmtime(seconds))

# Add batch message retrieval
async def get_messages_batch(client, channel, message_ids):
    """Retrieve multiple messages at once"""
    return await client.get_messages(channel, ids=message_ids)

# Add download semaphore for parallel downloads
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

async def download_media_with_retry(client, message, path, max_retries=3):
    """Download media with retry logic"""
    async with download_semaphore:
        for attempt in range(max_retries):
            try:
                result = await client.download_media(message.media, file=path)
                if result:
                    return result
            except errors.FloodWaitError as e:
                if attempt < max_retries - 1:
                    wait_time = e.seconds
                    print(f"\nRate limit hit. Waiting {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    continue
                raise
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"\nRetrying download after error: {str(e)}")
                    await asyncio.sleep(1)
                    continue
                raise
        return None

async def get_user_specific_dir(username, interaction_type):
    """Get or create user-specific download directory"""
    dir_name = f'downloads/{username}_{interaction_type}'
    os.makedirs(dir_name, exist_ok=True)
    return dir_name

async def download_reacted_media():
    # Use custom output directory if specified
    if args.output_dir:
        for key in DOWNLOAD_DIRS:
            DOWNLOAD_DIRS[key] = os.path.join(args.output_dir, key)
            os.makedirs(DOWNLOAD_DIRS[key], exist_ok=True)

    # Connect to the channel
    channel = await client.get_entity(channel_username)
    
    # Get pre-scan of new messages
    if args.resume_from:
        print(f"Resuming from message ID: {args.resume_from}")
    
    qualified_messages, log_data = await get_qualified_messages(channel)
    
    if args.dry_run:
        print("\nDRY RUN - No downloads will be performed")
        print(f"Would download {len(qualified_messages['all_reactions'])} files with reactions")
        print(f"Would download {len(qualified_messages['user_interactions'])} files with user interactions")
        return {}, [], []
    
    if args.verify_only:
        print("\nVerifying existing downloads...")
        # Implement verification of existing files
        return await verify_downloads(qualified_messages)
    
    # Initialize progress tracker
    total_downloads = len(qualified_messages['all_reactions'])
    progress = ProgressTracker(total_downloads)
    
    # Initialize tracking variables
    media_data = {
        'all_reactions': [],
        'user_interactions': []
    }
    successful_downloads = []
    failed_downloads = []
    attempted_downloads = []
    processed_messages = 0

    # Set up user-specific directory if needed
    user_dir = None
    if args.user_id or args.username:
        target_user = await client.get_entity(
            args.user_id if args.user_id else args.username
        )
        interaction_type = 'reacted' if args.reacted_by else 'results'
        user_dir = await get_user_specific_dir(
            target_user.username or str(target_user.id), 
            interaction_type
        )
        DOWNLOAD_DIRS['user_specific'] = user_dir

    # Process in batches
    for i in range(0, len(qualified_messages['all_reactions']), BATCH_SIZE):
        batch = qualified_messages['all_reactions'][i:i + BATCH_SIZE]
        
        # Get messages in batch
        message_ids = [msg['id'] for msg in batch]
        messages = await get_messages_batch(client, channel, message_ids)
        
        # Process batch
        for msg_info, message in zip(batch, messages):
            processed_messages += 1
            try:
                # Define path first
                path = f'{DOWNLOAD_DIRS["all_reactions"]}/{msg_info["base_filename"]}.jpg'
                
                # Skip if exists
                if os.path.exists(path) and not args.force_redownload:
                    print(f"Skipping existing file: {path}")
                    media_data['all_reactions'].append(msg_info)
                    successful_downloads.append(msg_info)
                    continue
                    
                # Download with retry logic
                result = await download_media_with_retry(
                    client, 
                    message, 
                    path, 
                    max_retries=args.max_retries
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
                
                # Update progress
                stats = progress.update()
                print(f"\rProgress: {stats['percent']:.1f}% | "
                      f"Elapsed: {progress.format_time(stats['elapsed'])} | "
                      f"Remaining: {progress.format_time(stats['remaining'])} | "
                      f"Rate: {stats['rate']:.1f} files/sec", end='')
                
                # Add to tracking on successful download
                media_data['all_reactions'].append(msg_info)
                successful_downloads.append(msg_info)
                
            except Exception as e:
                failed_downloads.append({
                    **msg_info,
                    'error': str(e)
                })
                print(f"Error during download of message {msg_info['id']}: {str(e)}")
                continue

    print("\nDownloads complete!")
    
    # Save final state
    save_checkpoint(log_data, is_final=True)
    
    # Process user interactions if specified
    if user_dir:
        for msg_info in qualified_messages['user_interactions']:
            try:
                # First check if file exists in all_reactions
                base_path = f"{msg_info['base_filename']}.jpg"
                src_path = f"{DOWNLOAD_DIRS['all_reactions']}/{base_path}"
                dst_path = f"{user_dir}/{base_path}"

                if os.path.exists(src_path):
                    # Copy from all_reactions if it exists
                    import shutil
                    shutil.copy2(src_path, dst_path)
                    print(f"Copied from all_reactions: {dst_path}")
                    continue

                # If not in all_reactions, download directly
                message = await client.get_messages(channel, ids=msg_info['id'])
                if not message:
                    raise Exception("Could not retrieve message")

                result = await download_media_with_retry(
                    client, 
                    message,
                    dst_path,
                    max_retries=args.max_retries
                )

                if not result:
                    raise Exception("Download failed - no media returned")
                
                print(f"Downloaded ({processed_messages}/{len(qualified_messages['user_interactions'])}): {dst_path}")
                file_size = os.path.getsize(dst_path)
                print(f"File size: {file_size} bytes")
                
                # Track the attempt and ensure message info is in log_data
                log_data['messages'][str(msg_info['id'])] = msg_info
                attempted_downloads.append({
                    **msg_info,
                    'path': dst_path,
                    'expected_size': file_size
                })
                
                # Update progress
                stats = progress.update()
                print(f"\rProgress: {stats['percent']:.1f}% | "
                      f"Elapsed: {progress.format_time(stats['elapsed'])} | "
                      f"Remaining: {progress.format_time(stats['remaining'])} | "
                      f"Rate: {stats['rate']:.1f} files/sec", end='')
                
                # Add to tracking on successful download
                media_data['user_interactions'].append(msg_info)
                successful_downloads.append(msg_info)
                
            except Exception as e:
                failed_downloads.append({
                    **msg_info,
                    'error': str(e)
                })
                print(f"Error during download of message {msg_info['id']}: {str(e)}")
                continue

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
        print(f"- Files with user interactions: {len([d for d in successful_downloads if d in media_data['user_interactions']])}")
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