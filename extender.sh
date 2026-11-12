#!/bin/sh
# extender.sh - Dual-band WiFi extender with persistent credentials, reconnect,
# status, and teardown. Run with sh extender.sh -h for usage.

export PATH=$PATH:/fhrom/bin:/usr/sbin:/sbin:/bin
CC="US"
TAB=$(printf '\t')
umask 077
trap 'stty echo 2>/dev/null' EXIT
trap 'stty echo 2>/dev/null; exit 1' INT

# ------------------------------------------------------------------ config
TOOLS_DIR="/fhconf/mytools"
PASS_FILE="$TOOLS_DIR/passwords"
SSID_5G="Ext5G"
SSID_2G="Ext"

# Load saved SSIDs from persistence file (overrides defaults; corrupted -> defaults)
SSID_CONF="$TOOLS_DIR/ssid.conf"
if [ -f "$SSID_CONF" ]; then
  while IFS='=' read -r _key _val; do
    case "$_key" in
      wl0.1) SSID_2G="$_val" ;;
      wl1)   SSID_5G="$_val" ;;
    esac
  done < "$SSID_CONF" 2>/dev/null || true
fi

# Load saved MACs from persistence file (wl0/wl0.1/wl1)
MAC_CONF="$TOOLS_DIR/mac.conf"
MAC_0G=""
MAC_2G=""
MAC_5G=""
if [ -f "$MAC_CONF" ]; then
  while IFS='=' read -r _key _val; do
    case "$_key" in
      wl0)   MAC_0G="$_val" ;;
      wl0.1) MAC_2G="$_val" ;;
      wl1)   MAC_5G="$_val" ;;
    esac
  done < "$MAC_CONF" 2>/dev/null || true
fi

# Load saved WPA2 password for the 2.4GHz AP (wl0.1)
WPA_CONF="$TOOLS_DIR/wpa.conf"
WPA_2G=""
if [ -f "$WPA_CONF" ]; then
  while IFS='=' read -r _key _val; do
    case "$_key" in
      wl0.1) WPA_2G="$_val" ;;
    esac
  done < "$WPA_CONF" 2>/dev/null || true
fi

# Runtime AP on/off state (no persistence; lost on reboot)
AP_STATE="/tmp/ext_ap_state"
AP_2G_ON=1
AP_5G_ON=0   # wl1 off by default
if [ -f "$AP_STATE" ]; then
  while IFS='=' read -r _key _val; do
    case "$_key" in
      wl0.1) case "$_val" in 0|off|OFF) AP_2G_ON=0 ;; 1|on|ON) AP_2G_ON=1 ;; esac ;;
      wl1)   case "$_val" in 0|off|OFF) AP_5G_ON=0 ;; 1|on|ON) AP_5G_ON=1 ;; esac ;;
    esac
  done < "$AP_STATE" 2>/dev/null || true
fi
# Write current state to file so status.cgi can read it
: > "$AP_STATE"
if [ "$AP_2G_ON" = "1" ]; then
  _2g_state=on
else
  _2g_state=off
fi
if [ "$AP_5G_ON" = "1" ]; then
  _5g_state=on
else
  _5g_state=off
fi
printf 'wl0.1=%s\n' "$_2g_state" >> "$AP_STATE"
printf 'wl1=%s\n' "$_5g_state" >> "$AP_STATE"
chmod 600 "$AP_STATE"

mkdir -p "$TOOLS_DIR"
[ -f "$PASS_FILE" ] || : > "$PASS_FILE"

# ------------------------------------------------------------------ argument parsing (before anything touches the radios)
MODE=scan
RNUM=""

case "$1" in
  "")
    MODE=scan
    ;;
  -h|--help)
    cat <<USAGE
Usage:
  sh $0               Scan for WiFi and connect
  sh $0 -r            List saved networks and choose one
  sh $0 -r <N>        Reconnect directly to saved network N
  sh $0 -r -d <N>     Delete saved network N
  sh $0 -s            Show current status (uplink, both APs, clients)
  sh $0 -k            Stop the extender and clean up
  sh $0 -h            Show this help
USAGE
    exit 0
    ;;
  -s)
    MODE=status
    ;;
  -k)
    MODE=kill
    ;;
  -r)
    if [ "$2" = "-d" ]; then
      MODE=delete
      RNUM="$3"
    elif [ -n "$2" ]; then
      MODE=reconnect_num
      RNUM="$2"
    else
      MODE=reconnect_list
    fi
    ;;
  *)
    echo "Unknown option: $1"
    echo "Use 'sh $0 -h' for help."
    exit 1
    ;;
esac

# ------------------------------------------------------------------ helpers used by -s / -k / -r -d (read-only or standalone)

show_clients() {
  iface=$1
  label=$2
  echo "  $label clients:"
  raw=$(wl -i "$iface" assoclist 2>/dev/null | sed -n 's/^assoclist //p')
  if [ -z "$raw" ]; then
    echo "    (none)"
    return
  fi
  printf '%s\n' "$raw" | tr ' ' '\n' | while read -r m; do
    [ -n "$m" ] || continue
    mlow=$(echo "$m" | tr 'A-Z' 'a-z')
    ip=$(dumpleases -f /tmp/udhcpd.leases 2>/dev/null | awk -v mac="$mlow" 'tolower($1)==mac{print $2}')
    echo "    $m  ${ip:-no lease yet}"
  done
}

status_report() {
  echo "== Extender status =="
  up_state=$(wpa_cli -i wl0 status 2>/dev/null | sed -n 's/^wpa_state=//p')
  up_ssid=$(wpa_cli -i wl0 status 2>/dev/null | sed -n 's/^ssid=//p')
  if [ "$up_state" = "COMPLETED" ] && [ -n "$up_ssid" ]; then
    up_rssi=$(wl -i wl0 status 2>/dev/null | sed -n 's/.*RSSI: *\(-*[0-9]*\) dBm.*/\1/p' | head -n1)
    up_ch=$(wl -i wl0 status 2>/dev/null | sed -n 's/.*Primary channel: *\([0-9]*\).*/\1/p')
    util_pct=$(wl -i wl0 status 2>/dev/null | sed -n 's/.*QBSS Channel Utilization:.*(\([0-9]*\) %).*/\1/p')
    echo "  Uplink    : $up_ssid  (channel ${up_ch:-?}, ${up_rssi:-?} dBm)"
    if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
      echo "  Internet  : yes"
    else
      echo "  Internet  : no"
    fi
    if [ -n "$util_pct" ] && [ "$util_pct" -ge 50 ] 2>/dev/null; then
      echo "  NOTE      : the uplink's 2.4GHz channel is busy (${util_pct}% utilization)."
      echo "              This also affects the 2.4GHz AP, since it shares that channel."
    fi
  else
    echo "  Uplink    : not connected"
    echo "  Internet  : no"
  fi

  echo
  ap5_ssid=$(wl -i wl1 ssid 2>/dev/null | sed -n 's/^Current SSID: *"\(.*\)"/\1/p')
  ap5_ch=$(wl -i wl1 status 2>/dev/null | sed -n 's/.*Primary channel: *\([0-9]*\).*/\1/p')
  echo "  5GHz AP   : ${ap5_ssid:-(off)}  (channel ${ap5_ch:-?})"
  show_clients wl1 "5GHz"

  echo
  ap2_ssid=$(wl -i wl0.1 ssid 2>/dev/null | sed -n 's/^Current SSID: *"\(.*\)"/\1/p')
  echo "  2.4GHz AP : ${ap2_ssid:-(off)}  (shares the uplink's channel)"
  show_clients wl0.1 "2.4GHz"
}

teardown() {
  echo "Stopping the extender..."
  killall tcpsvd udhcpd udhcpc wpa_supplicant hostapd dnsmasq 2>/dev/null
  rm -rf /var/run/wpa_supplicant /var/wpa.conf
  ifconfig br0 down 2>/dev/null
  brctl delbr br0 2>/dev/null
  route del default 2>/dev/null
  ip addr flush dev wl0 2>/dev/null
  wl -i wl1 radio off 2>/dev/null
  wl -i wl0.1 bss down 2>/dev/null
  iptables -F 2>/dev/null
  iptables -t nat -F 2>/dev/null
  echo 0 > /proc/sys/net/ipv4/ip_forward 2>/dev/null
  echo "Stopped."
}

delete_saved() {
  num=$1
  if [ ! -s "$PASS_FILE" ]; then
    echo "No saved networks to delete."
    return 1
  fi
  case "$num" in
    ''|*[!0-9]*)
      echo "Please give a number. Use 'sh $0 -h' for help."
      return 1
      ;;
  esac
  total=$(wc -l < "$PASS_FILE")
  if [ "$num" -lt 1 ] || [ "$num" -gt "$total" ]; then
    echo "No saved network number $num."
    return 1
  fi
  del_ssid=$(awk -F'|' -v n="$num" 'NR==n{print $1}' "$PASS_FILE")
  awk -v n="$num" 'NR!=n' "$PASS_FILE" > "${PASS_FILE}.tmp"
  mv "${PASS_FILE}.tmp" "$PASS_FILE"
  echo "Deleted \"$del_ssid\" from saved networks."
  return 0
}

# ------------------------------------------------------------------ early exits: these never touch cleanup/radios

if [ "$MODE" = status ]; then
  status_report
  exit 0
fi

if [ "$MODE" = kill ]; then
  teardown
  exit 0
fi

if [ "$MODE" = delete ]; then
  delete_saved "$RNUM"
  exit $?
fi

# ------------------------------------------------------------------ everything below is the scan / reconnect / connect flow

dmesg -n 1

start_scanner() {
  killall wpa_supplicant 2>/dev/null
  sleep 1
  rm -rf /var/run/wpa_supplicant
  mkdir -p /var/run/wpa_supplicant
  echo 'ctrl_interface=/var/run/wpa_supplicant' > /var/wpa.conf
  wpa_supplicant -B -i wl0 -D nl80211 -c /var/wpa.conf >/dev/null 2>&1
  sleep 2
}

scan_networks() {
  echo "Scanning airwaves..."
  wpa_cli -i wl0 scan >/dev/null 2>&1
  old=-1
  t=0
  while [ $t -lt 12 ]; do
    sleep 2
    t=$((t + 2))
    n=$(wpa_cli -i wl0 scan_results 2>/dev/null | wc -l)
    [ "$n" -eq "$old" ] && break
    old=$n
  done
  wpa_cli -i wl0 scan_results 2>/dev/null | awk -F"$TAB" '
    NR > 1 && $5 != "" {
      f = $4
      if (f ~ /EAP|WEP/ || $5 ~ /\\/) c = "NO"
      else if (f ~ /PSK/) c = "PSK"
      else if (f ~ /SAE|WPA|RSN/) c = "NO"
      else c = "OPEN"
      if (!($5 in best) || $3 + 0 > best[$5] + 0) {
        best[$5] = $3; fr[$5] = $2; cl[$5] = c
      }
    }
    END { for (s in best) printf "%d\t%d\t%s\t%s\n", best[s], fr[s], cl[s], s }
  ' > /tmp/n0
  sort -t "$TAB" -k1,1nr /tmp/n0 > /tmp/n1
  { awk -F"$TAB" '$3 != "NO"' /tmp/n1; awk -F"$TAB" '$3 == "NO"' /tmp/n1; } > /tmp/nets
}

pick_network() {
  scan_networks
  echo
  if [ -s /tmp/nets ]; then
    echo "WiFi networks found, strongest first:"
    awk -F"$TAB" '{
      sec = ($3 == "NO") ? "unsupported" : ($3 == "OPEN") ? "open" : "password"
      printf "%3d)  %-30s  %4d dBm   %s\n", NR, $4, $1, sec
    }' /tmp/nets
  else
    echo "No WiFi networks found. Check that the network is on and in range."
  fi
  echo
  echo "Type a number to choose, r = scan again, m = type a name, q = quit"
  printf "Choice: "
  read -r ans
  case "$ans" in
    q|Q) echo "Bye."; exit 0 ;;
    m|M)
      printf "Network name: "
      read -r SSID
      [ -n "$SSID" ] || return 1
      SEC=PSK
      printf "Is it an open network, with no password? (y/N): "
      read -r o
      case "$o" in y|Y) SEC=OPEN ;; esac
      return 0 ;;
    ''|*[!0-9]*) return 1 ;;
  esac
  line=$(sed -n "${ans}p" /tmp/nets)
  if [ -z "$line" ]; then
    echo "There is no number $ans in the list."
    return 1
  fi
  SEC=$(printf '%s\n' "$line" | cut -f3)
  SSID=$(printf '%s\n' "$line" | cut -f4-)
  if [ "$SEC" = NO ]; then
    echo "\"$SSID\" cannot be used (WPA3-only, WEP, or enterprise)."
    return 1
  fi
  return 0
}

find_saved() {
  awk -F'|' -v s="$SSID" '$1 == s { print; exit }' "$PASS_FILE" 2>/dev/null
}

check_saved_pass() {
  USE_SAVED=0
  saved_line=$(find_saved)
  [ -n "$saved_line" ] || return
  saved_sec=$(printf '%s\n' "$saved_line" | cut -d'|' -f2)
  saved_pass=$(printf '%s\n' "$saved_line" | cut -d'|' -f3)
  [ "$saved_sec" = "PSK" ] || return
  printf 'A saved password for "%s" was found. Use it? (Y/n): ' "$SSID"
  read -r ans
  case "$ans" in
    n|N) USE_SAVED=0 ;;
    *) PASS="$saved_pass"; USE_SAVED=1 ;;
  esac
}

save_credential() {
  [ -n "$SSID" ] || return
  awk -F'|' -v s="$SSID" '$1 != s' "$PASS_FILE" > "${PASS_FILE}.tmp" 2>/dev/null
  mv "${PASS_FILE}.tmp" "$PASS_FILE" 2>/dev/null
  printf '%s|%s|%s\n' "$SSID" "$SEC" "$PASS" >> "$PASS_FILE"
}

ask_password() {
  while true; do
    printf 'Password for "%s" (typing is hidden): ' "$SSID"
    stty -echo
    IFS= read -r PASS
    stty echo
    echo
    [ ${#PASS} -ge 8 ] && [ ${#PASS} -le 63 ] && return 0
    echo "  A WiFi password has 8 to 63 characters."
  done
}

connect_wifi() {
  killall wpa_supplicant 2>/dev/null
  sleep 1
  rm -rf /var/run/wpa_supplicant
  mkdir -p /var/run/wpa_supplicant
  # Convert SSID to hex for wpa_supplicant (xxd may not exist on all routers)
  if command -v xxd >/dev/null 2>&1; then
    HEX=$(printf '%s' "$SSID" | xxd -p | tr -d '\n')
  elif command -v od >/dev/null 2>&1; then
    HEX=$(printf '%s' "$SSID" | od -An -tx1 | tr -d ' \n')
  else
    HEX=""
  fi
  {
    echo 'ctrl_interface=/var/run/wpa_supplicant'
    echo 'network={'
    if [ -n "$HEX" ]; then
      echo "  ssid=$HEX"
    else
      echo "  ssid=\"$SSID\""
    fi
    echo '  scan_ssid=1'
    echo '  proto=RSN'
    echo '  pairwise=CCMP TKIP'
    echo '  group=CCMP TKIP'
    if [ "$SEC" = OPEN ]; then
      echo '  key_mgmt=NONE'
    else
      echo '  key_mgmt=WPA-PSK'
      printf '  psk="%s"\n' "$PASS"
    fi
    echo '}'
  } > /var/wpa.conf
  # Apply saved MAC to wl0 before connecting
  if [ -n "$MAC_0G" ]; then
    wl -i wl0 down 2>/dev/null
    sleep 1
    wl -i wl0 cur_etheraddr "$MAC_0G" >/dev/null 2>&1
    wl -i wl0 up 2>/dev/null
    sleep 1
  fi
  wpa_supplicant -B -i wl0 -D nl80211 -c /var/wpa.conf >/dev/null 2>&1
  saw=0
  t=0
  while [ $t -lt 25 ]; do
    sleep 1
    t=$((t + 1))
    st=$(wpa_cli -i wl0 status 2>/dev/null | sed -n 's/^wpa_state=//p')
    case "$st" in
      COMPLETED) rm -f /var/wpa.conf; return 0 ;;
      ASSOCIATED|4WAY_HANDSHAKE|GROUP_HANDSHAKE) saw=1 ;;
      DISCONNECTED|INACTIVE) [ $saw = 1 ] && { rm -f /var/wpa.conf; return 2; } ;;
    esac
  done
  rm -f /var/wpa.conf
  [ $saw = 1 ] && return 2
  return 1
}

join_network() {
  n=0
  USE_SAVED=0
  [ "$SEC" = PSK ] && check_saved_pass
  while [ $n -lt 3 ]; do
    n=$((n + 1))
    if [ "$SEC" = PSK ]; then
      if [ "$USE_SAVED" = 1 ] && [ $n -eq 1 ]; then
        :
      else
        ask_password
      fi
    fi
    echo "Connecting to \"$SSID\"..."
    connect_wifi
    r=$?
    if [ $r = 0 ]; then
      save_credential
      PASS=""
      return 0
    fi
    PASS=""
    if [ $r = 2 ]; then
      echo "  Wrong password for \"$SSID\"."
      USE_SAVED=0
      [ "$SEC" = PSK ] && [ $n -lt 3 ] && { echo "  Try again ($n of 3)."; continue; }
    fi
    echo "  No answer from \"$SSID\". It may be too far away, too weak,"
    echo "  or it blocks new devices (for example a MAC filter)."
    return 1
  done
  echo "  Three wrong passwords. Going back to the list."
  return 1
}

get_address() {
  cat > /var/dhcp.script <<'DHCP_EOF'
#!/bin/sh
case "$1" in
bound|renew)
  ifconfig $interface $ip netmask $subnet
  route del default 2>/dev/null
  route add default gw ${router%% *} dev $interface
  : > /var/resolv.conf
  for d in $dns; do echo "nameserver $d" >> /var/resolv.conf; done ;;
esac
DHCP_EOF
  chmod +x /var/dhcp.script
  udhcpc -i wl0 -s /var/dhcp.script -t 5 -T 3 -n >/dev/null 2>&1
}

subnet_busy() {
  if [ "$UP_PFX" -ge 24 ]; then
    case "$UP_IP." in "$1".*) return 0 ;; esac
  elif [ "$UP_PFX" -ge 16 ]; then
    pre=${1%.*}
    case "$UP_IP." in "$pre".*) return 0 ;; esac
  elif [ "$UP_PFX" -ge 8 ]; then
    pre=${1%%.*}
    case "$UP_IP." in "$pre".*) return 0 ;; esac
  else
    return 0
  fi
  return 1
}

echo "== 1/6  Cleaning up"
killall tcpsvd udhcpd udhcpc wpa_supplicant hostapd dnsmasq 2>/dev/null
rm -rf /var/run/wpa_supplicant /var/wpa.conf
ifconfig br0 down 2>/dev/null
brctl delbr br0 2>/dev/null
route del default 2>/dev/null
ip addr flush dev wl0 2>/dev/null

K=/lib/modules/4.1.52/kernel/net
for m in netfilter/nf_conntrack ipv4/netfilter/nf_defrag_ipv4 \
  ipv4/netfilter/nf_conntrack_ipv4 netfilter/nf_nat ipv4/netfilter/nf_nat_ipv4 \
  ipv4/netfilter/nf_nat_masquerade_ipv4 ipv4/netfilter/ip_tables \
  ipv4/netfilter/iptable_filter ipv4/netfilter/iptable_nat \
  ipv4/netfilter/ipt_MASQUERADE netfilter/xt_state netfilter/xt_conntrack; do
  insmod $K/$m.ko 2>/dev/null
done
iptables -F
iptables -t nat -F
if ! iptables -t nat -L >/dev/null 2>&1; then
  echo "ERROR: the firewall tables are not available, so sharing cannot work."
  echo "       Run: lsmod | grep -E 'nat|ip_tables'   and check dmesg."
  exit 1
fi
wl -i wl0 country $CC 2>/dev/null

echo

if [ "$MODE" = reconnect_list ] || [ "$MODE" = reconnect_num ]; then
    echo "== 2/6  Loading saved networks..."
    if [ ! -s "$PASS_FILE" ]; then
        echo "Error: no saved networks yet in $PASS_FILE."
        echo "Run 'sh $0' (no -r) to scan and connect, which saves it for next time."
        exit 1
    fi

    echo
    echo "Saved WiFi networks:"
    i=1
    while IFS='|' read -r s_ssid s_sec s_pass; do
        [ -n "$s_ssid" ] || continue
        if [ "$s_sec" = "OPEN" ]; then
            printf "  %2d) %-30s (open network)\n" "$i" "$s_ssid"
        else
            printf "  %2d) %-30s password: %s\n" "$i" "$s_ssid" "$s_pass"
        fi
        i=$((i + 1))
    done < "$PASS_FILE"
    echo

    if [ "$MODE" = reconnect_num ]; then
        case "$RNUM" in
          ''|*[!0-9]*)
            echo "Please give a number after -r, for example: sh $0 -r 2"
            exit 1
            ;;
        esac
        choice="$RNUM"
        echo "Reconnecting directly to saved network $choice..."
    else
        printf "Choose a number to reconnect: "
        read -r choice
    fi

    selected_ssid=""
    selected_sec=""
    selected_pass=""
    i=1
    while IFS='|' read -r s_ssid s_sec s_pass; do
        [ -n "$s_ssid" ] || continue
        if [ "$i" -eq "$choice" ]; then
            selected_ssid="$s_ssid"
            selected_sec="$s_sec"
            selected_pass="$s_pass"
            break
        fi
        i=$((i + 1))
    done < "$PASS_FILE"

    if [ -z "$selected_ssid" ]; then
        echo "No saved network number $choice."
        exit 1
    fi

    SSID="$selected_ssid"
    SEC="$selected_sec"
    PASS="$selected_pass"

    echo "Connecting to saved network: $SSID..."
    start_scanner
    connect_wifi
    rc=$?
    PASS=""
    if [ $rc -ne 0 ]; then
        echo "ERROR: failed to connect to saved network \"$SSID\"."
        echo
        echo "Next steps:"
        echo "  Run 'sh $0' to scan and pick a network (new or saved)."
        echo "  If the password changed, pick \"$SSID\" from that list and"
        echo "  choose to enter a new password when asked."
        exit 1
    fi
    echo "  Connected successfully. Asking for an address..."
    get_address

else
    echo "== 2/6  Choose the WiFi to extend"
    while true; do
      start_scanner
      pick_network || continue
      join_network || continue
      echo "  Connected to \"$SSID\". Asking for an address..."
      get_address && break
      echo "  ERROR: connected, but the network gave no address (DHCP)."
    done
fi

A=$(ip -4 addr show wl0 | awk '/inet /{print $2}')
UP_IP=${A%/*}
UP_PFX=${A#*/}
echo "  Address on the uplink: $UP_IP/$UP_PFX"

echo
echo "== 3/6  Checking the connection"
INTERNET=yes
GW=$(ip route | sed -n 's/^default via \([0-9.]*\).*/\1/p' | head -n 1)
if [ -z "$GW" ]; then
  echo "  WARNING: no gateway was given."
  INTERNET=no
elif ! ping -c 2 "$GW" >/dev/null 2>&1; then
  echo "  WARNING: gateway $GW does not answer."
  INTERNET=no
elif ! ping -c 2 8.8.8.8 >/dev/null 2>&1; then
  echo "  WARNING: no reply from the internet."
  INTERNET=no
else
  echo "  OK: gateway and internet work."
fi

LAN=""
for cand in 192.168.50 192.168.1 192.168.77 172.16.50 10.77.77; do
  subnet_busy "$cand" || { LAN=$cand; break; }
done
if [ -z "$LAN" ]; then
  echo "ERROR: could not find a free subnet for the extender."
  exit 1
fi
echo "  The extender will use $LAN.0/24."

echo
echo "== 4/6  WiFi names and channel selection"
echo "  5 GHz WiFi name   : $SSID_5G"
echo "  2.4 GHz WiFi name : $SSID_2G"

util_pct=$(wl -i wl0 status 2>/dev/null | sed -n 's/.*QBSS Channel Utilization:.*(\([0-9]*\) %).*/\1/p')
if [ -n "$util_pct" ] && [ "$util_pct" -ge 50 ] 2>/dev/null; then
  echo "  NOTE: the uplink's 2.4GHz channel is busy (${util_pct}% utilization)."
  echo "        The 2.4GHz AP shares that channel and can't pick a quieter one"
  echo "        on its own, since it's locked to whatever channel the uplink uses."
fi

echo "  Scanning 5 GHz neighbours for a quiet channel..."
wl -i wl1 down
wl -i wl1 ap 0
wl -i wl1 up
wl -i wl1 scan
sleep 8
CH=$(wl -i wl1 scanresults | awk '
  /RSSI:/ && /Channel:/ {
    for (i = 1; i <= NF; i++) {
      if ($i == "RSSI:") r = $(i + 1)
      if ($i == "Channel:") c = $(i + 1)
    }
    sub(/[^0-9].*/, "", c); c += 0
    p = exp(r / 10 * log(10))
    if (c >= 36 && c <= 48) a += p
    else if (c >= 149 && c <= 161) b += p
  }
  END { if (b < a) print 149; else print 36 }')
[ -n "$CH" ] || CH=36
echo "  Chosen 5G channel: $CH (80 MHz)"

echo
echo "== 5/6  Starting the wireless APs"
if [ "$AP_5G_ON" = "1" ]; then
  wl -i wl1 down
  # Apply saved MAC to wl1 before bringing up
  if [ -n "$MAC_5G" ]; then
    wl -i wl1 cur_etheraddr "$MAC_5G" >/dev/null 2>&1
  fi
  wl -i wl1 country $CC
  wl -i wl1 mpc 0
  wl -i wl1 apsta 0
  wl -i wl1 ap 1
  wl -i wl1 bss 1
  wl -i wl1 auth 0
  wl -i wl1 wsec 0
  wl -i wl1 chanspec 5g$CH/80 || wl -i wl1 chanspec 5g36/80
  wl -i wl1 sgi 1 2>/dev/null
  wl -i wl1 closed 0
  wl -i wl1 up
  wl -i wl1 ssid "$SSID_5G"
  wl -i wl1 radio on
else
  echo "  5 GHz AP (wl1): off by default. Turn on in Internet tab."
  wl -i wl1 radio off 2>/dev/null
fi

wl -i wl0 bss -C 1 up
ifconfig wl0.1 up
if [ "$AP_2G_ON" = "1" ]; then
  wl -i wl0.1 down 2>/dev/null
  # Apply saved MAC to wl0.1 before bringing up
  if [ -n "$MAC_2G" ]; then
    wl -i wl0.1 cur_etheraddr "$MAC_2G" >/dev/null 2>&1
  fi
  wl -i wl0.1 ap 1
  wl -i wl0.1 ssid "$SSID_2G"
  if [ -n "$WPA_2G" ]; then
    # WPA2-PSK (AES/CCMP) handled by hostapd; skip wl open-mode config
    wl -i wl0.1 sgi 1 2>/dev/null
    wl -i wl0.1 up
  else
    wl -i wl0.1 auth 0
    wl -i wl0.1 wpa_auth 0
    wl -i wl0.1 wsec 0
    wl -i wl0.1 sgi 1 2>/dev/null
    wl -i wl0.1 up
  fi
else
  wl -i wl0.1 down 2>/dev/null
  echo "  2.4GHz AP (wl0.1): off."
fi

brctl addbr br0
ifconfig wl1 up
brctl addif br0 wl1
ifconfig wl0.1 up
brctl addif br0 wl0.1
ifconfig lan0 up 2>/dev/null
ifconfig lan1 up 2>/dev/null
ifconfig lan2 up 2>/dev/null
ifconfig lan3 up 2>/dev/null
brctl addif br0 lan0 2>/dev/null
brctl addif br0 lan1 2>/dev/null
brctl addif br0 lan2 2>/dev/null
brctl addif br0 lan3 2>/dev/null
ifconfig br0 $LAN.1 netmask 255.255.255.0 up
printf 'start %s.100\nend %s.200\ninterface br0\nlease_file /tmp/udhcpd.leases\noption subnet 255.255.255.0\noption router %s.1\noption dns 1.1.1.1 8.8.8.8\n' "$LAN" "$LAN" "$LAN" > /tmp/udhcpd.conf
touch /tmp/udhcpd.leases
udhcpd /tmp/udhcpd.conf
if ! ps | grep -q '[u]dhcpd'; then
  echo "ERROR: the address server (udhcpd) did not start. Devices cannot join."
  exit 1
fi

# Start hostapd with WPA2 on wl0.1 if a password is configured
if [ -n "$WPA_2G" ]; then
  cat > /var/hostapd-wl0.1.conf <<HOSTAPD_EOF
interface=wl0.1
driver=nl80211
hw_mode=g
channel=6
ssid=$SSID_2G
wpa=2
wpa_pairwise=CCMP
rsn_pairwise=CCMP
wpa_passphrase=$WPA_2G
auth_algs=1
country_code=US
ctrl_interface=/var/run/hostapd
HOSTAPD_EOF
  setsid hostapd /var/hostapd-wl0.1.conf > /tmp/hostapd-wl0.1.log 2>&1 &
  sleep 1
  if ! ps | grep -q '[h]ostapd'; then
    echo "WARNING: hostapd failed to start on wl0.1; 2.4GHz AP may be open. Check /tmp/hostapd-wl0.1.log"
  fi
fi

echo
echo "== 6/6  Sharing the internet"
iptables -F
iptables -t nat -F
echo 1 > /proc/sys/net/ipv4/ip_forward
iptables -t nat -A POSTROUTING -o wl0 -j MASQUERADE
iptables -A FORWARD -i br0 -o wl0 -j ACCEPT
iptables -A FORWARD -i wl0 -o br0 -m state --state RELATED,ESTABLISHED -j ACCEPT

SHOWCH=$(wl -i wl1 status | sed -n 's/.*Primary channel: *\([0-9]*\).*/\1/p')
echo
echo "================================================"
echo " READY"
echo "  Extending : $SSID  (uplink address $UP_IP)"
echo "  5 GHz WiFi: $SSID_5G  (channel ${SHOWCH:-$CH}, SGI enabled)"
echo "  2.4G WiFi : $SSID_2G  (virtual wl0.1, SGI enabled)"
echo "  Addresses : $LAN.100 to $LAN.200, router $LAN.1"
echo "  Internet  : $INTERNET"
if [ -n "$WPA_2G" ]; then
  wpa2g_status="secured (WPA2)"
else
  wpa2g_status="open"
fi
if [ "$AP_5G_ON" = "1" ]; then
  wpa5g_status="open"
else
  wpa5g_status="off"
fi
echo "  WARNING: 2.4GHz AP ($SSID_2G) is $wpa2g_status. 5GHz AP ($SSID_5G) is $wpa5g_status."
echo "================================================"
