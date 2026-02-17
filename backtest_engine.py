"""
Backtest Engine for Quant Strategy.
Simulates the 'Quant Agent' logic over historical data.
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

# --- Configuration ---
SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "AMD", "NFLX"] # Universe subset
START_DATE = "2024-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")
INITIAL_CAPITAL = 10000.0

# --- Strategy Parameters (from SKILL.md) ---
# Weights: Momentum 35, Quality 25, Catalyst 20, Options 20
# Thresholds: High >= 70, Moderate 55-69
# Position Size: 15% max
# Stop Loss: -8%

def fetch_data(symbols, start, end):
    print(f"Fetching data for {len(symbols)} symbols from {start} to {end}...")
    data = yf.download(symbols, start=start, end=end, progress=True)
    return data

def calculate_features(close_series, volume_series):
    """
    Calculate features for a single symbol's time series.
    Returns a DataFrame with feature columns.
    """
    df = pd.DataFrame(index=close_series.index)
    df['Close'] = close_series
    df['Volume'] = volume_series
    
    # Momentum (35%)
    # 5D Return
    df['ret_5d'] = df['Close'].pct_change(5)
    # 20D Return
    df['ret_20d'] = df['Close'].pct_change(20)
    # SMA 50
    df['sma_50'] = df['Close'].rolling(window=50).mean()
    # SMA 200
    df['sma_200'] = df['Close'].rolling(window=200).mean()
    # Price vs SMA 50
    df['dist_sma_50'] = (df['Close'] - df['sma_50']) / df['sma_50']
    
    # RSI 14
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # Relative Volume
    df['vol_20d_avg'] = df['Volume'].rolling(window=20).mean().shift(1)
    df['rel_vol'] = df['Volume'] / df['vol_20d_avg']
    
    return df

def score_row(row):
    """
    Apply scoring logic to a single row (day) of features.
    Returns a score 0-100.
    """
    score = 0
    
    # --- Momentum (35 pts) ---
    # Uptrend: Price > SMA50
    if row['dist_sma_50'] > 0: score += 10
    # Strong Momentum: RSI > 50
    if row['rsi_14'] > 50: score += 10
    # Short term strength: 5D > 0
    if row['ret_5d'] > 0: score += 5
    # Medium term strength: 20D > 0
    if row['ret_20d'] > 0: score += 10
    
    # --- Quality/Fundamentals (25 pts) ---
    # Proxy: Low Volatility (ATR would be better, but using RSI stability for now)
    if 40 < row['rsi_14'] < 70: score += 15 # Not overbought/oversold
    # Proxy: Consistent volume
    if row['rel_vol'] > 0.8: score += 10
    
    # --- Catalyst (20 pts) ---
    # Proxy: Volume spike
    if row['rel_vol'] > 1.5: score += 20
    elif row['rel_vol'] > 1.2: score += 10
    
    # --- Options/Sentiment (20 pts) ---
    # Hard to backtest without options data. Assume neutral (10 pts)
    score += 10
    
    return score

def run_backtest():
    # 1. Get Data
    raw_data = fetch_data(SYMBOLS, START_DATE, END_DATE)
    close = raw_data['Close']
    volume = raw_data['Volume']
    
    # 2. Calculate Features & Scores
    scores = {}
    for sym in SYMBOLS:
        try:
            # Handle MultiIndex if present
            c = close[sym] if isinstance(close, pd.DataFrame) else close
            v = volume[sym] if isinstance(volume, pd.DataFrame) else volume
            
            feat_df = calculate_features(c, v)
            feat_df['score'] = feat_df.apply(score_row, axis=1)
            scores[sym] = feat_df
        except Exception as e:
            print(f"Error processing {sym}: {e}")
            continue
            
    # 3. Simulate Trading
    equity = INITIAL_CAPITAL
    cash = INITIAL_CAPITAL
    positions = {} # symbol -> qty
    history = []
    
    # Align dates
    dates = close.index
    
    print("\nStarting Simulation...")
    for date in dates:
        # 1. Update Portfolio Value
        daily_value = cash
        # Create a list of keys to avoid runtime modification issues
        held_symbols = [s for s in positions.keys() if not s.endswith('_entry')]
        
        for sym in held_symbols:
            qty = positions[sym]
            current_price = scores[sym].loc[date]['Close']
            daily_value += qty * current_price
            
            # Check Stop Loss (-8%)
            entry_price = positions[sym + '_entry']
            if current_price < entry_price * 0.92:
                print(f"{date.date()}: STOP LOSS {sym} @ {current_price:.2f} (Entry: {entry_price:.2f})")
                cash += qty * current_price
                del positions[sym]
                del positions[sym + '_entry']
        
        history.append({'date': date, 'equity': daily_value})
        
        # 2. Entry Logic
        # Max 1 new trade per day (as per SKILL)
        # Find best candidate
        candidates = []
        for sym in SYMBOLS:
            if sym in positions: continue
            
            try:
                row = scores[sym].loc[date]
                if pd.isna(row['score']): continue
                
                if row['score'] >= 70: # High conviction
                    candidates.append((sym, row['score'], row['Close']))
            except KeyError:
                continue
                
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        if candidates and cash > daily_value * 0.2: # Keep 20% cash buffer
            best_sym, best_score, price = candidates[0]
            
            # Position Sizing: 15% of equity
            target_size = daily_value * 0.15
            qty = int(target_size / price)
            
            if qty > 0 and cash >= qty * price:
                print(f"{date.date()}: BUY {best_sym} @ {price:.2f} (Score: {best_score})")
                cash -= qty * price
                positions[best_sym] = qty
                positions[best_sym + '_entry'] = price
                
    # 4. Results
    final_equity = history[-1]['equity']
    print(f"\nFinal Equity: ${final_equity:.2f}")
    print(f"Return: {((final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100:.2f}%")
    
if __name__ == "__main__":
    run_backtest()
