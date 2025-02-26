import os
from flask import Flask, jsonify
import requests
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Global variable to store the latest data
latest_data = {}

def fetch_kaspa_data():
    global latest_data
    # CoinGecko API endpoint for Kaspa (KAS)
    url = "https://api.coingecko.com/api/v3/coins/kaspa/market_chart"

    # Parameters for the API request
    params = {
        'vs_currency': 'usd',  # Currency to compare against (USD)
        'days': '365',         # Number of days of historical data
        'interval': 'daily'    # Data interval (daily)
    }

    # Make the API request
    response = requests.get(url, params=params)
    data = response.json()

    # Extract price, volume, and market cap data
    prices = data['prices']
    volumes = data['total_volumes']
    market_caps = data['market_caps']

    # Convert to a pandas DataFrame
    df = pd.DataFrame(prices, columns=['timestamp', 'price'])
    df['volume'] = [v[1] for v in volumes]
    df['market_cap'] = [m[1] for m in market_caps]

    # Convert timestamp to readable date
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms')

    # Drop the timestamp column
    df = df.drop(columns=['timestamp'])

    # Calculate risk metrics
    df['daily_return'] = df['price'].pct_change()
    volatility = df['daily_return'].std()
    df['cumulative_return'] = (1 + df['daily_return']).cumprod()
    df['drawdown'] = df['cumulative_return'] / df['cumulative_return'].cummax() - 1
    max_drawdown = df['drawdown'].min()

    # Store the latest data
    latest_data = {
        'volatility': volatility,
        'max_drawdown': max_drawdown,
        'latest_price': df['price'].iloc[-1],
        'latest_volume': df['volume'].iloc[-1],
        'latest_market_cap': df['market_cap'].iloc[-1]
    }

# Schedule data fetching every hour
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_kaspa_data, 'interval', hours=1)
scheduler.start()

# Root route
@app.route('/')
def home():
    return "Welcome to the Kaspa Risk Metrics API! Use the /data endpoint to get metrics."

# Data route
@app.route('/data')
def get_data():
    return jsonify(latest_data)

if __name__ == '__main__':
    # Fetch data immediately on startup
    fetch_kaspa_data()

    # Bind to the PORT environment variable (for Render) or default to 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
