# Telegram Media Scraper

A Python script to download media from Telegram channels based on reactions and user interactions.

![Duck Charts Example](duck-charts.jpg)

## Features

- Download media with reactions
- Filter by specific user's content (prompts or reactions)
- Track download progress and resume interrupted downloads
- Verify downloaded files
- Batch processing with rate limiting
- Customizable output directories

## Setup

1. Get your Telegram API credentials:
   - Visit https://my.telegram.org/auth
   - Log in with your phone number
   - Go to 'API development tools'
   - Create a new application
   - Copy your API_ID and API_HASH

2. Create a `.env` file using the template in `.env.example`:
   ```env
   API_ID=your_api_id
   API_HASH=your_api_hash
   CHANNEL_USERNAME=target_channel_username
   TOPIC_ID=0  # Default to 0 for main channel
   ```
   Note: CHANNEL_USERNAME should be without the @ symbol

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Basic Usage
```bash
# Download all media with reactions
python scrape.py

# Download only 5 items for testing
python scrape.py --limit 5

# Force redownload of all files
python scrape.py --force-redownload

# Clean workspace before starting
python scrape.py --clean
```

### User-Specific Downloads
```bash
# Get all images generated from user's prompts
python scrape.py --username someuser --replied-to

# Get all images the user reacted to
python scrape.py --username someuser --reacted-by

# Use user ID instead of username
python scrape.py --user-id 123456789 --replied-to
```

### Output Structure
```
downloads/
    all_reactions/      # Media with any reactions
    {username}_results/ # Replies to specific user
    {username}_reacted/ # Messages reacted to by specific user
```

## Advanced Options

```
--skip-all-reactions     Skip downloading media with any reactions
--force-redownload       Force redownload of all files
--limit N                Limit downloads to N items
--clean                  Delete all existing downloads and logs
--resume-from N          Resume from message ID
--max-retries N         Maximum retry attempts for failed downloads
--checkpoint-interval N  Save log every N successful downloads
--verify-only           Only verify existing downloads
--dry-run               Scan without downloading
--output-dir PATH       Custom download directory
```

## Debugging

For debugging issues:
1. Use `--dry-run` to scan without downloading
2. Check `download_log.json` for detailed message history
3. Run `debug_download.py` for specific message troubleshooting

## Files

- `scrape.py` - Main script
- `.env` - Configuration file (create from .env.example)
- `download_log.json` - Download history and message data
- `debug_download.py` - Debugging utility

## Notes

- Rate limits are automatically handled with exponential backoff
- Downloads are tracked and can be resumed if interrupted
- Files are named with format: `YYMMDD_HHMM_Username_rN_message_text`
  where N is the reaction count