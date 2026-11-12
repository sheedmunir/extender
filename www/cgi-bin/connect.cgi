#!/bin/sh
# connect.cgi - save a chosen WiFi (SSID|SEC|PASS) then start extending to it.
# Reuses the verified extender.sh -r <N> path so there is one connect flow.
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

if [ -n "$SAVED_FILE" ]; then SAVED="$SAVED_FILE"; else SAVED="/fhconf/mytools/passwords"; fi
if [ -n "$RECONNECT_EXTENDER" ]; then EXT="$RECONNECT_EXTENDER"; else EXT="/fhconf/mytools/extender.sh"; fi

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

BODY=$(cat)
SSID=$(dec "$(get ssid)")
SEC=$(dec "$(get sec)")
PASS=$(dec "$(get pass)")

echo "Content-Type: text/plain"
bad() { echo "Status: 400 Bad Request"; echo ""; echo "$1"; exit 0; }

[ -n "$SSID" ] || bad "A WiFi name is required."
case "$SSID" in *'|'*) bad "The WiFi name contains a character that cannot be saved.";; esac
case "$SEC" in OPEN|PSK) ;; *) bad "Unknown security type.";; esac
if [ "$SEC" = "PSK" ]; then
  LEN=$(printf '%s' "$PASS" | wc -c | tr -d ' ')
  [ "$LEN" -ge 8 ] && [ "$LEN" -le 63 ] || bad "A WiFi password has 8 to 63 characters."
  case "$PASS" in *'|'*) bad "The password contains '|' which cannot be saved.";; esac
else
  PASS=""
fi

# Save (replace an existing entry for the same SSID), then reconnect by number.
[ -f "$SAVED" ] || : > "$SAVED"
awk -F'|' -v s="$SSID" '$1 != s' "$SAVED" > "$SAVED.tmp" 2>/dev/null || : > "$SAVED.tmp"
printf '%s|%s|%s\n' "$SSID" "$SEC" "$PASS" >> "$SAVED.tmp"
mv "$SAVED.tmp" "$SAVED"
N=$(awk -F'|' -v s="$SSID" '$1 == s {print NR; exit}' "$SAVED")
case "$N" in ''|*[!0-9]*) bad "Could not save the network.";; esac

nohup sh "$EXT" -r "$N" > /tmp/connect.log 2>&1 &
echo "Status: 200 OK"
echo ""
echo "Saved $SSID. Extending started (network $N)."
