#!/bin/sh
# devices.cgi - connected WiFi clients with their DHCP hostname (when the device sent one).
# The firmware's udhcpd writes a binary lease file: lease(4) ip(4) mac(6) hostname(padded).
# We locate each MAC's bytes and read the printable hostname that follows it.
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

if [ -n "$LEASES_FILE" ]; then LEASES="$LEASES_FILE"; else LEASES="/tmp/udhcpd.leases"; fi
if [ -n "$ARP_FILE" ]; then ARP="$ARP_FILE"; else ARP="/proc/net/arp"; fi

esc() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g'; }

HEX=""
[ -s "$LEASES" ] && HEX=$(od -An -v -tx1 "$LEASES" 2>/dev/null)

name_for() {
  [ -n "$HEX" ] || return 0
  _pat=$(printf '%s' "$1" | tr 'A-F' 'a-f' | sed 's/:/ /g')
  _rest=${HEX#*$_pat}
  [ "$_rest" = "$HEX" ] && return 0
  _i=0
  for _b in $_rest; do
    [ "$_i" -ge 32 ] && break
    [ "$_b" = "00" ] && break
    _d=$((0x$_b))
    { [ "$_d" -lt 32 ] || [ "$_d" -gt 126 ]; } && break
    printf "\\$(printf '%03o' "$_d")"
    _i=$((_i + 1))
  done
}

list_clients() {
  if [ -n "$ASSOC_FILE" ]; then
    cut -f1,2 "$ASSOC_FILE" 2>/dev/null
  else
    wl -i wl1 assoclist 2>/dev/null | sed -n 's/^assoclist //p' | tr ' ' '\n' | grep -v '^$' | sed "s/^/wl1$(printf '\t')/"
    wl -i wl0.1 assoclist 2>/dev/null | sed -n 's/^assoclist //p' | tr ' ' '\n' | grep -v '^$' | sed "s/^/wl0.1$(printf '\t')/"
  fi
}

CLIENTS=/tmp/web_clients.$$
ROWS=/tmp/web_rows.$$
trap 'rm -f "$CLIENTS" "$ROWS"' EXIT
list_clients | tr -d '\r' | sed 's/^ *//; s/ *$//' | grep -v '^$' | sort -u > "$CLIENTS"

: > "$ROWS"
if [ -s "$CLIENTS" ]; then
  while IFS="$(printf '	')" read -r iface mac; do
    [ -n "$mac" ] || continue
    mac=$(printf '%s' "$mac" | tr 'A-F' 'a-f')
    ip=$(awk -v m="$mac" 'tolower($4)==tolower(m){print $1; exit}' "$ARP" 2>/dev/null)
    nm=$(name_for "$mac")
    [ -n "$nm" ] || nm="(no name)"
    printf '%s\t%s\t%s\t%s\n' "$nm" "${ip:-?}" "$mac" "$iface" >> "$ROWS"
  done < "$CLIENTS"
fi

echo "Content-Type: text/html"
echo "Cache-Control: no-store"
echo ""
echo "<table>"
echo "<tr class=\"hdr\"><td>Device</td><td>Interface &middot; Address</td></tr>"
if [ ! -s "$ROWS" ]; then
  echo "<tr><td>No devices</td><td></td></tr>"
else
  # Named devices first (A-Z), then the ones that sent no hostname.
  { awk -F'	' '$1 != "(no name)"' "$ROWS" | sort -f; awk -F'	' '$1 == "(no name)"' "$ROWS"; } |
  while IFS="$(printf '	')" read -r nm ip mac iface; do
    echo "<tr data-mac=\"$(esc "$mac")\"><td>$(esc "$nm")</td><td>$(esc "$iface") &middot; $(esc "$ip") &middot; $(esc "$mac")</td></tr>"
  done
fi
echo "</table>"
