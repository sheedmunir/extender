#!/bin/sh
# login.cgi - verify admin + password, set session cookie (5-min sliding, browser-close)
export PATH=$PATH:/fhrom/bin:/usr/sbin:/sbin:/bin
umask 077

# find passwd file (web root parent) or test override
if [ -n "$PASSWD_FILE" ]; then
  PASSWD="$PASSWD_FILE"
else
  DIR=$(cd "$(dirname "$0")/../.." && pwd)
  PASSWD="$DIR/passwd"
fi

# Login failure lockout: 3 failed attempts -> 1-minute lockout
FAIL_FILE="/tmp/ext_login_failures"
NOW=$(date +%s)
FAILURES=0
LOCKOUT_UNTIL=0
if [ -f "$FAIL_FILE" ]; then
  FAILURES=$(cut -d'|' -f1 "$FAIL_FILE" 2>/dev/null | tr -d ' ')
  LOCKOUT_UNTIL=$(cut -d'|' -f2 "$FAIL_FILE" 2>/dev/null | tr -d ' ')
  case "$FAILURES" in ''|*[!0-9]*) FAILURES=0;; esac
  case "$LOCKOUT_UNTIL" in ''|*[!0-9]*) LOCKOUT_UNTIL=0;; esac
fi
# Reset counter once lockout has expired
if [ "$LOCKOUT_UNTIL" -gt 0 ] && [ "$LOCKOUT_UNTIL" -le "$NOW" ] 2>/dev/null; then
  FAILURES=0
  LOCKOUT_UNTIL=0
fi
# Enforce lockout
if [ "$LOCKOUT_UNTIL" -gt "$NOW" ] 2>/dev/null; then
  REMAINING=$((LOCKOUT_UNTIL - NOW))
  echo "Content-Type: text/plain"
  echo "Status: 429 Too Many Requests"
  echo ""
  echo "Too many failed attempts. Try again in ${REMAINING}s."
  exit 0
fi

# Simple decode: python3 locally for tests, httpd -d on router (for %XX / + in passwords)
dec() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "$1" | python3 -c 'import sys,urllib.parse; sys.stdout.write(urllib.parse.unquote_plus(sys.stdin.read()))'
  elif command -v httpd >/dev/null 2>&1; then
    httpd -d "$1" 2>/dev/null || printf '%s' "$1"
  else
    printf '%s' "$1"
  fi
}

# Read POST body (Content-Length honored by httpd; test uses pipe)
BODY=$(cat)
U=$(printf '%s' "$BODY" | tr '&' '\n' | grep '^username=' | head -n1 | cut -d= -f2-)
P=$(printf '%s' "$BODY" | tr '&' '\n' | grep '^password=' | head -n1 | cut -d= -f2-)
U=$(dec "$U")
P=$(dec "$P")

OK=0
if [ "$U" = "admin" ] && [ -f "$PASSWD" ]; then
  STORED=$(cut -d: -f2 "$PASSWD" | tr -d '\r\n')
  CALC=$(printf '%s' "admin:Extender:$P" | md5sum | awk '{print $1}')
  [ "$CALC" = "$STORED" ] && OK=1
fi

echo "Content-Type: text/plain"
if [ "$OK" = "1" ]; then
  TOK=$(head -c 32 /dev/urandom 2>/dev/null | md5sum | awk '{print $1}')
  [ -n "$TOK" ] || TOK=$(date +%s | md5sum | awk '{print $1}')
  NOW=$(date +%s)
  printf '%s\n' "$NOW" > "/tmp/ext_sess_$TOK"
  chmod 600 "/tmp/ext_sess_$TOK" 2>/dev/null
  echo "Set-Cookie: session=$TOK; Path=/; HttpOnly; SameSite=Strict"
  echo ""
  echo "OK"
  # Reset failure counter on successful login
  printf '0|0\n' > "$FAIL_FILE"
  chmod 600 "$FAIL_FILE" 2>/dev/null
else
  FAILURES=$((FAILURES + 1))
  if [ "$FAILURES" -ge 3 ]; then
    LOCKOUT_UNTIL=$((NOW + 60))
  fi
  printf '%s|%s\n' "$FAILURES" "$LOCKOUT_UNTIL" > "$FAIL_FILE"
  chmod 600 "$FAIL_FILE" 2>/dev/null
  echo "Status: 401 Unauthorized"
  echo ""
  echo "Wrong username or password."
fi
