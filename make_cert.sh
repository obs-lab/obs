#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CERT_DIR="${OBS_CERT_DIR:-certs}"
HOSTNAME_ARG="${1:-}"

echo ""
echo "OBS-LAB - local certificate"
echo ""

if [ -z "$HOSTNAME_ARG" ]; then
  if command -v hostname &>/dev/null; then
    HOSTNAME_ARG="$(hostname)"
  else
    HOSTNAME_ARG="localhost"
  fi
fi

LAN_IP=""
if command -v ipconfig &>/dev/null; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
fi
if [ -z "$LAN_IP" ] && command -v hostname &>/dev/null; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi

mkdir -p "$CERT_DIR"

if command -v mkcert &>/dev/null; then
  echo "Using mkcert. Browsers will trust this certificate with no warning."
  echo ""
  mkcert -install
  if [ -n "$LAN_IP" ]; then
    mkcert -cert-file "$CERT_DIR/obs.crt" -key-file "$CERT_DIR/obs.key" \
      "$HOSTNAME_ARG" localhost 127.0.0.1 ::1 "$LAN_IP"
  else
    mkcert -cert-file "$CERT_DIR/obs.crt" -key-file "$CERT_DIR/obs.key" \
      "$HOSTNAME_ARG" localhost 127.0.0.1 ::1
  fi
elif command -v openssl &>/dev/null; then
  echo "mkcert not found, falling back to openssl."
  echo "The certificate will be self signed: each browser must accept it once."
  echo ""
  SAN="DNS:$HOSTNAME_ARG,DNS:localhost,IP:127.0.0.1"
  if [ -n "$LAN_IP" ]; then
    SAN="$SAN,IP:$LAN_IP"
  fi
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout "$CERT_DIR/obs.key" -out "$CERT_DIR/obs.crt" \
    -subj "/CN=$HOSTNAME_ARG" -addext "subjectAltName=$SAN"
else
  echo "ERROR: neither mkcert nor openssl was found."
  echo "   Install mkcert (recommended) or openssl and run this script again."
  exit 1
fi

chmod 600 "$CERT_DIR/obs.key"

echo ""
echo "Certificate written to $SCRIPT_DIR/$CERT_DIR"
echo ""
echo "Start OBS over https with:"
echo "   export OBS_SSL_CERT=\"$SCRIPT_DIR/$CERT_DIR/obs.crt\""
echo "   export OBS_SSL_KEY=\"$SCRIPT_DIR/$CERT_DIR/obs.key\""
echo "   ./start_prod.sh"
echo ""
if [ -n "$LAN_IP" ]; then
  echo "Then reach it at https://$LAN_IP:8000"
else
  echo "Then reach it at https://$HOSTNAME_ARG:8000"
fi
echo ""
