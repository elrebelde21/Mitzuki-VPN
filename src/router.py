"""
src/router.py  —  Router único de botones (corre en el último grupo de handlers).
"""
from telegram import Update
from telegram.ext import ContextTypes

from src.admin import button_handler_admin
from src.public import button_handler_public
from src.flow import is_conv_callback

ADMIN_PREFIXES = ('admin_', 'del_user_', 'vaydns_', 'confirm_', 'slip_uninstall_')


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data or ''
    if is_conv_callback(data):
        return  # lo atiende su conversación
    if data.startswith(ADMIN_PREFIXES) or data == 'noop':
        return await button_handler_admin(update, context)
    return await button_handler_public(update, context)
