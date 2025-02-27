import os
from flask import Flask, jsonify, request
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
            'days': 'max',         # Fetch entire history
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

        # Calculate risk based on price position
        min_price = df['price'].min()
        max_price = df['price'].max()
        df['risk'] = (df['price'] - min_price) / (max_price - min_price)  # Corrected risk calculation

        # Store the latest data
        latest_data = {
            'latest_date': df['date'].iloc[-1].strftime('%Y-%m-%d %H:%M:%S'),  # Timestamp
            'latest_market_cap': round(df['market_cap'].iloc[-1], 2),          # Market cap (rounded)
            'latest_price': round(df['price'].iloc[-1], 6),                    # Price (rounded)
            'latest_volume': round(df['volume'].iloc[-1], 2),                  # Volume (rounded)
            'min_price': round(min_price, 6),                                  # Min price (rounded)
            'max_price': round(max_price, 6),                                  # Max price (rounded)
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

# Historical data route
@app.route('/data/historical')
def get_historical_data():
    time_frame = request.args.get('timeFrame', 'all')  # Default to entire history
    days = {
        '1w': 7,
        '1m': 30,
        '3m': 90,
        '1y': 365,
        'all': 'max',  # Fetch entire history
    }.get(time_frame, 'max')  # Default to entire history if invalid time frame

    try:
        # Fetch data from CoinGecko
        url = "https://api.coingecko.com/api/v3/coins/kaspa/market_chart"
        params = {
            'vs_currency': 'usd',
            'days': days,
            'interval': 'daily',
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        # Process data
        prices = data['prices']
        df = pd.DataFrame(prices, columns=['timestamp', 'price'])
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.drop(columns=['timestamp'])

        # Calculate risk based on price position
        min_price = df['price'].min()
        max_price = df['price'].max()
        df['risk'] = (df['price'] - min_price) / (max_price - min_price)  # Corrected risk calculation

        # Prepare data for the frontend
        cleaned_data = df.dropna(subset=['risk'])
        historical_chart_data = {
            'dates': cleaned_data['date'].dt.strftime('%Y-%m-%d').tolist(),
            'prices': cleaned_data['price'].tolist(),
            'risks': cleaned_data['risk'].tolist(),
        }
        return jsonify(historical_chart_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Fetch data immediately on startup
    fetch_kaspa_data()

    # Bind to the PORT environment variable (for Render) or default to 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
