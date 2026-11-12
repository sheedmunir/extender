#!/bin/sh
# wpa.cgi - set or clear a WPA2-PSK password on the 2.4GHz AP (wl0.1).
# Password is persisted to /fhconf/mytools/wpa.conf (key=value: wl0.1=<pass>)
# and applied by extender.sh when the 2.4GHz AP comes up.
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

# Validate WPA2 password: 8 to 63 chars, no pipe or quote (config is pipe-delimited, hostapd config has no quoting)
valid_pass() {
  [ -n "$1" ] || return 1
  LEN=$(printf '%s' "$1" | wc -c | tr -d ' ')
  [ "$LEN" -ge 8 ] && [ "$LEN" -le 63 ] || return 1
  case "$1" in *'|'*|*'"'*) return 1 ;; esac
  return 0
}

# Validate AP state value
valid_state() {
  case "$1" in on|off|1|0) return 0 ;; *) return 1 ;; esac
}

WPA_CONF="/fhconf/mytools/wpa.conf"
if [ -n "$WPA_CONF_FILE" ]; then WPA_CONF="$WPA_CONF_FILE"; fi
[ -f "$WPA_CONF" ] || : > "$WPA_CONF"

# Read saved 5GHz SSID from ssid.conf (same source extender.sh uses)
SSID_CONF="/fhconf/mytools/ssid.conf"
SSID_5G="Ext5G"
if [ -f "$SSID_CONF" ]; then
  while IFS='=' read -r _key _val; do
    case "$_key" in
      wl1) SSID_5G="$_val" ;;
    esac
  done < "$SSID_CONF" 2>/dev/null || true
fi

AP_STATE="/tmp/ext_ap_state"
[ -f "$AP_STATE" ] || : > "$AP_STATE"

CHANGED=0
DID_SET=0
DID_CLEAR=0
DID_STATE=0
STATE_MSG=""

# --- Clear (restore to open) ---
RESTORE_WPA=$(dec "$(get restore_wpa_wl0.1)")
if [ -n "$RESTORE_WPA" ]; then
  grep -v "^wl0.1=" "$WPA_CONF" 2>/dev/null > "$WPA_CONF.tmp" || true
  mv "$WPA_CONF.tmp" "$WPA_CONF"
  chmod 600 "$WPA_CONF"
  CHANGED=1
  DID_CLEAR=1
fi

# --- Set WPA2 password ---
WPA_PASS=$(dec "$(get wl0.1)")
if [ -n "$WPA_PASS" ]; then
  valid_pass "$WPA_PASS" || bad "WPA2 password must be 8 to 63 characters and cannot contain | or \"."
  { grep -v "^wl0.1=" "$WPA_CONF" 2>/dev/null || true; printf '%s=%s\n' "wl0.1" "$WPA_PASS"; } > "$WPA_CONF.tmp"
  mv "$WPA_CONF.tmp" "$WPA_CONF"
  chmod 600 "$WPA_CONF"
  CHANGED=1
  DID_SET=1
fi

# --- AP on/off toggle (runtime only, no persistence) ---
for pair in "wl0.1_state:wl0.1" "wl1_state:wl1"; do
  IFACE=${pair#*:}
  FIELD=${pair%:*}
  VAL=$(dec "$(get "$FIELD")")
  if [ -n "$VAL" ]; then
    valid_state "$VAL" || bad "Invalid state for $IFACE (use on or off)."
    case "$VAL" in 1|ON) VAL=on ;; 0|OFF) VAL=off ;; esac

    # Check if WPA2 password is configured for wl0.1
    wpa_pass=""
    if [ "$IFACE" = "wl0.1" ] && [ -f "$WPA_CONF" ]; then
      wpa_pass=$(sed -n 's/^wl0.1=//p' "$WPA_CONF" 2>/dev/null)
    fi

    if [ "$IFACE" = "wl1" ]; then
      # wl1: physical interface, no hostapd — direct radio on/off is safe
      if [ "$VAL" = "off" ]; then
        wl -i wl1 radio off >/dev/null 2>&1
        wl -i wl1 down >/dev/null 2>&1
      else
        wl -i wl1 up >/dev/null 2>&1
        sleep 1
        wl -i wl1 radio on >/dev/null 2>&1
        # Re-apply AP settings so the 5GHz AP broadcasts again
        wl -i wl1 ap 1 >/dev/null 2>&1
        wl -i wl1 bss 1 >/dev/null 2>&1
        wl -i wl1 ssid "$SSID_5G" >/dev/null 2>&1
        wl -i wl1 auth 0 >/dev/null 2>&1
        wl -i wl1 wsec 0 >/dev/null 2>&1
      fi
    elif [ "$IFACE" = "wl0.1" ]; then
      if [ "$VAL" = "off" ]; then
        # Stop hostapd first if WPA2 is active (hostapd owns wl0.1 via nl80211)
        if [ -n "$wpa_pass" ]; then
          killall hostapd >/dev/null 2>&1
          sleep 1
        fi
        wl -i "$IFACE" down >/dev/null 2>&1
      else
        wl -i "$IFACE" up >/dev/null 2>&1
        sleep 1
        # Restart hostapd if WPA2 is configured
        if [ -n "$wpa_pass" ]; then
          ap_ssid=$(wl -i wl0.1 ssid 2>/dev/null | sed -n 's/^Current SSID: *"\(.*\)"/\1/p')
          [ -z "$ap_ssid" ] && ap_ssid="Ext"
          cat > /var/hostapd-wl0.1.conf <<HOSTAPD_EOF
interface=wl0.1
driver=nl80211
hw_mode=g
channel=6
ssid=$ap_ssid
wpa=2
wpa_pairwise=CCMP
rsn_pairwise=CCMP
wpa_passphrase=$wpa_pass
auth_algs=1
country_code=US
ctrl_interface=/var/run/hostapd
HOSTAPD_EOF
          setsid hostapd /var/hostapd-wl0.1.conf > /tmp/hostapd-wl0.1.log 2>&1 &
        fi
      fi
    fi

    grep -v "^$IFACE=" "$AP_STATE" 2>/dev/null > "${AP_STATE}.tmp" || true
    printf '%s=%s\n' "$IFACE" "$VAL" >> "${AP_STATE}.tmp"
    mv "${AP_STATE}.tmp" "$AP_STATE"
    chmod 600 "$AP_STATE"
    CHANGED=1
    DID_STATE=1
    STATE_MSG="$STATE_MSG $IFACE → $VAL;"
  fi
done

if [ "$CHANGED" = "1" ]; then
  echo "Status: 200 OK"
  echo ""
  if [ "$DID_SET" = "1" ]; then
    echo "WPA2 password set on 2.4GHz AP (wl0.1). Reconnect clients to apply."
  elif [ "$DID_CLEAR" = "1" ]; then
    echo "2.4GHz AP (wl0.1) restored to open (no password)."
  fi
  if [ "$DID_STATE" = "1" ]; then
    echo "AP state:$STATE_MSG"
  fi
else
  bad "Nothing to change. Provide a WPA2 password for wl0.1, or wl0.1_state/wl1_state (on/off)."
fi
