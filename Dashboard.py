"""GexFlows Dashboard - live gamma levels across the 8 tracked instruments."""
import streamlit as st
import sqlite3
import os
import sys
import subprocess
import pandas as pd
from datetime import datetime, timedelta, timezone
import theme
from instruments_config import PAIRS, GEX_PRODUCTS
from gex_database import get_latest_snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "gex_history.db")
COLLECTOR = os.path.join(HERE, "collector_all.py")

st.set_page_config(page_title="GexFlows", layout="wide", page_icon="📊")
theme.inject()
theme.sidebar_brand("Live gamma exposure terminal")

# Data considered "live" if the newest snapshot is younger than this. The
# collector sweeps every 10 min inside its scheduled window; 20 min of
# silence means the window has closed or something's stalled.
LIVE_THRESHOLD_SECONDS = 20 * 60

# Short TTL, deliberately much shorter than the collector's 10-min cadence --
# this is the upper bound on how stale an auto-refreshed card can be between
# collector writes, not a target to match it to. Queries here cost under 1ms
# (see the (product, captured_at DESC) index), so there's no real perf reason
# to cache longer, and a long TTL actively fights freshness. A manual
# Refresh/Pull explicitly clears these before rerunning regardless.
CACHE_TTL_SECONDS = 60

# How often the dashboard body re-renders itself with no user interaction
# (st.fragment(run_every=...)) -- keeps an open tab current within roughly
# this long of any new collector write, without needing a manual reload.
AUTO_REFRESH_SECONDS = 60


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_latest(product):
    return get_latest_snapshot(product, db_path=DB_PATH)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_history(product, limit=120):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""SELECT captured_at, spot_price, call_wall, put_wall, gamma_flip
        FROM gex_snapshots WHERE product = ?
        ORDER BY captured_at DESC LIMIT ?""", (product, limit))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    rows.reverse()
    return rows


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_overview():
    """Total snapshot count + newest capture timestamp, in one query pass."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MAX(captured_at) FROM gex_snapshots")
    n, latest = cur.fetchone()
    conn.close()
    return n, latest


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_export_df(start=None, end=None):
    """One row per instrument per snapshot -- the four GEX levels only (no
    raw-strike detail), for the CSV export and on-screen History table."""
    conn = sqlite3.connect(DB_PATH)
    placeholders = ",".join("?" * len(GEX_PRODUCTS))
    query = (f"SELECT captured_at, product, spot_price, call_wall, put_wall, gamma_flip "
             f"FROM gex_snapshots WHERE product IN ({placeholders})")
    params = list(GEX_PRODUCTS)
    if start:
        query += " AND captured_at >= ?"
        params.append(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).isoformat())
    if end:
        query += " AND captured_at < ?"
        params.append(datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).isoformat())
    query += " ORDER BY captured_at DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df.rename(columns={"captured_at": "timestamp", "product": "symbol",
                               "spot_price": "spot"})


def run_collector(args_list, timeout=60):
    """Runs collector_all.py as a one-off subprocess and waits for it to
    finish -- used by both the per-card Pull buttons and the page-wide
    Refresh button. Replaces the old flag-file-for-a-daemon-to-notice
    handshake now that the collector isn't a persistent process anymore
    (see gex-collector.timer)."""
    try:
        result = subprocess.run([sys.executable, COLLECTOR] + args_list, cwd=HERE,
                                 capture_output=True, text=True, timeout=timeout)
        lines = [ln for ln in (result.stdout + result.stderr).splitlines() if ln.strip()]
    except subprocess.TimeoutExpired:
        lines = [f"  timed out after {timeout}s"]
    failed = [ln for ln in lines if "ERROR" in ln or "SKIP" in ln]
    return lines, failed


def clear_data_caches():
    get_latest.clear()
    get_history.clear()
    get_overview.clear()
    get_export_df.clear()


def age_seconds(iso_ts):
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return None


def age_label(iso_ts):
    s = age_seconds(iso_ts)
    if s is None:
        return "—"
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{s / 60:.0f}m ago"
    if s < 86400:
        return f"{s / 3600:.0f}h ago"
    return f"{s / 86400:.0f}d ago"


def local_time(iso_ts):
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%H:%M:%S")
    except Exception:
        return "—"


def fmt(v):
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.1f}"
    if abs(v) >= 1:
        return f"{v:,.2f}"
    return f"{v:.4f}"


# ---------------------------- cards ----------------------------
def render_product(product):
    data = get_latest(product)
    if not data:
        theme.empty_state(f"{product} — no data yet",
                          "Waiting for the collector's first scheduled sweep, or use Refresh above.")
        return
    spot = data["spot_price"]; cw = data["call_wall"]
    pw = data["put_wall"]; flip = data["gamma_flip"]

    if flip is not None and spot is not None:
        regime = (theme.pill("bull", "Positive gamma") if spot > flip
                  else theme.pill("bear", "Negative gamma"))
    else:
        regime = theme.pill("neutral", "No flip data")

    hist = get_history(product, limit=120)
    delta = None
    if len(hist) > 3 and hist[0].get("spot_price") and spot:
        base = hist[0]["spot_price"]
        if base:
            delta = (spot - base) / base

    with st.container(border=True):
        head_col, pull_col = st.columns([6, 1])
        with head_col:
            theme.card_head(product,
                            delta_html=theme.delta_html(delta),
                            right_html=regime,
                            meta=age_label(data["captured_at"]))
        with pull_col:
            if st.button("📡", key=f"pull_{product}", width="stretch",
                         help=f"Force a live pull for {product} only (~15-20s, works "
                              f"outside the scheduled window)"):
                with st.spinner(f"Pulling {product}…"):
                    lines, failed = run_collector(["--pull", product])
                clear_data_caches()
                if failed:
                    st.toast(f"{product} pull failed: {failed[0].strip()}", icon="⚠️")
                else:
                    st.toast(f"{product} updated.", icon="📡")
                st.rerun()
        c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1.3])
        with c1: theme.stat_tile("Spot", fmt(spot))
        with c2: theme.stat_tile("Call Wall", fmt(cw))
        with c3: theme.stat_tile("Put Wall", fmt(pw))
        with c4: theme.stat_tile("Gamma Flip", fmt(flip), accent=True)
        theme.level_map(spot, pw, cw, flip, fmt=fmt)
        if len(hist) > 3:
            df = pd.DataFrame(hist)
            df["t"] = pd.to_datetime(df["captured_at"])
            chart_df = df[["t", "spot_price", "call_wall", "put_wall"]].set_index("t")
            st.line_chart(chart_df, height=160,
                          color=[theme.PRIMARY, theme.BEARISH, theme.BULLISH])
            theme.spark_legend([("Spot", theme.PRIMARY),
                                ("Call Wall", theme.BEARISH),
                                ("Put Wall", theme.BULLISH)])


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def render_dashboard_body():
    """Everything below the sidebar chrome, self-refreshing on its own timer
    (independent of user interaction) so an open tab picks up new collector
    writes without a manual reload -- see AUTO_REFRESH_SECONDS/CACHE_TTL_SECONDS
    above. Refresh/Pull buttons inside here still force an immediate update on
    click (subprocess pull + cache clear + st.rerun()) rather than waiting for
    the next tick."""
    # ---------------------------- header ----------------------------
    total_snaps, newest_ts = get_overview()
    feed_age = age_seconds(newest_ts) if newest_ts else None
    if feed_age is not None and feed_age < LIVE_THRESHOLD_SECONDS:
        status = theme.pill("bull", "Live", pulse=True)
    else:
        status = theme.pill("neutral", f"Idle · {age_label(newest_ts)}" if newest_ts else "No data")

    theme.hero(
        "GexFlows",
        "Gamma exposure levels — futures & index options · near-term structure",
        chips_html=(theme.chip("Snapshots", f"{total_snaps:,}")
                    + theme.chip("Last capture", local_time(newest_ts) if newest_ts else "—")),
        status_html=status,
    )

    hdr = st.columns([1, 5])
    with hdr[0]:
        if st.button("↻ Refresh", width="stretch",
                     help="Pulls fresh live data for all 8 instruments now (~15-20s), then "
                          "reloads. Works outside the scheduled collection window too."):
            with st.status("Pulling live data for all 8 instruments…", expanded=True) as status_box:
                lines, failed = run_collector(["--pull-all"])
                for ln in lines:
                    status_box.write(ln)
                if failed:
                    status_box.update(label=f"Done — {len(failed)} instrument(s) failed", state="error")
                else:
                    status_box.update(label="Done — all 8 instruments updated", state="complete")
            clear_data_caches()
            st.rerun()

    # ---------------------------- cards ----------------------------
    st.caption("Full GEX sweep — options chain, walls, gamma flip. Updated every 10 min, "
               "07:30–16:00 America/Chicago (Mon–Fri). This page auto-refreshes itself "
               f"every {AUTO_REFRESH_SECONDS}s.")
    for future, counterpart in PAIRS:
        row = st.columns(2)
        with row[0]:
            render_product(future)
        with row[1]:
            render_product(counterpart)

    # ---------------------------- history / export ----------------------------
    with st.expander(f"History — {total_snaps:,} snapshots", expanded=False):
        dcol1, dcol2 = st.columns(2)
        hist_start = dcol1.date_input("From", value=None, key="hist_from")
        hist_end = dcol2.date_input("To", value=None, key="hist_to")

        hist_df = get_export_df(hist_start or None, hist_end or None)
        st.dataframe(hist_df, width="stretch", hide_index=True)

        st.download_button(
            "⬇ Download history (CSV)",
            hist_df.to_csv(index=False).encode(),
            file_name=f"gexflows_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            width="stretch",
        )

    theme.footer(
        "GexFlows — data via Tastytrade / dxFeed · near-term (4 nearest expirations)",
        "Levels are probabilistic market-structure context, not trading signals",
    )


render_dashboard_body()
