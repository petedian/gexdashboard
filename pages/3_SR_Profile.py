"""Part 3 chart module: 8H/Daily + 1H synchronized panels per instrument,
each with a from-scratch dynamic Support/Resistance (pivot band-clustering)
overlay and a Visible Range Profile. Free-text symbol entry -- this only
needs candle data (no options chain/GEX math), so it isn't tied to the
curated GEX watchlist in instruments_config.py the way Dashboard.py is.
"""
import os

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import theme
import chart_data
import sr_profile

st.set_page_config(page_title="S/R + Profile", layout="wide", page_icon="📐")
theme.inject()
theme.sidebar_brand("Dynamic S/R + Visible Range Profile")

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "..", "chart_cache")
os.makedirs(STATE_DIR, exist_ok=True)
LAST_SYMBOL_FILE = os.path.join(STATE_DIR, "_last_sr_symbol.txt")


def load_last_symbol(default="/NQ"):
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

# ================= CONFIGURABLE (per spec defaults) =================
PIVOT_N = 10            # symmetric bar window each side for pivot detection
LOOKBACK_BARS = 284      # trailing bars considered for pivots/profile
BAND_WIDTH_PCT = 0.10    # cluster band width = (range high-low) * this
MIN_PIVOTS = 2           # pivots required in a band to confirm a level
LEVEL_CAP = 20           # max confirmed levels rendered
PROFILE_BINS = 24        # horizontal histogram resolution

HTF_DAYS = 400           # lookback window fetched for the 8H panel
H1_DAYS = 30             # lookback window fetched for the 1H panel
CACHE_TTL_SECONDS = 1800 # 30 min
# =======================================================================


def render_panel(candles, title, interval_label, height=520):
    if len(candles) < 2 * PIVOT_N + 1:
        theme.empty_state(f"{title} · {interval_label} — not enough bars yet",
                          f"Pivot detection needs {2*PIVOT_N+1}+ bars; only {len(candles)} available.")
        return

    sr = sr_profile.dynamic_sr_levels(
        candles, n=PIVOT_N, lookback_bars=LOOKBACK_BARS,
        band_width_pct=BAND_WIDTH_PCT, min_pivots=MIN_PIVOTS, cap=LEVEL_CAP)
    vrp = sr_profile.visible_range_profile(candles, lookback_bars=LOOKBACK_BARS, bins=PROFILE_BINS)

    fig = make_subplots(rows=1, cols=2, shared_yaxes=True,
                         column_widths=[0.82, 0.18], horizontal_spacing=0.01)

    fig.add_trace(go.Candlestick(
        x=[chart_data.to_ct_naive(c["time"]) for c in candles], open=[c["open"] for c in candles],
        high=[c["high"] for c in candles], low=[c["low"] for c in candles],
        close=[c["close"] for c in candles], name=title,
        increasing=dict(line=dict(color=theme.BULLISH, width=1), fillcolor=theme.BULLISH),
        decreasing=dict(line=dict(color=theme.BEARISH, width=1), fillcolor=theme.BEARISH),
    ), row=1, col=1)

    for lvl in sr["levels"]:
        fig.add_hline(y=lvl["price"], line_dash="solid", line_width=1,
                       line_color=theme.PRIMARY, opacity=0.55, row=1, col=1)
        fig.add_annotation(x=1.0, xref="x domain", y=lvl["price"], yref="y",
                            text=f" {lvl['price']:,.2f} ", showarrow=False,
                            xanchor="left",
                            font=dict(color=theme.PRIMARY, size=10,
                                      family=theme.PLOTLY_FONT["family"]),
                            bgcolor=theme.BG_SECONDARY, row=1, col=1)

    for label, price, color in [("Highest pivot high", sr["ref_high"], theme.BEARISH),
                                 ("Lowest pivot low", sr["ref_low"], theme.BULLISH)]:
        if price is not None:
            fig.add_hline(y=price, line_dash="dash", line_width=1, line_color=color,
                          opacity=0.5, row=1, col=1)

    if vrp["bins"]:
        # Buy-side (ask_volume) vs sell-side (bid_volume) stacked per price bin --
        # real aggressor-side split from the feed. Point of Control (highest-
        # volume bin) gets a bright outline so the key level still reads instantly.
        values = [b["value"] for b in vrp["bins"]]
        poc = values.index(max(values)) if values else -1
        y_mid = [(b["price_low"] + b["price_high"]) / 2 for b in vrp["bins"]]
        bar_width = [(b["price_high"] - b["price_low"]) * 0.9 for b in vrp["bins"]]
        customdata = [[b["price_low"], b["price_high"], b["buy_volume"], b["sell_volume"]]
                      for b in vrp["bins"]]
        line_widths = [1.6 if i == poc else 0 for i in range(len(values))]

        fig.add_trace(go.Bar(
            x=[b["sell_volume"] for b in vrp["bins"]], y=y_mid, orientation="h",
            marker=dict(color=theme.BEARISH, opacity=0.8,
                        line=dict(color=theme.TEXT, width=line_widths)),
            width=bar_width, customdata=customdata, name="Sell volume",
            hovertemplate=("%{customdata[0]:,.2f} – %{customdata[1]:,.2f}<br>"
                           "sell %{customdata[3]:,.0f} · buy %{customdata[2]:,.0f}<extra></extra>"),
            showlegend=False,
        ), row=1, col=2)
        fig.add_trace(go.Bar(
            x=[b["buy_volume"] for b in vrp["bins"]], y=y_mid, orientation="h",
            marker=dict(color=theme.BULLISH, opacity=0.8,
                        line=dict(color=theme.TEXT, width=line_widths)),
            width=bar_width, customdata=customdata, name="Buy volume",
            hovertemplate=("%{customdata[0]:,.2f} – %{customdata[1]:,.2f}<br>"
                           "buy %{customdata[2]:,.0f} · sell %{customdata[3]:,.0f}<extra></extra>"),
            showlegend=False,
        ), row=1, col=2)

    fig.update_layout(
        plot_bgcolor=theme.BG, paper_bgcolor=theme.BG,
        font=theme.PLOTLY_FONT, hoverlabel=theme.PLOTLY_HOVERLABEL,
        height=height, margin=dict(l=10, r=64, t=52, b=10), barmode="stack",
        title=dict(
            text=title, x=0.01,
            font=dict(size=16, color=theme.TEXT, family=theme.PLOTLY_FONT["family"]),
            subtitle=dict(text=f"{interval_label} · dynamic S/R + visible range profile",
                          font=dict(size=11, color=theme.TEXT_MUTED)),
        ),
        showlegend=False, hovermode="x unified",
        # TradingView-style interaction: drag inside the chart pans; dragging on
        # the time axis (bottom) or price axis (right) rescales just that axis.
        # Double-click anywhere resets to auto-range.
        dragmode="pan",
    )
    fig.update_xaxes(rangeslider_visible=False, gridcolor=theme.GRID, fixedrange=False,
                     tickfont=dict(size=11, color=theme.TEXT_MUTED), row=1, col=1)
    # The profile column's x (volume) axis stays fixed so panning/scrolling over
    # it can't slide the bars sideways; its y still follows the shared price axis.
    fig.update_xaxes(showticklabels=False, gridcolor=theme.GRID, fixedrange=True, row=1, col=2)
    # shared_yaxes=True keeps col 2 matched to col 1, so a price-axis drag
    # rescales the candles and the profile together.
    fig.update_yaxes(gridcolor=theme.GRID, side="right", fixedrange=False,
                     tickfont=dict(size=11, color=theme.TEXT_MUTED), row=1, col=1)
    fig.update_yaxes(showticklabels=False, fixedrange=False, row=1, col=2)

    st.plotly_chart(fig, width="stretch",
                    config={"displayModeBar": False, "scrollZoom": True,
                            "doubleClick": "reset+autosize"})
    if sr["levels"]:
        st.caption(f"{len(sr['levels'])} confirmed S/R level(s): "
                   + ", ".join(f"{l['price']:,.2f} ({l['num_pivots']}p)" for l in sr["levels"]))
    else:
        st.caption("No confirmed S/R levels yet in this lookback window.")


HTF_INTERVAL = "8h"   # left panel is always 8H, right panel is always 1H -- not user-selectable

top = st.columns([3, 1])
with top[0]:
    symbol = st.text_input("Instrument", value=load_last_symbol(), label_visibility="collapsed",
                            placeholder="Type any ticker (e.g. /NQ, /ES, AAPL)...").strip().upper()
with top[1]:
    refresh = st.button("Refresh", width="stretch")

if not symbol:
    st.stop()

# accept "NQ" or "/NQ" the same way -- futures need the leading slash to
# resolve a front-month contract, so normalize rather than force the syntax.
lookup_symbol = symbol if symbol.startswith("/") else f"/{symbol}"

st.caption("Dynamic S/R (pivot band-clustering) + Visible Range Profile — computed from scratch "
           f"against our own OHLC data. N={PIVOT_N}, lookback={LOOKBACK_BARS} bars, "
           f"band={BAND_WIDTH_PCT*100:.0f}%, min pivots={MIN_PIVOTS}.")
st.divider()

ttl = 0 if refresh else CACHE_TTL_SECONDS
with st.spinner(f"Loading {symbol}..."):
    htf_candles, htf_age, htf_err = chart_data.get_candles_cached(lookup_symbol, HTF_INTERVAL, HTF_DAYS, ttl)
    h1_candles, h1_age, h1_err = chart_data.get_candles_cached(lookup_symbol, "1h", H1_DAYS, ttl)
    if not htf_candles and not h1_candles:
        # not a futures symbol (or futures resolution failed) -- try as-typed,
        # e.g. plain equities like AAPL don't take a leading slash at all.
        htf_candles, htf_age, htf_err = chart_data.get_candles_cached(symbol, HTF_INTERVAL, HTF_DAYS, ttl)
        h1_candles, h1_age, h1_err = chart_data.get_candles_cached(symbol, "1h", H1_DAYS, ttl)
        lookup_symbol = symbol

if htf_candles or h1_candles:
    save_last_symbol(symbol)


def _age_pill(label, age):
    if not isinstance(age, (int, float)) or age < 60:
        return theme.pill("bull", f"{label} · fresh")
    return theme.pill("neutral", f"{label} · {age/60:.0f}m old")


theme.statusline(_age_pill(HTF_INTERVAL.upper(), htf_age) + _age_pill("1H", h1_age))

if "sr_expanded_panel" not in st.session_state:
    st.session_state.sr_expanded_panel = None
expanded = st.session_state.sr_expanded_panel

if expanded is None:
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("⤢ Expand", key="expand_htf", width="stretch"):
            st.session_state.sr_expanded_panel = "htf"
            st.rerun()
        if htf_err and not htf_candles:
            st.error(f"Couldn't load {HTF_INTERVAL} candles: {htf_err}")
        else:
            render_panel(htf_candles, symbol, HTF_INTERVAL.upper())
    with col_b:
        if st.button("⤢ Expand", key="expand_1h", width="stretch"):
            st.session_state.sr_expanded_panel = "1h"
            st.rerun()
        if h1_err and not h1_candles:
            st.error(f"Couldn't load 1H candles: {h1_err}")
        else:
            render_panel(h1_candles, symbol, "1H")
else:
    if st.button("✕ Back to both charts", width="stretch"):
        st.session_state.sr_expanded_panel = None
        st.rerun()
    if expanded == "htf":
        if htf_err and not htf_candles:
            st.error(f"Couldn't load {HTF_INTERVAL} candles: {htf_err}")
        else:
            render_panel(htf_candles, symbol, HTF_INTERVAL.upper(), height=780)
    else:
        if h1_err and not h1_candles:
            st.error(f"Couldn't load 1H candles: {h1_err}")
        else:
            render_panel(h1_candles, symbol, "1H", height=780)
