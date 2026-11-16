"""
src/flow.py  —  Piezas comunes de las conversaciones (pasos de creación).

Cada conversación vive en su propio grupo de handlers. Sus fallbacks solo
CIERRAN la conversación en silencio: la respuesta visible la da el router
(grupo final), así nunca se responde dos veces ni queda un paso "colgado"
comiéndose lo que el usuario escribe después.
"""
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler

# Callbacks que maneja alguna conversación (el router los ignora)
CONV_EXACT = {'create_account', 'create_wg', 'admin_premium', 'slip_pass_random', 'pcancel'}
CONV_PREFIXES = ('sd_', 'sc_', 'wd_', 'pacc_', 'pcon_', 'pday_', 'ppln_')


def is_conv_callback(data: str) -> bool:
    return data in CONV_EXACT or data.startswith(CONV_PREFIXES)

FLOW_TIMEOUT = 15 * 60


async def end_silent(update, context):
    for k in [k for k in context.user_data if k.startswith('f_')]:
        context.user_data.pop(k, None)
    return ConversationHandler.END


def fallbacks(own_prefixes=()):
    """Cierra la conversación ante /start, /cancel, ✖️ Cancelar o cualquier otro botón."""
    own = '|'.join(own_prefixes)
    other_buttons = f'^(?!{own})' if own else None
    return [
        CommandHandler(['start', 'cancel'], end_silent),
        CallbackQueryHandler(end_silent, pattern=other_buttons),
    ]
