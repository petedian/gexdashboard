"""GEX Profile page - options volume/IV by strike for the 8 tracked
instruments, computed entirely from the same Tastytrade/dxFeed chain pull the
collector already does (no external/third-party data source, ever -- see
CLAUDE.md's Publishing & IP rules and GEX Profile conventions).
"""
import os
import sys
import math
import subprocess
from collections import defaultdict
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

import streamlit as st
import plotly.graph_objects as go

import theme
from instruments_config import GEX_PRODUCTS
from gex_database import (get_latest_snapshot, get_strike_volume_detail,
                           get_last_two_snapshot_ids, get_recent_snapshots)

st.set_page_config(page_title="GEX Profile", layout="wide", page_icon="📶")
theme.inject()
theme.sidebar_brand("GEX Profile — options flow by strike")

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "..", "gex_history.db")
COLLECTOR = os.path.join(HERE, "..", "collector_all.py")
CT = ZoneInfo("America/Chicago")

# Short TTL, same reasoning as Dashboard.py -- these reads are cheap (a few
# hundred rows, indexed), so caching longer would just fight freshness. Paired
# with the background poll below, an open tab picks up a new collector
# snapshot within about a minute of it landing.
CACHE_TTL_SECONDS = 60
AUTO_REFRESH_SECONDS = 60


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_latest_snapshot(symbol):
    return get_latest_snapshot(symbol, db_path=DB_PATH)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_strike_rows(snapshot_id):
    return get_strike_volume_detail(snapshot_id, db_path=DB_PATH)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_previous_rows(symbol):
    _, prev_id = get_last_two_snapshot_ids(symbol, db_path=DB_PATH)
    if prev_id is None:
        return []
    return get_strike_volume_detail(prev_id, db_path=DB_PATH)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_recent(symbol, limit=120):
    rows = get_recent_snapshots(symbol, limit=limit, db_path=DB_PATH)
    rows.reverse()
    return rows


def clear_data_caches():
    load_latest_snapshot.clear()
    load_strike_rows.clear()
    load_previous_rows.clear()
    load_recent.clear()


def pull_fresh_snapshot(symbol, timeout=60):
    """Same one-off subprocess pull mechanism as Dashboard.py/Chart page --
    collector_all.py isn't a persistent daemon, see gex-collector.timer."""
    try:
        subprocess.run([sys.executable, COLLECTOR, "--pull", symbol],
                        cwd=os.path.join(HERE, ".."), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        pass


def fmt(v):
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.1f}"
    if abs(v) >= 1:
        return f"{v:,.2f}"
    return f"{v:.4f}"


def describe_distance(strike, level, label, spot):
    if level is None:
        return None
    diff = strike - level
    tolerance = (spot * 0.0015) if spot else 0.5
    if abs(diff) <= tolerance:
        return f"AT {label}"
    direction = "above" if diff > 0 else "below"
    return f"{abs(diff):,.1f} pts {direction} {label}"


# ---------------------------- quick-access buttons ----------------------------
if "vp_symbol" not in st.session_state:
    st.session_state["vp_symbol"] = GEX_PRODUCTS[0]

quick_cols = st.columns(len(GEX_PRODUCTS))
for i, qsym in enumerate(GEX_PRODUCTS):
    with quick_cols[i]:
        if st.button(qsym, key=f"vp_quick_{qsym}", width="stretch",
                     type="primary" if st.session_state["vp_symbol"] == qsym else "secondary"):
            st.session_state["vp_symbol"] = qsym

symbol = st.session_state["vp_symbol"]

top = st.columns([3, 1])
with top[0]:
    st.caption(f"Options volume/IV by strike for {symbol} — same Tastytrade chain pull "
               f"the collector already does every 10 min, no other data source.")
with top[1]:
    refresh = st.button("Refresh (ignore cache)", width="stretch", key="vp_refresh")

# Background poll: reruns the page the moment the collector writes a newer
# snapshot for this symbol, no user interaction required (mirrors the same
# pattern on pages/1_GEX_Chart.py).
@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _poll_for_new_snapshot(sym=symbol):
    snap = get_latest_snapshot(sym, db_path=DB_PATH)
    seen_key = f"_vp_last_seen_{sym}"
    latest_ts = snap["captured_at"] if snap else None
    if seen_key not in st.session_state:
        st.session_state[seen_key] = latest_ts
    elif st.session_state[seen_key] != latest_ts:
        st.session_state[seen_key] = latest_ts
        st.rerun()
_poll_for_new_snapshot()

if refresh:
    with st.spinner(f"Pulling fresh data for {symbol}…"):
        pull_fresh_snapshot(symbol)
        clear_data_caches()

snap = load_latest_snapshot(symbol)
if not snap:
    theme.empty_state(f"{symbol} — no data yet",
                      "Waiting for the collector's first scheduled sweep, or click Refresh above.")
    st.stop()

rows = load_strike_rows(snap["id"])
if not rows:
    theme.empty_state(f"{symbol} — no volume/IV data yet",
                      "This snapshot predates the volume/IV capture, or hasn't been pulled "
                      "since -- click Refresh above, or wait for the next scheduled sweep.")
    st.stop()

# ---------------------------- expiration selector ----------------------------
by_exp = defaultdict(list)
for r in rows:
    by_exp[r["expiration"]].append(r)
expirations = sorted(by_exp.keys())[:3]

if "vp_expiration" not in st.session_state or st.session_state["vp_expiration"] not in expirations:
    st.session_state["vp_expiration"] = expirations[0]

today_str = datetime.now(CT).date().isoformat()
exp_cols = st.columns(len(expirations))
for i, exp in enumerate(expirations):
    with exp_cols[i]:
        label = f"{exp} (0DTE)" if exp == today_str else exp
        if st.button(label, key=f"vp_exp_{exp}", width="stretch",
                     type="primary" if st.session_state["vp_expiration"] == exp else "secondary"):
            st.session_state["vp_expiration"] = exp

selected_exp = st.session_state["vp_expiration"]
exp_rows = sorted(by_exp[selected_exp], key=lambda r: r["strike"])

mode = st.radio("View", ["Session total", "Last 10-min delta"], horizontal=True,
                 key="vp_mode", label_visibility="collapsed")

if mode == "Last 10-min delta":
    prev_rows = load_previous_rows(symbol)
    prev_by_strike = {r["strike"]: r for r in prev_rows if r["expiration"] == selected_exp}
    display_rows = []
    for r in exp_rows:
        p = prev_by_strike.get(r["strike"], {})
        cv = (r["call_volume"] or 0) - (p.get("call_volume") or 0)
        pv = (r["put_volume"] or 0) - (p.get("put_volume") or 0)
        # floor at 0 -- a negative delta means a volume-count reset (e.g. day
        # rollover) between snapshots, not that volume went backwards
        display_rows.append({**r, "call_volume": max(cv, 0), "put_volume": max(pv, 0)})
    if not prev_rows:
        st.caption("Only one snapshot exists yet for this expiration -- delta will show once "
                   "a second collector pull lands.")
else:
    display_rows = exp_rows

spot = snap["spot_price"]

# ---------------------------- header stats ----------------------------
total_call = sum(r["call_volume"] or 0 for r in display_rows)
total_put = sum(r["put_volume"] or 0 for r in display_rows)
hist = load_recent(symbol)
day_change = None
if len(hist) > 1 and hist[0].get("spot_price") and spot:
    base = hist[0]["spot_price"]
    if base:
        day_change = (spot - base) / base

h1, h2, h3, h4, h5 = st.columns(5)
with h1: theme.stat_tile("Spot", fmt(spot))
with h2: theme.stat_tile("Today's Change", f"{day_change * 100:+.2f}%" if day_change is not None else "—")
with h3: theme.stat_tile("Put Volume", f"{total_put:,}")
with h4: theme.stat_tile("Call Volume", f"{total_call:,}")
with h5: theme.stat_tile("P/C Ratio", f"{(total_put / total_call):.2f}" if total_call else "—", accent=True)

# ---------------------------- expected move ----------------------------
# Standard closed-form 1-sigma lognormal move: Spot x ATM_IV x sqrt(T/365).
# Sourced from Greeks.volatility (already collected) rather than a live ATM
# straddle premium -- robust even when a specific strike's last trade is
# stale or missing. See CLAUDE.md's GEX Profile conventions.
atm_row = min(exp_rows, key=lambda r: abs(r["strike"] - spot)) if spot else None
atm_iv = None
if atm_row:
    atm_iv = atm_row["call_iv"] if atm_row["strike"] >= spot else atm_row["put_iv"]
    if atm_iv is None:
        atm_iv = atm_row["put_iv"] or atm_row["call_iv"]

try:
    exp_date = date.fromisoformat(selected_exp)
    days_to_expiry = (exp_date - datetime.now(CT).date()).days
except ValueError:
    days_to_expiry = None

expected_move = None
if atm_iv and spot and days_to_expiry is not None:
    # 0DTE still has hours left in the session -- floor at a fraction of a day
    # rather than showing a literal zero-width band at T=0.
    t_days = max(days_to_expiry, 0.3)
    expected_move = spot * float(atm_iv) * math.sqrt(t_days / 365)

# ---------------------------- IV smile (OTM side per strike) ----------------------------
iv_smile_x, iv_smile_y = [], []
for r in exp_rows:
    otm_iv = r["call_iv"] if r["strike"] >= spot else r["put_iv"]
    if otm_iv is None:
        otm_iv = r["put_iv"] if r["strike"] >= spot else r["call_iv"]
    if otm_iv is not None:
        iv_smile_x.append(r["strike"])
        iv_smile_y.append(float(otm_iv) * 100)

# ---------------------------- chart ----------------------------
strikes = [r["strike"] for r in display_rows]
call_vols = [r["call_volume"] or 0 for r in display_rows]
put_vols = [r["put_volume"] or 0 for r in display_rows]

fig = go.Figure()
fig.add_trace(go.Bar(x=strikes, y=call_vols, name="Call Volume", marker_color=theme.BULLISH))
fig.add_trace(go.Bar(x=strikes, y=put_vols, name="Put Volume", marker_color=theme.BEARISH))

if iv_smile_x:
    fig.add_trace(go.Scatter(x=iv_smile_x, y=iv_smile_y, name="IV Smile", mode="lines",
                              line=dict(color=theme.TEXT_MUTED, dash="dash", width=1.6),
                              yaxis="y2"))

if expected_move:
    fig.add_vrect(x0=spot - expected_move, x1=spot + expected_move,
                  fillcolor=theme.PRIMARY, opacity=0.10, line_width=0,
                  annotation_text=f"±1σ ({expected_move:,.1f}pt)", annotation_position="top left",
                  annotation_font=dict(color=theme.PRIMARY, family=theme.FONT_MONO, size=10))
    fig.add_vrect(x0=spot - 2 * expected_move, x1=spot + 2 * expected_move,
                  fillcolor=theme.PRIMARY, opacity=0.05, line_width=0,
                  annotation_text=f"±2σ ({2 * expected_move:,.1f}pt)", annotation_position="top right",
                  annotation_font=dict(color=theme.PRIMARY, family=theme.FONT_MONO, size=10))

# These overlay lines are "our" reference levels for whichever expiration is
# selected. The GEX snapshot's call_wall/put_wall/gamma_flip are blended
# across all 4 fetched expirations -- accurate context regardless of which
# expiration's volume you're looking at, but not specific to it. When the
# selected expiration IS the one the collector computed a dedicated 0DTE-only
# reading for (snap["dte_expiration"], see collector_all.py's engine_0dte),
# use that instead -- it reflects only today's chain, not a blend diluted by
# weekly/monthly OI.
showing_0dte_levels = selected_exp == snap.get("dte_expiration") and any(
    snap.get(k) for k in ("call_wall_0dte", "put_wall_0dte", "gamma_flip_0dte"))
if showing_0dte_levels:
    wall_put, wall_call, flip = (snap.get("put_wall_0dte"), snap.get("call_wall_0dte"),
                                  snap.get("gamma_flip_0dte"))
else:
    wall_put, wall_call, flip = snap.get("put_wall"), snap.get("call_wall"), snap.get("gamma_flip")

for label, level, color, dash, width in [
    ("Put Wall", wall_put, theme.BULLISH, "dash", 1.2),
    ("Call Wall", wall_call, theme.BEARISH, "dash", 1.2),
    ("Gamma Flip", flip, theme.PRIMARY, "solid", 2.4),
]:
    if level:
        fig.add_vline(x=level, line_dash=dash, line_width=width, line_color=color, opacity=0.9,
                      annotation_text=label, annotation_position="top",
                      annotation_font=dict(color=color, family=theme.FONT_MONO, size=10))

# Top-3 call/put volume strikes -- today's most fought-over levels
top_calls = sorted(display_rows, key=lambda r: r["call_volume"] or 0, reverse=True)[:3]
top_puts = sorted(display_rows, key=lambda r: r["put_volume"] or 0, reverse=True)[:3]
for r in top_calls:
    if r["call_volume"]:
        fig.add_annotation(x=r["strike"], y=r["call_volume"], text=f"{r['call_volume']:,}",
                           showarrow=False, yshift=12,
                           font=dict(size=9, color=theme.BULLISH, family=theme.FONT_MONO))
for r in top_puts:
    if r["put_volume"]:
        fig.add_annotation(x=r["strike"], y=r["put_volume"], text=f"{r['put_volume']:,}",
                           showarrow=False, yshift=12,
                           font=dict(size=9, color=theme.BEARISH, family=theme.FONT_MONO))

fig.update_layout(
    plot_bgcolor=theme.BG, paper_bgcolor=theme.BG, font=theme.PLOTLY_FONT,
    hoverlabel=theme.PLOTLY_HOVERLABEL,
    height=560,
    barmode="group",
    bargap=0.15,
    margin=dict(l=10, r=110, t=60, b=10),
    title=dict(
        text=f"{symbol} GEX Profile", x=0.01,
        font=dict(size=17, color=theme.TEXT, family=theme.PLOTLY_FONT["family"]),
        subtitle=dict(text=f"{selected_exp} expiration · {mode} · "
                           f"{'0DTE-only levels' if showing_0dte_levels else 'blended levels (4 nearest exp)'}",
                      font=dict(size=11.5, color=theme.TEXT_MUTED)),
    ),
    xaxis=dict(title="Strike", gridcolor=theme.GRID, showline=False,
               tickfont=dict(size=11, color=theme.TEXT_MUTED)),
    yaxis=dict(title="Volume", gridcolor=theme.GRID, showline=False,
               tickfont=dict(size=11, color=theme.TEXT_MUTED)),
    yaxis2=dict(title="IV %", overlaying="y", side="right", showgrid=False,
                tickfont=dict(size=11, color=theme.TEXT_MUTED)),
    legend=dict(orientation="h", y=1.14, x=0, font=dict(size=10, color=theme.TEXT_MUTED)),
    hovermode="x unified",
)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
theme.export_png_button(fig, key=f"export_volprofile_{symbol}_{selected_exp}")

if not iv_smile_x:
    st.caption(f"IV data unavailable for {symbol}'s {selected_exp} expiration -- smile hidden.")

# ---------------------------- Volume vs. Walls readout ----------------------------
readout_lines = []
if top_calls and top_calls[0]["call_volume"]:
    r = top_calls[0]
    parts = [p for p in [
        describe_distance(r["strike"], snap.get("call_wall"), "call wall", spot),
        describe_distance(r["strike"], snap.get("put_wall"), "put wall", spot),
        describe_distance(r["strike"], snap.get("gamma_flip"), "gamma flip", spot),
    ] if p]
    readout_lines.append(f"Heaviest call volume **{r['strike']:,.1f}** ({r['call_volume']:,}) — "
                          + "; ".join(parts) if parts else "no wall/flip data yet")
if top_puts and top_puts[0]["put_volume"]:
    r = top_puts[0]
    parts = [p for p in [
        describe_distance(r["strike"], snap.get("call_wall"), "call wall", spot),
        describe_distance(r["strike"], snap.get("put_wall"), "put wall", spot),
        describe_distance(r["strike"], snap.get("gamma_flip"), "gamma flip", spot),
    ] if p]
    readout_lines.append(f"Heaviest put volume **{r['strike']:,.1f}** ({r['put_volume']:,}) — "
                          + "; ".join(parts) if parts else "no wall/flip data yet")

if readout_lines:
    with st.container(border=True):
        st.markdown("**Volume vs. Walls**")
        for line in readout_lines:
            st.caption(line)

theme.footer(
    "GexFlows — data via Tastytrade / dxFeed · options volume & IV by strike",
    "Factual alignment only -- not a prediction of future price action",
)
