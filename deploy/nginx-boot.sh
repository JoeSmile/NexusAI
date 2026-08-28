#!/bin/sh
# Fail fast with a readable reason instead of nginx crash-looping on missing TLS/SPA.
set -eu

if [ ! -f /etc/nginx/ssl/cert.pem ] || [ ! -f /etc/nginx/ssl/key.pem ]; then
  echo "nginx: missing TLS files under /etc/nginx/ssl (cert.pem + key.pem)." >&2
  echo "On the host: bash deploy/ssl/gen-self-signed.sh  (or install ACME certs)." >&2
  exit 1
fi

if [ ! -f /usr/share/nginx/html/index.html ]; then
  echo "nginx: frontend/dist is empty (Docker created a blank bind-mount)." >&2
  echo "Build: Node >=20.19 + pnpm; then: rsync -a --delete frontend/dist/ <deploy-host>:/path/frontend/dist/" >&2
  echo "Do not scp the dist directory itself (that nests dist/dist)." >&2
  exit 1
fi

exec nginx -g "daemon off;"
