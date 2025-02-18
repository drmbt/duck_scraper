"""
Generate interactive HTML dashboard from Telegram download logs
Features:
- Reactions by user
- Reactions over time
- Message frequency analysis
- Interactive filtering and sorting
"""

import pandas as pd
import json
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os

def load_log_file():
    """Load the download log JSON file"""
    log_file = 'download_log.json'
    if not os.path.exists(log_file):
        raise FileNotFoundError(f"Could not find {log_file}")
        
    with open(log_file, 'r') as f:
        return json.load(f)

def generate_dashboard():
    log_data = load_log_file()
    
    # Convert to DataFrame
    df = pd.DataFrame.from_dict(log_data['messages'], orient='index')
    df['date'] = pd.to_datetime(df['date_iso'])
    
    # Add total reactions to DataFrame
    df['total_reactions'] = df['reactions'].apply(lambda x: sum(r['count'] for r in x))
    
    # Create timestamp for filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f'telegram_dashboard_{timestamp}.html'
    
    # Create visualizations
    fig1 = px.bar(df.groupby('reply_name')['total_reactions'].sum().sort_values(ascending=False).reset_index(), 
                  x='reply_name', y='total_reactions', 
                  title='Total Reactions by User',
                  labels={'reply_name': 'User', 'total_reactions': 'Total Reactions'})
    
    fig2 = px.scatter(df, x='date', y='total_reactions', 
                      hover_data=['reply_name', 'reply_text', 'url'],
                      title='Reactions Over Time',
                      labels={'date': 'Date', 'total_reactions': 'Reactions'})
    
    # Add daily aggregation
    daily_msgs = df.groupby(df['date'].dt.date).size().reset_index()
    daily_msgs.columns = ['date', 'count']
    fig3 = px.bar(daily_msgs, x='date', y='count',
                  title='Messages per Day',
                  labels={'date': 'Date', 'count': 'Message Count'})
    
    # Add reaction type analysis
    reaction_types = pd.DataFrame([
        {'emoji': r['emoji'], 'count': r['count']}
        for msg in df['reactions'] 
        for r in msg
    ])
    fig4 = px.pie(reaction_types.groupby('emoji')['count'].sum().reset_index(), 
                  values='count', names='emoji',
                  title='Distribution of Reaction Types')

    # Add top messages table
    top_msgs = df.nlargest(10, 'total_reactions')[
        ['reply_name', 'reply_text', 'total_reactions', 'url']
    ].to_html(index=False, render_links=True)

    # Add time of day analysis
    df['hour'] = df['date'].dt.hour
    hourly_activity = px.bar(
        df.groupby('hour').size().reset_index(),
        x='hour', y=0,
        title='Activity by Hour of Day',
        labels={'hour': 'Hour', '0': 'Message Count'}
    )

    # Add user engagement over time - fixed version
    monthly_users = df.groupby([
        df['date'].dt.strftime('%Y-%m'),  # Use string format instead of Period
        'reply_name'
    ]).size().reset_index()
    monthly_users.columns = ['month', 'user', 'messages']
    
    monthly_activity = px.line(
        monthly_users.pivot(
            index='month',
            columns='user',
            values='messages'
        ).fillna(0),
        title='User Activity Over Time',
        labels={'value': 'Messages', 'variable': 'User'}
    )

    # Generate HTML
    dashboard_html = f"""
    <html>
        <head>
            <title>Telegram Stats Dashboard</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .plot {{ margin-bottom: 30px; }}
                .stats-grid {{ 
                    display: grid;
                    grid-template-columns: repeat(2, 1fr);
                    gap: 20px;
                    margin-bottom: 30px;
                }}
                .stat-box {{
                    background: #f5f5f5;
                    padding: 15px;
                    border-radius: 8px;
                    text-align: center;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                }}
                th, td {{
                    padding: 8px;
                    border: 1px solid #ddd;
                    text-align: left;
                }}
                th {{ background: #f5f5f5; }}
            </style>
        </head>
        <body>
            <h1>Telegram Channel Analytics</h1>
            
            <div class="stats-grid">
                <div class="stat-box">
                    <h3>Total Messages</h3>
                    <p>{len(df):,}</p>
                </div>
                <div class="stat-box">
                    <h3>Total Reactions</h3>
                    <p>{df['total_reactions'].sum():,}</p>
                </div>
                <div class="stat-box">
                    <h3>Active Users</h3>
                    <p>{df['reply_name'].nunique():,}</p>
                </div>
                <div class="stat-box">
                    <h3>Avg Reactions/Message</h3>
                    <p>{df['total_reactions'].mean():.1f}</p>
                </div>
            </div>

            <h2>User Engagement</h2>
            <div class="plot">{fig1.to_html()}</div>
            
            <h2>Temporal Analysis</h2>
            <div class="plot">{fig2.to_html()}</div>
            <div class="plot">{fig3.to_html()}</div>
            <div class="plot">{hourly_activity.to_html()}</div>
            
            <h2>Reaction Analysis</h2>
            <div class="plot">{fig4.to_html()}</div>
            
            <h2>User Trends</h2>
            <div class="plot">{monthly_activity.to_html()}</div>
            
            <h2>Top 10 Most Reacted Messages</h2>
            {top_msgs}
            
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body>
    </html>
    """
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(dashboard_html)
    
    print(f"Dashboard generated: {filename}")

if __name__ == "__main__":
    generate_dashboard() 