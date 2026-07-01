from flask import Flask, render_template, jsonify, request
import httpx
import asyncio
from threading import Thread

app = Flask(__name__)

MARKET_DATA_CACHE = []
GLOBAL_PORTFOLIO_DYNAMICS = {}  # Disinkronkan dinamis tiap request dari browser

# ==================== TELEGRAM BOT CONFIGURATION ====================
TELEGRAM_TOKEN = "8979605471:AAGToVU4-bkZIPi9DeqhE8CCNYIp-bM3Bvs"
TELEGRAM_CHAT_ID = "@cryptoradar_quantum"
# ====================================================================

LIVE_PRICE_MAP = {}
GLOBAL_BTC_STATUS = {"is_safe": True, "reason": "Connecting"}
ASYNC_HTTP_CLIENT = None

async def send_telegram_alert_async(message):
    if not TELEGRAM_TOKEN or "ENTER_TOKEN" in TELEGRAM_TOKEN or not ASYNC_HTTP_CLIENT:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = await ASYNC_HTTP_CLIENT.post(url, json=payload, timeout=5)
        return res.status_code == 200
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")
        return False

def send_telegram_alert_sync_bridge(message):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(send_telegram_alert_async(message))
    finally:
        loop.close()

async def check_bitcoin_circuit_breaker(client):
    global GLOBAL_BTC_STATUS
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=48"
        response = await client.get(url, timeout=4)
        if response.status_code == 200:
            klines = response.json()
            closes = [float(k[4]) for k in klines]
            live_btc = closes[-1]
            btc_ma24 = sum(closes[-24:]) / 24
            btc_open_1h = float(klines[-1][1])
            btc_change_1h = ((live_btc - btc_open_1h) / btc_open_1h) * 100
            
            if btc_change_1h <= -1.5:
                GLOBAL_BTC_STATUS = {"is_safe": False, "reason": f"BTC DUMP ({btc_change_1h:.1f}%)"}
            elif live_btc < btc_ma24:
                GLOBAL_BTC_STATUS = {"is_safe": False, "reason": "BTC BEARISH (Below MA24)"}
            else:
                GLOBAL_BTC_STATUS = {"is_safe": True, "reason": "BTC SAFE"}
    except:
        GLOBAL_BTC_STATUS = {"is_safe": True, "reason": "BTC CHECK DELAYED"}

async def get_combined_tickers_data_async(client):
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        response = await client.get(url, timeout=5)
        if response.status_code == 200:
            all_tickers = response.json()
            ticker_dict = {}
            filtered_list = []
            
            for t in all_tickers:
                symbol = t['symbol']
                if symbol.endswith('USDT') and not any(x in symbol for x in ['UPUSDT', 'DOWNUSDT', 'BUSDUSDT', 'USDCUSDT', 'FDUSDUSDT', 'EURUSDT']):
                    live_p = float(t['lastPrice'])
                    LIVE_PRICE_MAP[symbol] = live_p
                    
                    filtered_list.append({
                        "symbol": symbol,
                        "pure_vol_24h": float(t['quoteVolume']),
                        "price_change_pct_24h": float(t['priceChangePercent'])
                    })
            
            filtered_list.sort(key=lambda x: x['pure_vol_24h'], reverse=True)
            top_50_symbols = [item['symbol'] for item in filtered_list[:50]]
            
            # Gabungkan Top 50 dengan koin dinamis yang sedang dipantau oleh browser user
            portfolio_symbols = [f"{coin}USDT" for coin in GLOBAL_PORTFOLIO_DYNAMICS.keys()]
            target_symbols = list(set(top_50_symbols + portfolio_symbols))
            
            for item in filtered_list:
                if item['symbol'] in target_symbols:
                    ticker_dict[item['symbol']] = {
                        "pure_vol_24h": item['pure_vol_24h'],
                        "price_change_pct_24h": item['price_change_pct_24h']
                    }
            
            for sym in target_symbols:
                if sym not in LIVE_PRICE_MAP:
                    LIVE_PRICE_MAP[sym] = 0.0

            return ticker_dict
    except Exception as e:
        print(f"Failed to update master ticker data: {e}")
    return {}

async def fetch_klines_safely_async(client, symbol, interval, limit):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        response = await client.get(url, timeout=5)
        if response.status_code == 200: 
            return response.json()
    except: 
        pass
    return None

def calculate_ma(prices, period):
    if len(prices) < period: return 0.0
    return sum(prices[-period:]) / period

def calculate_macd_efficient(prices):
    if len(prices) < 35: 
        return 0.0, 0.0, 0.0
    
    def get_ema_list(data, period):
        alpha = 2 / (period + 1)
        ema_res = []
        current_ema = sum(data[:period]) / period
        ema_res.append(current_ema)
        for price in data[period:]:
            current_ema = (price * alpha) + (current_ema * (1 - alpha))
            ema_res.append(current_ema)
        return ema_res

    ema12_list = get_ema_list(prices, 12)
    ema26_list = get_ema_list(prices, 26)
    
    offset = len(ema12_list) - len(ema26_list)
    macd_line = [e12 - e26 for e12, e26 in zip(ema12_list[offset:], ema26_list)]
    
    if len(macd_line) < 9:
        return 0.0, 0.0, 0.0
        
    signal_alpha = 2 / (9 + 1)
    current_signal = sum(macd_line[:9]) / 9
    for m_val in macd_line[9:]:
        current_signal = (m_val * signal_alpha) + (current_signal * (1 - signal_alpha))
        
    current_macd = macd_line[-1]
    return current_macd, current_signal, current_macd - current_signal

def extract_market_structure_and_vol_ma(klines_1h):
    volumes = [float(k[7]) for k in klines_1h]
    vol_ma20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 1.0
    highs_48h = [float(k[2]) for k in klines_1h[-49:-1]]
    local_swing_high = max(highs_48h) if highs_48h else 0.0
    
    obv_proxy = 0
    for i in range(-5, -1):
        try:
            c_close = float(klines_1h[i][4])
            p_close = float(klines_1h[i-1][4])
            v = float(klines_1h[i][7])
            if c_close > p_close: obv_proxy += v
            elif c_close < p_close: obv_proxy -= v
        except: pass
    return vol_ma20, local_swing_high, obv_proxy

def calculate_atr_and_spread(klines_1d, klines_1h):
    true_ranges = []
    for i in range(1, len(klines_1d)):
        high = float(klines_1d[i][2])
        low = float(klines_1d[i][3])
        prev_close = float(klines_1d[i-1][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0
    current_spread = float(klines_1h[-1][2]) - float(klines_1h[-1][3])
    recent_spreads = [float(k[2]) - float(k[3]) for k in klines_1h[-6:-1]]
    return atr, current_spread / (sum(recent_spreads) / len(recent_spreads) if recent_spreads else 1)

async def process_single_coin_pipeline(client, symbol, m_data, last_alerts_state, user_portfolio, semaphore):
    async with semaphore:
        task_1w = fetch_klines_safely_async(client, symbol, '1w', 4)   
        task_1d = fetch_klines_safely_async(client, symbol, '1d', 105)  
        task_1h = fetch_klines_safely_async(client, symbol, '1h', 60)  
        
        klines_1w, klines_1d, klines_1h = await asyncio.gather(task_1w, task_1d, task_1h)
        if not klines_1w or not klines_1d or not klines_1h or len(klines_1h) < 40 or len(klines_1d) < 99: return None
            
        try:
            coin_name = symbol.replace("USDT", "")
            w1_close, w2_close = float(klines_1w[-2][4]), float(klines_1w[-3][4])
            is_macro_bullish = w1_close >= w2_close  
            
            live_price = LIVE_PRICE_MAP.get(symbol, float(klines_1h[-1][4]))
            open_price = float(klines_1h[-1][1])
            price_pct_1h = ((live_price - open_price) / open_price) * 100
            atr, spread_ratio = calculate_atr_and_spread(klines_1d, klines_1h)
            
            vol_ma20, local_swing_high, obv_proxy = extract_market_structure_and_vol_ma(klines_1h)
            daily_closes = [float(k[4]) for k in klines_1d]
            hourly_closes = [float(k[4]) for k in klines_1h]
            ma25_daily, ma99_daily = calculate_ma(daily_closes, 25), calculate_ma(daily_closes, 99)
            
            macd_line, signal_line, macd_hist = calculate_macd_efficient(hourly_closes)
            is_ma_trend_bullish = live_price > ma25_daily and live_price > ma99_daily
            is_macd_momentum_bullish = macd_hist > 0
            
            live_volume = float(klines_1h[-1][7])
            vol_spike_ratio = live_volume / vol_ma20 if vol_ma20 > 0 else 0
            
            market_liquidity_pool = m_data.get("pure_vol_24h", 0)
            if market_liquidity_pool >= 50000000: required_vol_spike = 1.5
            elif market_liquidity_pool <= 5000000: required_vol_spike = 3.5
            else: required_vol_spike = 2.0

            prev_hour_close = float(klines_1h[-2][4])
            is_msb_breakout = (live_price > local_swing_high) and (prev_hour_close > local_swing_high * 0.995) and local_swing_high > 0

            hour_high, hour_low = float(klines_1h[-1][2]), float(klines_1h[-1][3])
            candle_body = abs(live_price - open_price)
            candle_total_range = max(0.0001, hour_high - hour_low)
            body_to_range_ratio = candle_body / candle_total_range
            is_whale_churning = (vol_spike_ratio > required_vol_spike * 1.5) and (body_to_range_ratio < 0.20)

            base_whale = 30.0 + (vol_spike_ratio * 12.0)
            if obv_proxy > 0: base_whale += 15.0
            if spread_ratio < 0.9: base_whale += 10.0
            if is_whale_churning: base_whale -= 25.0  
            whale_dominance = round(max(10.0, min(99.0, base_whale)), 1)
            
            fase = "CONSOLIDATION"
            momentum_score = (vol_spike_ratio * 35) + (whale_dominance * 0.5) + (price_pct_1h * 15)
            is_overextended = (live_price > ma25_daily + (2.5 * atr)) and atr > 0

            if price_pct_1h > 0.4 and vol_spike_ratio >= required_vol_spike and not is_whale_churning:
                if is_msb_breakout and is_macro_bullish and is_ma_trend_bullish and is_macd_momentum_bullish:
                    fase, momentum_score = "INSTITUTIONAL BUY", momentum_score + 150
                elif is_msb_breakout:
                    fase, momentum_score = "VALID BREAKOUT", momentum_score + 80
                else:
                    fase = "EARLY RALLY"
            elif (price_pct_1h > 3.0 and vol_spike_ratio >= required_vol_spike * 2) or is_overextended: 
                fase = "OVERBOUGHT PEAK"
            elif price_pct_1h < -1.5 and vol_spike_ratio >= required_vol_spike: 
                fase, momentum_score = "EARLY DOWNTREND", momentum_score - 100
            elif is_whale_churning and price_pct_1h > 0:
                fase = "WHALE CHURNING (HIGH RISK)"

            if not GLOBAL_BTC_STATUS["is_safe"] and coin_name not in user_portfolio:
                status_rencana_otomatis = "WAIT & SEE"
                fase = f"ENGINE LOCKED ({GLOBAL_BTC_STATUS['reason']})"
            else:
                if fase in ["INSTITUTIONAL BUY", "VALID BREAKOUT", "EARLY RALLY", "EARLY RALLY (WEAK VOL)"]:
                    status_rencana_otomatis = "BUY STAGE"
                elif fase == "OVERBOUGHT PEAK":
                    status_rencana_otomatis = "TAKE PROFIT"
                else:
                    status_rencana_otomatis = "WAIT & SEE"

            harga_terformat = f"${live_price:.8f}" if live_price < 1.0 else f"${live_price:.4f}"
            if coin_name not in last_alerts_state or last_alerts_state[coin_name] != fase:
                if fase in ["VALID BREAKOUT", "INSTITUTIONAL BUY"] and GLOBAL_BTC_STATUS["is_safe"] and vol_spike_ratio >= 2.5:
                    emoji = "👑 BRAND NEW MSB!" if fase == "INSTITUTIONAL BUY" else "🔥 BREAKOUT SPIKE"
                    asyncio.create_task(send_telegram_alert_async(
                        f"{emoji}\n\nCoin: *{coin_name}*\nMarket Structure: `BREAKOUT RESISTANCE`\n"
                        f"Vol vs MA20 Speed: `{vol_spike_ratio:.1f}x` (Req: {required_vol_spike}x)\n"
                        f"Whale Dominance: `{whale}%`\n"
                        f"Live Price: `*{harga_terformat}*`"
                    ))
                last_alerts_state[coin_name] = fase

            coin_p_data = user_portfolio.get(coin_name, {})
            entry_price = coin_p_data.get("costPrice", 0.0)
            amount = coin_p_data.get("amount", 0.0)

            dynamic_tp = entry_price + (2 * atr) if entry_price > 0 else 0.0
            dynamic_cl = entry_price - (1.5 * atr) if entry_price > 0 else 0.0

            max_allowed_atr = live_price * 0.15
            smoothed_atr = min(atr, max_allowed_atr) if atr > 0 else (live_price * 0.02)
            is_volume_backed_breakout = (vol_spike_ratio >= required_vol_spike) and (whale_dominance >= 50.0)

            if status_rencana_otomatis == "BUY STAGE" and is_msb_breakout and is_volume_backed_breakout:
                saran_entry = local_swing_high + (0.15 * smoothed_atr)
            elif status_rencana_otomatis == "BUY STAGE" and not is_volume_backed_breakout:
                saran_entry = live_price - (0.75 * smoothed_atr)
                fase = "EARLY RALLY (WEAK VOL)"
            else:
                saran_entry = live_price - (0.5 * smoothed_atr)

            if entry_price > 0:
                if live_price >= dynamic_tp: status_rencana_otomatis = "TAKE PROFIT"
                elif live_price <= dynamic_cl: status_rencana_otomatis = "CUT LOSS"
                saran_entry = live_price - (0.75 * smoothed_atr)

            pnl_val, pnl_pct, current_value = 0.0, 0.0, 0.0
            if entry_price > 0 and amount > 0:
                current_value = amount * live_price
                initial_value = amount * entry_price
                pnl_val = current_value - initial_value
                pnl_pct = (pnl_val / initial_value) * 100

            return {
                "koin": coin_name, "harga": live_price, "persen_harga": price_pct_1h,
                "rasio": vol_spike_ratio, "fase": fase, "atr": atr, "whale": whale_dominance, "skor": momentum_score,
                "is_portfolio": coin_name in user_portfolio,
                "amount": amount, "entry": entry_price, "tp": dynamic_tp, "cl": dynamic_cl,
                "status_aksi": status_rencana_otomatis, "saran_entry": saran_entry,
                "pnl_val": pnl_val, "pnl_pct": pnl_pct, "current_value": current_value
            }
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            return None

async def main_analysis_loop():
    global MARKET_DATA_CACHE, ASYNC_HTTP_CLIENT
    last_alerts_state = {} 
    
    async with httpx.AsyncClient() as client:
        ASYNC_HTTP_CLIENT = client
        semaphore = asyncio.Semaphore(12) 
        
        while True:
            await check_bitcoin_circuit_breaker(client)
            ticker_master_data = await get_combined_tickers_data_async(client)
            if not ticker_master_data:
                await asyncio.sleep(4)
                continue
            
            tasks = [process_single_coin_pipeline(client, symbol, m_data, last_alerts_state, GLOBAL_PORTFOLIO_DYNAMICS, semaphore) for symbol, m_data in ticker_master_data.items()]
            results = await asyncio.gather(*tasks)
            temp_data = [r for r in results if r is not None]
            
            temp_data.sort(key=lambda x: (x['is_portfolio'], x['skor']), reverse=True)
            MARKET_DATA_CACHE = temp_data
            await asyncio.sleep(4)

def start_async_engine_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main_analysis_loop())

@app.route('/')
def index(): return render_template('index.html')

# MENGUBAH ENDPOINT MENJADI POST AGAR DAPAT MENERIMA DATA PORTFOLIO DARI BROWSER USER
@app.route('/api/data', methods=['POST'])
def get_data():
    global GLOBAL_PORTFOLIO_DYNAMICS
    try:
        req = request.json or {}
        # Tangkap data asset yang dikirim dari localStorage browser pengguna
        GLOBAL_PORTFOLIO_DYNAMICS = req.get("portfolio", {})
    except Exception as e:
        print(f"Failed to synchronize dynamic portfolio cache: {e}")
        
    return jsonify({
        "btc_status": GLOBAL_BTC_STATUS,
        "market": MARKET_DATA_CACHE
    })

@app.route('/api/telegram/send_manual', methods=['POST'])
def send_manual_alert():
    try:
        req = request.json
        coin = req.get("koin", "").strip().upper()
        fase = req.get("fase", "MONITORING")
        harga = float(req.get("harga", 0))
        rasio = float(req.get("rasio", 0))
        whale = float(req.get("whale", 0))
        status_aksi = req.get("status_aksi", "WAIT & SEE")
        saran = float(req.get("saran_entry", 0))

        harga_fmt = f"${harga:.8f}" if harga < 1.0 else f"${harga:.4f}"
        saran_fmt = f"${saran:.8f}" if saran < 1.0 else f"${saran:.4f}"
        
        msg = (
            f"📢 *MANUAL QUANTUM SIGNAL ALERT*\n\n"
            f"Coin: *{coin}*\n"
            f"Market Phase: `{fase}`\n"
            f"Current Price: `*{harga_fmt}*`\n"
            f"Vol vs MA20: `{rasio:.1f}x`\n"
            f"Whale Dominance: `{whale}%`\n"
            f"Action Strategy: *{status_aksi}*\n"
            f"Suggested Entry Trigger: `*{saran_fmt}*`"
        )
        
        success = send_telegram_alert_sync_bridge(msg)
        if success:
            return jsonify({"status": "success", "message": "Signal broadcasted!"})
        return jsonify({"status": "error", "message": "Failed to send message via Telegram."}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

if __name__ == '__main__':
    Thread(target=start_async_engine_thread, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False)
