#!/bin/bash

set -e

gunicorn --bind 0.0.0.0:${PORT:-10000} app:app &
exec python3 bot.py
