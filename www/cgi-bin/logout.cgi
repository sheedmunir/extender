#!/bin/sh
# logout.cgi - clear session file and cookie
export PATH=$PATH:/fhrom/bin:/usr/sbin:/sbin:/bin
umask 077
COOK=$(printf '%s' "$HTTP_COOKIE" | tr ';' '\n' | sed 's/^ *//' | grep '^session=' | cut -d= -f2 | tr -d ' \r')
[ -n "$COOK" ] && rm -f "/tmp/ext_sess_$COOK"
echo "Content-Type: text/plain"
echo "Set-Cookie: session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
echo ""
echo "Logged out."
