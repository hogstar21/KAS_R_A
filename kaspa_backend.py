import os
from flask import Flask, jsonify, request, send_file
import requests
import pandas as pd
import numpy as np
from apscheduler.schedulers.background import BackgroundScheduler
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Load environment variables from .env file
load_dotenv()

# Get your Fear and Greed API key from environment variables
FEAR_GREED_API_KEY = os.environ.get('FEAR_GREED_API_KEY', '')

app = Flask(__name__)

# Enable CORS with a wildcard to allow all origins temporarily
CORS(app, resources={r"/*": {"origins": "*"}})

# Global variable to store the latest data
latest_data = {}
historical_data = pd.DataFrame()

def fetch_fear_greed_data(days=365):
    """
    Fetch historical Fear and Greed Index data from alternative.me API.
    Returns a DataFrame with dates and corresponding fear and greed values.
    """
    try:
        # URL for the alternative.me Fear and Greed Index API
        fear_greed_url = "https://api.alternative.me/fng/"
        
        # Parameters for the API request
        params = {
            'limit': days,  # Number of days to fetch
            'format': 'json',  # Response format
            # REMOVED 'date_format': 'us' to get Unix timestamps
        }
        
        # Make the API request
        response = requests.get(fear_greed_url, params=params)
        response.raise_for_status()
        
        # Parse the JSON response
        fear_greed_data = response.json()
        
        # Extract the data points
        data_points = fear_greed_data.get('data', [])
        
        # Create a DataFrame from the data points
        fg_df = pd.DataFrame(data_points)
        
        # Convert timestamp (in seconds) to datetime
        fg_df['timestamp'] = pd.to_datetime(fg_df['timestamp'], unit='s')
        # Rest of the code remains unchanged...
        fg_df['value'] = fg_df['value'].astype(int)
        
        # Rename columns to match our naming convention
        fg_df = fg_df.rename(columns={
            'timestamp': 'date',
            'value': 'fear_greed_index'
        })
        
        # Calculate fear_greed_risk (0-1 scale where 0 = greedy = higher risk, 100 = fearful = lower risk)
        fg_df['fear_greed_risk'] = fg_df['fear_greed_index'] / 100
        
        # Sort by date (ascending)
        fg_df = fg_df.sort_values('date')
        
        return fg_df
    
    except Exception as e:
        print(f"Error fetching Fear and Greed data from alternative.me: {str(e)}")
        # Return empty DataFrame with required columns
        return pd.DataFrame(columns=['date', 'fear_greed_index', 'fear_greed_risk'])
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
        volumes = historical_data_raw['total_volumes']
        market_caps = historical_data_raw['market_caps']
        
        # Create DataFrame with all metrics
        df = pd.DataFrame({
            'timestamp': [x[0] for x in prices],
            'price': [x[1] for x in prices],
            'volume': [x[1] for x in volumes],
            'market_cap': [x[1] for x in market_caps]
        })
        
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.drop(columns=['timestamp'])
        df = df.sort_values('date')

        # Calculate price metrics
        df['price_pct_change'] = df['price'].pct_change()
        df['log_return'] = np.log(df['price'] / df['price'].shift(1))

        # 1. VOLATILITY METRICS
        # Short-term volatility (14-day)
        df['volatility_14d'] = df['log_return'].rolling(window=14).std() * np.sqrt(14)
        # Medium-term volatility (30-day)
        df['volatility_30d'] = df['log_return'].rolling(window=30).std() * np.sqrt(30)
        # Long-term volatility (90-day)
        df['volatility_90d'] = df['log_return'].rolling(window=90).std() * np.sqrt(90)
        
        # Normalize volatilities (0-1 scale)
        for col in ['volatility_14d', 'volatility_30d', 'volatility_90d']:
            max_val = df[col].max()
            min_val = df[col].min()
            df[f'{col}_norm'] = (df[col] - min_val) / (max_val - min_val) if max_val > min_val else 0
        
        # 2. TECHNICAL INDICATORS
        # RSI (14-day)
        delta = df['price'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 0.00001)
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi'] = df['rsi'].fillna(50)
        
        # Normalize RSI (convert to 0-1 risk scale, higher RSI = lower risk)
        df['rsi_risk'] = 1 - (df['rsi'] / 100)
        
        # Moving Averages
        df['ma_50'] = df['price'].rolling(window=50).mean().fillna(df['price'])
        df['ma_200'] = df['price'].rolling(window=200).mean().fillna(df['price'])
        
        # MA Crossover signal (1 = bearish, 0 = bullish)
        df['ma_cross_risk'] = ((df['ma_50'] < df['ma_200']).astype(int) * 0.8) + 0.1
        
        # 3. MARKET SENTIMENT - Now using historical Fear & Greed data
        # Fetch historical Fear & Greed data
        fg_data = fetch_fear_greed_data()
        
        if not fg_data.empty:
            # Merge with our price data based on date
            # First, ensure the date field in both DataFrames is in the same format
            df['date_only'] = df['date'].dt.date
            fg_data['date_only'] = fg_data['date'].dt.date
            
            # Convert to dictionary for faster lookups
            fg_dict = fg_data.set_index('date_only')[['fear_greed_index', 'fear_greed_risk']].to_dict('index')
            
            # Map fear and greed values to each date in our price data
            df['fear_greed_index'] = df['date_only'].map(lambda x: fg_dict.get(x, {}).get('fear_greed_index', 50) 
                                                     if x in fg_dict else 50)
            df['fear_greed_risk'] = df['date_only'].map(lambda x: fg_dict.get(x, {}).get('fear_greed_risk', 0.5) 
                                                    if x in fg_dict else 0.5)
            
            # Clean up temporary column
            df = df.drop(columns=['date_only'])
        else:
            # If we couldn't get historical fear and greed data, use alternative/fallback
            # Fetch current Fear & Greed Index as fallback
            try:
                sentiment_url = "https://api.alternative.me/fng/"
                sentiment_response = requests.get(sentiment_url)
                sentiment_data = sentiment_response.json()
                fear_greed_index = int(sentiment_data['data'][0]['value'])
                # Convert to risk (0-1 scale where 0 = greedy = higher risk, 100 = fearful = lower risk)
                fear_greed_risk = (100 - fear_greed_index) / 100
            except:
                fear_greed_index = 50
                fear_greed_risk = 0.5
                
            # If no historical data available, use the current value for all dates (suboptimal)
            print("Warning: Using current Fear & Greed index for all historical data points")
            df['fear_greed_index'] = fear_greed_index  
            df['fear_greed_risk'] = fear_greed_risk
        
        # 4. NETWORK ACTIVITY 
        # Calculate volume-based network activity metrics
        df['volume_ma_30'] = df['volume'].rolling(window=30).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma_30']
        df['volume_risk'] = 1 - (df['volume_ratio'] / df['volume_ratio'].max())
        df['volume_risk'] = df['volume_risk'].fillna(0.5)
        
        # Calculate Network Value to Transactions (NVT) Ratio
        df['nvt_ratio'] = df['market_cap'] / df['volume'].replace(0, 1)
        
        # Normalize NVT (higher NVT = higher risk)
        nvt_max = df['nvt_ratio'].max()
        nvt_min = df['nvt_ratio'].min()
        df['nvt_risk'] = (df['nvt_ratio'] - nvt_min) / (nvt_max - nvt_min) if nvt_max > nvt_min else 0.5
        df['nvt_risk'] = df['nvt_risk'].fillna(0.5)
        
        # 5. RISK/REWARD RATIO
        # MVRV ratio proxy (using price to MA ratio as substitute)
        df['price_to_ma200_ratio'] = df['price'] / df['ma_200']
        
        # Convert to risk (higher ratio = higher risk)
        max_ratio = df['price_to_ma200_ratio'].max()
        min_ratio = df['price_to_ma200_ratio'].min()
        df['mvrv_risk'] = (df['price_to_ma200_ratio'] - min_ratio) / (max_ratio - min_ratio) if max_ratio > min_ratio else 0.5
        df['mvrv_risk'] = df['mvrv_risk'].fillna(0.5)
        
        # Combine all metrics into weighted risk score with adjustable weights
        weights = {
            'volatility': 0.0,  # Higher weight for volatility
            'technical': 0.0,   # Technical indicators
            'sentiment': 1,   # Market sentiment
            'network': 0.0,     # Network activity
            'valuation': 0.0    # Risk/reward and valuation
        }
        
        df['weighted_risk'] = (
            # Volatility component (25%)
            ((df['volatility_14d_norm'] * 0.4) + 
             (df['volatility_30d_norm'] * 0.4) + 
             (df['volatility_90d_norm'] * 0.2)) * weights['volatility'] +
            
            # Technical indicators component (20%)
            ((df['rsi_risk'] * 0.5) + 
             (df['ma_cross_risk'] * 0.5)) * weights['technical'] +
            
            # Market sentiment component (15%)
            df['fear_greed_risk'] * weights['sentiment'] +
            
            # Network activity component (20%)
            ((df['volume_risk'] * 0.5) + 
             (df['nvt_risk'] * 0.5)) * weights['network'] +
            
            # Valuation/Risk-Reward component (20%)
            df['mvrv_risk'] * weights['valuation']
        )
        
        # Ensure risk is between 0-1
        df['weighted_risk'] = df['weighted_risk'].clip(0, 1)
        
        # Get latest fear and greed index (from our historical data or fallback)
        latest_fg_index = df['fear_greed_index'].iloc[-1]
        
        # Store the latest data
        latest_data = {
            'latest_date': df['date'].iloc[-1].strftime('%Y-%m-%d %H:%M:%S'),
            'latest_market_cap': round(market_cap, 2),
            'latest_price': round(current_price, 6),
            'latest_volume': round(volume_24h, 2),
            'latest_risk': round(df['weighted_risk'].iloc[-1], 4),
            'fear_greed_index': int(latest_fg_index),
            'volatility_30d': round(df['volatility_30d'].iloc[-1], 6),
            'rsi': round(df['rsi'].iloc[-1], 2),
            'nvt_ratio': round(df['nvt_ratio'].iloc[-1], 2),
        }

        # Update historical data
        historical_data = df

    except Exception as e:
        print(f"Error fetching data: {str(e)}")
        latest_data = {'error': str(e)}

# Rest of your code remains the same
# (server routes, CORS settings, etc.)

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
    cleaned_data = df.dropna(subset=['weighted_risk'])
    historical_chart_data = {
        'dates': cleaned_data['date'].dt.strftime('%Y-%m-%d').tolist(),
        'prices': cleaned_data['price'].tolist(),
        'weighted_risks': cleaned_data['weighted_risk'].tolist(),
        'volatility': cleaned_data['volatility_30d'].tolist(),
        'rsi': cleaned_data['rsi'].tolist(),
        'ma_50': cleaned_data['ma_50'].tolist(),
        'ma_200': cleaned_data['ma_200'].tolist(),
        'nvt_ratio': cleaned_data['nvt_ratio'].tolist(),
        'fear_greed_index': cleaned_data['fear_greed_index'].tolist(),
        'volume': cleaned_data['volume'].tolist(),
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
