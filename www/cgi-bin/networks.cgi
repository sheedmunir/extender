#!/bin/sh
# networks.cgi - list saved WiFi networks (SSID + type only, passwords hidden).
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

# Saved file: test override SAVED_FILE, else router path
if [ -n "$SAVED_FILE" ]; then
  SAVED="$SAVED_FILE"
else
  SAVED="/fhconf/mytools/passwords"
fi

esc() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'; }

echo "Content-Type: text/html"
echo "Cache-Control: no-store"
echo ""
echo "<table>"
echo "<tr><td>Saved WiFi</td><td>Details</td><td></td></tr>"
if [ ! -s "$SAVED" ]; then
  echo "<tr><td>No saved networks</td><td></td><td></td></tr>"
else
  N=0
  while IFS='|' read -r ssid sec; do
    [ -n "$ssid" ] || continue
    N=$((N+1))
    if [ "$sec" = "OPEN" ]; then typ="open network"; else typ="password network"; fi
    echo "<tr><td>$(esc "$ssid")</td><td>$(esc "$typ")</td><td><span class="row-actions"><button type=\"button\" class=\"btn btn-secondary btn-sm\" data-recon=\"$N\">Reconnect</button><button type=\"button\" class=\"btn btn-danger btn-sm\" data-del=\"$N\">Delete</button></span></td></tr>"
  done < "$SAVED"
fi
echo "</table>"
