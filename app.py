import math
from flask import Flask, jsonify, render_template

app = Flask(__name__)

# ==========================================
# 1. HELPER FUNCTIONS & INDIKATOR MATEMATIS
# ==========================================

def calculate_ma(prices, period):
    """Menghitung Simple Moving Average (SMA)"""
    if len(prices) < period:
        return sum(prices) / len(prices) if prices else 0.0
    return sum(prices[-period:]) / period

def calculate_std_dev(prices, period):
    """Menghitung Standar Deviasi untuk Bollinger Bands & Z-Score"""
    if len(prices) < period: 
        return 0.0
    ma = sum(prices[-period:]) / period
    variance = sum((x - ma) ** 2 for x in prices[-period:]) / period
    return math.sqrt(variance)

def detect_bullish_divergence(prices, macd_hists, period=10):
    """
    Mendeteksi Bullish Divergence (Awal Pembalikan Tren/Reversal):
    Harga membuat Lower Low atau bergerak turun, tetapi MACD Histogram membuat Higher Low.
    """
    if len(prices) < period or len(macd_hists) < period: 
        return False
    
    recent_prices = prices[-period:]
    recent_macd = macd_hists[-period:]
    
    # Cari indeks harga terendah dalam rentang waktu terdekat
    min_p_idx = recent_prices.index(min(recent_prices))
    
    # Validasi jika pola memenuhi syarat divergensi di area bottom
    if 0 < min_p_idx < period - 1:
        if recent_prices[-1] <= recent_prices[min_p_idx] and recent_macd[-1] > recent_macd[min_p_idx]:
            return True
    return False

# ==========================================
# 2. CORE PIPELINE: ANALISIS PASAR ADAPTIF
# ==========================================

def process_single_coin_pipeline(coin_data, btc_status):
    """
    Memproses satu koin menggunakan matriks volume likuiditas,
    skor dominasi whale, pengaman makro BTC, dan 4 parameter prediksi awal tren.
    """
    # Ekstraksi Data Dasar Koin (Simulasi data dari Binance API / DB)
    symbol = coin_data.get("symbol")
    live_price = coin_data.get("live_price")
    vol_24h = coin_data.get("vol_24h")            # Total volume 24 jam dalam USD
    live_volume = coin_data.get("live_volume")    # Volume candle jam ini
    
    hourly_closes = coin_data.get("hourly_closes", []) # List penutupan harga 1h (min 30 data)
    hourly_volumes = coin_data.get("hourly_volumes", []) # List volume harian/jam
    macd_hists = coin_data.get("macd_hists", [])       # List nilai histori MACD histogram
    
    # Jika data tidak cukup, return status dasar
    if len(hourly_closes) < 25:
        return {"symbol": symbol, "fase": "INSUFFICIENT DATA", "score": 0}

    # Perhitungan Teknis Dasar
    ma20_hourly = calculate_ma(hourly_closes, 20)
    ma25_daily = coin_data.get("ma25_daily", ma20_hourly) # fallback ke hourly jika tidak ada
    atr = coin_data.get("atr", live_price * 0.02)         # rata-rata jarak volatilitas koin
    
    price_pct_1h = ((live_price - hourly_closes[-2]) / hourly_closes[-2]) * 100 if len(hourly_closes) >= 2 else 0.0
    avg_vol_20h = calculate_ma(hourly_volumes, 20) if hourly_volumes else 1.0
    vol_spike_ratio = live_volume / avg_vol_20h

    # ----------------------------------------------------
    # IMPLEMENTASI 4 OPSI PENINGKATAN PREDIKSI AWAL TREN
    # ----------------------------------------------------
    
    # Opsi 1: Volume Velocity (Akselerasi Kecepatan Volume)
    prev_volume = hourly_volumes[-2] if len(hourly_volumes) >= 2 else 1.0
    vol_velocity = (live_volume - prev_volume) / prev_volume if prev_volume > 0 else 0.0

    # Opsi 2: Volatility Squeeze (Bollinger Bands masuk ke dalam Keltner Channels)
    std_dev_20 = calculate_std_dev(hourly_closes, 20)
    bb_upper = ma20_hourly + (2.0 * std_dev_20)
    bb_lower = ma20_hourly - (2.0 * std_dev_20)
    
    kc_upper = ma20_hourly + (1.5 * atr)
    kc_lower = ma20_hourly - (1.5 * atr)
    
    is_squeeze = (bb_upper < kc_upper) and (bb_lower > kc_lower)

    # Opsi 3: Bullish Divergence (Sinyal Reversal Tersembunyi)
    is_bullish_div = detect_bullish_divergence(hourly_closes, macd_hists, period=10)

    # Opsi 4: Z-Score (Mengukur Kejenuhan dan Kompresi Konsolidasi terhadap MA)
    z_score = (live_price - ma25_daily) / std_dev_20 if std_dev_20 > 0 else 0.0

    # ----------------------------------------------------
    # MATRIKS KONDISI LAMA (VOLUME & WHALE)
    # ----------------------------------------------------
    
    # Penentuan Batas Lonjakan Volume Berdasarkan Likuiditas Pasar
    if vol_24h >= 50000000:       # Big Cap (>= $50M)
        required_vol_spike = 1.5
    elif vol_24h <= 5000000:      # Small Cap (<= $5M)
        required_vol_spike = 3.5
    else:                         # Mid Cap
        required_vol_spike = 2.0

    # Kalkulasi Whale Dominance (Proksi OBV & Spread)
    spread = coin_data.get("high_1h", live_price) - coin_data.get("low_1h", live_price)
    avg_spread_6h = coin_data.get("avg_spread_6h", spread if spread > 0 else 1.0)
    spread_ratio = spread / avg_spread_6h if avg_spread_6h > 0 else 1.0
    
    whale_score = 30 + (vol_spike_ratio * 12)
    if coin_data.get("obv_trend") == "UP": whale_score += 15
    if spread_ratio < 0.9: whale_score += 10  # Harga dijaga, akumulasi diam-diam
    if vol_spike_ratio > 3.0 and abs(price_pct_1h) < 0.15: whale_score -= 25 # Churning penalti
    
    whale_dominance = max(10, min(99, whale_score))
    is_whale_churning = (vol_spike_ratio > 3.0 and abs(price_pct_1h) < 0.15)

    # Kondisi Structural Breakout (MSB) Lama
    is_msb_breakout = live_price > max(hourly_closes[-24:]) if len(hourly_closes) >= 24 else False

    # ----------------------------------------------------
    # KLASIFIKASI FASE AKHIR (MENGGABUNGKAN SEMUA PARAMETER)
    # ----------------------------------------------------
    momentum_score = 0
    fase = "CONSOLIDATION"

    # Sistem Pengaman Makro (Bitcoin Circuit Breaker)
    if btc_status == "LOCKED":
        fase = "ENGINE LOCKED (BTC DUMP)"
        momentum_score = 0
    elif btc_status == "BEARISH_FILTER":
        fase = "WAIT & SEE (BTC WEAK)"
        momentum_score = 20
    else:
        # Pengecekan dimulai dari indikator Prediksi Awal (Proaktif) ke indikator Tren (Reaktif)
        
        # Skenario 1: Squeeze Breakout (Ledakan Awal Tren Paling Valid)
        if is_squeeze and vol_velocity > 1.8 and price_pct_1h > 0.3:
            fase = "⚡ SQUEEZE BREAKOUT (EARLY TREND)"
            momentum_score = 140
            
        # Skenario 2: Akumulasi Diam-diam oleh Whale (Harga Tenang, Volume Meledak, Z-Score Rendah)
        elif abs(price_pct_1h) < 0.2 and vol_velocity > 2.5 and abs(z_score) < 0.5:
            fase = "🐳 WHALE ACCUMULATION (SILENT)"
            momentum_score = 110
            
        # Skenario 3: Pembalikan Arah Momentum di Harga Bawah (Reversal)
        elif is_bullish_div and price_pct_1h > 0.4:
            fase = "🔄 MOMENTUM REVERSAL (BOTTOMING)"
            momentum_score = 100
            
        # Skenario 4: Whale Churning (Distribusi Bahaya)
        elif is_whale_churning:
            fase = "⚠️ WHALE CHURNING (HIGH RISK)"
            momentum_score = 30
            
        # Skenario 5: Breakout Konvensional Terkonfirmasi (Logika Lama)
        elif price_pct_1h > 0.4 and vol_spike_ratio >= required_vol_spike:
            if is_msb_breakout and whale_dominance > 70:
                fase = "INSTITUTIONAL BUY"
                momentum_score = 150
            elif is_msb_breakout:
                fase = "VALID BREAKOUT"
                momentum_score = 80
            else:
                fase = "EARLY RALLY (WEAK VOL)"
                momentum_score = 50
                
        # Skenario 6: Jenuh Beli Ekstrem
        elif live_price > ma25_daily + (2.5 * atr):
            fase = "OVERBOUGHT PEAK"
            momentum_score = 40

    # ----------------------------------------------------
    # MATRIKS ATR DINAMIS (TARGET & STOP LOSS)
    # ----------------------------------------------------
    tp_multiplier = 2.0
    cl_multiplier = 1.5
    
    if vol_spike_ratio > 3.0: tp_multiplier += 1.0     # Perlebar target karena momentum kencang
    if whale_dominance > 75: cl_multiplier += 0.5      # Perlebar stoploss agar tidak kena goyangan ekor bandar
    if btc_status == "BEARISH_FILTER": tp_multiplier -= 0.5  # Persempit target jika pasar makro kurang mendukung
    
    take_profit = live_price + (atr * tp_multiplier)
    stop_loss = live_price - (atr * cl_multiplier)

    return {
        "symbol": symbol,
        "live_price": round(live_price, 4),
        "fase": fase,
        "momentum_score": momentum_score,
        "whale_dominance": f"{whale_dominance}%",
        "vol_velocity_pct": f"{round(vol_velocity * 100, 1)}%",
        "is_squeeze_active": is_squeeze,
        "z_score": round(z_score, 2),
        "take_profit": round(take_profit, 4),
        "stop_loss": round(stop_loss, 4)
    }

# ==========================================
# 3. ROUTE FLASK / SIMULASI ENDPOINT
# ==========================================

@app.route('/api/radar-engine')
def get_radar_analysis():
    # 1. Simulasi Logika Bitcoin Circuit Breaker
    # Aturan: Cek dump 1 jam terakhir (>1.5%) atau posisi di bawah MA 24
    btc_dump_detected = False 
    btc_below_ma24 = False     
    
    if btc_dump_detected:
        btc_status = "LOCKED"
    elif btc_below_ma24:
        btc_status = "BEARISH_FILTER"
    else:
        btc_status = "HEALTHY"

    # 2. Simulasi Data Koin yang Masuk ke Pipeline
    mock_coins_data = [
        {
            "symbol": "BTCUSD_SQUEEZE_DEMO",
            "live_price": 10.5,
            "vol_24h": 65000000,
            "live_volume": 4500.0,
            "high_1h": 10.6,
            "low_1h": 10.1,
            "avg_spread_6h": 0.5,
            "obv_trend": "UP",
            "hourly_closes": [10.0, 10.1, 10.0, 10.1, 10.0, 10.1, 10.0, 10.1, 10.0, 10.1, 10.2], 
            "hourly_volumes": [1000, 1100, 950, 1050, 1000, 1100, 950, 1050, 1000, 1200, 4100], # Volume melonjak drastis (Vol Velocity)
            "macd_hists": [-0.1, -0.05, 0.01, 0.02, 0.01, -0.01, 0.02, 0.03, 0.04, 0.05, 0.08],
            "ma25_daily": 10.1,
            "atr": 0.15
        }
    ]
    
    # Jalankan analisa untuk semua koin
    results = [process_single_coin_pipeline(coin, btc_status) for coin in mock_coins_data]
    return jsonify(results)

@app.route('/')
def index():
    return "Quantum Radar Engine Backend Active."

if __name__ == '__main__':
    # Jalankan server lokal Flask
    app.run(debug=True, port=5000)
