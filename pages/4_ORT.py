"""ORT (Opening Range Trade) system -- John's method, generalized to any
symbol you type (MGC was just the worked example, not a hardcoded target).

Stage 1: session clock + box builder + storage.
Stage 2: fib extension engine (this file) -- ladder only renders once the
box is LOCKED, matching the source doc ("once the box is set, draw fib
extensions off the box"), not during formation while the range is still moving.
HTF confluence was tried and pulled back out (didn't land well) -- instruction
panel and trade log/guardrails are still the remaining stages.

Session times are anchored to America/Chicago (CT); zoneinfo handles DST
transitions automatically, no manual offset math.
"""
import os
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import streamlit as st
import plotly.graph_objects as go

import theme
import chart_data
import ort_database
import ort_fib

st.set_page_config(page_title="ORT", layout="wide", page_icon="📦")
theme.inject()
theme.sidebar_brand("ORT — Opening Range Trade system")
ort_database.init_db()

CT = ZoneInfo("America/Chicago")
LONDON_OPEN_CT = dtime(2, 0)
BOX_START_CT = dtime(6, 20)
BOX_END_CT = dtime(7, 20)

CANDLE_INTERVAL = "5m"
LOOKBACK_DAYS = 3          # enough to always have today's session + weekend gaps
CACHE_TTL_SECONDS = 120    # short -- this page cares about "right now" during box formation

HERE = os.path.dirname(os.path.abspath(__file__))
LAST_SYMBOL_FILE = os.path.join(HERE, "..", "chart_cache", "_last_ort_symbol.txt")


def load_last_symbol(default="MGC"):
    try:
        with open(LAST_SYMBOL_FILE) as f:
            s = f.read().strip()
            return s if s else default
    except Exception:
        return default


def save_last_symbol(symbol):
    try:
        with open(LAST_SYMBOL_FILE, "w") as f:
            f.write(symbol)
    except Exception:
        pass


def ct_to_utc(date_ct, time_ct):
    return datetime.combine(date_ct, time_ct, tzinfo=CT).astimezone(timezone.utc)


st.title("📦 ORT — Opening Range Trade")
st.caption("Box: 6:20–7:20 AM CT. London Open reference: 2:00 AM CT. Works for any futures symbol.")

top = st.columns([2, 1, 1])
with top[0]:
    symbol = st.text_input("Symbol", value=load_last_symbol(), label_visibility="collapsed",
                            placeholder="Type any ticker (e.g. MGC, /MGC, ES, AAPL)...").strip().upper()
with top[1]:
    refresh = st.button("Refresh", width="stretch")

if not symbol:
    st.stop()

# accept "MGC" or "/MGC" the same way -- futures need the leading slash to
# resolve a front-month contract, so normalize rather than force the user to
# remember the syntax.
lookup_symbol = symbol if symbol.startswith("/") else f"/{symbol}"

with st.spinner(f"Loading {symbol}..."):
    ttl = 0 if refresh else CACHE_TTL_SECONDS
    candles, age, err = chart_data.get_candles_cached(lookup_symbol, CANDLE_INTERVAL, LOOKBACK_DAYS, ttl)
    if not candles:
        # not a futures symbol (or futures resolution failed) -- try as-typed,
        # e.g. plain equities like AAPL don't take a leading slash at all.
        candles, age, err = chart_data.get_candles_cached(symbol, CANDLE_INTERVAL, LOOKBACK_DAYS, ttl)
        lookup_symbol = symbol

if candles:
    save_last_symbol(symbol)

if not candles:
    theme.empty_state(f"No data for {symbol}",
                       err or "Check the ticker, or that it has recent intraday activity.")
    st.stop()

st.caption(f"Resolved as {lookup_symbol} · {'freshly loaded' if age == 0 else f'cached {age/60:.0f} min ago'}"
           + (f" ({err})" if err and age else ""))

now_ct = datetime.now(CT)
today_ct = now_ct.date()

box_start_utc = ct_to_utc(today_ct, BOX_START_CT)
box_end_utc = ct_to_utc(today_ct, BOX_END_CT)
london_open_utc = ct_to_utc(today_ct, LONDON_OPEN_CT)

box_candles = [c for c in candles if box_start_utc <= c["time"] < box_end_utc]
trade_date_str = today_ct.isoformat()

stored = ort_database.get_box(trade_date_str, symbol)

st.divider()
state_col, box_col = st.columns([1, 2])

if now_ct.time() < BOX_START_CT:
    box_is_locked = False
    with state_col:
        st.markdown(theme.pill("neutral", "Box not open yet"), unsafe_allow_html=True)
        st.caption(f"Forms {BOX_START_CT.strftime('%-I:%M %p')}–{BOX_END_CT.strftime('%-I:%M %p')} CT")
    box_high = box_low = None

elif now_ct.time() < BOX_END_CT:
    box_is_locked = False
    box_high = max((c["high"] for c in box_candles), default=None)
    box_low = min((c["low"] for c in box_candles), default=None)
    with state_col:
        st.markdown(theme.pill("accent", "Box forming", pulse=True), unsafe_allow_html=True)
        st.caption(f"Locks at {BOX_END_CT.strftime('%-I:%M %p')} CT — running high/low so far")
    with box_col:
        c1, c2 = st.columns(2)
        c1.metric("Running high", f"{box_high:,.2f}" if box_high is not None else "—")
        c2.metric("Running low", f"{box_low:,.2f}" if box_low is not None else "—")

else:
    box_is_locked = False
    if stored:
        box_high, box_low = stored["box_high"], stored["box_low"]
        locked_note = f"locked {stored['locked_at'][11:16]} UTC"
        box_is_locked = True
    elif box_candles:
        box_high = max(c["high"] for c in box_candles)
        box_low = min(c["low"] for c in box_candles)
        ort_database.save_box(trade_date_str, symbol, box_high, box_low)
        locked_note = "locked just now"
        box_is_locked = True
    else:
        box_high = box_low = None
        locked_note = None

    with state_col:
        if box_high is not None:
            st.markdown(theme.pill("bull", "Box locked"), unsafe_allow_html=True)
            st.caption(locked_note)
        else:
            st.markdown(theme.pill("bear", "No data in box window"), unsafe_allow_html=True)
            st.caption("No candles fell in 6:20–7:20 AM CT for this symbol/date — market closed then?")
    if box_high is not None:
        with box_col:
            c1, c2, c3 = st.columns(3)
            c1.metric("Box high", f"{box_high:,.2f}")
            c2.metric("Box low", f"{box_low:,.2f}")
            c3.metric("Box range", f"{box_high - box_low:,.2f}")

fib = ort_fib.fib_extension_levels(box_high, box_low) if box_is_locked else None

st.divider()

if fib:
    fib_above, fib_below = fib["above"], fib["below"]
    st.subheader("Fib extension ladder")
    st.caption("Anchored off the locked box (0% = box edge, 100% = one box-range beyond it). "
               "257%/314% are stretch zones — treat as exhaustion/take-profit areas, not fresh entries.")
    fib_col_above, fib_col_below = st.columns(2)
    with fib_col_above:
        st.markdown(f"**Above box** ({theme.BULLISH})")
        for lvl in fib_above:
            tag = " · stretch" if lvl["stretch"] else ""
            st.markdown(f"`{lvl['pct']:>3}%`  {lvl['price']:,.2f}{tag}")
    with fib_col_below:
        st.markdown(f"**Below box** ({theme.BEARISH})")
        for lvl in fib_below:
            tag = " · stretch" if lvl["stretch"] else ""
            st.markdown(f"`{lvl['pct']:>3}%`  {lvl['price']:,.2f}{tag}")
    st.divider()
elif box_high is not None and not box_is_locked:
    st.caption("Fib ladder appears once the box locks at 7:20 AM CT — the range is still moving during formation.")
    st.divider()
    fib_above = fib_below = []
else:
    fib_above = fib_below = []

# ---------------------------- session chart ----------------------------
fig = go.Figure(data=[go.Candlestick(
    x=[chart_data.to_ct_naive(c["time"]) for c in candles], open=[c["open"] for c in candles],
    high=[c["high"] for c in candles], low=[c["low"] for c in candles],
    close=[c["close"] for c in candles], name=symbol,
    increasing_line_color=theme.BULLISH, increasing_fillcolor=theme.BULLISH,
    decreasing_line_color=theme.BEARISH, decreasing_fillcolor=theme.BEARISH,
)])

# Chart coordinates below are all Chicago-time-naive to match the candlestick
# x-axis above -- the box-window filtering earlier in the script stays in UTC
# (correctness there doesn't depend on display timezone), these are separate
# CT-converted copies used only for plotting.
last_candle_time = chart_data.to_ct_naive(candles[-1]["time"])
box_start_ct = chart_data.to_ct_naive(box_start_utc)
box_end_ct = chart_data.to_ct_naive(box_end_utc)


def day_bound_line(x0, y_price, color, width=1.4, dash="solid", opacity=1.0):
    """A horizontal segment bounded to [x0, last candle] -- NOT a full-width
    add_hline, which stretches across the entire multi-day chart regardless
    of which day a level belongs to. This is what keeps the box/fib lines
    scoped to today only instead of smearing across prior days."""
    fig.add_shape(type="line", xref="x", yref="y", x0=x0, x1=last_candle_time,
                  y0=y_price, y1=y_price, line=dict(color=color, width=width, dash=dash),
                  opacity=opacity)


# London Open reference: a horizontal price line at that candle's open, for
# the most recent session only -- bounded from the London Open candle forward,
# not repeated across every day in the multi-day lookback.
london_candle = next((c for c in candles if c["time"] >= london_open_utc), None)
if london_candle is not None and london_candle["time"] < london_open_utc + timedelta(minutes=10):
    london_price = london_candle["open"]
    day_bound_line(chart_data.to_ct_naive(london_candle["time"]), london_price, theme.TEXT_MUTED,
                   width=1.3, dash="dot")
    fig.add_annotation(x=1.0, xref="paper", y=london_price, yref="y",
                        text=f" London Open {london_price:,.2f} ", showarrow=False,
                        xanchor="right", font=dict(color=theme.TEXT_MUTED, size=10), bgcolor=theme.BG)

fig.add_vline(x=box_start_ct, line_dash="dash", line_width=1, line_color=theme.PRIMARY)
fig.add_vline(x=box_end_ct, line_dash="dash", line_width=1, line_color=theme.PRIMARY)

if box_high is not None:
    day_bound_line(box_start_ct, box_high, "#FFA500", width=1.4)
    day_bound_line(box_start_ct, box_low, "#FFA500", width=1.4)

for lvl in fib_above:
    width = 1.6 if lvl["stretch"] else 1.0
    day_bound_line(box_start_ct, lvl["price"], theme.BULLISH, width=width, opacity=0.75)
    fig.add_annotation(x=1.0, xref="paper", y=lvl["price"], yref="y",
                        text=f" {lvl['pct']}% ({lvl['price']:,.2f}) ", showarrow=False,
                        xanchor="left", font=dict(color=theme.BULLISH, size=10), bgcolor=theme.BG)
for lvl in fib_below:
    width = 1.6 if lvl["stretch"] else 1.0
    day_bound_line(box_start_ct, lvl["price"], theme.BEARISH, width=width, opacity=0.75)
    fig.add_annotation(x=1.0, xref="paper", y=lvl["price"], yref="y",
                        text=f" {lvl['pct']}% ({lvl['price']:,.2f}) ", showarrow=False,
                        xanchor="left", font=dict(color=theme.BEARISH, size=10), bgcolor=theme.BG)

fig.update_layout(
    plot_bgcolor=theme.BG, paper_bgcolor=theme.BG,
    font=theme.PLOTLY_FONT, hoverlabel=theme.PLOTLY_HOVERLABEL,
    height=560, margin=dict(l=10, r=60, t=30, b=10),
    dragmode="pan", xaxis_rangeslider_visible=False, showlegend=False, hovermode="x unified",
    xaxis=dict(gridcolor=theme.GRID, fixedrange=False),
    yaxis=dict(gridcolor=theme.GRID, side="right", fixedrange=False),
)
st.plotly_chart(fig, width="stretch",
                 config={"displayModeBar": False, "scrollZoom": True, "doubleClick": "reset+autosize"})

# ---------------------------- historical boxes ----------------------------
st.subheader("Box history")
history = ort_database.get_recent_boxes(symbol, limit=20)
if history:
    for row in history:
        with st.container(border=True):
            cols = st.columns(4)
            cols[0].markdown(f"**{row['trade_date']}**")
            cols[1].metric("High", f"{row['box_high']:,.2f}")
            cols[2].metric("Low", f"{row['box_low']:,.2f}")
            cols[3].metric("Range", f"{row['box_high'] - row['box_low']:,.2f}")
else:
    theme.empty_state("No boxes stored yet for this symbol",
                       "One gets locked automatically once 7:20 AM CT passes.")
