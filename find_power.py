import subprocess
import time

# Common pins used for Relays/Power on Custom Boards (wPi numbers)
# 2 = Pin 7 (Coin Signal usually)
# The others are likely the Power Trigger
POSSIBLE_PINS = ["0", "1", "3", "4", "5", "6", "8", "9", "10", "13", "15", "16"]

print("--- POWER PIN HUNTER ---")
print("Watch your Coin Slot. Tell me which Pin makes it LIGHT UP.")
print("------------------------------------------------")

for pin in POSSIBLE_PINS:
    print(f"Testing wPi PIN: {pin} ...")

    # Set mode to Output
    subprocess.run(["gpio", "mode", pin, "out"])

    # Turn ON (Try High)
    subprocess.run(["gpio", "write", pin, "1"])
    time.sleep(2) # Wait 2 seconds

    # Turn OFF
    subprocess.run(["gpio", "write", pin, "0"])
    time.sleep(0.5)

print("--- DONE ---")
