"""
src/wireguard.py  —  Crear cuenta WireGuard: nombre → días → .conf + QR.

El peer se agrega al servidor ANTES de entregar el archivo; si el servidor no
lo acepta, la cuenta se revierte y se avisa (nunca se entrega un .conf que no anda).
"""
import re
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ConversationHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

import config
from database import Database
from lib.helpers import is_admin
from lib.ui import header, kv, code, b, esc, steps, quote, bg, safe_edit
from lib.wireguard_manager import WireGuardManager
from src.menus import get_main_menu, get_cancel_menu, options_menu, get_home_only
from src.public import check_can_create, DAY_OPTS
from src.cards import wg_card, send_wg_files, created_keyboard
from src.flow import fallbacks, FLOW_TIMEOUT

db = Database(config.DB_PATH)
wg = WireGuardManager(db)

WG_USER, WG_DAYS = 20, 21


def _days_kb(caps):
    opts = [d for d in DAY_OPTS if not caps or d <= caps['max_days']] or [caps['max_days']]
    if caps and caps['max_days'] not in opts:
        opts.append(caps['max_days'])
    return options_menu('wd_', opts, per_row=4, suffix='d')


async def start_create_wg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    ok, err, caps = check_can_create(uid)
    if not ok:
        await safe_edit(query, err, get_main_menu(is_admin(uid)))
        return ConversationHandler.END
    if not db.get_config('wg_pubkey'):
        await safe_edit(query, f"{header('⚠️', 'WireGuard no está listo')}\n"
                               "El administrador todavía no instaló WireGuard en el servidor.",
                        get_main_menu(is_admin(uid)))
        return ConversationHandler.END

    context.user_data['f_wcaps'] = caps
    await safe_edit(query,
                    f"{header('🛡️', 'Nueva cuenta WireGuard', steps(1, 2))}\n"
                    "📝 Escribí un <b>nombre</b> para el dispositivo:\n\n"
                    + quote("3 a 31 caracteres · minúsculas, números, - o _\nEj: <code>celular</code>, <code>ana-pc</code>"),
                    get_cancel_menu())
    return WG_USER


async def wg_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip().lower()
    if not re.match(r'^[a-z][a-z0-9_-]{2,30}$', name):
        await update.message.reply_text("❌ Nombre inválido (3-31: minúsculas, números, - o _).\n✍️ Probá otro:",
                                        reply_markup=get_cancel_menu())
        return WG_USER
    if db.get_user_by_name(name):
        await update.message.reply_text("❌ Ese nombre ya está en uso. ✍️ Probá otro:", reply_markup=get_cancel_menu())
        return WG_USER
    context.user_data['f_wname'] = name
    caps = context.user_data.get('f_wcaps')
    limit = f" (máx. {caps['max_days']})" if caps else ""
    await update.message.reply_text(
        f"{header('🛡️', 'Nueva cuenta WireGuard', steps(2, 2))}\n"
        f"{kv('📱', 'Dispositivo', code(name))}\n\n"
        f"📅 ¿Cuántos <b>días</b> durará?{limit}\n<i>Elegí o escribí un número.</i>",
        parse_mode='HTML', reply_markup=_days_kb(caps))
    return WG_DAYS


async def wg_days_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await _finish(int(query.data[3:]), query.message, True, update.effective_user.id, context)


async def wg_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
    except ValueError:
        days = 0
    return await _finish(days, update.message, False, update.effective_user.id, context)


async def _finish(days: int, message, is_button: bool, user_id: int, context):
    caps = context.user_data.get('f_wcaps')
    if days <= 0 or days > 3650 or (caps and days > caps['max_days']):
        txt = f"❌ Tu plan permite máximo <b>{caps['max_days']}</b> días." if caps and days > 0 else "❌ Número inválido."
        await message.reply_text(txt, parse_mode='HTML', reply_markup=_days_kb(caps))
        return WG_DAYS

    name = context.user_data.pop('f_wname', None)
    context.user_data.pop('f_wcaps', None)
    server = db.ensure_default_server()
    if not name or not server:
        await message.reply_text("❌ Se perdieron los datos del formulario. Empezá de nuevo.",
                                 reply_markup=get_home_only())
        return ConversationHandler.END

    status = (await message.edit_text("⏳ <b>Creando tu WireGuard...</b>", parse_mode='HTML') if is_button
              else await message.reply_text("⏳ <b>Creando tu WireGuard...</b>", parse_mode='HTML'))

    prep = wg.prepare_peer(server['id'], name)
    if not prep.get('success'):
        await status.edit_text(f"❌ {esc(prep.get('error', 'Error'))}", reply_markup=get_home_only())
        return ConversationHandler.END

    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    acc_id = db.add_wg_user(user_id, name, server['id'], expires_at, prep['ip'], prep['client_pub'],
                            prep['client_priv'])
    res = await bg(wg.rebuild, server['id'])
    if not res.get('success'):
        db.delete_user_by_id(acc_id)          # no entregar un .conf que no funciona
        db.add_log('CREATE_WG_FAIL', f"{name}: {res.get('error', '')[:200]}", user_id)
        await status.edit_text(f"{header('❌', 'No se pudo activar en el servidor')}\n"
                               f"{esc(res.get('error', 'Error'))[:800]}\n\n"
                               "Avisale al administrador.", parse_mode='HTML', reply_markup=get_home_only())
        return ConversationHandler.END

    db.add_log('CREATE_WG', f"WireGuard {name} creado ({days}d)", user_id)
    account = db.get_user_by_id(acc_id)
    await status.edit_text(wg_card(account, title="¡WireGuard listo! 🎉"), parse_mode='HTML')
    await send_wg_files(message, account, created_keyboard('wireguard'))
    return ConversationHandler.END


OWN = ('wd_', 'create_wg')

wg_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_create_wg, pattern='^create_wg$')],
    states={
        WG_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, wg_user)],
        WG_DAYS: [
            CallbackQueryHandler(wg_days_btn, pattern=r'^wd_\d+$'),
            MessageHandler(filters.TEXT & ~filters.COMMAND, wg_days),
        ],
    },
    fallbacks=fallbacks(OWN),
    allow_reentry=True,
    conversation_timeout=FLOW_TIMEOUT,
)
