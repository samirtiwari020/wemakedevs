"""
ClimateShield Telegram Polling Runner
Runs the Telegram bot in background polling mode for local live testing.
"""

import sys
import os
import asyncio

# Setup path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.telegram_bot import get_citizen_telegram_bot

async def main():
    bot = get_citizen_telegram_bot()
    if not bot.is_configured:
        print("❌ Telegram Bot Token is not configured. Please check .env file.")
        return

    print("==================================================")
    print("🤖 CLIMATESHIELD TELEGRAM BOT POLLER RUNNING")
    print("==================================================")
    print("Bot Username: @climate_shield_bot")
    print("Listening for citizen messages, GPS locations, and commands...")
    print("Press Ctrl+C to stop.")
    print("--------------------------------------------------")
    
    await bot.start_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping bot...")
