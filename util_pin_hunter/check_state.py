import wiringpi
import time

PIN = 3  # Your Coin Pin

wiringpi.wiringPiSetupPhys()
wiringpi.pinMode(PIN, 0)      # Input
wiringpi.pullUpDnControl(PIN, 2) # Pull Up

print(f"Checking PIN {PIN}...")
try:
    while True:
        state = wiringpi.digitalRead(PIN)
        if state == 0:
            print("State: 0 (LOW) - ACTIVE/GROUNDED [Coin Detected]")
        else:
            print("State: 1 (HIGH) - IDLE [Waiting]")
        time.sleep(0.5)
except KeyboardInterrupt:
    pass