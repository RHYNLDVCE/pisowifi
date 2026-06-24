#!/bin/bash

LEASE_FILE="/var/lib/misc/dnsmasq.leases"

EXCLUDED_HOSTS_REGEX="EAP|Archer|MeshLink|Wavelink|TP-Link"

awk -v regex="$EXCLUDED_HOSTS_REGEX" '
{
    ip=$3
    hostname=$4

    if (hostname !~ regex)
        print ip
}
' "$LEASE_FILE" | while read -r ip; do

    echo "Checking $ip"

    # HTTP
    if curl -m 3 -s -I "http://$ip" >/dev/null 2>&1; then
        title=$(curl -m 3 -s "http://$ip" | \
            grep -i -o '<title>.*</title>' | head -n1)

        echo "[HTTP] $ip $title"
    fi

    # HTTPS
    if curl -k -m 3 -s -I "https://$ip" >/dev/null 2>&1; then
        title=$(curl -k -m 3 -s "https://$ip" | \
            grep -i -o '<title>.*</title>' | head -n1)

        echo "[HTTPS] $ip $title"
    fi

done
