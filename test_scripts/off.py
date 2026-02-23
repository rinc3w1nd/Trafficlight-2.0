#!/usr/bin/env python3
"""Turn all traffic lights off.

Usage:
    python3 off.py
    GPIOZERO_PIN_FACTORY=mock python3 off.py  # Run without hardware
"""

from gpiozero import TrafficLights

traffic_lights = TrafficLights(red=17, yellow=27, green=22)
traffic_lights.off()
traffic_lights.close()
print("All lights turned off.")
