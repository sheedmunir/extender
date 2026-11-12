#!/bin/sh
# reconnect.cgi - reconnect to saved network by number (background fresh extend).
export PATH=$PATH:/fhrom/bin:/usr/sbin:/sbin:/bin
umask 077

COOK=$(printf '%s' "$HTTP_COOKIE" | tr ';' '\n' | sed 's/^ *//' | grep '^session=' | cut -d= -f2 | tr -d ' \r')
SF="/tmp/ext_sess_$COOK"
NOW=$(date +%s)
SEEN=$(cat "$SF" 2>/dev/null)
case "$SEEN" in ''|*[!0-9]*) AUTH=0;; *) AGE=$((NOW-SEEN)); if [ "$AGE" -le 300 ]; then AUTH=1; printf '%s\n' "$NOW" > "$SF"; else AUTH=0; rm -f "$SF"; fi;; esac
if [ "$AUTH" != "1" ]; then
  echo "Content-Type: text/plain"
  echo "Status: 401 Unauthorized"
  echo ""
  echo "Login required."
  exit 0
fi

# Saved file + extender path (test overrides)
if [ -n "$SAVED_FILE" ]; then SAVED="$SAVED_FILE"; else SAVED="/fhconf/mytools/passwords"; fi
if [ -n "$RECONNECT_EXTENDER" ]; then EXT="$RECONNECT_EXTENDER"; else EXT="/fhconf/mytools/extender.sh"; fi

BODY=$(cat)
ACT=$(printf '%s' "$BODY" | tr '&' '\n' | grep '^action=' | head -n1 | cut -d= -f2-)
N=$(printf '%s' "$BODY" | tr '&' '\n' | grep '^n=' | head -n1 | cut -d= -f2-)

echo "Content-Type: text/plain"
if [ "$ACT" != "reconnect" ]; then
  echo "Status: 400 Bad Request"
  echo ""
  echo "action=reconnect required."
  exit 0
fi
case "$N" in ''|*[!0-9]*)
  echo "Status: 400 Bad Request"
  echo ""
  echo "n must be a number."
  exit 0
  ;;
esac
if [ ! -s "$SAVED" ]; then
  echo "Status: 400 Bad Request"
  echo ""
  echo "No saved networks."
  exit 0
fi
TOTAL=$(wc -l < "$SAVED")
if [ "$N" -lt 1 ] || [ "$N" -gt "$TOTAL" ]; then
  echo "Status: 400 Bad Request"
  echo ""
  echo "No saved network number $N."
  exit 0
fi
SSID=$(awk -F'|' -v n="$N" 'NR==n{print $1}' "$SAVED")

# Start fresh extend in background so the HTTP reply is immediate.
# Extender will rebuild uplink/APs/NAT; web restarts after (start.sh flow).
nohup sh "$EXT" -r "$N" > /tmp/reconnect.log 2>&1 &
echo "Status: 200 OK"
echo ""
echo "Reconnect started to $SSID."
