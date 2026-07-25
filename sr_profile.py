"""Dynamic Support/Resistance (pivot band-clustering) + Visible Range Profile,
computed from scratch against our own OHLC candle data. Pure functions, no
external indicator/platform dependency -- see PROJECT spec Part 3.

Both overlays operate over the same trailing lookback window (P bars) so a
chart's S/R levels and its volume profile describe a consistent range.
"""


def find_pivots(candles, n=10):
    """A bar is a pivot high if its high is the max within [n] bars each side
    (a symmetric fractal); pivot low is the mirror. Returns two lists, each
    chronological (oldest first): pivot highs, pivot lows. A pivot near the
    most-recent edge of `candles` won't appear until n bars have printed after
    it -- that lag is what keeps levels from being recomputed every single bar."""
    highs, lows = [], []
    total = len(candles)
    for i in range(n, total - n):
        window = candles[i - n:i + n + 1]
        h, l = candles[i]["high"], candles[i]["low"]
        if h == max(c["high"] for c in window):
            highs.append({"index": i, "time": candles[i]["time"], "price": h})
        if l == min(c["low"] for c in window):
            lows.append({"index": i, "time": candles[i]["time"], "price": l})
    return highs, lows


def dynamic_sr_levels(candles, n=10, lookback_bars=284, band_width_pct=0.10, min_pivots=2, cap=20):
    """Band-clustering dynamic S/R, per spec:

    1. Detect pivots (find_pivots).
    2. Restrict to the trailing `lookback_bars`.
    3. Walk pivots most-recent -> oldest. For each not-yet-used pivot, open a
       band centered on its price, width = (range high-low over the lookback)
       * band_width_pct, and count other not-yet-used pivots inside it.
    4. If the band holds >= min_pivots total (seed + others), confirm a level
       at the seed pivot's own price and mark every pivot in the band used.
    5. Cap at `cap` levels. Also return the single highest pivot-high and
       lowest pivot-low in the lookback as separate reference lines.

    Returns {"levels": [{"price": ..., "num_pivots": ...}, ...] (most-recent-
    seed first), "ref_high": price_or_None, "ref_low": price_or_None}.
    """
    if len(candles) < 2 * n + 1:
        return {"levels": [], "ref_high": None, "ref_low": None}

    window = candles[-lookback_bars:] if len(candles) > lookback_bars else candles
    offset = len(candles) - len(window)

    highs, lows = find_pivots(candles, n=n)
    # keep only pivots whose bar falls inside the trailing lookback window
    highs = [p for p in highs if p["index"] >= offset]
    lows = [p for p in lows if p["index"] >= offset]

    if not highs and not lows:
        return {"levels": [], "ref_high": None, "ref_low": None}

    ref_high = max((p["price"] for p in highs), default=None)
    ref_low = min((p["price"] for p in lows), default=None)

    range_hi = max(c["high"] for c in window)
    range_lo = min(c["low"] for c in window)
    band_width = (range_hi - range_lo) * band_width_pct

    all_pivots = sorted(highs + lows, key=lambda p: p["index"], reverse=True)  # most-recent first
    used = [False] * len(all_pivots)

    levels = []
    for i, seed in enumerate(all_pivots):
        if used[i]:
            continue
        lo, hi = seed["price"] - band_width / 2, seed["price"] + band_width / 2
        members = [j for j, p in enumerate(all_pivots) if not used[j] and lo <= p["price"] <= hi]
        if len(members) >= min_pivots:
            for j in members:
                used[j] = True
            levels.append({"price": seed["price"], "num_pivots": len(members)})
            if len(levels) >= cap:
                break

    return {"levels": levels, "ref_high": ref_high, "ref_low": ref_low}


def visible_range_profile(candles, lookback_bars=284, bins=24):
    """Volume-at-price histogram over the trailing `lookback_bars`, split into
    buy-side (ask_volume, buyer-initiated) and sell-side (bid_volume,
    seller-initiated) per price bin -- real aggressor-side data from the feed,
    not derived. Falls back to a neutral tick-count proxy (1 per candle) when
    an instrument has no real volume (e.g. cash indices), so the profile still
    renders instead of going blank -- there's no buy/sell split to fall back
    to in that case, since there's no real volume to split."""
    window = candles[-lookback_bars:] if len(candles) > lookback_bars else candles
    if not window:
        return {"bins": [], "poc": None}

    lo = min(c["low"] for c in window)
    hi = max(c["high"] for c in window)
    if hi <= lo:
        return {"bins": [], "poc": None}

    has_volume = any(c.get("volume") for c in window)
    width = (hi - lo) / bins
    buy_buckets = [0.0] * bins
    sell_buckets = [0.0] * bins

    def bucket_index(price):
        idx = int((price - lo) / width)
        return max(0, min(bins - 1, idx))

    for c in window:
        typical = (c["high"] + c["low"] + c["close"]) / 3
        idx = bucket_index(typical)
        if has_volume:
            buy_buckets[idx] += c.get("buy_volume", 0.0)
            sell_buckets[idx] += c.get("sell_volume", 0.0)
        else:
            buy_buckets[idx] += 0.5  # neutral proxy, split evenly -- no real
            sell_buckets[idx] += 0.5  # buy/sell data exists to split instead

    profile = [{"price_low": lo + i * width, "price_high": lo + (i + 1) * width,
                "buy_volume": buy_buckets[i], "sell_volume": sell_buckets[i],
                "value": buy_buckets[i] + sell_buckets[i]} for i in range(bins)]
    poc_bin = max(profile, key=lambda b: b["value"]) if profile else None
    return {"bins": profile, "poc": poc_bin, "is_volume": has_volume}
