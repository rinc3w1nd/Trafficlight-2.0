#!/usr/bin/env python3
"""Traffic light controller web application.

A Flask-based web interface for controlling a Raspberry Pi traffic light
with red, yellow, and green LEDs via gpiozero.
"""

import atexit
import logging
import os
import threading
from datetime import datetime, timedelta
from random import choice
from time import sleep

from flask import Flask, abort, redirect, render_template, request, url_for
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

# Closing countdown configuration
KEYHOLDER_PASSWORD: str = os.environ.get("TRAFFIC_PASSWORD", "changeme")
CLOSING_WARN_MINUTES: int = 30
CLOSING_FLASH_MINUTES: int = 10
CLOSING_HOLD_MINUTES: int = 30
FLASH_SPEED_START: float = 1.0
FLASH_SPEED_END: float = 0.1

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
# Closing countdown state
# ---------------------------------------------------------------------------
closing_state: dict = {
    "active": False,
    "close_time": None,
    "phase": "normal",
    "thread": None,
    "cancel_event": None,
}


def get_closing_info() -> dict:
    """Return a template-friendly dict describing the current closing state."""
    if not closing_state["active"]:
        return {"active": False, "phase": "normal", "minutes_remaining": None, "close_time_str": None}

    now = datetime.now()
    close_time = closing_state["close_time"]
    remaining = (close_time - now).total_seconds() / 60.0
    return {
        "active": True,
        "phase": closing_state["phase"],
        "minutes_remaining": max(0, int(remaining)),
        "close_time_str": close_time.strftime("%-I:%M %p"),
    }


def _run_closing_sequence() -> None:
    """Background thread that drives the closing countdown phases."""
    cancel = closing_state["cancel_event"]
    close_time = closing_state["close_time"]
    warn_start = close_time - timedelta(minutes=CLOSING_WARN_MINUTES)
    flash_start = close_time - timedelta(minutes=CLOSING_FLASH_MINUTES)
    hold_end = close_time + timedelta(minutes=CLOSING_HOLD_MINUTES)

    def _cancelled() -> bool:
        return cancel.is_set()

    def _sleep_until(target: datetime) -> bool:
        """Sleep in 0.5s increments until target or cancellation. Returns True if cancelled."""
        while datetime.now() < target:
            if _cancelled():
                return True
            sleep(0.5)
        return False

    try:
        # Wait until warning phase begins
        if _sleep_until(warn_start):
            return

        # --- Warning phase: solid yellow ---
        closing_state["phase"] = "warning"
        logger.info("Closing sequence: warning phase (solid yellow)")
        traffic_lights.green.off()
        traffic_lights.red.off()
        traffic_lights.yellow.on()

        if _sleep_until(flash_start):
            return

        # --- Flashing phase: red blink, speed ramps up ---
        closing_state["phase"] = "flashing"
        logger.info("Closing sequence: flashing phase (red blink)")
        traffic_lights.yellow.off()

        total_flash_seconds = CLOSING_FLASH_MINUTES * 60.0
        while datetime.now() < close_time:
            if _cancelled():
                return
            remaining = (close_time - datetime.now()).total_seconds()
            progress = 1.0 - (remaining / total_flash_seconds) if total_flash_seconds > 0 else 1.0
            progress = max(0.0, min(1.0, progress))
            interval = FLASH_SPEED_START + (FLASH_SPEED_END - FLASH_SPEED_START) * progress
            half = interval / 2.0
            traffic_lights.red.on()
            sleep(half)
            if _cancelled():
                return
            traffic_lights.red.off()
            sleep(half)

        # --- Closed phase: solid red ---
        closing_state["phase"] = "closed"
        logger.info("Closing sequence: closed phase (solid red)")
        traffic_lights.red.on()

        if _sleep_until(hold_end):
            return

        # --- Off phase: all off, sequence ends ---
        closing_state["phase"] = "off"
        logger.info("Closing sequence: off phase (all lights off)")
        traffic_lights.off()

    finally:
        if _cancelled():
            logger.info("Closing sequence cancelled")
        closing_state["active"] = False
        closing_state["phase"] = "normal"
        closing_state["close_time"] = None
        closing_state["thread"] = None
        closing_state["cancel_event"] = None


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
    return render_template(
        "main.html",
        pins=get_light_states(),
        closing=get_closing_info(),
        message=request.args.get("msg"),
    )


@app.route("/toggle/<color>/<action>")
def toggle(color: str, action: str) -> str:
    """Control a single traffic light.

    Args:
        color: One of 'red', 'yellow', 'green'.
        action: One of 'on', 'off', 'toggle', 'party'.
    """
    if closing_state["active"]:
        abort(403, description="Closing in progress — lights are locked.")
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
    if closing_state["active"]:
        abort(403, description="Closing in progress — lights are locked.")
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


@app.route("/close", methods=["POST"])
def schedule_close() -> str:
    """Schedule a closing countdown. Requires keyholder password and minutes."""
    password = request.form.get("password", "")
    minutes_str = request.form.get("minutes", "")

    if password != KEYHOLDER_PASSWORD:
        return redirect(url_for("main", msg="Invalid password."))

    try:
        minutes = int(minutes_str)
        if minutes < 1:
            raise ValueError
    except (ValueError, TypeError):
        return redirect(url_for("main", msg="Invalid number of minutes."))

    if closing_state["active"]:
        return redirect(url_for("main", msg="Closing already in progress."))

    close_time = datetime.now() + timedelta(minutes=minutes)

    # If the requested time is shorter than the warning phase, start warning immediately
    closing_state["close_time"] = close_time
    closing_state["active"] = True
    closing_state["phase"] = "normal"
    closing_state["cancel_event"] = threading.Event()

    thread = threading.Thread(target=_run_closing_sequence, daemon=True)
    closing_state["thread"] = thread
    thread.start()

    logger.info("Closing scheduled in %d minutes (at %s)", minutes, close_time.strftime("%-I:%M %p"))
    return redirect(url_for("main"))


@app.route("/cancel-close", methods=["POST"])
def cancel_close() -> str:
    """Cancel an active closing countdown. Requires keyholder password."""
    password = request.form.get("password", "")

    if password != KEYHOLDER_PASSWORD:
        return redirect(url_for("main", msg="Invalid password."))

    if not closing_state["active"]:
        return redirect(url_for("main", msg="No closing in progress."))

    cancel_event = closing_state["cancel_event"]
    thread = closing_state["thread"]
    if cancel_event:
        cancel_event.set()
    if thread:
        thread.join(timeout=5)

    # Reset lights to off after cancellation
    traffic_lights.off()
    logger.info("Closing cancelled by keyholder")
    return redirect(url_for("main"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting traffic light server on %s:%d", HOST, PORT)
    app.run(host=HOST, port=PORT, debug=False)
