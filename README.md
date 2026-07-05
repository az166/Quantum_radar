# Crypto Radar Quantum Market Engine

Crypto Radar Quantum Market Engine is a real-time cryptocurrency market scanner and portfolio tracking web application built on top of Flask. It utilizes a hybrid data architecture combining asynchronous backend processing for heavy technical analysis and frontend WebSockets for lightning-fast, zero-latency price updates without overloading the server.
The system incorporates a Dynamic ATR Strategic Matrix to intelligently compute risk mitigation levels (Entry Trigger, Take Profit, and Cut Loss) based on market volatility and Bitcoin's macro health status (Circuit Breaker).

# Key Features
 * Hybrid Data Engine (REST + WebSocket): Employs an asynchronous REST API (httpx) on the backend to pull and calculate heavy technical indicators every 20 seconds, while utilizing a multiplexed Binance WebSocket connection on the client side for instant, real-time ticker streams.
 * Bitcoin Circuit Breaker (Anti-Dump Protection): Continuously monitors BTC price action. If Bitcoin dumps (\le -1.5\% within 1 hour) or falls below its MA24, the engine automatically tightens risk management and restricts new buying signals.
 * Market Structure & Whale Dominance Analysis: Automatically identifies market phases such as Institutional Buy, Valid Breakout, and Early Rally. It also flags market manipulation risks like Whale Churning by correlating volume spikes against the 20-period volume MA and proxy OBV metrics.
 * Dynamic ATR Risk Matrix: Mathematically calculates Take Profit (TP) and Cut Loss (CL) boundaries using Average True Range (ATR). These levels automatically expand during volume spikes or contract into defensive mode when market conditions turn bearish.
 * Isolated Multi-Device Security: Portfolio assets, amounts, and cost bases are stored safely inside each user's local browser storage (Local Storage) and synchronized via a unique hardware identifier on the server.
 * Automated & Manual Telegram Alerts: Automatically broadcasts premium breakout signals (Market Structure Breaks - MSB) directly to your designated Telegram channel. A manual ✈️ Send button is also embedded in the dashboard for instant signal broadcasting on demand.

# System Architecture & Code Structure
The project features a lightweight yet highly optimized codebase:
 * app.py: The central backend engine (Flask). Manages the background thread loops that fetch historical candlestick data (1w, 1d, 1h) from the Binance API, computes MA, MACD, and ATR indicators, tracks Bitcoin metrics, and handles REST API endpoints for user state updates.
 * templates/index.html: A highly responsive, single-page application interface crafted using Tailwind CSS. It manages local client-side states, established live stream pipes directly with Binance WebSockets, and performs targeted structural DOM element updates for maximum efficiency.

# Prerequisites & Installation
Requirements
 * Python 3.8 or higher
 * Stable internet connection (to connect to Binance API and WebSockets)
Installation Steps
 * Clone the Repository:
   git clone https://github.com/az166/Quantum_radar.git
cd Quantum_radar

 * Create and Activate a Virtual Environment:
# Linux/macOS
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
.\venv\Scripts\activate

 * Install Dependencies:
   Create a requirements.txt file and make sure the following packages are listed:
   Flask==3.0.x
httpx==0.27.x

   Then execute the installation command:
   pip install -r requirements.txt

# Telegram Bot Integration
To enable automated or manual signaling, modify the following environment variables inside your app.py file:
#==================== TELEGRAM BOT CONFIGURATION ====================
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_API_TOKEN"
TELEGRAM_CHAT_ID = "@your_channel_username_or_chat_id"
#====================================================================

> Security Warning: It is highly recommended to shift these hardcoded credentials to a .env file if you plan to host this application on a public production server.

# How to Run the Application
Launch the local Flask development server by running:
python app.py

Once initialized, open your preferred web browser and navigate to:
http://127.0.0.1:5000

# Dashboard Guide:
 * Adding an Asset: Type any coin ticker (e.g., SOL, ADA, DOT) into the Add New Watchlist Asset field. The engine will immediately track its USDT pair.
 * Managing Portfolios: Click the Manage button next to any asset to input your total tokens (Amount) and average purchase price (Cost Price). The tracker instantly handles PnL ratios, records historical price peaks (Trailing Stop), and changes its operational flag to HOLDING, TAKE PROFIT, or CUT LOSS dynamically.
 * Manual Signals: Press the ✈️ Send button to immediately compile and broadcast the quantitative matrix of that specific asset into your Telegram channel.
 
