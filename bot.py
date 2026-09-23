import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from datetime import datetime

import config
from src.start import start_command
from src.public import button_handler_public, create_conv
from src.admin import (
    button_handler_admin,
    admin_create_conv
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


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
    expired = db.get_expired_slipstream_users()
    if not expired:
        return
    for user in expired:
        try:
            slipstream.delete_user(user['server_id'], user['username'])
            db.deactivate_slipstream_user(user['username'])
            db.add_log('DELETE_EXPIRED', f"Usuario {user['username']} expirado", 0)
            print(f"Usuario {user['username']} eliminado (expirado)")
        except Exception as e:
            print(f"Error eliminando {user['username']}: {e}")


def main():
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start", start_command))

    # Conversaciones
    app.add_handler(admin_create_conv)
    app.add_handler(create_conv)

    # Botones
    app.add_handler(CallbackQueryHandler(button_handler))

    # Job cada 5 minutos
    app.job_queue.run_repeating(check_expired_users, interval=300, first=10)

    print("🤖 Bot VPN Pro iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()