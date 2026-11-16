"""
src/premium.py  —  Planes premium (revendedores).

Flujo con BOTONES (recomendado): botón "⭐ Dar Premium" en el panel admin →
pide el telegram_id (tipeado) → cuentas → conexiones → días por cuenta →
duración del plan, todo con botones.

Comandos (atajos):
    /premium <telegram_id> <cuentas> <conex> <dias> <dias_plan>
    /unpremium <telegram_id>
    /plan   (usuario ve su plan)   ·   /id (usuario ve su telegram_id)
"""
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler, ContextTypes, MessageHandler, filters,
    CallbackQueryHandler, CommandHandler
)

import config
from database import Database
from lib.helpers import is_admin, escape_html
from lib.ui import header, kv, code, b, fmt_date, steps, tip
from src.flow import fallbacks, FLOW_TIMEOUT

db = Database(config.DB_PATH)

# Estados del flujo por botones
P_TGID, P_ACC, P_CONN, P_DAYS, P_PLAN = range(10, 15)

# Opciones de cada paso
ACC_OPTS = [1, 2, 3, 5, 10]
CONN_OPTS = [1, 2, 3, 5]
DAYS_OPTS = [7, 15, 30, 60, 90]
PLAN_OPTS = [30, 60, 90, 180, 365]


def _row(prefix, opts):
    return [InlineKeyboardButton(str(o), callback_data=f'{prefix}_{o}') for o in opts]


def _kb(prefix, opts):
    # agrupa en filas de 3 + botón cancelar
    rows = [opts[i:i + 3] for i in range(0, len(opts), 3)]
    kb = [[InlineKeyboardButton(str(o), callback_data=f'{prefix}_{o}') for o in r] for r in rows]
    kb.append([InlineKeyboardButton("✖️ Cancelar", callback_data='pcancel')])
    return InlineKeyboardMarkup(kb)


# ==========================================
# FLUJO POR BOTONES
# ==========================================
async def premium_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Solo admin", show_alert=True)
        return ConversationHandler.END

    context.user_data['p'] = {}
    await query.edit_message_text(
        f"{header('⭐', 'Dar Premium', steps(1, 5))}\n"
        "🆔 Escribí el <b>ID de Telegram</b> del usuario:\n"
        + tip("El usuario lo ve mandándole <code>/id</code> al bot."),
        parse_mode='HTML'
    )
    return P_TGID


async def premium_tgid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    try:
        tgid = int(txt)
        if tgid <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ ID inválido. Escribí solo números:")
        return P_TGID

    context.user_data['p']['tgid'] = tgid
    await update.message.reply_text(
        f"{header('⭐', 'Dar Premium', steps(2, 5))}\n"
        f"🆔 Usuario: <code>{tgid}</code>\n\n"
        "📦 ¿Cuántas <b>cuentas</b> puede crear?",
        parse_mode='HTML',
        reply_markup=_kb('pacc', ACC_OPTS)
    )
    return P_ACC


async def premium_acc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['p']['acc'] = int(query.data.split('_')[1])
    await query.edit_message_text(
        f"{header('⭐', 'Dar Premium', steps(3, 5))}\n"
        f"📦 Cuentas: <b>{context.user_data['p']['acc']}</b>\n\n"
        "📱 ¿Cuántas <b>conexiones</b> por cuenta?",
        parse_mode='HTML',
        reply_markup=_kb('pcon', CONN_OPTS)
    )
    return P_CONN


async def premium_conn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['p']['conn'] = int(query.data.split('_')[1])
    await query.edit_message_text(
        f"{header('⭐', 'Dar Premium', steps(4, 5))}\n"
        f"📱 Conexiones: <b>{context.user_data['p']['conn']}</b>\n\n"
        "📅 ¿Cuántos <b>días máximo</b> por cuenta?",
        parse_mode='HTML',
        reply_markup=_kb('pday', DAYS_OPTS)
    )
    return P_DAYS


async def premium_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['p']['days'] = int(query.data.split('_')[1])
    await query.edit_message_text(
        f"{header('⭐', 'Dar Premium', steps(5, 5))}\n"
        f"📅 Días por cuenta: <b>{context.user_data['p']['days']}</b>\n\n"
        "⏳ ¿Cuánto <b>dura el plan</b> (días)?",
        parse_mode='HTML',
        reply_markup=_kb('ppln', PLAN_OPTS)
    )
    return P_PLAN


async def premium_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    p = context.user_data.get('p', {})
    p['plan'] = int(query.data.split('_')[1])

    db.set_reseller(p['tgid'], p['acc'], p['conn'], p['days'], p['plan'])
    db.add_log('GRANT_PREMIUM',
               f"Plan a {p['tgid']}: {p['acc']}c/{p['conn']}conx/{p['days']}d (dura {p['plan']}d)",
               query.from_user.id)
    r = db.get_reseller(p['tgid'])

    await query.edit_message_text(
        "\n".join([
            header('✅', 'Premium otorgado'),
            kv("🆔", "Usuario", code(p['tgid'])),
            kv("📦", "Cuentas máx.", b(p['acc'])),
            kv("📱", "Conexiones por cuenta", b(p['conn'])),
            kv("📅", "Días máx. por cuenta", b(p['days'])),
            kv("⏳", "El plan vence", b(fmt_date(r['expires_at']))),
            tip("Avisale que ya puede entrar con /start."),
        ]),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⭐ Premium", callback_data='admin_premium_menu'),
            InlineKeyboardButton("◀️ Panel", callback_data='admin_panel')]])
    )
    try:
        await context.bot.send_message(
            p['tgid'],
            "\n".join([header('⭐', '¡Ya sos Premium!'),
                        kv("📦", "Cuentas", b(p['acc'])),
                        kv("📱", "Conexiones por cuenta", b(p['conn'])),
                        kv("⏳", "Tu plan vence", b(fmt_date(r['expires_at']))),
                        tip("Mandá /start para crear tus cuentas.")]),
            parse_mode='HTML')
    except Exception:
        pass
    context.user_data.pop('p', None)
    return ConversationHandler.END


async def premium_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop('p', None)
    await query.edit_message_text(
        "✖️ Cancelado.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Panel", callback_data='admin_panel')]]))
    return ConversationHandler.END


premium_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(premium_start, pattern='^admin_premium$')],
    states={
        P_TGID: [MessageHandler(filters.TEXT & ~filters.COMMAND, premium_tgid)],
        P_ACC: [CallbackQueryHandler(premium_acc, pattern='^pacc_')],
        P_CONN: [CallbackQueryHandler(premium_conn, pattern='^pcon_')],
        P_DAYS: [CallbackQueryHandler(premium_days, pattern='^pday_')],
        P_PLAN: [CallbackQueryHandler(premium_plan, pattern='^ppln_')],
    },
    fallbacks=[CallbackQueryHandler(premium_cancel, pattern='^pcancel$')]
              + fallbacks(('pacc_', 'pcon_', 'pday_', 'ppln_', 'pcancel', 'admin_premium$')),
    allow_reentry=True,
    conversation_timeout=FLOW_TIMEOUT,
)


# ==========================================
# COMANDOS (atajos)
# ==========================================
USAGE = (
    "📋 <b>Uso:</b>\n"
    "<code>/premium &lt;telegram_id&gt; &lt;cuentas&gt; &lt;conex&gt; &lt;dias&gt; &lt;dias_plan&gt;</code>\n\n"
    "Ejemplo: <code>/premium 123456789 3 5 30 30</code>\n\n"
    "O usá el botón <b>⭐ Dar Premium</b> del panel (paso a paso)."
)


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Solo admin.")
        return
    args = context.args
    if len(args) != 5:
        await update.message.reply_text(USAGE, parse_mode='HTML')
        return
    try:
        tgid, accounts, conn, days, plan_days = (int(a) for a in args)
        if min(accounts, conn, days, plan_days) <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Valores inválidos.\n\n" + USAGE, parse_mode='HTML')
        return
    db.set_reseller(tgid, accounts, conn, days, plan_days)
    db.add_log('GRANT_PREMIUM', f"Plan a {tgid}: {accounts}c/{conn}conx/{days}d", update.effective_user.id)
    r = db.get_reseller(tgid)
    await update.message.reply_text(
        f"✅ <b>Plan otorgado</b>\n🆔 <code>{tgid}</code> · 📦 {accounts} · 📱 {conn} · 📅 {days}d · "
        f"⏳ vence {r['expires_at'][:10]}",
        parse_mode='HTML'
    )


async def unpremium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Solo admin.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("📋 Uso: <code>/unpremium &lt;telegram_id&gt;</code>", parse_mode='HTML')
        return
    try:
        tgid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ telegram_id inválido.")
        return
    db.remove_reseller(tgid)
    db.add_log('REVOKE_PREMIUM', f"Plan quitado a {tgid}", update.effective_user.id)
    await update.message.reply_text(f"✅ Plan de <code>{tgid}</code> eliminado.", parse_mode='HTML')


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    r = db.get_reseller(uid)
    if not r or not db.is_reseller_active(uid):
        await update.message.reply_text(
            "🔒 <b>No tenés un plan premium activo.</b>\n\n"
            f"Contactá al owner: {escape_html(config.OWNER_CONTACT)}",
            parse_mode='HTML'
        )
        return
    used = db.count_user_accounts(uid)
    try:
        days_left = (datetime.fromisoformat(r['expires_at']) - datetime.now()).days
    except (ValueError, TypeError):
        days_left = 0
    await update.message.reply_text(
        f"⭐ <b>Tu Plan Premium</b>\n\n"
        f"📦 Cuentas: <b>{used}/{r['max_accounts']}</b>\n"
        f"📱 Conexiones máx por cuenta: <b>{r['max_conn']}</b>\n"
        f"📅 Días máx por cuenta: <b>{r['max_days']}</b>\n"
        f"⏳ Tu plan vence en: <b>{days_left}</b> días",
        parse_mode='HTML'
    )


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(
        f"{header('🆔', 'Tu ID de Telegram')}\n<code>{u.id}</code>\n\n"
        f"Tocalo para copiarlo y pasáselo a {escape_html(config.OWNER_CONTACT)} para obtener acceso.",
        parse_mode='HTML'
    )