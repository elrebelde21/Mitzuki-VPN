import html
import config
from database import Database

db = Database(config.DB_PATH)


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def escape_html(text: str) -> str:
    return html.escape(str(text))


def can_create_account(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    if db.is_public_mode():
        return True
    if db.is_premium(user_id):
        return True
    return False