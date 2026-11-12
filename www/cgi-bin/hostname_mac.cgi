#!/bin/sh
# hostname_mac.cgi - change router hostname (uplink DHCP) and/or interface MAC.
# MACs are persisted to /fhconf/mytools/mac.conf and applied on extender restart.
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
echo "Content-Type: text/plain"
bad() { echo "Status: 400 Bad Request"; echo ""; echo "$1"; exit 0; }

# Validate MAC format: XX:XX:XX:XX:XX:XX
valid_mac() {
  case "$1" in
    ''|*[!0-9A-Fa-f:]*) return 1 ;;
  esac
  [ "$(printf '%s' "$1" | wc -c | tr -d ' ')" = "17" ] || return 1
  return 0
}

# Validate hostname: non-empty, alphanumeric + hyphens, max 63 chars
valid_hostname() {
  [ -n "$1" ] || return 1
  [ "$(printf '%s' "$1" | wc -c | tr -d ' ')" -le 64 ] || return 1
  case "$1" in
    *[!a-zA-Z0-9-]*) return 1 ;;
  esac
  return 0
}

CHANGED=0
DID_SSID=0
DID_HOSTNAME=0
DID_MAC=0
DID_RESTORE_HOSTNAME=0
DID_RESTORE_MAC=0

# --- Restore handlers ---
RESTORE_SSID=$(dec "$(get restore_ssid)")
if [ -n "$RESTORE_SSID" ]; then
  SSID_FILE="/fhconf/mytools/ssid.conf"
  [ -f "$SSID_FILE" ] || : > "$SSID_FILE"
  case "$RESTORE_SSID" in
    wl0.1) grep -v "^wl0.1=" "$SSID_FILE" 2>/dev/null > "$SSID_FILE.tmp" || true ;;
    wl1)   grep -v "^wl1=" "$SSID_FILE" 2>/dev/null > "$SSID_FILE.tmp" || true ;;
    all)   : > "$SSID_FILE.tmp" ;;
  esac
  mv "$SSID_FILE.tmp" "$SSID_FILE"
  chmod 600 "$SSID_FILE"
  # Live reset to defaults
  case "$RESTORE_SSID" in
    wl0.1) wl -i wl0.1 ssid Ext >/dev/null 2>&1 ;;
    wl1)   wl -i wl1 ssid Ext5G >/dev/null 2>&1 ;;
    all)   wl -i wl0.1 ssid Ext >/dev/null 2>&1; wl -i wl1 ssid Ext5G >/dev/null 2>&1 ;;
  esac
  CHANGED=1
  DID_SSID=1
fi

RESTORE_HOSTNAME=$(dec "$(get restore_hostname)")
if [ -n "$RESTORE_HOSTNAME" ]; then
  HOSTNAME_FILE="/tmp/hostname.conf"
  rm -f "$HOSTNAME_FILE"
  # Re-run udhcpc without hostname option
  killall udhcpc 2>/dev/null
  sleep 1
  udhcpc -i wl0 -s /var/dhcp.script -t 5 -T 3 -n >/dev/null 2>&1
  CHANGED=1
  DID_RESTORE_HOSTNAME=1
fi

RESTORE_MAC=$(dec "$(get restore_mac)")
if [ -n "$RESTORE_MAC" ]; then
  MAC_CONF="/fhconf/mytools/mac.conf"
  MAC_DEFAULTS="/fhconf/mytools/mac_defaults"
  [ -f "$MAC_CONF" ] || : > "$MAC_CONF"
  default_mac() { sed -n "s/^$1=//p" "$MAC_DEFAULTS" 2>/dev/null | head -n1; }
  apply_default_mac() {
    _dm=$(default_mac "$1")
    [ -n "$_dm" ] || return 0
    wl -i "$1" down 2>/dev/null
    wl -i "$1" cur_etheraddr "$_dm" >/dev/null 2>&1
    wl -i "$1" up 2>/dev/null
  }
  case "$RESTORE_MAC" in
    wl1)   grep -v "^wl1=" "$MAC_CONF" 2>/dev/null > "$MAC_CONF.tmp" || true
           apply_default_mac wl1 ;;
  esac
  [ -f "$MAC_CONF.tmp" ] && mv "$MAC_CONF.tmp" "$MAC_CONF"
  chmod 600 "$MAC_CONF"
  CHANGED=1
  DID_RESTORE_MAC=1
fi

# --- Hostname change ---
HOSTNAME=$(dec "$(get hostname)")
if [ -n "$HOSTNAME" ]; then
  valid_hostname "$HOSTNAME" || bad "Invalid hostname (letters, digits, hyphens only, max 63)."
  killall udhcpc 2>/dev/null
  sleep 1
  if ! udhcpc -i wl0 -x hostname:"$HOSTNAME" -s /var/dhcp.script -t 5 -T 3 -n >/dev/null 2>&1; then
    bad "Failed to set hostname '$HOSTNAME' on wl0."
  fi
  HOSTNAME_FILE="/tmp/hostname.conf"
  printf '%s\n' "$HOSTNAME" > "$HOSTNAME_FILE"
  chmod 600 "$HOSTNAME_FILE"
  CHANGED=1
  DID_HOSTNAME=1
fi

# --- MAC changes: save to persistence file only (no auto-restart) ---
MAC_CONF="/fhconf/mytools/mac.conf"
[ -f "$MAC_CONF" ] || : > "$MAC_CONF"

save_mac() {
  _iface="$1"
  _val="$2"
  [ -f "$MAC_CONF" ] || : > "$MAC_CONF"
  { grep -v "^$_iface=" "$MAC_CONF" 2>/dev/null || true; printf '%s=%s\n' "$_iface" "$_val"; } > "$MAC_CONF.tmp"
  mv "$MAC_CONF.tmp" "$MAC_CONF"
  chmod 600 "$MAC_CONF"
}

for pair in "mac5g:wl1"; do
  IFACE=${pair#*:}
  FIELD=${pair%:*}
  VAL=$(dec "$(get "$FIELD")")
  if [ -n "$VAL" ]; then
    valid_mac "$VAL" || bad "Invalid MAC for $IFACE (use XX:XX:XX:XX:XX:XX)."
    save_mac "$IFACE" "$VAL"
    CHANGED=1
    DID_MAC=1
  fi
done

if [ "$CHANGED" = "1" ]; then
  echo "Status: 200 OK"
  echo ""
  if [ "$DID_SSID" = "1" ]; then
    echo "SSID restored to default. Clients on that AP will reconnect."
  elif [ "$DID_RESTORE_HOSTNAME" = "1" ] && [ "$DID_RESTORE_MAC" = "1" ]; then
    echo "Hostname and MACs restored to default."
  elif [ "$DID_RESTORE_HOSTNAME" = "1" ]; then
    echo "Hostname restored to default."
  elif [ "$DID_RESTORE_MAC" = "1" ]; then
    echo "MAC restored to default."
  elif [ "$DID_HOSTNAME" = "1" ] && [ "$DID_MAC" = "1" ]; then
    echo "Hostname applied. MACs saved - reconnect to apply MAC changes."
  elif [ "$DID_MAC" = "1" ]; then
    echo "MACs saved. Reconnect to apply changes."
  elif [ "$DID_HOSTNAME" = "1" ]; then
    echo "Hostname applied."
  else
    echo "Changes saved."
  fi
else
  bad "Nothing to change. Provide hostname and/or MAC."
fi
