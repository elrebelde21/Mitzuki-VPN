from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from lib.helpers import is_admin, escape_html
from lib.runtime import uptime_str
from src.menus import get_main_menu
from database import Database
import config

db = Database(config.DB_PATH)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin_user = is_admin(user.id)

    # --- MODO PRIVADO: bloqueo directo, sin botones ---
    if not db.is_public_mode():
        is_premium = db.is_premium(user.id)
        if not is_admin_user and not is_premium:
            await update.message.reply_text(
                config.PRIVATE_MESSAGE,
                parse_mode='HTML'
            )
            return

    # --- MODO PÚBLICO o Admin/Premium ---
    servers = db.get_all_servers()
    total_servers = len(servers)
    users = db.get_active_users_count()
    status = "✅ Servidor Activo" if total_servers > 0 else "⚠️ Sin servidor configurado"

    # Detalle del usuario
    my_accounts = db.count_user_accounts(user.id)
    user_line = f"👤 Tus cuentas: <b>{my_accounts}</b>"
    if db.is_reseller_active(user.id):
        r = db.get_reseller(user.id)
        try:
            plan_days = (datetime.fromisoformat(r['expires_at']) - datetime.now()).days
        except (ValueError, TypeError):
            plan_days = 0
        user_line += (f"\n⭐ Plan: {my_accounts}/{r['max_accounts']} cuentas · "
                      f"vence en {plan_days}d")

    welcome = f"""
✨ <b>¡Bienvenido al NETWORK VPN!</b> 🚀

Hello {escape_html(user.first_name)} 👋

━━━━━━━━━━━━━━━━━━━
📊 <b>Estado del Sistema</b>
━━━━━━━━━━━━━━━━━━━
📶 Estado: {status}
👥 Cuentas totales: {users}
{user_line}
⏱️ Uptime: <b>{uptime_str()}</b>
━━━━━━━━━━━━━━━━━━━

Selecciona una opción
"""
    await update.message.reply_text(welcome, parse_mode='HTML', reply_markup=get_main_menu(is_admin_user))