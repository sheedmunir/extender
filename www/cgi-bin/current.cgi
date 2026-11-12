#!/bin/sh
# current.cgi - return current SSID + MAC per interface as key=value plain text.
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

echo "Content-Type: text/plain"
echo "Cache-Control: no-store"
echo ""

# Read current SSID for an interface
get_ssid() {
  wl -i "$1" ssid 2>/dev/null | sed -n 's/^Current SSID: *"\(.*\)"/\1/p'
}
# Read current MAC for an interface
get_mac() {
  wl -i "$1" cur_etheraddr 2>/dev/null | sed -n 's/^cur_etheraddr: *\(.*\)/\1/p'
}

# Read persisted hostname (set via hostname_mac.cgi, volatile in /tmp)
HOSTNAME_FILE="/tmp/hostname.conf"
if [ -f "$HOSTNAME_FILE" ]; then
  HOSTNAME_VAL=$(cat "$HOSTNAME_FILE" 2>/dev/null)
else
  HOSTNAME_VAL=""
fi

printf 'wl0_ssid=%s\n' "$(get_ssid wl0)"
printf 'wl0_1_ssid=%s\n' "$(get_ssid wl0.1)"
printf 'wl1_ssid=%s\n' "$(get_ssid wl1)"
printf 'wl0_mac=%s\n' "$(get_mac wl0)"
printf 'wl0_1_mac=%s\n' "$(get_mac wl0.1)"
printf 'wl1_mac=%s\n' "$(get_mac wl1)"
printf 'hostname=%s\n' "$HOSTNAME_VAL"
