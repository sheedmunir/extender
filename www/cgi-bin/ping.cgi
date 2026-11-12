#!/bin/sh
# ping.cgi - quick reachability test: gateway (lan side) and internet.
export PATH=$PATH:/fhrom/bin:/usr/sbin:/sbin:/bin
umask 077

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

if [ -n "$PING_GW" ]; then GW="$PING_GW"; else GW=$(ip -4 addr show br0 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1); fi
if [ -n "$PING_NET" ]; then NET="$PING_NET"; else NET="8.8.8.8"; fi

if [ -n "$PING_SLEEP" ]; then WAIT="$PING_SLEEP"; else WAIT=2; fi

# Lightweight mode for the dashboard row: ping.cgi?inet=1 prints yes|no and
# caches the answer for status.cgi, so the status table never waits on a ping.
if [ "$QUERY_STRING" = "inet" ]; then
  if ping -c 1 -W "$WAIT" "$NET" >/dev/null 2>&1; then S=yes; else S=no; fi
  printf '%s|%s\n' "$(date +%s)" "$S" > /tmp/ext_inet_cache.tmp && mv /tmp/ext_inet_cache.tmp /tmp/ext_inet_cache
  echo "Content-Type: text/plain"
  echo "Cache-Control: no-store"
  echo ""
  echo "$S"
  exit 0
fi

echo "Content-Type: text/html"
echo "Cache-Control: no-store"
echo ""
echo "<table>"
if [ -n "$GW" ] && ping -c 1 -W "$WAIT" "$GW" >/dev/null 2>&1; then
  echo "<tr><td>Gateway</td><td>ok ($GW)</td></tr>"
else
  echo "<tr><td>Gateway</td><td>no reply (${GW:-unknown})</td></tr>"
fi
if ping -c 1 -W "$WAIT" "$NET" >/dev/null 2>&1; then
  echo "<tr><td>Internet</td><td>ok ($NET)</td></tr>"
else
  echo "<tr><td>Internet</td><td>no reply ($NET)</td></tr>"
fi
echo "</table>"
