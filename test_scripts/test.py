#!/usr/bin/env python3
"""Test script: run a traffic light sequence continuously.

Press Ctrl+C to stop. GPIO pins are cleaned up automatically by gpiozero.

Usage:
    python3 test.py
    GPIOZERO_PIN_FACTORY=mock python3 test.py  # Run without hardware
"""

from time import sleep

from gpiozero import TrafficLights

SEQUENCE: list[str] = ["red", "yellow", "green", "yellow"]
STEP_DURATION: float = 0.19

traffic_lights = TrafficLights(red=17, yellow=27, green=22)


def light_on(color: str) -> None:
    """Flash a single light briefly."""
    led = getattr(traffic_lights, color)
    led.on()
    sleep(STEP_DURATION)
    led.off()


def run_sequence(sequence: list[str]) -> None:
    """Run the light sequence in a loop until interrupted."""
    print("Starting traffic light sequence (Ctrl+C to stop)...")
    try:
        while True:
            for color in sequence:
                light_on(color)
    except KeyboardInterrupt:
        print("\nSequence stopped.")
    finally:
        traffic_lights.off()


if __name__ == "__main__":
    run_sequence(SEQUENCE)
