import sys

sys.path.insert(0, "backend")

from app.ai_interpreter import interpret_with_ai
from app.config import get_settings

settings = get_settings()

try:
    plan = interpret_with_ai(
        "Which product generated the highest revenue?", settings
    )
    print("SUCCESS with interpret_with_ai! Plan:", plan)
except Exception:
    import traceback

    traceback.print_exc()
