import os
from flask import Flask, jsonify, request, send_from_directory
import requests
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, static_folder='static')
CORS(app)  # Enable CORS for all routes

# Global variable to store the latest data
latest_data = {}
historical_data = pd.DataFrame()

def fetch_kaspa_data():
    global latest_data, historical_data
    try:
        # CoinGecko API endpoint for current data
        latest_url = "https://api.coingecko.com/api/v3/simple/price"
        latest_params = {
            'ids': 'kaspa',
            'vs_currencies': 'usd',
            'include_market_cap': 'true',
            'include_24hr_vol': 'true'
        }
        
        # Make the API request for current data
        response = requests.get(latest_url, params=latest_params)
        response.raise_for_status()
        data = response.json()
        
        # Debug: Print the API response
        print("Latest Data API Response:", data)
        
        # Extract current price, market cap, and volume
        kas_data = data['kaspa']
        current_price = kas_data['usd']
        market_cap = kas_data['usd_market_cap']
        volume_24h = kas_data['usd_24h_vol']
        
        # Now fetch historical data
        historical_url = "https://api.coingecko.com/api/v3/coins/kaspa/market_chart"
        historical_params = {
            'vs_currency': 'usd',
            'days': 'max'  # Fetch all available historical data
        }
        
        historical_response = requests.get(historical_url, params=historical_params)
        historical_response.raise_for_status()
        historical_data_raw = historical_response.json()
        
        # Debug: Print the historical data response
        print("Historical Data API Response:", historical_data_raw)
        
        # Process historical data
        prices = historical_data_raw['prices']
        timestamps = [x[0] for x in prices]  # Extract timestamps
        prices = [x[1] for x in prices]      # Extract prices
        
        # Create DataFrame
        df = pd.DataFrame({
            'timestamp': timestamps,
            'price': prices
        })
        
        # Convert timestamp to datetime
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.drop(columns=['timestamp'])
        
        # Sort by date
        df = df.sort_values('date')
        
        # Calculate risk metrics
        min_price = df['price'].min()
        max_price = df['price'].max()
        
        # Handle division by zero
        if max_price == min_price:
            df['risk'] = 0  # Set risk to 0 if max_price == min_price
        else:
            df['risk'] = (df['price'] - min_price) / (max_price - min_price)  # Price-based risk
            
        # Calculate volatility (30-day rolling standard deviation)
        df['volatility'] = df['price'].rolling(window=min(30, len(df))).std()
        
        # Handle NaN values in volatility
        df['volatility'] = df['volatility'].fillna(0)  # Replace NaN with 0
        
        # Calculate RSI (Relative Strength Index)
        delta = df['price'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=min(14, len(df)-1)).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=min(14, len(df)-1)).mean()
        
        # Avoid division by zero
        rs = gain / loss.replace(0, 0.00001)
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # Handle NaN values in RSI
        df['rsi'] = df['rsi'].fillna(50)  # Replace NaN with 50 (neutral RSI)
        
        # Calculate moving averages (50-day and 200-day)
        df['ma_50'] = df['price'].rolling(window=min(50, len(df))).mean()
        df['ma_200'] = df['price'].rolling(window=min(200, len(df))).mean()
        
        # Handle NaN values in moving averages
        df['ma_50'] = df['ma_50'].fillna(df['price'])  # Replace NaN with current price
        df['ma_200'] = df['ma_200'].fillna(df['price'])  # Replace NaN with current price
        
        # Calculate risk/reward ratio (simplified)
        df['risk_reward'] = df['price'].pct_change(periods=min(30, len(df)-1)) / (df['volatility'] + 0.00001)  # Avoid division by zero
        
        # Handle NaN values in risk/reward ratio
        df['risk_reward'] = df['risk_reward'].fillna(0)  # Replace NaN with 0
        
        # Store the latest data
        latest_data = {
            'latest_date': df['date'].iloc[-1].strftime('%Y-%m-%d %H:%M:%S'),  # Timestamp
            'latest_market_cap': round(market_cap, 2),                        # Market cap (rounded)
            'latest_price': round(current_price, 6),                          # Price (rounded)
            'latest_volume': round(volume_24h, 2),                            # Volume (rounded)
            'min_price': round(min_price, 6),                                 # Min price (rounded)
            'max_price': round(max_price, 6),                                 # Max price (rounded)
        }
        
        # Update historical data
        historical_data = df
        
        print("Data successfully fetched from CoinGecko API")
    except Exception as e:
        # Handle errors gracefully
        print(f"Error fetching data: {str(e)}")
        latest_data = {
            'error': str(e)
        }

# Serve static files
@app.route('/')
def serve_index():
    return send_from_directory('static', 'index.html')

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
