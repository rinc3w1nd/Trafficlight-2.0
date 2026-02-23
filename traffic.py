#!/usr/bin/env python3
"""Traffic light controller web application.

A Flask-based web interface for controlling a Raspberry Pi traffic light
with red, yellow, and green LEDs via gpiozero.
"""

import atexit
import logging
import os
from random import choice
from time import sleep

from flask import Flask, abort, render_template
from gpiozero import TrafficLights

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RED_PIN: int = int(os.environ.get("TRAFFIC_RED_PIN", "17"))
YELLOW_PIN: int = int(os.environ.get("TRAFFIC_YELLOW_PIN", "27"))
GREEN_PIN: int = int(os.environ.get("TRAFFIC_GREEN_PIN", "22"))
HOST: str = os.environ.get("TRAFFIC_HOST", "0.0.0.0")
PORT: int = int(os.environ.get("TRAFFIC_PORT", "80"))
BLINK_ON_TIME: float = float(os.environ.get("TRAFFIC_BLINK_ON", "0.25"))
BLINK_OFF_TIME: float = float(os.environ.get("TRAFFIC_BLINK_OFF", "0.25"))
PARTY_DEFAULT_ITERATIONS: int = int(os.environ.get("TRAFFIC_PARTY_ITERATIONS", "5"))
PARTY_SINGLE_ITERATIONS: int = 19
COUNTDOWN_STEP_DELAY: float = 1.0
LIGHT_ORDER: tuple[str, ...] = ("red", "yellow", "green")
VALID_COLORS: set[str] = set(LIGHT_ORDER)
VALID_ACTIONS: set[str] = {"on", "off", "toggle", "party"}
MAX_RAGER_ITERATIONS: int = 100

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("traffic")

# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------
traffic_lights = TrafficLights(red=RED_PIN, yellow=YELLOW_PIN, green=GREEN_PIN)
atexit.register(traffic_lights.close)
logger.info(
    "Traffic lights initialized: red=%d, yellow=%d, green=%d",
    RED_PIN, YELLOW_PIN, GREEN_PIN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_light_states() -> dict[str, dict[str, int | str]]:
    """Return current state of each light for template rendering."""
    states: dict[str, dict[str, int | str]] = {}
    for color in LIGHT_ORDER:
        led = getattr(traffic_lights, color)
        states[color] = {
            "pin": led.pin.number,
            "state": "on" if led.is_lit else "off",
        }
    return states


def blinky_blink(color: str) -> None:
    """Blink a single LED once, blocking until complete."""
    led = getattr(traffic_lights, color)
    led.blink(on_time=BLINK_ON_TIME, off_time=BLINK_OFF_TIME, n=1, background=False)


def count_down() -> None:
    """Flash each light in sequence: red, yellow, green."""
    traffic_lights.off()
    sleep(BLINK_ON_TIME)
    for color in LIGHT_ORDER:
        led = getattr(traffic_lights, color)
        led.on()
        sleep(COUNTDOWN_STEP_DELAY)
        led.off()


# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.route("/")
def main() -> str:
    """Render the main page showing current light states."""
    return render_template("main.html", pins=get_light_states())


@app.route("/toggle/<color>/<action>")
def toggle(color: str, action: str) -> str:
    """Control a single traffic light.

    Args:
        color: One of 'red', 'yellow', 'green'.
        action: One of 'on', 'off', 'toggle', 'party'.
    """
    if color not in VALID_COLORS:
        logger.warning("Invalid color requested: %s", color)
        abort(404, description=f"Unknown color: {color}")
    if action not in VALID_ACTIONS:
        logger.warning("Invalid action requested: %s", action)
        abort(404, description=f"Unknown action: {action}")

    led = getattr(traffic_lights, color)

    if action == "on":
        led.on()
        message = f"Turned {color} on."
    elif action == "off":
        led.off()
        message = f"Turned {color} off."
    elif action == "toggle":
        led.toggle()
        message = f"Toggled {color}."
    elif action == "party":
        for _ in range(PARTY_SINGLE_ITERATIONS):
            blinky_blink(color)
        message = "Partied hard."

    logger.info(message)
    return render_template("main.html", message=message, pins=get_light_states())


@app.route("/rager/")
@app.route("/rager/<iterations>")
def party_hard(iterations: str = "5") -> str:
    """Run a random blink party across all lights.

    Args:
        iterations: Number of random blinks (default 5, capped at 100).
    """
    try:
        num_iterations = min(int(iterations), MAX_RAGER_ITERATIONS)
        if num_iterations < 0:
            num_iterations = PARTY_DEFAULT_ITERATIONS
    except ValueError:
        logger.warning("Invalid iterations value: %r, using default", iterations)
        num_iterations = PARTY_DEFAULT_ITERATIONS

    count_down()
    sleep(COUNTDOWN_STEP_DELAY)

    colors = list(LIGHT_ORDER)
    for _ in range(num_iterations):
        blinky_blink(choice(colors))

    logger.info("Rager completed: %d iterations", num_iterations)
    return render_template("main.html", pins=get_light_states())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting traffic light server on %s:%d", HOST, PORT)
    app.run(host=HOST, port=PORT, debug=False)
