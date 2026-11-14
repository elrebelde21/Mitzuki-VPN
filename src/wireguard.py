"""
src/wireguard.py  —  Flujo del bot para WireGuard.

Botón 🛡️ WireGuard → nombre → días → crea el peer y envía .conf + QR.
Respeta los límites del plan premium (cuentas y días), igual que SSH.
"""
import re
from io import BytesIO
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
)

import config
from database import Database
from lib.helpers import is_admin, escape_html, can_create_account
from src.menus import get_main_menu
from lib.wireguard_manager import WireGuardManager

try:
    import qrcode
    HAS_QR = True
except Exception:
    HAS_QR = False

db = Database(config.DB_PATH)
wg = WireGuardManager(db)

WG_USER, WG_DAYS = 20, 21


def _caps_for(user_id):
    """Límites del plan (None = admin, sin límite)."""
    if is_admin(user_id):
        return None
    if db.is_reseller_active(user_id):
        r = db.get_reseller(user_id)
        return {'max_accounts': r['max_accounts'], 'max_days': r['max_days']}
    return {'max_accounts': 1, 'max_days': 30}


async def start_create_wg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not can_create_account(user_id):
        await query.edit_message_text(
            config.PRIVATE_MESSAGE, parse_mode='HTML',
            reply_markup=get_main_menu(is_admin(user_id)))
        return ConversationHandler.END

    caps = _caps_for(user_id)
    context.user_data['wg_caps'] = caps
    if caps:
        used = db.count_user_accounts(user_id)
        if used >= caps['max_accounts']:
            await query.edit_message_text(
                f"❌ <b>Llegaste a tu límite de cuentas</b>\n\n"
                f"Tu plan permite <b>{caps['max_accounts']}</b> y ya tenés <b>{used}</b>.",
                parse_mode='HTML', reply_markup=get_main_menu(is_admin(user_id)))
            return ConversationHandler.END

    servers = db.get_all_servers()
    if not servers:
        await query.edit_message_text("❌ No hay servidor.", reply_markup=get_main_menu(is_admin(user_id)))
        return ConversationHandler.END

    if not wg.is_wireguard_installed(servers[0]['id']):
        await query.edit_message_text(
            "❌ <b>WireGuard no está instalado</b>\n\nPedile al admin que lo instale.",
            parse_mode='HTML', reply_markup=get_main_menu(is_admin(user_id)))
        return ConversationHandler.END

    await query.edit_message_text(
        "🛡️ <b>Crear WireGuard</b>\n\n📝 Escribí el <b>nombre</b> (minúsculas):",
        parse_mode='HTML')
    return WG_USER


async def wg_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip().lower()
    if not re.match(r'^[a-z][a-z0-9_-]{0,30}$', name):
        await update.message.reply_text("❌ Nombre inválido (minúsculas, números, - o _). De nuevo:")
        return WG_USER
    if db.get_user_by_name(name):
        await update.message.reply_text("❌ Ya existe una cuenta con ese nombre. Otro:")
        return WG_USER
    context.user_data['wg_name'] = name
    await update.message.reply_text(
        f"Nombre: <b>{escape_html(name)}</b>\n\n📅 ¿Cuántos <b>días</b>?",
        parse_mode='HTML')
    return WG_DAYS


async def wg_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Número inválido:")
        return WG_DAYS

    caps = context.user_data.get('wg_caps')
    if caps and days > caps['max_days']:
        await update.message.reply_text(
            f"❌ Tu plan permite máximo <b>{caps['max_days']}</b> días. Poné ese o menos:",
            parse_mode='HTML')
        return WG_DAYS

    name = context.user_data.get('wg_name')
    user_id = update.effective_user.id
    servers = db.get_all_servers()
    if not servers:
        await update.message.reply_text("❌ No hay servidor.")
        context.user_data.clear()
        return ConversationHandler.END
    server = servers[0]
    sid = server['id']

    creando = await update.message.reply_text(
        f"🛡️ <b>Creando '{escape_html(name)}'...</b>\n\n⏳", parse_mode='HTML')

    prep = wg.prepare_peer(sid, name)
    if not prep.get('success'):
        try:
            await creando.delete()
        except Exception:
            pass
        await update.message.reply_text(
            f"❌ {escape_html(prep.get('error', 'Error'))}",
            reply_markup=get_main_menu(is_admin(user_id)))
        context.user_data.clear()
        return ConversationHandler.END

    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    db.add_wg_user(user_id, name, sid, expires_at, prep['ip'], prep['client_pub'], prep['client_priv'])
    wg.rebuild(sid)
    conf = wg.client_conf(prep['client_priv'], prep['ip'], prep['server_pub'], prep['endpoint'])
    db.add_log('CREATE_WG', f"WireGuard {name} creado ({days}d)", user_id)

    try:
        await creando.delete()
    except Exception:
        pass

    # Archivo .conf
    doc = BytesIO(conf.encode())
    doc.name = f"{name}.conf"
    await update.message.reply_document(
        document=doc, filename=f"{name}.conf",
        caption=(f"🛡️ <b>WireGuard: {escape_html(name)}</b>\n"
                 f"📅 {days} días · ⏳ expira {expires_at[:10]}\n"
                 f"🌐 IP: <code>{escape_html(prep['ip'])}</code>"),
        parse_mode='HTML')

    # Botón de descarga de la app WireGuard (link configurable en config.WG_APP_DOWNLOAD_URL)
    wg_app_url = getattr(config, 'WG_APP_DOWNLOAD_URL',
                         'https://play.google.com/store/apps/details?id=com.wireguard.android')
    download_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Descargar App", url=wg_app_url)]
    ])

    # QR
    if HAS_QR:
        img = qrcode.make(conf)
        bio = BytesIO()
        img.save(bio, format='PNG')
        bio.seek(0)
        await update.message.reply_photo(
            photo=bio, caption="📱 Escaneá este QR desde la app WireGuard (botón + → Escanear).",
            reply_markup=download_kb)
    else:
        await update.message.reply_text(
            "📱 Importá el archivo .conf en la app WireGuard.",
            reply_markup=download_kb)

    context.user_data.clear()
    return ConversationHandler.END


wg_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_create_wg, pattern='^create_wg$')],
    states={
        WG_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, wg_user)],
        WG_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, wg_days)],
    },
    fallbacks=[]
)