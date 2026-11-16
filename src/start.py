from telegram import Update
from telegram.ext import ContextTypes

import config
from database import Database
from lib.helpers import is_admin
from lib.ui import BRAND, LINE, esc, tip, bar, days_left, safe_edit
from src.menus import get_main_menu

db = Database(config.DB_PATH)


def plan_line(user_id: int) -> str:
    if is_admin(user_id):
        return "👑 Plan: <b>Administrador</b> · sin límites"
    used = db.count_user_accounts(user_id)
    if db.is_reseller_active(user_id):
        r = db.get_reseller(user_id)
        d = max(days_left(r['expires_at']), 0)
        return (f"⭐ Plan: <b>Premium</b> · vence en {d} días\n"
                f"📦 Cuentas: {bar(used, r['max_accounts'], 8)} {used}/{r['max_accounts']}")
    return f"🆓 Plan: <b>Gratis</b> · 📦 Cuentas: {used}/1"


def home_text(user) -> str:
    server = db.get_all_servers()
    ready = bool(server) and (bool(server[0].get('pubkey')) or bool(db.get_config('wg_pubkey')))
    status = "🟢 Servicio en línea" if ready else "🟡 Servicio en configuración"
    return (
        f"🚀 <b>{esc(BRAND.upper())}</b>\n"
        f"<i>Internet libre, rápido y seguro</i>\n"
        f"{LINE}\n"
        f"👋 Hola, <b>{esc(user.first_name or 'amigo')}</b>\n\n"
        f"{status}\n"
        f"{plan_line(user.id)}\n"
        f"{tip('Elegí un protocolo abajo y creá tu cuenta en segundos.')}"
    )


async def send_home(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    user = update.effective_user
    kb = get_main_menu(is_admin(user.id))
    if edit and update.callback_query:
        await safe_edit(update.callback_query, home_text(user), kb)
    else:
        await update.effective_message.reply_text(home_text(user), parse_mode='HTML', reply_markup=kb,
                                                  disable_web_page_preview=True)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not db.is_public_mode() and not is_admin(user.id) and not db.is_premium(user.id):
        await update.message.reply_text(config.PRIVATE_MESSAGE, parse_mode='HTML')
        return
    await send_home(update, context)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✖️ Operación cancelada.")
    await send_home(update, context)
