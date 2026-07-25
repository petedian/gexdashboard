"""Shared visual theme for the dashboard -- Key Level Trading brand. One
source of truth for colors so Dashboard.py, pages/1_Chart.py, and any future
pages all match instead of each hand-rolling its own palette.

Also exposes small HTML component helpers (pill, card_head, empty_state,
hero, spark_legend, footer, stat_tile, export_png_button) so pages share one
visual language instead of re-inventing ad-hoc markup.
"""
from datetime import datetime

import streamlit as st
import plotly.graph_objects as go

BG = "#0b1220"
BG_SECONDARY = "#101a2e"
GRID = "#1d2a44"
TEXT = "#e9edf4"
TEXT_MUTED = "#8b98ad"
# Brass -- THE key color: key levels, gamma flip, primary buttons, highlights.
PRIMARY = "#c9a34a"
PRIMARY_HOVER = "#e8c979"
BULLISH = "#5fae8a"
BEARISH = "#c96a5a"

# rgba() derivatives of the same palette hues -- used for glows, washes and
# translucent surfaces. No new hues, just alpha steps of the approved colors.
PRIMARY_RGB = "201, 163, 74"
BULLISH_RGB = "95, 174, 138"
BEARISH_RGB = "201, 106, 90"

# Typography -- Bricolage Grotesque for headings, Archivo for body/UI text,
# IBM Plex Mono for every numeric readout (prices, strikes, tickers).
FONT_HEADING = "'Bricolage Grotesque', -apple-system, sans-serif"
FONT_BODY = "'Archivo', -apple-system, sans-serif"
FONT_MONO = "'IBM Plex Mono', ui-monospace, monospace"

# Plotly defaults shared by every chart page so all figures read as one
# system. Mono because axis ticks, hover values, and titles are all
# tickers/prices/strikes.
PLOTLY_FONT = dict(family=FONT_MONO, size=12, color=TEXT)
PLOTLY_HOVERLABEL = dict(
    bgcolor=BG_SECONDARY,
    bordercolor=GRID,
    font=dict(family=FONT_MONO, size=12, color=TEXT),
)


def inject():
    st.markdown(f"""<style>
        @import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@700;800&family=Archivo:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

        html, body, .stApp, [class*="css"] {{
            font-family: {FONT_BODY};
        }}

        /* base surface: flat brand dark with a barely-there cool wash at the
           top so the app has depth without introducing any new hue */
        .stApp {{
            background-color: {BG};
            background-image: radial-gradient(ellipse 90% 40% at 50% -10%,
                rgba({PRIMARY_RGB}, 0.05), transparent 65%);
            background-attachment: fixed;
        }}

        /* streamlit's top chrome: translucent glass instead of a solid slab */
        [data-testid="stHeader"] {{
            background: rgba(19, 23, 34, 0.82);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
        }}

        /* ---------------- typography ---------------- */
        h1, h2, h3 {{
            color: {TEXT};
            font-family: {FONT_HEADING};
            font-weight: 700;
            letter-spacing: -0.01em;
        }}
        h1 {{ font-weight: 800; letter-spacing: -0.02em; }}
        h2 {{
            border-left: 3px solid {PRIMARY};
            padding-left: 12px;
            font-size: 1.3rem;
        }}
        [data-testid="stCaptionContainer"], .stCaption {{ color: {TEXT_MUTED}; }}

        /* ---------------- metric tiles ---------------- */
        [data-testid="stMetric"] {{
            background: linear-gradient(180deg, {BG_SECONDARY} 0%, rgba(26, 30, 41, 0.55) 100%);
            padding: 14px 16px;
            border-radius: 10px;
            border: 1px solid {GRID};
            border-top-color: rgba(255, 255, 255, 0.07);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
            transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
        }}
        [data-testid="stMetric"]:hover {{
            transform: translateY(-2px);
            border-color: rgba({PRIMARY_RGB}, 0.55);
            box-shadow: 0 8px 22px rgba(0, 0, 0, 0.4),
                        0 0 0 1px rgba({PRIMARY_RGB}, 0.12);
        }}
        [data-testid="stMetricLabel"] {{
            color: {TEXT_MUTED};
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.07em;
        }}
        [data-testid="stMetricLabel"] p {{ font-size: 0.72rem; }}
        [data-testid="stMetricValue"] {{
            font-family: {FONT_MONO};
            font-weight: 600;
            letter-spacing: -0.01em;
        }}

        /* ---------------- bordered containers (cards) ---------------- */
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: linear-gradient(180deg, {BG_SECONDARY} 0%, rgba(26, 30, 41, 0.7) 100%);
            border-color: {GRID} !important;
            border-radius: 14px !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04),
                        0 4px 14px rgba(0, 0, 0, 0.22);
            transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
            border-color: rgba({PRIMARY_RGB}, 0.45) !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04),
                        0 10px 26px rgba(0, 0, 0, 0.35),
                        0 0 0 1px rgba({PRIMARY_RGB}, 0.10);
        }}

        /* ---------------- buttons ---------------- */
        .stButton > button {{
            border-radius: 8px;
            border: 1px solid {GRID};
            background-color: {BG_SECONDARY};
            color: {TEXT};
            font-weight: 500;
            min-height: 44px;
            transition: all 0.15s ease;
        }}
        .stButton > button:hover {{
            border-color: {PRIMARY};
            color: {PRIMARY};
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }}
        .stButton > button:active {{ transform: translateY(0px); }}
        .stButton > button:focus-visible {{
            outline: none;
            box-shadow: 0 0 0 3px rgba({PRIMARY_RGB}, 0.35);
        }}

        /* ---------------- inputs / selects ---------------- */
        .stTextInput input, .stSelectbox > div > div, .stTextArea textarea {{
            background-color: {BG_SECONDARY};
            border-radius: 8px;
            border: 1px solid {GRID};
            transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }}
        .stTextInput input:focus, .stTextArea textarea:focus {{
            border-color: {PRIMARY} !important;
            box-shadow: 0 0 0 3px rgba({PRIMARY_RGB}, 0.18);
        }}

        /* ---------------- tabs: quiet underline style ---------------- */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 6px;
            border-bottom: 1px solid {GRID};
        }}
        .stTabs [data-baseweb="tab"] {{
            color: {TEXT_MUTED};
            font-weight: 600;
            letter-spacing: 0.01em;
            background: transparent;
            border-radius: 8px 8px 0 0;
            transition: color 0.15s ease, background-color 0.15s ease;
        }}
        .stTabs [data-baseweb="tab"]:hover {{
            color: {TEXT};
            background-color: rgba({PRIMARY_RGB}, 0.06);
        }}
        .stTabs [aria-selected="true"] {{ color: {TEXT} !important; }}
        .stTabs [data-baseweb="tab-highlight"] {{ background-color: {PRIMARY}; height: 2px; }}
        .stTabs [data-baseweb="tab-border"] {{ background-color: {GRID}; }}

        /* dividers a touch more subtle */
        hr {{ border-color: {GRID}; }}

        /* st.info/warning/error/success default to light-theme colors that
           clash against this dark background -- force the dark card style,
           let the built-in icon keep its own semantic color */
        [data-testid="stAlertContainer"] {{
            background-color: {BG_SECONDARY} !important;
            border: 1px solid {GRID} !important;
            border-left: 3px solid {PRIMARY} !important;
            border-radius: 10px !important;
            color: {TEXT} !important;
        }}
        [data-testid="stAlertContainer"] p {{ color: {TEXT} !important; }}

        /* expanders match the card language */
        [data-testid="stExpander"] {{
            border: 1px solid {GRID};
            border-radius: 10px;
            background-color: {BG_SECONDARY};
            overflow: hidden;
        }}
        [data-testid="stExpander"] summary {{ color: {TEXT_MUTED}; }}
        [data-testid="stExpander"] summary:hover {{ color: {TEXT}; }}

        /* ---------------- sidebar ---------------- */
        [data-testid="stSidebar"] {{
            background-color: {BG_SECONDARY};
            border-right: 1px solid {GRID};
        }}
        [data-testid="stSidebarNav"] a {{
            border-radius: 8px;
            transition: background-color 0.15s ease;
        }}
        [data-testid="stSidebarNav"] a:hover {{
            background-color: rgba({PRIMARY_RGB}, 0.08);
        }}
        .sidebar-brand {{
            padding: 16px 20px 14px 20px;
            border-bottom: 1px solid {GRID};
            margin-bottom: 8px;
        }}
        .sidebar-brand-eyebrow {{
            font-family: {FONT_MONO};
            font-size: 0.62rem;
            font-weight: 600;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: {PRIMARY};
            margin-bottom: 6px;
        }}
        .sidebar-brand-row {{ display: flex; align-items: center; gap: 12px; }}
        .sidebar-brand-mark {{
            width: 38px; height: 38px;
            border-radius: 10px;
            display: flex; align-items: center; justify-content: center;
            font-size: 19px;
            background: linear-gradient(135deg, rgba({PRIMARY_RGB}, 0.22), rgba({PRIMARY_RGB}, 0.06));
            border: 1px solid rgba({PRIMARY_RGB}, 0.35);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
            flex-shrink: 0;
        }}
        .sidebar-brand-title {{
            font-family: {FONT_HEADING};
            font-size: 1.02rem;
            font-weight: 700;
            color: {TEXT};
            letter-spacing: 0.01em;
            line-height: 1.15;
        }}
        .sidebar-brand-sub {{
            font-size: 0.7rem;
            color: {TEXT_MUTED};
            margin-top: 2px;
            letter-spacing: 0.01em;
        }}
        .sidebar-brand-tagline {{
            font-family: {FONT_MONO};
            font-size: 0.66rem;
            font-weight: 500;
            color: {PRIMARY};
            margin-top: 8px;
            letter-spacing: 0.02em;
        }}

        /* dataframes/tables, if any page uses them */
        [data-testid="stDataFrame"] {{ border: 1px solid {GRID}; border-radius: 8px; }}

        /* ---------------- scrollbars ---------------- */
        ::-webkit-scrollbar {{ width: 10px; height: 10px; }}
        ::-webkit-scrollbar-track {{ background: {BG}; }}
        ::-webkit-scrollbar-thumb {{
            background: {GRID};
            border-radius: 6px;
            border: 2px solid {BG};
        }}
        ::-webkit-scrollbar-thumb:hover {{ background: {TEXT_MUTED}; }}

        /* ================= shared components ================= */

        /* hero band (main page header) */
        .gx-hero {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            flex-wrap: wrap;
            padding: 20px 24px;
            border-radius: 14px;
            border: 1px solid {GRID};
            background:
                radial-gradient(500px 130px at 0% 0%, rgba({PRIMARY_RGB}, 0.10), transparent 65%),
                linear-gradient(180deg, {BG_SECONDARY} 0%, rgba(26, 30, 41, 0.55) 100%);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05),
                        0 6px 20px rgba(0, 0, 0, 0.28);
            margin-bottom: 6px;
        }}
        .gx-hero-left {{ display: flex; align-items: center; gap: 14px; min-width: 0; }}
        .gx-logo {{
            width: 46px; height: 46px;
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 23px;
            background: linear-gradient(135deg, rgba({PRIMARY_RGB}, 0.25), rgba({PRIMARY_RGB}, 0.07));
            border: 1px solid rgba({PRIMARY_RGB}, 0.4);
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
            flex-shrink: 0;
        }}
        .gx-hero-title {{
            font-family: {FONT_HEADING};
            font-size: 1.45rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: {TEXT};
            line-height: 1.15;
        }}
        .gx-hero-sub {{ font-size: 0.8rem; color: {TEXT_MUTED}; margin-top: 3px; }}
        .gx-hero-right {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}

        /* stat chips (hero right side) */
        .gx-chip {{
            padding: 8px 14px;
            border-radius: 10px;
            background: rgba(19, 23, 34, 0.55);
            border: 1px solid {GRID};
            min-width: 92px;
        }}
        .gx-chip-label {{
            font-size: 0.62rem;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            color: {TEXT_MUTED};
            font-weight: 600;
        }}
        .gx-chip-value {{
            font-family: {FONT_MONO};
            font-size: 0.95rem;
            font-weight: 600;
            color: {TEXT};
            margin-top: 1px;
        }}

        /* status / regime pills */
        .gx-pill {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 3px 11px;
            border-radius: 999px;
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            white-space: nowrap;
            border: 1px solid;
        }}
        .gx-pill .gx-dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }}
        .gx-pill-bull {{
            color: {BULLISH};
            background: rgba({BULLISH_RGB}, 0.12);
            border-color: rgba({BULLISH_RGB}, 0.35);
        }}
        .gx-pill-bull .gx-dot {{ background: {BULLISH}; }}
        .gx-pill-bear {{
            color: {BEARISH};
            background: rgba({BEARISH_RGB}, 0.12);
            border-color: rgba({BEARISH_RGB}, 0.35);
        }}
        .gx-pill-bear .gx-dot {{ background: {BEARISH}; }}
        .gx-pill-accent {{
            color: {PRIMARY};
            background: rgba({PRIMARY_RGB}, 0.12);
            border-color: rgba({PRIMARY_RGB}, 0.35);
        }}
        .gx-pill-accent .gx-dot {{ background: {PRIMARY}; }}
        .gx-pill-neutral {{
            color: {TEXT_MUTED};
            background: rgba(120, 123, 134, 0.10);
            border-color: rgba(120, 123, 134, 0.35);
        }}
        .gx-pill-neutral .gx-dot {{ background: {TEXT_MUTED}; }}

        @keyframes gx-pulse {{
            0%   {{ box-shadow: 0 0 0 0 rgba({BULLISH_RGB}, 0.5); }}
            70%  {{ box-shadow: 0 0 0 6px rgba({BULLISH_RGB}, 0); }}
            100% {{ box-shadow: 0 0 0 0 rgba({BULLISH_RGB}, 0); }}
        }}
        .gx-dot-pulse {{ animation: gx-pulse 2s ease-out infinite; }}

        /* product card header row */
        .gx-card-head {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            flex-wrap: wrap;
            margin: 2px 0 10px 0;
        }}
        .gx-card-head-left {{ display: flex; align-items: baseline; gap: 10px; min-width: 0; }}
        .gx-card-symbol {{
            font-family: {FONT_MONO};
            font-size: 1.08rem;
            font-weight: 600;
            letter-spacing: 0.01em;
            color: {TEXT};
        }}
        .gx-card-head-right {{ display: flex; align-items: center; gap: 10px; }}
        .gx-card-meta {{ font-size: 0.7rem; color: {TEXT_MUTED}; white-space: nowrap; }}
        .gx-delta-up {{ font-family: {FONT_MONO}; color: {BULLISH}; font-weight: 600; font-size: 0.82rem; }}
        .gx-delta-down {{ font-family: {FONT_MONO}; color: {BEARISH}; font-weight: 600; font-size: 0.82rem; }}
        .gx-delta-flat {{ font-family: {FONT_MONO}; color: {TEXT_MUTED}; font-weight: 600; font-size: 0.82rem; }}

        /* ---------------- stat tiles (like stMetric, but styleable per-instance) ---------------- */
        .gx-stat {{
            container-type: inline-size;
            background: linear-gradient(180deg, {BG_SECONDARY} 0%, rgba(16, 26, 46, 0.55) 100%);
            padding: 12px 10px;
            border-radius: 10px;
            border: 1px solid {GRID};
            border-top-color: rgba(255, 255, 255, 0.07);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
            min-width: 0;
            overflow: hidden;
        }}
        .gx-stat-accent {{ border-color: rgba({PRIMARY_RGB}, 0.5); }}
        .gx-stat-label {{
            color: {TEXT_MUTED};
            font-weight: 500;
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }}
        .gx-stat-value {{
            font-family: {FONT_MONO};
            font-weight: 700;
            /* container-query units so the number always scales to fit its
               own card, regardless of the page's overall column layout --
               a fixed/viewport-relative size clipped digits on narrow
               (4-across) card rows. Wider tiles (e.g. a headline Spot column)
               read larger for free since cqw is relative to the tile itself. */
            font-size: clamp(0.62rem, 14.5cqw, 1.65rem);
            letter-spacing: -0.015em;
            margin-top: 3px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: clip;
        }}
        .gx-stat-label {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .gx-stat-value {{ color: {TEXT}; }}
        .gx-stat-accent .gx-stat-value {{ color: {PRIMARY}; }}

        /* ---------------- level map: horizontal gauge showing spot pinned
           between put wall (support) and call wall (resistance), with the
           gamma-flip zero-cross marked -- the "graphic" read of a card's
           four stat tiles, at a glance instead of four separate numbers. */
        .gx-levelmap {{ margin: 16px 4px 2px 4px; }}
        .gx-levelmap-track {{
            position: relative;
            height: 5px;
            border-radius: 999px;
            background: linear-gradient(90deg,
                rgba({BULLISH_RGB}, 0.45) 0%, {GRID} 48%, {GRID} 52%, rgba({BEARISH_RGB}, 0.45) 100%);
            margin: 20px 7px 9px 7px;
        }}
        .gx-levelmap-marker {{
            position: absolute;
            top: 50%;
            width: 2px;
            height: 14px;
            transform: translate(-50%, -50%);
            border-radius: 1px;
        }}
        .gx-levelmap-marker-flip {{
            background: {PRIMARY};
            box-shadow: 0 0 6px rgba({PRIMARY_RGB}, 0.7);
            width: 2px;
            height: 18px;
        }}
        .gx-levelmap-spot {{
            position: absolute;
            top: 50%;
            transform: translate(-50%, -50%);
            width: 11px; height: 11px;
            border-radius: 50%;
            background: {TEXT};
            border: 2px solid {BG};
            box-shadow: 0 0 0 1.5px {TEXT}, 0 2px 6px rgba(0, 0, 0, 0.5);
            z-index: 2;
        }}
        .gx-levelmap-spot-bull {{
            background: {BULLISH};
            box-shadow: 0 0 0 1.5px {BULLISH}, 0 0 9px rgba({BULLISH_RGB}, 0.75);
        }}
        .gx-levelmap-spot-bear {{
            background: {BEARISH};
            box-shadow: 0 0 0 1.5px {BEARISH}, 0 0 9px rgba({BEARISH_RGB}, 0.75);
        }}
        .gx-levelmap-labels {{
            display: flex;
            justify-content: space-between;
            font-family: {FONT_MONO};
            font-size: 0.66rem;
            color: {TEXT_MUTED};
            letter-spacing: 0.01em;
        }}
        .gx-levelmap-labels span {{ display: flex; flex-direction: column; gap: 1px; }}
        .gx-levelmap-labels span:last-child {{ align-items: flex-end; }}
        .gx-levelmap-labels span:nth-child(2) {{ align-items: center; }}
        .gx-levelmap-label-val {{ color: {TEXT}; font-weight: 700; font-size: 0.78rem; }}

        /* sparkline legend (colored dots, text in text tokens) */
        .gx-legend {{
            display: flex;
            gap: 14px;
            flex-wrap: wrap;
            font-size: 0.68rem;
            color: {TEXT_MUTED};
            margin-top: 2px;
            letter-spacing: 0.02em;
        }}
        .gx-legend-item {{ display: inline-flex; align-items: center; gap: 5px; }}
        .gx-legend-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}

        /* designed empty state */
        .gx-empty {{
            border: 1px dashed {GRID};
            border-radius: 12px;
            padding: 22px 18px;
            text-align: center;
            background: rgba(26, 30, 41, 0.4);
            margin: 4px 0;
        }}
        .gx-empty-title {{ color: {TEXT}; font-weight: 600; font-size: 0.9rem; }}
        .gx-empty-hint {{ color: {TEXT_MUTED}; font-size: 0.76rem; margin-top: 4px; }}

        /* footer */
        .gx-footer {{
            margin-top: 10px;
            padding: 14px 4px 4px 4px;
            border-top: 1px solid {GRID};
            font-size: 0.72rem;
            color: {TEXT_MUTED};
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 8px;
        }}

        /* inline status line above charts (cache freshness etc.) */
        .gx-statusline {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            font-size: 0.74rem;
            color: {TEXT_MUTED};
            margin: 2px 0 6px 0;
        }}

        /* accessibility: kill motion for users who ask for it */
        @media (prefers-reduced-motion: reduce) {{
            *, *::before, *::after {{
                animation: none !important;
                transition: none !important;
            }}
        }}

        /* mobile (~380-420px phones): tighter padding, no horizontal overflow,
           metric numbers scaled down so 4-across rows (which stack to full-width
           rows at this breakpoint) don't look oversized */
        @media (max-width: 480px) {{
            .block-container {{
                padding-top: 1.2rem;
                padding-left: 0.8rem;
                padding-right: 0.8rem;
            }}
            [data-testid="stMetric"] {{ padding: 10px 12px; }}
            [data-testid="stMetricValue"] {{ font-size: 1.3rem; }}
            [data-testid="stMetricLabel"] p {{ font-size: 0.7rem; }}
            h1 {{ font-size: 1.5rem; }}
            h2 {{ font-size: 1.2rem; }}
            h3 {{ font-size: 1.05rem; }}
            /* hero stacks; chips wrap full-width and stay tappable */
            .gx-hero {{ padding: 16px; }}
            .gx-hero-title {{ font-size: 1.2rem; }}
            .gx-hero-right {{ width: 100%; }}
            .gx-chip {{ flex: 1; min-width: 0; }}
            /* tab strip scrolls sideways instead of squashing labels */
            .stTabs [data-baseweb="tab-list"] {{ overflow-x: auto; }}
            /* long labels/captions wrap instead of forcing horizontal scroll */
            p, span, div {{ overflow-wrap: break-word; }}
        }}
    </style>""", unsafe_allow_html=True)


def sidebar_brand(subtitle="Live gamma exposure terminal"):
    """Small branded header above the page nav in the sidebar -- call once
    per page, right after theme.inject(). This is the one mount point every
    page already calls, so the KEY LEVEL TRADING masthead + tagline live
    here to guarantee they show up app-wide."""
    st.sidebar.markdown(f"""
        <div class="sidebar-brand">
            <div class="sidebar-brand-eyebrow">Key Level Trading</div>
            <div class="sidebar-brand-row">
                <div class="sidebar-brand-mark">📊</div>
                <div>
                    <div class="sidebar-brand-title">GexFlows</div>
                    <div class="sidebar-brand-sub">{subtitle}</div>
                </div>
            </div>
            <div class="sidebar-brand-tagline">Positioned to the key levels.</div>
        </div>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# HTML component helpers. All return markup strings (composable); the render_*
# variants push straight into the page.
# ---------------------------------------------------------------------------

def pill(kind, label, pulse=False):
    """kind: bull | bear | accent | neutral. Returns HTML for a status pill."""
    dot_cls = "gx-dot gx-dot-pulse" if pulse else "gx-dot"
    return (f'<span class="gx-pill gx-pill-{kind}">'
            f'<span class="{dot_cls}"></span>{label}</span>')


def chip(label, value):
    return (f'<div class="gx-chip"><div class="gx-chip-label">{label}</div>'
            f'<div class="gx-chip-value">{value}</div></div>')


def hero(title, subtitle, chips_html="", status_html="", icon="📊"):
    st.markdown(f"""
        <div class="gx-hero">
            <div class="gx-hero-left">
                <div class="gx-logo">{icon}</div>
                <div>
                    <div class="gx-hero-title">{title} {status_html}</div>
                    <div class="gx-hero-sub">{subtitle}</div>
                </div>
            </div>
            <div class="gx-hero-right">{chips_html}</div>
        </div>
    """, unsafe_allow_html=True)


def card_head(symbol, delta_html="", right_html="", meta=""):
    meta_html = f'<span class="gx-card-meta">{meta}</span>' if meta else ""
    st.markdown(f"""
        <div class="gx-card-head">
            <div class="gx-card-head-left">
                <span class="gx-card-symbol">{symbol}</span>{delta_html}
            </div>
            <div class="gx-card-head-right">{right_html}{meta_html}</div>
        </div>
    """, unsafe_allow_html=True)


def delta_html(pct):
    """Signed percent-change span colored by direction (exact palette hexes)."""
    if pct is None:
        return ""
    cls = "gx-delta-flat"
    arrow = ""
    if pct > 0.0005:
        cls, arrow = "gx-delta-up", "▲ "
    elif pct < -0.0005:
        cls, arrow = "gx-delta-down", "▼ "
    return f'<span class="{cls}">{arrow}{pct * 100:+.2f}%</span>'


def spark_legend(items):
    """items: list of (label, color). Text stays in muted ink; the dot carries color."""
    spans = "".join(
        f'<span class="gx-legend-item">'
        f'<span class="gx-legend-dot" style="background:{color}"></span>{label}</span>'
        for label, color in items)
    st.markdown(f'<div class="gx-legend">{spans}</div>', unsafe_allow_html=True)


def empty_state(title, hint=""):
    hint_html = f'<div class="gx-empty-hint">{hint}</div>' if hint else ""
    st.markdown(f"""
        <div class="gx-empty">
            <div class="gx-empty-title">{title}</div>
            {hint_html}
        </div>
    """, unsafe_allow_html=True)


def footer(left, right=""):
    st.markdown(f"""
        <div class="gx-footer"><span>{left}</span><span>{right}</span></div>
    """, unsafe_allow_html=True)


def statusline(html):
    st.markdown(f'<div class="gx-statusline">{html}</div>', unsafe_allow_html=True)


def stat_tile(label, value, accent=False):
    """Renders like st.metric but stylable per-instance -- st.metric shares
    one CSS class across every metric on the page, so it can't make just one
    tile's number brass (used for the Gamma Flip stat)."""
    cls = "gx-stat gx-stat-accent" if accent else "gx-stat"
    st.markdown(f"""
        <div class="{cls}">
            <div class="gx-stat-label">{label}</div>
            <div class="gx-stat-value">{value}</div>
        </div>
    """, unsafe_allow_html=True)


def level_map(spot, put_wall, call_wall, gamma_flip, fmt=str):
    """Horizontal gauge: put wall (support, green) on the left, call wall
    (resistance, red) on the right, gamma flip marked in brass, and a pin
    showing where spot currently sits between them -- the graphic complement
    to the four stat-tile numbers, colored by the same bull/bear convention
    already used for the spark legend (put wall=bullish, call wall=bearish).

    `fmt` is a value -> display-string callable (the caller's own number
    formatter, so this stays agnostic of precision/units).
    Renders nothing if there isn't enough data to place spot meaningfully.
    """
    vals = [v for v in (spot, put_wall, call_wall, gamma_flip) if v is not None]
    if spot is None or put_wall is None or call_wall is None or len(vals) < 3:
        return
    lo, hi = min(vals), max(vals)
    span = hi - lo
    if span <= 0:
        return
    pad = span * 0.08
    lo -= pad
    hi += pad
    span = hi - lo

    def pct(v):
        return max(0.0, min(100.0, (v - lo) / span * 100))

    spot_cls = "gx-levelmap-spot"
    if gamma_flip is not None:
        spot_cls += " gx-levelmap-spot-bull" if spot > gamma_flip else " gx-levelmap-spot-bear"

    markers = (
        f'<div class="gx-levelmap-marker" style="left:{pct(put_wall):.2f}%; background:{BULLISH};"></div>'
        f'<div class="gx-levelmap-marker" style="left:{pct(call_wall):.2f}%; background:{BEARISH};"></div>'
    )
    if gamma_flip is not None:
        markers += (f'<div class="gx-levelmap-marker gx-levelmap-marker-flip" '
                    f'style="left:{pct(gamma_flip):.2f}%;"></div>')
    markers += f'<div class="{spot_cls}" style="left:{pct(spot):.2f}%;"></div>'

    flip_val = f'<span class="gx-levelmap-label-val">{fmt(gamma_flip) if gamma_flip is not None else "—"}</span>'
    st.markdown(f"""
        <div class="gx-levelmap">
            <div class="gx-levelmap-track">{markers}</div>
            <div class="gx-levelmap-labels">
                <span>Put Wall<span class="gx-levelmap-label-val">{fmt(put_wall)}</span></span>
                <span>Gamma Flip{flip_val}</span>
                <span>Call Wall<span class="gx-levelmap-label-val">{fmt(call_wall)}</span></span>
            </div>
        </div>
    """, unsafe_allow_html=True)


def export_png_button(fig, key):
    """'Export branded PNG' button: renders a copy of `fig` at 1920px wide
    with the brand header burned in top-left and the date bottom-right, then
    offers it as a download. Two-step (export click -> download_button)
    because Streamlit can't trigger a file save from a single click, and
    building the PNG on every rerun would be wasted work.

    Requires kaleido (fig.to_image) -- see requirements.txt.
    """
    if st.button("Export branded PNG", key=key):
        branded = go.Figure(fig)
        branded.update_layout(
            width=1920,
            paper_bgcolor=BG,
            plot_bgcolor=BG,
            margin=dict(l=70, r=150, t=190, b=80),
        )
        # Pin the page's own title (ticker + interval) close to the plot so
        # our brand line, well above it, never collides with it. Note:
        # layout.title.y is a fraction of the WHOLE figure (0=bottom,
        # 1=top), unlike annotation yref="paper" below, which is relative
        # to the plot area itself -- these are not the same coordinate
        # space, easy to mix up.
        if branded.layout.title and branded.layout.title.text:
            branded.update_layout(title=dict(y=0.80, yanchor="top"))
        branded.add_annotation(
            text="KEY LEVEL TRADING — GexFlows",
            xref="paper", yref="paper", x=0, y=1.22,
            showarrow=False, xanchor="left", yanchor="bottom",
            font=dict(family=FONT_HEADING, size=28, color=TEXT),
        )
        branded.add_annotation(
            text=datetime.now().strftime("%Y-%m-%d"),
            xref="paper", yref="paper", x=1, y=-0.09,
            showarrow=False, xanchor="right", yanchor="top",
            font=dict(family=FONT_MONO, size=15, color=PRIMARY),
        )
        try:
            png_bytes = branded.to_image(format="png", width=1920, scale=1)
        except Exception as e:
            st.error(f"PNG export failed -- is kaleido installed? ({e})")
            return
        st.download_button(
            "Download PNG", data=png_bytes,
            file_name=f"gexflows_{datetime.now():%Y%m%d_%H%M}.png",
            mime="image/png", key=f"{key}_dl",
        )
