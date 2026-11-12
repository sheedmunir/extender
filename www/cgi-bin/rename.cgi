#!/bin/sh
# rename.cgi - live rename of a running AP's SSID (wl0.1 or wl1).
# Protected by 5-min cookie session.
export PATH=$PATH:/fhrom/bin:/usr/sbin:/sbin:/bin
umask 077

# Session check (5-min sliding idle, browser-close cookie)
COOK=$(printf '%s' "$HTTP_COOKIE" | tr ';' '\n' | sed 's/^ *//' | grep '^session=' | cut -d= -f2 | tr -d ' \r')
SF="/tmp/ext_sess_$COOK"
NOW=$(date +%s)
SEEN=$(cat "$SF" 2>/dev/null)
case "$SEEN" in ''|*[!0-9]*) AUTH=0;; *) AGE=$((NOW-SEEN)); if [ "$AGE" -le 300 ]; then AUTH=1; printf '%s\n' "$NOW" > "$SF"; else AUTH=0; rm -f "$SF"; fi;; esac
# Test override: TEST_FORCE_AUTH=1 bypasses locally (no session file) - never set on router
if [ "$TEST_FORCE_AUTH" = "1" ] && [ -z "$COOK" ]; then AUTH=1; fi
if [ "$AUTH" != "1" ]; then
  echo "Content-Type: text/plain"
  echo "Status: 401 Unauthorized"
  echo ""
  echo "Login required."
  exit 0
fi

# URL decode helper
dec() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "$1" | python3 -c 'import sys,urllib.parse; sys.stdout.write(urllib.parse.unquote_plus(sys.stdin.read()))'
  elif command -v httpd >/dev/null 2>&1; then
    httpd -d "$1" 2>/dev/null || printf '%s' "$1"
  else
    printf '%s' "$1"
  fi
}
get() { printf '%s' "$BODY" | tr '&' '\n' | grep "^$1=" | head -n1 | cut -d= -f2-; }

# Read POST body
BODY=$(cat)
IFACE=$(dec "$(get iface)")
SSID=$(dec "$(get ssid)")

echo "Content-Type: text/plain"
bad() { echo "Status: 400 Bad Request"; echo ""; echo "$1"; exit 0; }

# Validate iface whitelist (only the two APs we own)
case "$IFACE" in wl0.1|wl1) ;; *) bad "Invalid interface. Use wl0.1 or wl1.";; esac

# Validate ssid
[ -n "$SSID" ] || bad "A WiFi name is required."
LEN=$(printf '%s' "$SSID" | wc -c | tr -d ' ')
[ "$LEN" -ge 1 ] && [ "$LEN" -le 33 ] || bad "SSID must be 1 to 32 characters."

# Reject characters that would break key=value persistence
case "$SSID" in *'='*) bad "SSID cannot contain '='.";; esac

# Apply live rename (instant, no restart)
if ! wl -i "$IFACE" ssid "$SSID" >/dev/null 2>&1; then
  bad "wl -i $IFACE ssid '$SSID' failed. Check that the AP is up."
fi

# Persist to ssid.conf (key=value, mode 600, created on first save)
SSID_FILE="/fhconf/mytools/ssid.conf"
[ -f "$SSID_FILE" ] || : > "$SSID_FILE"
{
  grep -v "^$IFACE=" "$SSID_FILE" 2>/dev/null || true
  printf '%s=%s\n' "$IFACE" "$SSID"
} > "$SSID_FILE.tmp"
mv "$SSID_FILE.tmp" "$SSID_FILE"
chmod 600 "$SSID_FILE"

echo "Status: 200 OK"
echo ""
echo "Renamed $IFACE to '$SSID'. Clients on this AP will reconnect."
