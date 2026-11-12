#!/bin/sh
# start.sh - start the Extender web page (BusyBox httpd) on the gateway IP.
# Run AFTER extender.sh has finished. Usage: sh start.sh
export PATH=$PATH:/fhrom/bin:/usr/sbin:/sbin:/bin
umask 077

DIR=$(cd "$(dirname "$0")" && pwd)
WWW="$DIR/www"
PORT=80
REALM=Extender
CONF="$DIR/httpd.conf"
HASHFILE="$DIR/passwd"
PIDFILE="$DIR/httpd.pid"

[ -d "$WWW" ] || { echo "Missing $WWW (put index.html and cgi-bin/status.cgi there)"; exit 1; }

IP=$(ip -4 addr show br0 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1)
if [ -z "$IP" ]; then
  echo "br0 has no IP. Run extender.sh first."
  exit 1
fi

# First run: store admin:md5(admin:Extender:password) (custom login, not httpd Basic Auth)
if [ ! -s "$HASHFILE" ] || ! grep -q '^admin:' "$HASHFILE" 2>/dev/null; then
  echo "First run: set the PAGE password (not the WiFi password)."
  while :; do
    printf "Page password: "
    stty -echo 2>/dev/null; read -r P; stty echo 2>/dev/null; echo
    [ -n "$P" ] && break
    echo "Password cannot be empty."
  done
  HASH=$(printf '%s' "admin:Extender:$P" | md5sum | awk '{print $1}')
  printf 'admin:%s\n' "$HASH" > "$HASHFILE"
  chmod 600 "$HASHFILE"
  echo "Saved login hash (user: admin) to $HASHFILE"
fi

# No httpd Basic Auth anymore (custom login page). Write empty config so no auth lines load.
: > "$CONF"
chmod 600 "$CONF"
chmod +x "$WWW/cgi-bin/status.cgi"
chmod +x "$WWW/cgi-bin/login.cgi"
chmod +x "$WWW/cgi-bin/logout.cgi"
chmod +x "$WWW/cgi-bin/networks.cgi"
chmod +x "$WWW/cgi-bin/delete.cgi"
chmod +x "$WWW/cgi-bin/reconnect.cgi"
chmod +x "$WWW/cgi-bin/scan.cgi"
chmod +x "$WWW/cgi-bin/connect.cgi"
chmod +x "$WWW/cgi-bin/ping.cgi"
chmod +x "$WWW/cgi-bin/devices.cgi"
chmod +x "$WWW/cgi-bin/rename.cgi"
chmod +x "$WWW/cgi-bin/current.cgi"
chmod +x "$WWW/cgi-bin/hostname_mac.cgi"
chmod +x "$WWW/cgi-bin/wpa.cgi"

# Stop only our own previous instance
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  kill "$(cat "$PIDFILE")"
  sleep 1
fi

echo "Starting web page at http://$IP:$PORT (custom login page, user: admin)"
echo "Stop with: kill \$(cat $PIDFILE)"
if command -v nohup >/dev/null 2>&1; then
  nohup httpd -f -h "$WWW" -p "$IP:$PORT" -c "$CONF" >/dev/null 2>&1 &
else
  httpd -f -h "$WWW" -p "$IP:$PORT" -c "$CONF" >/dev/null 2>&1 &
fi
echo $! > "$PIDFILE"
