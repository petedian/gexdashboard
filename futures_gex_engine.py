"""
Futures GEX Engine - CME futures options gamma exposure.
- Per-product contract multipliers (futures-specific).
- Call wall = largest call gamma AT/ABOVE spot (resistance).
- Put wall  = largest put gamma AT/BELOW spot (support).
- Gamma flip = net-GEX zero crossing nearest spot, tail noise ignored.
"""
import re
import threading
from collections import defaultdict

PRODUCT_SPECS = {
    "/ES":  {"multiplier": 50,   "name": "E-mini S&P 500"},
    "/MES": {"multiplier": 5,    "name": "Micro E-mini S&P 500"},
    "/NQ":  {"multiplier": 20,   "name": "E-mini Nasdaq-100"},
    "/MNQ": {"multiplier": 2,    "name": "Micro E-mini Nasdaq-100"},
    "/RTY": {"multiplier": 50,   "name": "E-mini Russell 2000"},
    "/CL":  {"multiplier": 1000, "name": "Crude Oil"},
    "/MCL": {"multiplier": 100,  "name": "Micro Crude Oil"},
    "/NG":  {"multiplier": 10000,"name": "Natural Gas"},
    "/GC":  {"multiplier": 100,  "name": "Gold"},
    "/SI":  {"multiplier": 5000, "name": "Silver"},
    "/HG":  {"multiplier": 25000,"name": "Copper"},
    "/ZB":  {"multiplier": 1000, "name": "30-Year T-Bond"},
    "/ZN":  {"multiplier": 1000, "name": "10-Year T-Note"},
    "/ZF":  {"multiplier": 1000, "name": "5-Year T-Note"},
    "/ZT":  {"multiplier": 2000, "name": "2-Year T-Note"},
    "/6E":  {"multiplier": 125000, "name": "Euro FX"},
    "/6J":  {"multiplier": 12500000, "name": "Japanese Yen"},
    "/6B":  {"multiplier": 62500, "name": "British Pound"},
    "/6A":  {"multiplier": 100000, "name": "Australian Dollar"},
    "/6C":  {"multiplier": 100000, "name": "Canadian Dollar"},
    "/ZC":  {"multiplier": 50,   "name": "Corn"},
    "/ZS":  {"multiplier": 50,   "name": "Soybeans"},
    "/ZW":  {"multiplier": 50,   "name": "Wheat"},
    "/MYM": {"multiplier": 0.5,  "name": "Micro E-mini Dow"},
    "/M2K": {"multiplier": 5,    "name": "Micro E-mini Russell 2000"},
    "/MGC": {"multiplier": 10,   "name": "Micro Gold"},
    # The 4 tracked index/ETF counterparts (instruments_config.COUNTERPARTS) --
    # standard OCC equity/index option multiplier, 100 shares/contract.
    "SPX":  {"multiplier": 100, "name": "S&P 500 Index", "equity": True},
    "QQQ":  {"multiplier": 100, "name": "Nasdaq 100 ETF", "equity": True},
    "USO":  {"multiplier": 100, "name": "United States Oil Fund ETF", "equity": True},
    "GLD":  {"multiplier": 100, "name": "SPDR Gold Shares ETF", "equity": True},
    # NOTE: the futures rows above stay in this table even though only
    # /ES /NQ /CL /GC are collected -- the GEX Chart page's free-text ticker
    # box can still be pointed at any futures product and needs
    # get_multiplier() to resolve it correctly instead of silently falling
    # back to DEFAULT_MULTIPLIER. Equity tickers don't need an entry here at
    # all (the Chart page hardcodes 100 for any non-futures symbol), so this
    # table only carries the 4 counterparts actually read by the collector.
}
DEFAULT_MULTIPLIER = 50

def get_multiplier(product_symbol):
    spec = PRODUCT_SPECS.get(product_symbol)
    return spec["multiplier"] if spec else DEFAULT_MULTIPLIER

def parse_futures_option_symbol(streamer_symbol):
    if not streamer_symbol:
        return None
    core = streamer_symbol.split(":")[0]
    match = None
    for m in re.finditer(r'([CP])(\d+(?:\.\d+)?)$', core):
        match = m
    if not match:
        m2 = re.search(r'([CP])(\d+(?:\.\d+)?)(?!.*[CP]\d)', core)
        if not m2:
            return None
        match = m2
    return {"type": match.group(1), "strike": float(match.group(2))}

class FuturesGEXCalculator:
    def __init__(self, product_symbol, spot_price=0.0):
        self.product_symbol = product_symbol
        self.multiplier = get_multiplier(product_symbol)
        self.spot_price = spot_price
        self.lock = threading.Lock()
        self.options = {}
        self.gex_by_strike = defaultdict(lambda: {"call_gex": 0.0, "put_gex": 0.0})

    def update_spot_price(self, price):
        with self.lock:
            if price and price > 0:
                self.spot_price = price

    def update_gamma(self, streamer_symbol, gamma):
        parsed = parse_futures_option_symbol(streamer_symbol)
        if not parsed:
            return
        with self.lock:
            entry = self.options.setdefault(streamer_symbol,
                {"gamma": None, "oi": None, "type": parsed["type"], "strike": parsed["strike"]})
            entry["gamma"] = gamma
            self._recalc_strike(parsed["strike"])

    def update_open_interest(self, streamer_symbol, oi):
        parsed = parse_futures_option_symbol(streamer_symbol)
        if not parsed:
            return
        with self.lock:
            entry = self.options.setdefault(streamer_symbol,
                {"gamma": None, "oi": None, "type": parsed["type"], "strike": parsed["strike"]})
            entry["oi"] = oi
            self._recalc_strike(parsed["strike"])

    def _recalc_strike(self, strike):
        call_gex = 0.0
        put_gex = 0.0
        for opt in self.options.values():
            if opt["strike"] != strike:
                continue
            if opt["gamma"] is None or opt["oi"] is None:
                continue
            g = float(opt["gamma"]) * float(opt["oi"]) * self.multiplier \
                * self.spot_price * self.spot_price * 0.01
            if opt["type"] == "C":
                call_gex += g
            else:
                put_gex += g
        self.gex_by_strike[strike]["call_gex"] = call_gex
        self.gex_by_strike[strike]["put_gex"] = put_gex

    def get_levels(self):
        with self.lock:
            if not self.gex_by_strike:
                return {"call_wall": None, "put_wall": None,
                        "gamma_flip": None, "total_net_gex": 0.0, "num_strikes": 0}
            strikes = sorted(self.gex_by_strike.keys())
            spot = self.spot_price if self.spot_price > 0 else strikes[len(strikes)//2]

            # Call wall: biggest call gamma AT/ABOVE spot (resistance overhead)
            # Put wall:  biggest put gamma  AT/BELOW spot (support below)
            call_wall = None; call_val = 0.0
            put_wall = None; put_val = 0.0
            net_by_strike = {}
            max_abs_net = 0.0
            total_net = 0.0

            for k in strikes:
                cg = self.gex_by_strike[k]["call_gex"]
                pg = self.gex_by_strike[k]["put_gex"]
                net = cg - pg
                net_by_strike[k] = net
                total_net += net
                if abs(net) > max_abs_net:
                    max_abs_net = abs(net)
                if k >= spot and cg > call_val:
                    call_val = cg; call_wall = k
                if k <= spot and pg > put_val:
                    put_val = pg; put_wall = k

            # Fallbacks if spot sits at an extreme (no strikes on one side)
            if call_wall is None:
                for k in strikes:
                    cg = self.gex_by_strike[k]["call_gex"]
                    if cg > call_val:
                        call_val = cg; call_wall = k
            if put_wall is None:
                for k in strikes:
                    pg = self.gex_by_strike[k]["put_gex"]
                    if pg > put_val:
                        put_val = pg; put_wall = k

            # Gamma flip: zero crossing nearest spot, ignore tail noise
            threshold = max_abs_net * 0.02
            candidates = []
            for i in range(len(strikes) - 1):
                k1, k2 = strikes[i], strikes[i+1]
                n1 = net_by_strike[k1]; n2 = net_by_strike[k2]
                if abs(n1) < threshold and abs(n2) < threshold:
                    continue
                if n1 * n2 < 0 and n2 != n1:
                    candidates.append(k1 + (k2 - k1) * (-n1) / (n2 - n1))
            gamma_flip = min(candidates, key=lambda f: abs(f - spot)) if candidates else None

            return {"call_wall": call_wall, "put_wall": put_wall,
                    "gamma_flip": gamma_flip, "total_net_gex": total_net,
                    "num_strikes": len(strikes)}

    def get_gex_by_strike(self):
        with self.lock:
            rows = []
            for k in sorted(self.gex_by_strike.keys()):
                cg = self.gex_by_strike[k]["call_gex"]
                pg = self.gex_by_strike[k]["put_gex"]
                rows.append((k, cg, pg, cg - pg))
            return rows


class VolumeIVTracker:
    """Per-(expiration, strike) day-volume + IV tracker for the Volume
    Profile page. Deliberately separate from FuturesGEXCalculator -- that
    class blends all fetched expirations into one row per strike (what the
    wall/gamma-flip math needs), so it has nowhere to put a real per-
    expiration dimension without changing what its existing callers get
    back. This class shares no state with it; the validated GEX math is
    untouched by this class existing.

    Persists only strikes within STRIKE_BAND of spot to bound
    strike_volume_detail's row growth -- the full chain is still fetched and
    subscribed exactly as before, this only bounds what gets written to disk.
    Wider than FuturesGEXCalculator's wall-detection needs, because the IV
    smile and the 2x expected-move band both want more room than a wall does.
    """
    STRIKE_BAND = 0.15

    def __init__(self, spot_price=0.0):
        self.spot_price = spot_price
        self.lock = threading.Lock()
        self.data = {}  # (expiration, strike, "C"|"P") -> {"volume": int|None, "iv": float|None}

    def update_spot_price(self, price):
        with self.lock:
            if price and price > 0:
                self.spot_price = price

    def update_volume(self, streamer_symbol, expiration, day_volume):
        parsed = parse_futures_option_symbol(streamer_symbol)
        if not parsed:
            return
        with self.lock:
            key = (expiration, parsed["strike"], parsed["type"])
            entry = self.data.setdefault(key, {"volume": None, "iv": None})
            entry["volume"] = int(day_volume) if day_volume is not None else None

    def update_iv(self, streamer_symbol, expiration, volatility):
        parsed = parse_futures_option_symbol(streamer_symbol)
        if not parsed:
            return
        with self.lock:
            key = (expiration, parsed["strike"], parsed["type"])
            entry = self.data.setdefault(key, {"volume": None, "iv": None})
            entry["iv"] = float(volatility) if volatility is not None else None

    def get_rows(self):
        """(expiration, strike, call_volume, put_volume, call_iv, put_iv)
        rows, merged across call/put per (expiration, strike), filtered to
        +/-STRIKE_BAND of spot."""
        with self.lock:
            lo, hi = None, None
            if self.spot_price > 0:
                lo = self.spot_price * (1 - self.STRIKE_BAND)
                hi = self.spot_price * (1 + self.STRIKE_BAND)
            merged = {}
            for (expiration, strike, opt_type), vals in self.data.items():
                if lo is not None and not (lo <= strike <= hi):
                    continue
                row = merged.setdefault((expiration, strike),
                                         {"call_volume": None, "put_volume": None,
                                          "call_iv": None, "put_iv": None})
                if opt_type == "C":
                    row["call_volume"] = vals["volume"]
                    row["call_iv"] = vals["iv"]
                else:
                    row["put_volume"] = vals["volume"]
                    row["put_iv"] = vals["iv"]
            return [
                (expiration, strike, r["call_volume"], r["put_volume"], r["call_iv"], r["put_iv"])
                for (expiration, strike), r in sorted(merged.items())
            ]


if __name__ == "__main__":
    print("Products in table:", len(PRODUCT_SPECS))
    print(", ".join(PRODUCT_SPECS.keys()))
    print("\nSelf-test: symbol parsing")
    for s in ["./E1AN26P7605:XCME", "./E1AN26C6060:XCME"]:
        print(f"  {s} -> {parse_futures_option_symbol(s)}")
    print("\nEngine module OK.")
