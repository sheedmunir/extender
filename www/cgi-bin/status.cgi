#!/bin/sh
# status.cgi - live status for the Extender page (protected by 5-min cookie).
# Same data as `sh extender.sh -s`, as a small HTML table.
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

esc() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g'; }
INET_CACHE=/tmp/ext_inet_cache
# Cached internet state, max 2 minutes old; the page refreshes it via ping.cgi?inet=1
inet_state() {
  t=$(sed -n 's/^\([0-9]*\)|.*$/\1/p' "$INET_CACHE" 2>/dev/null)
  s=$(sed -n 's/^[0-9]*|//p' "$INET_CACHE" 2>/dev/null)
  case "$t" in ''|*[!0-9]*) t=0 ;; esac
  if [ -n "$s" ] && [ $(( $(date +%s) - t )) -le 120 ]; then
    printf '%s' "$s"
  else
    printf 'checking'
  fi
}

echo "Content-Type: text/html"
echo "Cache-Control: no-store"
echo ""
echo "<table>"

hostname=$(cat /tmp/hostname.conf 2>/dev/null)
[ -n "$hostname" ] && echo "<tr><td>Hostname</td><td>$(esc "$hostname")</td></tr>"

mac0=$(wl -i wl0 cur_etheraddr 2>/dev/null | sed -n 's/^ *cur_etheraddr: *//p')
[ -n "$mac0" ] && echo "<tr><td>wl0 MAC</td><td>$(esc "$mac0")</td></tr>"

mac1=$(wl -i wl1 cur_etheraddr 2>/dev/null | sed -n 's/^ *cur_etheraddr: *//p')
[ -n "$mac1" ] && echo "<tr><td>wl1 MAC</td><td>$(esc "$mac1")</td></tr>"

up_state=$(wpa_cli -i wl0 status 2>/dev/null | sed -n 's/^wpa_state=//p')
up_ssid=$(wpa_cli -i wl0 status 2>/dev/null | sed -n 's/^ssid=//p')
if [ "$up_state" = "COMPLETED" ] && [ -n "$up_ssid" ]; then
  echo "<tr><td>Uplink</td><td>$(esc "$up_ssid")</td></tr>"
  echo "<tr id=\"inetRow\"><td>Internet</td><td>$(inet_state)</td></tr>"
else
  echo "<tr><td>Uplink</td><td>not connected</td></tr>"
  echo "<tr id=\"inetRow\"><td>Internet</td><td>no</td></tr>"
fi

ap5_ssid=$(wl -i wl1 ssid 2>/dev/null | sed -n 's/^Current SSID: *"\(.*\)"/\1/p')
ap5_ch=$(wl -i wl1 status 2>/dev/null | sed -n 's/.*Primary channel: *\([0-9]*\).*/\1/p')
ap5_state="off"
if [ -f /tmp/ext_ap_state ]; then
  s5=$(sed -n 's/^wl1=//p' /tmp/ext_ap_state 2>/dev/null)
  case "$s5" in on|1) ap5_state="on" ;; esac
fi
ap5_sec="open"
echo "<tr><td>5GHz AP</td><td>$(esc "${ap5_ssid:-(off)}") (${ap5_state}, $ap5_sec)</td></tr>"

ap2_ssid=$(wl -i wl0.1 ssid 2>/dev/null | sed -n 's/^Current SSID: *"\(.*\)"/\1/p')
ap2_state="off"
if [ -f /tmp/ext_ap_state ]; then
  s2=$(sed -n 's/^wl0.1=//p' /tmp/ext_ap_state 2>/dev/null)
  case "$s2" in on|1) ap2_state="on" ;; esac
fi
ap2_sec="open"
if [ -f /fhconf/mytools/wpa.conf ]; then
  p=$(sed -n 's/^wl0.1=//p' /fhconf/mytools/wpa.conf 2>/dev/null)
  [ -n "$p" ] && ap2_sec="wpa2"
fi
echo "<tr><td>2.4GHz AP</td><td>$(esc "${ap2_ssid:-(off)}") (${ap2_state}, $ap2_sec)</td></tr>"

n5=$(wl -i wl1 assoclist 2>/dev/null | sed -n 's/^assoclist //p' | tr ' ' '\n' | grep -c '[0-9A-Fa-f]')
echo "<tr><td>5GHz clients</td><td>$n5</td></tr>"

n2=$(wl -i wl0.1 assoclist 2>/dev/null | sed -n 's/^assoclist //p' | tr ' ' '\n' | grep -c '[0-9A-Fa-f]')
echo "<tr><td>2.4GHz clients</td><td>$n2</td></tr>"

echo "</table>"
