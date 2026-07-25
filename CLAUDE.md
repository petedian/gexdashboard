# Options Gamma Exposure Dashboard - Technical Documentation

## Project Overview
Real-time options gamma exposure (GEX) dashboard using Tastytrade API and dxFeed WebSocket for live market data.

**Created:** December 2025
**Status:** Production-ready
**Purpose:** Monitor gamma exposure, volume, and open interest for SPX, NDX, SPY, QQQ, and custom symbols

**Developer Documentation:** [Tastytrade API Getting Started Guide](https://developer.tastytrade.com/getting-started/)

---

## Setup Guide

### Prerequisites

#### 1. Install Python (3.8 or higher)

**Windows:**
1. Download Python from [python.org/downloads](https://www.python.org/downloads/)
2. Run the installer
3. ⚠️ **IMPORTANT**: Check "Add Python to PATH" during installation
4. Click "Install Now"
5. Verify installation:
   ```bash
   python --version
   ```
   Should show: `Python 3.x.x`

**Already have Python?** Verify version:
```bash
python --version
```
Must be 3.8 or higher.

#### 2. Get Tastytrade API Credentials

**Step-by-step process to get your API credentials:**

1. **Log into your Tastytrade account** at [tastytrade.com](https://tastytrade.com)

2. **Navigate to API Settings:**
   - Click your profile/account menu
   - Go to: **Manage → My Profile → API**

3. **Opt into API Access:**
   - Find the "API Access" section
   - Click to **enable/opt-in to API access**
   - Agree to terms if prompted

4. **Copy your credentials:**
   - **Client ID**: Copy and save this
   - **Client Secret**: Click "Show" and copy this
   - ⚠️ **Keep these secure** - treat them like passwords

5. **Create OAuth Application/Grant:**
   - Look for "Create OAuth Application" or "Generate Refresh Token"
   - Click to create a new application/grant
   - Give it a name (e.g., "GEX Dashboard")

6. **Get Refresh Token:**
   - After creating the application, a **Refresh Token** will be displayed
   - ⚠️ **CRITICAL**: This token is **shown only once**!
   - **Copy it immediately** and save securely
   - If you lose it, you'll need to create a new OAuth application

7. **You should now have:**
   - ✅ Client ID
   - ✅ Client Secret
   - ✅ Refresh Token

#### 3. Project Setup

**Clone or download this project**, then:

1. **Install dependencies:**
   ```bash
   cd "C:\Users\user\Desktop\tasty"
   pip install -r requirements.txt
   ```

2. **Create `.env` file** in the project root:
   ```bash
   # Copy the template
   copy .env.example .env
   ```

3. **Edit `.env` file** with your credentials:
   ```
   CLIENT_ID=your_client_id_here
   CLIENT_SECRET=your_client_secret_here
   REFRESH_TOKEN=your_refresh_token_here
   ```

   ⚠️ **Important notes:**
   - **NO quotes** around values
   - **NO spaces** around the `=` sign
   - Replace `your_client_id_here`, etc. with actual values from Tastytrade

   **Example:**
   ```
   CLIENT_ID=upfjfhdudjfudufuf.....
   CLIENT_SECRET=kfugucud.......
   REFRESH_TOKEN=dGFzdHljcududva2Vu...
   ```

4. **Test authentication:**
   ```bash
   python get_access_token.py
   ```

   If successful, you'll see:
   ```
   ✅ Access token obtained! (valid for 900s)
   💾 Token saved to tasty_token.json
   ```

5. **Run the dashboard:**
   ```bash
   start_simple_dashboard.bat
   ```

   Or manually:
   ```bash
   streamlit run simple_dashboard.py
   ```

6. **Open in browser:**
   - Automatically opens at: http://localhost:8501
   - If not, manually navigate to that URL

### Troubleshooting Setup

**"python is not recognized"**
- Python not added to PATH during installation
- Reinstall Python and check "Add Python to PATH"

**"ModuleNotFoundError"**
- Dependencies not installed
- Run: `pip install -r requirements.txt`

**"Missing required environment variables"**
- `.env` file not created or incorrect format
- Check: no quotes, no spaces around `=`
- Verify all three variables are present

**"Failed to get access token" (401)**
- Credentials are incorrect
- Verify you copied Client ID, Secret, and Refresh Token correctly
- Check for extra spaces or characters
- Refresh token may have expired - create new OAuth application in Tastytrade

**"Token expired"**
- Should auto-refresh automatically
- If persistent, delete `tasty_token.json` and `streamer_token.json`, then restart

---

## Active Files

### Core Application (multipage Streamlit app -- `streamlit run Dashboard.py`)
- **`Dashboard.py`** - Landing page: live gamma levels (Spot / Call Wall / Put Wall / Gamma Flip) for the 8 tracked instruments in `instruments_config.py`, paired futures-next-to-counterpart, read straight from `gex_history.db`. Also has the "History" export section (CSV download + on-screen table).
- **`pages/1_GEX_Chart.py`** - Candlestick chart + GEX level overlay. 8 quick-access buttons load the tracked instruments instantly from `gex_history.db` (no live pull on navigation); the free-text box still reaches any other ticker live via Tastytrade/dxFeed, with a disk-backed cache in `chart_cache/`
- **`pages/2_SR_Profile.py`** - Dynamic support/resistance + visible-range volume profile
- **`pages/3_ORT.py`** - Opening Range Trade (ORT) box/level system
- **`pages/2_GEX_Profile.py`** - Options volume/IV by strike for the 8 tracked instruments (8 quick-access buttons, same instant-load-from-`gex_history.db` pattern as the Chart page) -- see "GEX Profile Page Conventions" below
- **`theme.py`** - Single source of truth for the Key Level Trading brand (colors, fonts, CSS injection, and shared HTML components like stat tiles, pills, hero banner) -- every page calls `theme.inject()` + `theme.sidebar_brand()`

### Background Collector
- **`collector_all.py`** - A CLI, not a persistent daemon. `gex-collector.timer` (systemd user timer) invokes it every 10 min inside the scheduled window; default/`--sweep` mode does one pull of all 8 instruments and exits (no-ops immediately if invoked outside the window -- belt-and-suspenders behind the timer). `--pull SYMBOL` / `--pull-all` are one-off manual pulls (bypass the window check by design) -- these are what Dashboard.py's Refresh/per-card Pull buttons and the GEX Chart page's Refresh button launch as a subprocess and wait on.
- **`instruments_config.py`** - Exactly 8 tracked instruments (`FUTURES`, `COUNTERPARTS`, `PAIRS`, `GEX_PRODUCTS`) driving the collector and Dashboard.py -- see "Tracked Instruments" below.
- **`futures_gex_engine.py`, `gex_database.py`** - GEX calculation and database access helpers shared by the collector and pages. `gex_database.get_latest_snapshot()` is the one shared "read the latest row" query used by both Dashboard.py's cards and the Chart page's quick-access buttons.
- **`purge_old_gex_data.py`** - Retention/cleanup script for `gex_history.db` (5-day rolling), runs via `gex-purge.timer`.

### Authentication & Utilities
- **`utils/auth.py`** - Token management and authentication
- **`utils/gex_calculator.py`** - Thread-safe GEX calculations and aggregation
- **`get_access_token.py`** - Standalone OAuth token retrieval script
- **`get_streamer_token.py`** - Standalone streamer token retrieval script

### Configuration
- **`.env`** - API credentials (CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
- **`requirements.txt`** - Python dependencies
- **`.streamlit/config.toml`** - Streamlit theme config (brand colors), not git-tracked

### Cached Data (auto-generated)
- `tasty_token.json` - Cached access token (15min expiry)
- `streamer_token.txt` - Cached streamer token (longer expiry)
- `gex_history.db` - SQLite store of GEX snapshots, written by `collector_all.py`

### Superseded (not run by the live service -- kept for reference only)
- `simple_dashboard.py`, `demo_dashboard.py` - Earlier single-file dashboard versions, predating the `Dashboard.py` + `pages/` multipage app

## Architecture

### Tracked Instruments (exactly 8 -- permanent convention, no others)

The dashboard and collector track exactly these 8 -- 4 futures paired with their index/ETF counterpart. Do not add other equities/gauges/instruments back without updating this table and `instruments_config.py` together.

| Future | Counterpart | Multiplier (future) | Multiplier (counterpart) |
|---|---|---|---|
| /ES | SPX | 50 ($50 × index) | 100 (OCC index option) |
| /NQ | QQQ | 20 ($20 × index) | 100 (OCC ETF option) |
| /CL | USO | 1000 (1,000 barrels) | 100 (OCC ETF option) |
| /GC | GLD | 100 (100 troy oz) | 100 (OCC ETF option) |

Multipliers live in `futures_gex_engine.py::PRODUCT_SPECS`. Non-tracked futures rows (e.g. `/MES`, `/RTY`) are deliberately kept in that table too -- the GEX Chart page's free-text ticker box can still be pointed at any futures product and needs `get_multiplier()` to resolve correctly.

### Collection Schedule

`collector_all.py` is a CLI, invoked by `gex-collector.timer` (systemd user timer) every 10 minutes, **07:30–16:00 America/Chicago, Monday–Friday only** (named-timezone, DST-safe -- never a hardcoded UTC offset). No overnight or weekend runs. The collector itself re-checks this window and exits immediately if invoked outside it (belt-and-suspenders behind the timer). Manual pulls (`--pull SYMBOL` / `--pull-all`, launched by the dashboard's Refresh/Pull buttons) are the **one** exception allowed outside the window.

### Data Flow
```
gex-collector.timer (systemd, every 10 min, 07:30-16:00 America/Chicago Mon-Fri)
    ↓ fires
collector_all.py --sweep (one-shot process, exits immediately if outside the window)
    ↓ pulls all 8 instruments in instruments_config.GEX_PRODUCTS
1. Get OAuth access token (from .env or cache)
    ↓
2. Get streamer token for dxFeed
    ↓
3. Connect to WebSocket: wss://tasty-openapi-ws.dxfeed.com/realtime
    ↓
4. Fetch underlying price (Trade or Quote events)
    ↓
5. Generate option symbols around current price
    ↓
6. Subscribe to Greeks, Summary (OI), Trade (Volume)
    ↓
7. Calculate GEX and aggregate by strike
    ↓
8. Write a snapshot row to gex_history.db, process exits
    ↓
Dashboard.py / pages/*.py read gex_history.db on each page load/rerun
and render it -- they don't talk to the API directly except
pages/1_GEX_Chart.py's free-text box, which fetches live for any
ticker outside the tracked 8
```

### Multipage Dashboard Approach
- **Scheduled collector, foreground reader** - `collector_all.py` only runs (and only talks to the API) on the timer's 10-min cadence inside the window, or on a manual pull; `Dashboard.py` and most pages just read `gex_history.db`
- **On-demand pulls** - Dashboard.py's page-wide "Refresh" button and each card's "📡 Pull" button launch `collector_all.py --pull-all` / `--pull SYMBOL` as a one-off subprocess and wait for it to finish (~15-20s), then clear `st.cache_data` and rerender
- **Ad-hoc tickers bypass the DB** - `pages/1_GEX_Chart.py`'s free-text box fetches live for any symbol outside the tracked 8, with its own disk cache (`chart_cache/<SYMBOL>.json`) as a fallback; the 8 quick-access buttons on that page instead read `gex_history.db` directly (same helper Dashboard.py uses), so navigating there is instant
- **Self-refreshing, no manual reload needed** - `Dashboard.py`'s body is an `st.fragment(run_every=60)`, and `pages/1_GEX_Chart.py` / `pages/2_GEX_Profile.py` each poll `gex_history.db` every 60s for a newer snapshot of whichever tracked instrument is selected and rerun themselves when one lands. `st.cache_data` TTLs on these DB reads are 60s (short on purpose, not aligned to the 10-min collector cadence -- the queries cost under 1ms, so there's no perf reason to cache longer, and a long TTL would just fight freshness). An open tab picks up a new collector snapshot within ~60s on its own.
- **Weekend compatible** - Shows the last captured snapshot on weekends/off-hours (the collector simply doesn't run then)

### GEX Profile Page Conventions

`pages/2_GEX_Profile.py` reads a dedicated table, `strike_volume_detail` (in `gex_history.db`, schema in `gex_database.py::init_db()`): `id, snapshot_id, expiration, strike, call_volume, put_volume, call_iv, put_iv`, one row per `(expiration, strike)`, 1:1 linked to the `gex_snapshots` row it came from via `snapshot_id`. This is **separate** from `gex_strike_detail` (the GEX table), which blends all 4 fetched expirations into one row per strike for the wall/gamma-flip math -- `strike_volume_detail` is the only place per-expiration data exists in this codebase.

- **Data source** - `Trade.day_volume` (per-contract cumulative day volume) and `Greeks.volatility` (IV), both from the same dxFeed chain subscription the collector already holds open for GEX -- no new API call, no third-party/external data source, ever (see Publishing & IP rules below). `collector_all.py::collect_one()` builds a `streamer_symbol -> expiration` map and a `VolumeIVTracker` (in `futures_gex_engine.py`, deliberately separate from `FuturesGEXCalculator` so the validated GEX math is untouched) to capture this per-expiration.
- **Persistence band** - only strikes within ±15% of spot are written to `strike_volume_detail` (`VolumeIVTracker.STRIKE_BAND`), to bound row growth -- the full chain is still fetched/subscribed as always, this only bounds what gets persisted. `purge_old_gex_data.py` deletes from this table too, on the same 5-day rolling retention as everything else.
- **Expected move** - standard closed-form `Spot × ATM_IV × √(T/365)`, `ATM_IV` = the IV at the strike nearest spot for the selected expiration. Deliberately not a live ATM straddle premium (would need a new per-contract price read that can be stale/missing for thin strikes). 0DTE (T=0) floors at 0.3 days rather than showing a literal zero-width band -- this is an approximation, not a precise time-to-close calculation.
- **IV smile** - at each strike, plots the OTM side's IV (call IV above spot, put IV below) -- the more liquid/reliable side in practice. If IV is missing entirely for an instrument/expiration, the smile trace is hidden with a caption, never backfilled from another source.
- **"Volume vs. Walls" readout** - purely factual distance-from-level statements (e.g. "12 pts above put wall") for the top volume strikes, no predictive language.

### 0DTE-Only Walls/Gamma-Flip

Alongside the existing blended walls (`gex_snapshots.call_wall/put_wall/gamma_flip`, computed across all 4 fetched expirations), the collector also computes a **0DTE-only** reading: same wall/gamma-flip math, but fed gamma/OI for only the nearest fetched expiration -- stored in `gex_snapshots.call_wall_0dte / put_wall_0dte / gamma_flip_0dte / dte_expiration` (nullable columns, added via an idempotent `ALTER TABLE` in `init_db()` since `CREATE TABLE IF NOT EXISTS` doesn't retroactively add columns to an existing table).

- **Why** - the blended view mixes today's chain with weekly/monthly OI, which can pull a wall away from where dealers are actually hedging *today*. This is specifically for 0DTE iron condor short-strike selection: when the blended and 0DTE-only walls agree, that's a higher-confidence anchor; when they diverge, the gap itself is the signal.
- **Implementation** - `collector_all.py::collect_one()` runs a *second* `FuturesGEXCalculator` instance (`engine_0dte`), fed via the existing `g()`/`s()` listeners but filtered to symbols where `expiration_of[symbol] == nearest_exp_str`. Zero changes to `FuturesGEXCalculator` itself -- same non-invasive pattern as `VolumeIVTracker`. No new subscriptions, no new API calls.
- **Can be `None`/absent** - a product may have no same-day listing (weekends, holidays), or the 0DTE-only chain alone may have no clean gamma-flip zero-crossing even when the blended one does (fewer data points). Always check for `None` before displaying; never substitute the blended value silently.
- **Display**: `pages/1_GEX_Chart.py` draws these as dotted lines (vs. the blended dashed/solid ones) for the 8 tracked instruments only, labeled on the chart's left edge so they never collide with the blended labels on the right. `pages/2_GEX_Profile.py` swaps its wall/flip overlay to the 0DTE-only values when the currently-selected expiration button *is* `dte_expiration` (labeled "0DTE-only levels" in the subtitle), and falls back to blended for the other two expiration buttons.

## Dashboard Features

### 1. Symbol Configuration
**Tracked instruments (Dashboard.py, exactly 8):** `/ES`, `/NQ`, `/CL`, `/GC` and their counterparts `SPX`, `QQQ`, `USO`, `GLD` -- see "Tracked Instruments" under Architecture for the paired grouping and multipliers. No other instrument is collected or shown on the main dashboard.

**GEX Chart page (`pages/1_GEX_Chart.py`):** 8 quick-access buttons for the tracked instruments (instant load from `gex_history.db`), plus a free-text box that reaches any other ticker live via Tastytrade/dxFeed (e.g. AAPL, TSLA, NDX, IWM) -- strike increment/expiration handling is automatic from the chain, not manually configured.

### 2. GEX Visualizations

**Three View Modes:**
1. **Calls vs Puts** - Separate green/red bars (call up, put down)
2. **Net GEX** - Single bar per strike (green=calls dominate, red=puts dominate)
3. **Absolute GEX** - Blue bars showing |Net| magnitude only

**GEX Metrics:**
- Total Call GEX
- Total Put GEX
- Net GEX (Call - Put)
- Max GEX Strike (largest |Net GEX|)

### 3. Volume & Open Interest Analysis

**Charts:**
- Open Interest by Strike (calls vs puts)
- Volume by Strike (calls vs puts)

**Top Strikes Tables (3 tabs):**
- By Total OI - Top 10 strikes with most open interest
- By Total Volume - Top 10 strikes with most trading activity
- By Put/Call Ratio - Top 10 bearish sentiment strikes

### 4. Auto-Refresh
- Enable/disable checkbox
- Configurable interval: 30-300 seconds
- Countdown display to next refresh
- Persists view selection across refreshes

## GEX Calculation

### Formula
```
GEX = Gamma × Open Interest × 100 × Spot Price
```

### Max GEX Strike
The strike with the **largest absolute net GEX**:
```python
Net GEX = Call GEX - Put GEX
Max GEX Strike = strike where |Net GEX| is largest
```

**Can be positive or negative:**
- **Positive Net GEX**: Calls dominate (dealers long gamma)
- **Negative Net GEX**: Puts dominate (dealers short gamma)

**Meaning:**
- **Gamma Magnet** - Price level with most hedging activity
- **Support/Resistance** - Market makers concentrate hedging here
- **Price Attraction** - During low volatility, price gravitates toward Max GEX strike

### Example Calculation
```
Strike 6000:
  Gamma: 0.05
  Open Interest: 1000
  Spot Price: $6000

  Call GEX = 0.05 × 1000 × 100 × 6000 = $30,000,000
  Put GEX = 0.04 × 1500 × 100 × 6000 = $36,000,000
  Net GEX = $30M - $36M = -$6M (puts dominate)
  |Net GEX| = $6M
```

## dxFeed WebSocket Protocol

### Connection Sequence
```
1. WebSocket Connect
   → SETUP (keepalive: 60s)
   ← SETUP acknowledgment

2. Authentication
   ← AUTH_STATE (UNAUTHORIZED)
   → AUTH (token: streamer_token)
   ← AUTH_STATE (AUTHORIZED)

3. Channel Setup
   → CHANNEL_REQUEST (service: FEED, contract: AUTO)
   ← CHANNEL_OPENED (channel: 1)

4. Subscribe to Data
   → FEED_SUBSCRIPTION (add: [symbols with event types])
   ← FEED_DATA (continuous stream)
```

### Event Types Used

**Quote** - Bid/ask prices
```json
{
  "eventType": "Quote",
  "eventSymbol": "SPX",
  "bidPrice": 6050.25,
  "askPrice": 6050.50,
  "time": 1702569600000
}
```

**Trade** - Last trade price and volume
```json
{
  "eventType": "Trade",
  "eventSymbol": ".SPXW251219C6000",
  "price": 10.5,
  "dayVolume": 1234
}
```

**Greeks** - Option Greeks and IV
```json
{
  "eventType": "Greeks",
  "eventSymbol": ".SPXW251219C6000",
  "gamma": 0.05,
  "delta": 0.52,
  "theta": -0.35,
  "vega": 0.42,
  "volatility": 0.18
}
```

**Summary** - Open interest and prev close
```json
{
  "eventType": "Summary",
  "eventSymbol": ".SPXW251219C6000",
  "openInterest": 1234,
  "prevClose": 10.25
}
```

## Option Symbol Format

All option symbols use **dot prefix**:
```
.{PREFIX}{YYMMDD}{C|P}{STRIKE}
```

**Examples:**
- `.SPXW251219C6000` - SPX Weekly, Dec 19 2025, Call, $6000 strike
- `.NDXP251219P21000` - NDX PM-settled, Dec 19 2025, Put, $21000 strike
- `.SPY251219C680` - SPY, Dec 19 2025, Call, $680 strike
- `.QQQ251219P612` - QQQ, Dec 19 2025, Put, $612 strike

**Strike Formatting:**
- Integer strikes: `680` (not `680.0`)
- Decimal strikes: `2.5` (for stocks like AAPL)

### OAuth Flow (Refresh Token)
```python
# From .env file
CLIENT_ID = "your_client_id"
CLIENT_SECRET = "your_secret"
REFRESH_TOKEN = "your_refresh_token"

# Exchange for access token
POST https://api.tastytrade.com/oauth/token
  grant_type: refresh_token
  refresh_token: REFRESH_TOKEN

# Response
{
  "access_token": "eyklgtdjci...........",
  "expires_in": 900  // 15 minutes
}
```

### Streamer Token Flow
```python
# Get streamer token for dxFeed
GET https://api.tastyworks.com/api-quote-tokens
  Authorization: Bearer {access_token}

# Response
{
  "token": "dnfujfvx............",
  "websocket-url": "wss://tasty-openapi-ws.dxfeed.com/realtime"
}
```

## Key Configuration

### .env File Format
```
CLIENT_ID=your_client_id_here
CLIENT_SECRET=your_secret_here
REFRESH_TOKEN=your_refresh_token_here
```
**No quotes needed!**

### Automatic Token Management
- **Access tokens** (15min expiry) - Auto-refreshed when <60 seconds remaining
- **Streamer tokens** (~20h expiry) - Auto-refreshed when <5 minutes remaining
- **Token files**: `tasty_token.json` and `streamer_token.json` (auto-generated with expiration timestamps)
- **No manual refresh needed** - Tokens refresh automatically in the background

**How it works:**
1. First fetch creates token file with expiration timestamp
2. Subsequent requests check timestamp before using cached token
3. If expired or expiring soon, automatically fetches new token
4. Completely transparent - no user intervention required

### Expiration Date
- **Format**: YYMMDD (e.g., 251219 for December 19, 2025)
- **Default**: Today's date
- **Usage**: Manually change to any option expiration

### Strike Range
- **Strikes Above Center**: 5-50 (default: 25)
- **Strikes Below Center**: 5-50 (default: 25)
- Generates strikes around current underlying price

## Running the Dashboard

The production instance runs as the `gex-dashboard.service` systemd user unit,
serving `Dashboard.py` on port 8501 behind the `nginx_gexflows.conf` reverse
proxy. Data collection is separate: `gex-collector.timer` fires
`collector_all.py` every 10 min inside the scheduled window (see "Collection
Schedule" under Architecture) -- it is not a persistent service.

### Manual
```bash
streamlit run Dashboard.py
```

Opens at: http://localhost:8501

## Troubleshooting

### Common Issues

**1. Token Errors (401)**
- **Automatic refresh** - Tokens now refresh automatically when expired
- If persistent: Check `.env` file has correct credentials (no quotes)
- Verify REFRESH_TOKEN is still valid in your Tastytrade account
- Manual refresh (if needed): `python get_access_token.py` or `python get_streamer_token.py`

**2. No Data on Weekends**
- Expected behavior - shows Friday's closing data
- Greeks/OI may be stale
- Real-time updates: Mon-Fri 9:30 AM - 4:00 PM ET

**3. Symbol Format Errors**
- All options must have dot prefix (`.SPY`, not `SPY`)
- Integer strikes for whole numbers (`680`, not `680.0`)
- Check expiration format (YYMMDD, exactly 6 digits)

**4. Volume = 0**
- Normal on weekends (no trading)
- During market hours, volume accumulates

**5. NaN or Missing Data**
- Some symbols may not have Greeks/OI immediately
- Wait 15-20 seconds for full data collection
- Check symbol exists and has options for that expiration

## Reference Library

`reference/` contains the owner's research library — screenshots, PDFs, and
day notes (`reference/README.md` documents the conventions). Consult it when
asked, e.g. "look at reference/...". Treat third-party materials in it as
inspiration and validation reference **only**: never copy their visual
designs verbatim, never extract their proprietary data into our database,
and never reproduce their text in our outputs.

## Publishing & IP rules

Non-negotiable, for all future sessions:

1. **Never use other companies' names, trademarks, or coined/proprietary
   terms** in anything we publish, export, or illustrate — no third-party
   vendor names, no coined product-feature names from other firms, no
   competitor branding. Applies to: chart exports, PNG/PDF outputs,
   dashboard labels, alt text, filenames of published assets, code comments
   that end up in public repos, and any generated marketing or educational
   material.
2. **Use generic industry terms instead**: "dealer flow," "gamma exposure,"
   "charm pressure," "key levels," "positioning heatmap," "flow monitor." If
   unsure whether a term is generic options vocabulary or someone's coined
   brand term, ASK the owner before using it in anything publishable.
3. **Our own brand vocabulary** is: Key Level Trading, GexFlows, RAGES,
   "Positioned to the key levels." Prefer these.
4. **Internal-only files** (`reference/`, private notes, code comments in
   this private repo) may mention third-party tools for comparison purposes
   — the restriction is on anything published, exported, or shown to
   subscribers.
5. **Never scrape, extract, or import data from third-party platforms**
   into `gex_history.db` or any output. Our only data source is our own
   broker API feed.





