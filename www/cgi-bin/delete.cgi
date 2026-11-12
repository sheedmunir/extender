#!/bin/sh
# delete.cgi - delete saved network by number (POST action=delete&n=N).
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

if [ -n "$SAVED_FILE" ]; then
  SAVED="$SAVED_FILE"
else
  SAVED="/fhconf/mytools/passwords"
fi

BODY=$(cat)
ACT=$(printf '%s' "$BODY" | tr '&' '\n' | grep '^action=' | head -n1 | cut -d= -f2-)
N=$(printf '%s' "$BODY" | tr '&' '\n' | grep '^n=' | head -n1 | cut -d= -f2-)

echo "Content-Type: text/plain"
if [ "$ACT" != "delete" ]; then
  echo "Status: 400 Bad Request"
  echo ""
  echo "action=delete required."
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
DEL_SSID=$(awk -F'|' -v n="$N" 'NR==n{print $1}' "$SAVED")
awk -v n="$N" 'NR!=n' "$SAVED" > "${SAVED}.tmp"
mv "${SAVED}.tmp" "$SAVED"
chmod 600 "$SAVED" 2>/dev/null
echo "Status: 200 OK"
echo ""
echo "Deleted $DEL_SSID."
