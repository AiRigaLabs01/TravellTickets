import os
from dotenv import load_dotenv

load_dotenv()

TRAVELPAYOUTS_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000")

DEBUG_MONITORING_MESSAGES = os.getenv("DEBUG_MONITORING_MESSAGES", "false").lower() in ("1", "true", "yes", "on")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./travelltickets.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

AVIASALES_BASE_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AVIASALES_SITE_BASE = "https://www.aviasales.ru"

YANDEX_TRAVEL_BASE = "https://travel.yandex.ru/avia/search/result/"
