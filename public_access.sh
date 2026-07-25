#!/bin/bash
# Quick on/off switch for PUBLIC internet access (dashboard.gexflows.com) only.
# This does NOT affect your own access on the home network -- the dashboard
# itself (gex-dashboard.service) keeps running the whole time; this only
# starts/stops the Cloudflare tunnel that exposes it to the internet.
#
# Usage:
#   ./public_access.sh on       turn public access ON
#   ./public_access.sh off      turn public access OFF
#   ./public_access.sh status   check current state

case "$1" in
  on)
    systemctl --user start gex-tunnel.service
    echo "Public access is now ON — dashboard.gexflows.com is reachable."
    ;;
  off)
    systemctl --user stop gex-tunnel.service
    echo "Public access is now OFF — dashboard.gexflows.com is unreachable."
    echo "Your home network access is unaffected."
    ;;
  status)
    if systemctl --user is-active --quiet gex-tunnel.service; then
      echo "Public access is currently ON."
    else
      echo "Public access is currently OFF."
    fi
    ;;
  *)
    echo "Usage: ./public_access.sh [on|off|status]"
    exit 1
    ;;
esac
