import os
from flask import Flask, jsonify, request, send_file
import requests
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Enable CORS with a wildcard to allow all origins temporarily
# This ensures your API is accessible from any frontend during development
CORS(app, resources={r"/*": {"origins": "*"}})

# Global variable to store the latest data
latest_data = {}
historical_data = pd.DataFrame()

def fetch_kaspa_data():
    global latest_data, historical_data
    try:
        # Fetch current data from CoinGecko
        latest_url = "https://api.coingecko.com/api/v3/simple/price"
        latest_params = {
            'ids': 'kaspa',
            'vs_currencies': 'usd',
            'include_market_cap': 'true',
            'include_24hr_vol': 'true'
        }
        response = requests.get(latest_url, params=latest_params)
        response.raise_for_status()
        data = response.json()
        kas_data = data['kaspa']
        current_price = kas_data['usd']
        market_cap = kas_data['usd_market_cap']
        volume_24h = kas_data['usd_24h_vol']

        # Fetch historical data
        historical_url = "https://api.coingecko.com/api/v3/coins/kaspa/market_chart"
        historical_params = {
            'vs_currency': 'usd',
            'days': '365'
        }
        historical_response = requests.get(historical_url, params=historical_params)
        historical_response.raise_for_status()
        historical_data_raw = historical_response.json()

        # Process historical data
        prices = historical_data_raw['prices']
        timestamps = [x[0] for x in prices]
        prices = [x[1] for x in prices]

        df = pd.DataFrame({
            'timestamp': timestamps,
            'price': prices
        })
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.drop(columns=['timestamp'])
        df = df.sort_values('date')

        # Calculate min and max prices
        min_price = df['price'].min()
        max_price = df['price'].max()

        # Calculate risk (price-based)
        df['risk'] = (df['price'] - min_price) / (max_price - min_price)

        # Calculate volatility (30-day rolling standard deviation)
        df['volatility'] = df['price'].rolling(window=30).std().fillna(0)

        # Calculate RSI
        delta = df['price'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 0.00001)
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi'] = df['rsi'].fillna(50)

        # Calculate moving averages
        df['ma_50'] = df['price'].rolling(window=50).mean().fillna(df['price'])
        df['ma_200'] = df['price'].rolling(window=200).mean().fillna(df['price'])

        # Calculate risk/reward ratio
        df['risk_reward'] = df['price'].pct_change(periods=30) / (df['volatility'] + 0.00001)
        df['risk_reward'] = df['risk_reward'].fillna(0)

        # Fetch market sentiment (Fear & Greed Index)
        sentiment_url = "https://api.alternative.me/fng/"
        sentiment_response = requests.get(sentiment_url)
        sentiment_data = sentiment_response.json()
        fear_greed_index = sentiment_data['data'][0]['value']

        # Fetch network activity (example: transaction count)
        # Replace with actual API call to fetch transaction count or hash rate
        df['transaction_count'] = 1000  # Placeholder for now

        # Calculate NVT Ratio (Network Value to Transaction Ratio)
        df['nvt_ratio'] = market_cap / (df['transaction_count'] + 0.00001)

        # Combine all metrics into a weighted risk score
        df['weighted_risk'] = (
            df['risk'] * 0.4 +  # Price-based risk
            df['volatility'] * 0.2 +  # Volatility
            (df['rsi'] / 100) * 0.1 +  # RSI
            (1 - df['risk_reward']) * 0.1 +  # Risk/Reward
            (df['nvt_ratio'] / df['nvt_ratio'].max()) * 0.2  # NVT Ratio
        )

        # Store the latest data
        latest_data = {
            'latest_date': df['date'].iloc[-1].strftime('%Y-%m-%d %H:%M:%S'),
            'latest_market_cap': round(market_cap, 2),
            'latest_price': round(current_price, 6),
            'latest_volume': round(volume_24h, 2),
            'min_price': round(min_price, 6),
            'max_price': round(max_price, 6),
            'fear_greed_index': fear_greed_index,
        }

        # Update historical data
        historical_data = df

    except Exception as e:
        print(f"Error fetching data: {str(e)}")
        latest_data = {'error': str(e)}

# Ensure CORS headers are on all responses
@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

# Serve the index.html file
@app.route('/')
def serve_index():
    return send_file('index.html')

# Latest data route
@app.route('/data/latest')
def get_latest_data():
    return jsonify(latest_data)

# Historical data route
@app.route('/data/historical')
def get_historical_data():
    time_frame = request.args.get('timeFrame', 'all')  # Default to entire history
    
    if historical_data.empty:
        return jsonify({'error': 'No historical data available'}), 404
    
    # Filter data based on time frame
    df = historical_data.copy()
    
    if time_frame != 'all':
        days = {
            '1w': 7,
            '1m': 30, 
            '3m': 90,
            '1y': 365,
        }.get(time_frame, len(df))
        
        # Filter to the last N days
        end_date = df['date'].max()
        start_date = end_date - pd.Timedelta(days=days)
        df = df[df['date'] >= start_date]
    
    # Prepare data for the frontend
    cleaned_data = df.dropna(subset=['risk'])
    historical_chart_data = {
        'dates': cleaned_data['date'].dt.strftime('%Y-%m-%d').tolist(),
        'prices': cleaned_data['price'].tolist(),
        'risks': cleaned_data['risk'].tolist(),
        'volatility': cleaned_data['volatility'].tolist(),
        'rsi': cleaned_data['rsi'].tolist(),
        'ma_50': cleaned_data['ma_50'].tolist(),
        'ma_200': cleaned_data['ma_200'].tolist(),
        'risk_reward': cleaned_data['risk_reward'].tolist(),
    }
    return jsonify(historical_chart_data)

if __name__ == '__main__':
    # Fetch data immediately on startup
    fetch_kaspa_data()
    
    # Schedule data fetching every hour
    scheduler = BackgroundScheduler()
    scheduler.add_job(fetch_kaspa_data, 'interval', hours=1)
    scheduler.start()
    
    # Bind to the PORT environment variable (for Render) or default to 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
