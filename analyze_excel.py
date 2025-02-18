"""
Generate Excel report from Telegram download logs
Provides sortable sheets for:
- All messages
- User statistics 
- Reaction summaries
"""

import pandas as pd
import json
import os
from datetime import datetime

def load_log_file():
    """Load the download log JSON file"""
    log_file = 'download_log.json'
    if not os.path.exists(log_file):
        raise FileNotFoundError(f"Could not find {log_file}")
        
    with open(log_file, 'r') as f:
        return json.load(f)

def export_excel_report():
    log_data = load_log_file()
    
    # Convert messages to DataFrame
    df = pd.DataFrame.from_dict(log_data['messages'], orient='index')
    
    # Add total reaction count column
    df['total_reactions'] = df['reactions'].apply(lambda x: sum(r['count'] for r in x))
    
    # Create timestamp for filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f'telegram_stats_{timestamp}.xlsx'
    
    # Export to Excel with multiple sheets
    with pd.ExcelWriter(filename) as writer:
        # Full data
        df.to_excel(writer, sheet_name='All Messages')
        
        # User summary
        user_stats = df.groupby('reply_name').agg({
            'id': 'count',
            'total_reactions': 'sum'
        }).reset_index()
        user_stats.columns = ['User', 'Message Count', 'Total Reactions']
        user_stats.sort_values('Total Reactions', ascending=False, inplace=True)
        user_stats.to_excel(writer, sheet_name='User Stats', index=False)
        
        # Reaction summary
        reaction_counts = df.groupby('reply_name')['reactions'].apply(
            lambda x: pd.Series([r['emoji'] for msgs in x for r in msgs]).value_counts()
        ).fillna(0)
        reaction_counts.to_excel(writer, sheet_name='Reaction Types')
    
    print(f"Excel report generated: {filename}")

if __name__ == "__main__":
    export_excel_report() 