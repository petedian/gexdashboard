"""Single source of truth for the scoped instrument universe. Every part of
the system (collector, dashboard, chart module) imports its symbol lists from
here instead of hardcoding/duplicating them.

Contract multiplier/display-name metadata stays in futures_gex_engine.py's
PRODUCT_SPECS (that's its existing job and other code already reads it via
get_multiplier()) -- this file adds the entries needed for the new symbols
below so that lookup keeps working, but doesn't re-own that responsibility.
"""

# Exactly 8 tracked instruments: 4 futures + their index/ETF counterpart.
# Paired so the dashboard can render them adjacent to each other.
FUTURES = ["/ES", "/NQ", "/CL", "/GC"]
COUNTERPARTS = ["SPX", "QQQ", "USO", "GLD"]

# (future, counterpart) -- drives the dashboard's paired-row layout.
PAIRS = [("/ES", "SPX"), ("/NQ", "QQQ"), ("/CL", "USO"), ("/GC", "GLD")]

# Everything that goes through the full GEX sweep (collector's main loop).
GEX_PRODUCTS = FUTURES + COUNTERPARTS
