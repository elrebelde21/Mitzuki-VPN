import logging

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

import config
from database import Database
from lib.ssh_accounts_manager import SSHAccountsManager
from lib.wireguard_manager import WireGuardManager
from lib.ui import header, kv, b, fmt_date, tip, bg, days_left

from src.system import system_command
from src.speedtest import speedtest_command
from src.start import start_command, cancel_command
from src.public import create_conv
from src.wireguard import wg_conv
from src.router import button_handler
from src.premium import premium_conv, premium_command, unpremium_command, plan_command, id_command

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('paramiko').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

db = Database(config.DB_PATH)
ssh_accounts = SSHAccountsManager(db)
wireguard = WireGuardManager(db)


async def _notify(context, telegram_id: int, text: str):
    if not telegram_id:
        return
    try:
        await context.bot.send_message(telegram_id, text, parse_mode='HTML')
    except Exception:
        pass


async def check_expired_users(context: ContextTypes.DEFAULT_TYPE):
    """Cada 5 min: avisa a quien vence en <24h y borra del servidor las cuentas vencidas."""
    # Aviso previo (una sola vez por cuenta)
    for u in db.get_all_users():
        try:
            if days_left(u['expires_at']) == 0 and not db.get_config(f"warned_{u['id']}"):
                db.set_config(f"warned_{u['id']}", '1')
                await _notify(context, u.get('telegram_id'), "\n".join([
                    header('⏰', 'Tu cuenta vence pronto'),
                    kv("👤", "Cuenta", b(u['username'])),
                    kv("📅", "Vence", b(fmt_date(u['expires_at']))),
                    tip(f"Para renovarla escribile a {config.OWNER_CONTACT}."),
                ]))
        except Exception as e:
            logger.warning(f"aviso de vencimiento: {e}")

    expired = db.get_expired_users()
    wg_servers = set()
    for user in expired:
        try:
            db.delete_user_by_id(user['id'])
            if user.get('conn_type') == 'wireguard':
                if user.get('server_id'):
                    wg_servers.add(user['server_id'])
            elif user.get('username') and user.get('server_id'):
                await bg(ssh_accounts.delete_user, user['server_id'], user['username'])
            db.add_log('DELETE_EXPIRED', f"Cuenta {user.get('username')} vencida", 0)
            await _notify(context, user.get('telegram_id'), "\n".join([
                header('🔴', 'Tu cuenta venció'),
                kv("👤", "Cuenta", b(user['username'])),
                tip("Podés crear otra desde /start o pedir una renovación."),
            ]))
        except Exception as e:
            logger.warning(f"Error eliminando {user.get('username')}: {e}")
    for sid in wg_servers:
        try:
            await bg(wireguard.rebuild, sid)
        except Exception as e:
            logger.warning(f"Error rebuild WG server {sid}: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error no controlado", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("⚠️ Ocurrió un error inesperado. Probá de nuevo con /start.")
        except Exception:
            pass


async def post_init(app: Application):
    db.ensure_default_server()
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 Menú principal"),
        BotCommand("plan", "⭐ Ver mi plan"),
        BotCommand("id", "🆔 Ver mi ID de Telegram"),
        BotCommand("cancel", "✖️ Cancelar lo que estoy haciendo"),
    ])


def main():
    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    # Cada conversación en su propio grupo: si el usuario salta de una a otra, la vieja
    # se cierra sola y la nueva arranca al primer toque.
    app.add_handler(create_conv, group=0)
    app.add_handler(wg_conv, group=1)
    app.add_handler(premium_conv, group=2)

    # Comandos y router de botones (último grupo)
    g = 10
    app.add_handler(CommandHandler("start", start_command), group=g)
    app.add_handler(CommandHandler("cancel", cancel_command), group=g)
    app.add_handler(CommandHandler("system", system_command), group=g)
    app.add_handler(CommandHandler("speedtest", speedtest_command), group=g)
    app.add_handler(CommandHandler("premium", premium_command), group=g)
    app.add_handler(CommandHandler("unpremium", unpremium_command), group=g)
    app.add_handler(CommandHandler("plan", plan_command), group=g)
    app.add_handler(CommandHandler("id", id_command), group=g)
    app.add_handler(CallbackQueryHandler(button_handler), group=g)

    app.add_error_handler(error_handler)
    app.job_queue.run_repeating(check_expired_users, interval=300, first=15)

    print(f"🤖 {config.BOT_NAME} iniciado")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
