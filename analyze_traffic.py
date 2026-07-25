#!/usr/bin/env python3
"""Summarizes nginx_access.log into a plain-English traffic report --
who's hitting the dashboard, how often, and whether anything looks like
scraping (non-browser tools, rapid-fire request bursts) rather than
normal human browsing.

Usage: python3 analyze_traffic.py [path-to-log]  (defaults to nginx_access.log
       in this same directory)
"""
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

LOG_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "nginx_access.log")

# matches the gexflows_access log_format defined in nginx_gexflows.conf
LINE_RE = re.compile(
    r'^(?P<ip>\S+) - \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+)[^"]*" '
    r'(?P<status>\d+) (?P<bytes>\d+) "(?P<referer>[^"]*)" '
    r'"(?P<ua>[^"]*)" rt=(?P<rt>\S+)'
)
TIME_FMT = "%d/%b/%Y:%H:%M:%S %z"

# real browsers virtually always include "Mozilla" (legacy compatibility
# string every major browser still sends); scripts/scrapers/bots typically
# don't, or use a recognizable library/tool signature instead.
BOT_HINTS = ("python-requests", "scrapy", "curl", "wget", "go-http-client",
             "postman", "axios", "aiohttp", "okhttp", "bot", "spider",
             "crawler", "libwww", "httpclient", "java/")

# more requests per minute than this, sustained, reads as automated rather
# than a person clicking around
RATE_FLAG_PER_MIN = 20
MIN_REQUESTS_TO_FLAG_RATE = 8


def parse_time(s):
    return datetime.strptime(s, TIME_FMT)


def load(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, errors="replace") as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            d = m.groupdict()
            try:
                d["dt"] = parse_time(d["time"])
            except ValueError:
                continue
            rows.append(d)
    return rows


def is_bot_ua(ua):
    if not ua or ua == "-":
        return True
    low = ua.lower()
    return any(hint in low for hint in BOT_HINTS)


def main():
    rows = load(LOG_PATH)
    if not rows:
        print(f"No parseable requests yet in {LOG_PATH}.")
        print("(Empty is normal right after setup -- check back once there's been some real traffic.)")
        return

    by_ip = defaultdict(list)
    for r in rows:
        by_ip[r["ip"]].append(r)

    print(f"Traffic report — {LOG_PATH}")
    print(f"{len(rows)} requests, {len(by_ip)} distinct IP(s), "
          f"{rows[0]['dt']:%Y-%m-%d %H:%M} -> {rows[-1]['dt']:%Y-%m-%d %H:%M}\n")

    summary = []
    for ip, reqs in by_ip.items():
        reqs_sorted = sorted(reqs, key=lambda r: r["dt"])
        first, last = reqs_sorted[0]["dt"], reqs_sorted[-1]["dt"]
        span_sec = max((last - first).total_seconds(), 1)
        rate_per_min = len(reqs) / span_sec * 60
        paths = sorted({r["path"] for r in reqs})
        uas = sorted({r["ua"] for r in reqs})
        # per-REQUEST bot count, not "does this IP's UA set contain any bot
        # signature" -- a mixed IP (e.g. one earlier scripted call sharing a
        # NAT/gateway with later real browser traffic) shouldn't taint every
        # request from that IP as suspicious.
        bot_count = sum(1 for r in reqs if is_bot_ua(r["ua"]))
        bot_like = bot_count > 0
        mostly_bot = bot_count / len(reqs) >= 0.5
        rate_flag = len(reqs) >= MIN_REQUESTS_TO_FLAG_RATE and rate_per_min >= RATE_FLAG_PER_MIN
        summary.append({
            "ip": ip, "count": len(reqs), "paths": paths, "uas": uas,
            "first": first, "last": last, "rate_per_min": rate_per_min,
            "bot_count": bot_count, "bot_like": bot_like, "mostly_bot": mostly_bot,
            "rate_flag": rate_flag,
        })

    summary.sort(key=lambda s: -s["count"])

    flagged = [s for s in summary if s["bot_like"] or s["rate_flag"]]
    if flagged:
        print("=== Flagged (non-browser user-agent and/or high request rate) ===")
        for s in flagged:
            reasons = []
            if s["bot_like"]:
                severity = "mostly" if s["mostly_bot"] else "partially"
                reasons.append(f"{severity} non-browser ({s['bot_count']}/{s['count']} requests)")
            if s["rate_flag"]:
                reasons.append(f"{s['rate_per_min']:.1f} req/min")
            print(f"  {s['ip']:20s} {s['count']:4d} req  [{', '.join(reasons)}]")
            print(f"    user-agent(s): {', '.join(s['uas']) or '(none)'}")
            print(f"    paths hit: {', '.join(s['paths'][:8])}"
                  + (f" (+{len(s['paths'])-8} more)" if len(s["paths"]) > 8 else ""))
        print()
    else:
        print("=== Nothing flagged -- no non-browser user-agents or unusually high request rates ===\n")

    print("=== All traffic, by volume ===")
    for s in summary[:25]:
        tag = " ⚠" if (s["mostly_bot"] or s["rate_flag"]) else (" ~" if s["bot_like"] else "")
        print(f"  {s['ip']:20s} {s['count']:4d} req  "
              f"{s['first']:%H:%M:%S}-{s['last']:%H:%M:%S}  "
              f"{len(s['paths'])} page(s){tag}")
    if len(summary) > 25:
        print(f"  ... and {len(summary) - 25} more IP(s)")


if __name__ == "__main__":
    main()
