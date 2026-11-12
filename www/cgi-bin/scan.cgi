#!/bin/sh
# scan.cgi - nearby WiFi networks (SSID + signal + security), strongest first.
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

RAW=/tmp/web_scan.$$
SORTED=/tmp/web_sort.$$
NETS=/tmp/web_nets.$$
trap 'rm -f "$RAW" "$SORTED" "$NETS"' EXIT

# Test seam: SCAN_RESULTS_FILE holds wpa_cli scan_results text (no radio needed)
if [ -n "$SCAN_RESULTS_FILE" ]; then
  cp "$SCAN_RESULTS_FILE" "$RAW" 2>/dev/null
else
  # Scan on the uplink radio; it stays connected while scanning.
  wpa_cli -i wl0 scan >/dev/null 2>&1
  old=-1
  t=0
  while [ $t -lt 10 ]; do
    sleep 2
    t=$((t + 2))
    n=$(wpa_cli -i wl0 scan_results 2>/dev/null | wc -l)
    [ "$n" -eq "$old" ] && break
    old=$n
  done
  wpa_cli -i wl0 scan_results 2>/dev/null > "$RAW"
fi

# One row per SSID (strongest BSS), unsupported ones last.
awk -F'	' '
  NR > 1 && $5 != "" {
    f = $4
    if (f ~ /EAP|WEP/ || $5 ~ /\\/) c = "NO"
    else if (f ~ /PSK/) c = "PSK"
    else if (f ~ /SAE|WPA|RSN/) c = "NO"
    else c = "OPEN"
    if (!($5 in best) || $3 + 0 > best[$5] + 0) { best[$5] = $3; cl[$5] = c }
  }
  END { for (s in best) printf "%d\t%s\t%s\n", best[s], cl[s], s }
' "$RAW" | sort -t'	' -k1,1nr > "$SORTED"
{ awk -F'	' '$2 != "NO"' "$SORTED"; awk -F'	' '$2 == "NO"' "$SORTED"; } > "$NETS"

esc() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g'; }

echo "Content-Type: text/html"
echo "Cache-Control: no-store"
echo ""
echo "<table>"
echo "<tr><td>WiFi</td><td>Signal</td><td>Security</td><td></td></tr>"
if [ ! -s "$NETS" ]; then
  echo "<tr><td>No networks found</td><td></td><td></td><td></td></tr>"
else
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    sig=$(printf '%s' "$line" | cut -f1)
    cls=$(printf '%s' "$line" | cut -f2)
    ssid=$(printf '%s' "$line" | cut -f3-)
    case "$cls" in
      PSK) typ="password" ;;
      OPEN) typ="open" ;;
      *) typ="unsupported" ;;
    esac
    if [ "$cls" = "NO" ]; then
      echo "<tr><td>$(esc "$ssid")</td><td>${sig} dBm</td><td>$typ</td><td></td></tr>"
    else
      echo "<tr><td>$(esc "$ssid")</td><td>${sig} dBm</td><td>$typ</td><td><button type=\"button\" class=\"btn btn-primary btn-sm\" data-ssid=\"$(esc "$ssid")\" data-sec=\"$cls\">Use</button></td></tr>"
    fi
  done < "$NETS"
fi
echo "</table>"
