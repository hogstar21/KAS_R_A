import os
from flask import Flask, jsonify
import requests
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from flask_cors import CORS  # Import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global variable to store the latest data
latest_data = {}
historical_data = pd.DataFrame()

def fetch_kaspa_data():
    global latest_data, historical_data
    try:
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
        response.raise_for_status()  # Raise an error for bad status codes
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
        df['volatility'] = df['daily_return'].rolling(window=7).std()  # 7-day rolling volatility
        df['cumulative_return'] = (1 + df['daily_return']).cumprod()
        df['drawdown'] = df['cumulative_return'] / df['cumulative_return'].cummax() - 1
        max_drawdown = df['drawdown'].min()

        # Calculate 24-hour and 7-day price changes
        price_change_24h = ((df['price'].iloc[-1] - df['price'].iloc[-2]) / df['price'].iloc[-2]) * 100
        price_change_7d = ((df['price'].iloc[-1] - df['price'].iloc[-8]) / df['price'].iloc[-8]) * 100

        # Store the latest data
        latest_data = {
            'latest_date': df['date'].iloc[-1].strftime('%Y-%m-%d %H:%M:%S'),  # Timestamp
            'latest_market_cap': round(df['market_cap'].iloc[-1], 2),          # Market cap (rounded)
            'latest_price': round(df['price'].iloc[-1], 6),                    # Price (rounded)
            'latest_volume': round(df['volume'].iloc[-1], 2),                  # Volume (rounded)
            'max_drawdown': round(max_drawdown, 4),                           # Max drawdown (rounded)
            'volatility': round(df['volatility'].iloc[-1], 4),                # Volatility (rounded)
            'price_change_24h': round(price_change_24h, 2),                   # 24h price change (rounded)
            'price_change_7d': round(price_change_7d, 2)                      # 7d price change (rounded)
        }

        # Update historical data
        historical_data = df
    except Exception as e:
        # Handle errors gracefully
        latest_data = {
            'error': str(e)
        }

# Schedule data fetching every hour
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_kaspa_data, 'interval', hours=1)
scheduler.start()

# Root route
@app.route('/')
def home():
    return "Welcome to the Kaspa Risk Metrics API! Use the /data endpoint to get metrics."

# Live data route
@app.route('/data/live')
def get_live_data():
    return jsonify(latest_data)

# Historical data route
@app.route('/data/historical')
def get_historical_data():
    if historical_data.empty:
        return jsonify({'error': 'No historical data available'}), 404

    # Remove rows with NaN values in the 'volatility' column
    cleaned_data = historical_data.dropna(subset=['volatility'])

    # Prepare historical data for the chart
    historical_chart_data = {
        'dates': cleaned_data['date'].dt.strftime('%Y-%m-%d').tolist(),  # Dates as strings
        'prices': cleaned_data['price'].tolist(),                        # Price data
        'risks': cleaned_data['volatility'].tolist()                     # Risk data (volatility)
    }
    return jsonify(historical_chart_data)

if __name__ == '__main__':
    # Fetch data immediately on startup
    fetch_kaspa_data()

    # Bind to the PORT environment variable (for Render) or default to 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
