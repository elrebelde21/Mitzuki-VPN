import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

import config
from database import Database
from lib.ssh_accounts_manager import SSHAccountsManager
from lib.wireguard_manager import WireGuardManager

from src.system import system_command
from src.speedtest import speedtest_command
from src.start import start_command
from src.public import button_handler_public, create_conv
from src.wireguard import wg_conv
from src.admin import (
    button_handler_admin,
    admin_create_conv
)
from src.premium import (
    premium_conv,
    premium_command,
    unpremium_command,
    plan_command,
    id_command,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database(config.DB_PATH)
ssh_accounts = SSHAccountsManager(db)
wireguard = WireGuardManager(db)


async def button_handler(update: Update, context):
    """Router de botones: primero admin, luego público"""
    query = update.callback_query
    data = query.data

    # Botones que van a ADMIN
    if (data.startswith('admin_') or
        data.startswith('del_user_') or
        data.startswith('premium_') or
        data.startswith('vaydns_') or
        data.startswith('confirm_') or
        data == 'cancel_action'):
        return await button_handler_admin(update, context)

    # Todo lo demás → PÚBLICO
    return await button_handler_public(update, context)


async def check_expired_users(context):
    """Borra del servidor las cuentas SSH vencidas y las desactiva en la DB."""
    expired = db.get_expired_users()
    if not expired:
        return
    wg_servers = set()
    for user in expired:
        try:
            if user.get('conn_type') == 'wireguard':
                db.delete_user_by_id(user['id'])
                if user.get('server_id'):
                    wg_servers.add(user['server_id'])
            else:
                if user.get('username') and user.get('server_id'):
                    ssh_accounts.delete_user(user['server_id'], user['username'])
                db.delete_user_by_id(user['id'])
            db.add_log('DELETE_EXPIRED', f"Cuenta {user.get('username')} expirada", 0)
            print(f"Cuenta {user.get('username')} eliminada (expirada)")
        except Exception as e:
            print(f"Error eliminando {user.get('username')}: {e}")
    # Reconstruir WireGuard una vez por servidor afectado (saca los peers vencidos)
    for sid in wg_servers:
        try:
            wireguard.rebuild(sid)
        except Exception as e:
            print(f"Error rebuild WG server {sid}: {e}")


def main():
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("system", system_command))
    app.add_handler(CommandHandler("speedtest", speedtest_command))

    # Comandos premium / planes
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("unpremium", unpremium_command))
    app.add_handler(CommandHandler("plan", plan_command))
    app.add_handler(CommandHandler("id", id_command))

    # Conversaciones
    app.add_handler(premium_conv)
    app.add_handler(admin_create_conv)
    app.add_handler(create_conv)
    app.add_handler(wg_conv)

    # Botones
    app.add_handler(CallbackQueryHandler(button_handler))

    # Job cada 5 minutos: limpiar cuentas vencidas
    app.job_queue.run_repeating(check_expired_users, interval=300, first=10)

    print("🤖 Bot VPN Pro iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()