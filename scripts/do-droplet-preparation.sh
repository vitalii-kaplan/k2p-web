#!/usr/bin/env bash
set -euo pipefail

apt-get update
apt-get -y upgrade
apt-get -y install ca-certificates curl git

# Docker official repo
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

. /etc/os-release
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify
docker version
docker compose version