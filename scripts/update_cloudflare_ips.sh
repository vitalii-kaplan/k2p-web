#!/usr/bin/env bash
set -euo pipefail

out="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/nginx/cloudflare_ips.conf"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

{
  echo "# Generated from Cloudflare IPs list"
  curl -fsSL https://www.cloudflare.com/ips-v4 | sed 's|^|set_real_ip_from |; s|$|;|'
  curl -fsSL https://www.cloudflare.com/ips-v6 | sed 's|^|set_real_ip_from |; s|$|;|'
} > "$tmp"

mv "$tmp" "$out"
echo "Wrote $out"
