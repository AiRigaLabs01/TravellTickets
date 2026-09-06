import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
# Do not load operator credentials or start real external integrations in tests.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
for name in ("TRAVELPAYOUTS_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ADMIN_PASSWORD_HASH", "SESSION_SECRET"):
    os.environ[name] = ""
