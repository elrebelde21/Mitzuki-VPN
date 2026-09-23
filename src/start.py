from telegram import Update
from telegram.ext import ContextTypes
from lib.helpers import is_admin, escape_html
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

    if total_servers > 0:
        status = "✅ Servidor Activo"
        server_info = f"\n🖥️ Servidor: {escape_html(servers[0]['name'])}\n🌐 IP: {escape_html(servers[0]['ip'])}"
    else:
        status = "⚠️ Sin servidor configurado"
        server_info = "\n\n💡 Usa /admin para instalar uno."

    welcome = f"""
✨ <b>¡Bienvenido al Cuba VPN!</b> {escape_html(user.first_name)} 🚀

━━━━━━━━━━━━━━━━━━━
📊 <b>Estado del Sistema</b>
━━━━━━━━━━━━━━━━━━━
📌 Servidores: {total_servers}
👥 Cuentas activas: {users}
📶 Estado: {status}
{server_info}
━━━━━━━━━━━━━━━━━━━

Selecciona una opción 👇
"""
    await update.message.reply_text(welcome, parse_mode='HTML', reply_markup=get_main_menu(is_admin_user))