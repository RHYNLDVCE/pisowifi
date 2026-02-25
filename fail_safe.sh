#!/bin/bash

# 1. Flush the IPSet (Removes all authorized MACs instantly)
# If the set doesn't exist, ignore the error
ipset flush authorized_users 2>/dev/null

# 2. Kill all active connections (Stop videos/games immediately)
conntrack -F 2>/dev/null

# 3. (Optional) Turn off Coin Slot Relay (GPIO 5 on Orange Pi)
# We use 'gpio' command if available, or sysfs
# Adjust '5' to your specific pin mapping if needed
gpio write 5 0 2>/dev/null

echo "🔒 FAIL-SAFE TRIGGERED: Internet blocked & Sessions killed."