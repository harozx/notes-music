#!/usr/bin/env bash
pkill -f "python3? app.py"; pkill -f "cloudflared.*tunnel.*run"; echo stopped
