#!/bin/bash

# Azure startup script for Telegram bot
echo "🚀 Starting Telegram Bot Application..."

# Set environment variables (these should be set in Azure App Service Configuration)
export PYTHONPATH=/home/site/wwwroot
export FLASK_APP=app.py

# Start with gunicorn
echo "📡 Starting with Gunicorn..."
cd /home/site/wwwroot
gunicorn --bind 0.0.0.0:5000 --workers 1 --timeout 120 --preload app:app