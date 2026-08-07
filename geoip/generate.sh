#!/bin/bash
set -euo pipefail

CHNROUTES2_URL="https://raw.githubusercontent.com/misakaio/chnroutes2/master/chnroutes.txt"
CHNROUTES2_IPV6_URL="https://raw.githubusercontent.com/misakaio/chnroutes2/master/chnroutes6.txt"

mkdir -p dist

echo "Fetching CN IPv4 list..."
curl -sSfL "$CHNROUTES2_URL" | grep -v '^#' | grep -v '^$' > dist/cn-ipv4.txt

echo "Fetching CN IPv6 list..."
curl -sSfL "$CHNROUTES2_IPV6_URL" | grep -v '^#' | grep -v '^$' > dist/cn-ipv6.txt

echo "Generating Clash ruleset..."
{
  sed 's/^/IP-CIDR,/' dist/cn-ipv4.txt
  sed 's/^/IP-CIDR6,/' dist/cn-ipv6.txt
} > dist/clash-ruleset.list

echo "Generating ipset rules (IPv4)..."
{
  echo "create chnroute hash:net family inet hashsize 4096 maxelem 131072"
  sed 's/^/add chnroute /' dist/cn-ipv4.txt
} > dist/chnroute.ipset

echo "Generating ipset rules (IPv6)..."
{
  echo "create chnroute6 hash:net family inet6 hashsize 4096 maxelem 65536"
  sed 's/^/add chnroute6 /' dist/cn-ipv6.txt
} > dist/chnroute6.ipset

echo ""
echo "Done. Output files:"
wc -l dist/*.txt dist/*.list dist/*.ipset
