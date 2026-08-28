#!/usr/bin/env bash
# Generate a self-signed cert for first boot. Replace with ACME/public CA before real traffic.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
CN="${TLS_CN:-localhost}"
DAYS="${TLS_DAYS:-825}"

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$DIR/key.pem" \
  -out "$DIR/cert.pem" \
  -days "$DAYS" \
  -subj "/CN=${CN}"

chmod 600 "$DIR/key.pem"
echo "wrote $DIR/cert.pem and $DIR/key.pem (CN=${CN}, ${DAYS} days)"
echo "smoke: curl -k https://${CN}/health"
echo "SAN mismatch in browsers is expected; swap in Let's Encrypt / corporate certs for production."
