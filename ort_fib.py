"""Fib extension engine for the ORT box. Pure function, no Streamlit/plotting
dependency -- verified against the reference TradingView screenshot's actual
numbers (box_high=4069.1, box_low=4058.1 -> the 0/25/50/75/100/117/127%
levels on both sides matched this formula to within rounding).

Two independent ladders, each anchored to ITS OWN side of the box:
  above (green) -- 0% = box_high, 100% = one box-range above box_high
  below (red)   -- 0% = box_low,  100% = one box-range below box_low
"""

FIB_PCTS = [0, 25, 50, 75, 100, 117, 127, 257, 314]
STRETCH_PCTS = {257, 314}  # per the source doc: exhaustion/take-profit zone, not fresh entries


def fib_extension_levels(box_high, box_low):
    box_range = box_high - box_low
    above = [{"pct": p, "price": box_high + (p / 100) * box_range, "stretch": p in STRETCH_PCTS}
             for p in FIB_PCTS]
    below = [{"pct": p, "price": box_low - (p / 100) * box_range, "stretch": p in STRETCH_PCTS}
             for p in FIB_PCTS]
    return {"above": above, "below": below, "box_range": box_range}
