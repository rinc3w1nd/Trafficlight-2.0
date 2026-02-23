#!/bin/bash
# Quick launcher for manual testing. In production, use:
#   sudo systemctl start traffic
exec python3 "$(dirname "$0")/traffic.py"
