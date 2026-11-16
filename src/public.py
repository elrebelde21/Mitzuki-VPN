"""
src/public.py  —  Pantallas del usuario: mis cuentas, plan, guías y creación de VayDNS.
"""
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb
from telegram.ext import ConversationHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

import config
from database import Database
from lib.helpers import is_admin, can_create_account
from lib.ui import (header, kv, code, b, esc, tip, warn, quote, steps, expiry, fmt_date, bar,
                    bg, safe_edit, owner_url)
from lib.ssh_accounts_manager import SSHAccountsManager
from lib.wireguard_manager import WireGuardManager
from src.menus import (get_main_menu, get_password_menu, get_cancel_menu, options_menu, get_help_menu,
                       get_help_back, get_home_only)
from src.cards import vaydns_card, wg_card, send_wg_files, created_keyboard, app_buttons
from src.flow import fallbacks, FLOW_TIMEOUT
from src.start import send_home

db = Database(config.DB_PATH)
ssh_accounts = SSHAccountsManager(db)
wireguard = WireGuardManager(db)

CREATE_SSH_USER, CREATE_SSH_PASSWORD, CREATE_SSH_DAYS, CREATE_SSH_DEVICES = 1, 2, 3, 4

DAY_OPTS = [1, 3, 7, 15, 30, 60, 90]
CONN_OPTS = [1, 2, 3, 4, 5, 10]
FREE_PLAN = {'max_accounts': 1, 'max_conn': 3, 'max_days': 30}


def caps_for(user_id: int):
    """Límites del plan del usuario (None = admin, sin límite)."""
    if is_admin(user_id):
        return None
    if db.is_reseller_active(user_id):
        r = db.get_reseller(user_id)
        return {'max_accounts': r['max_accounts'], 'max_conn': r['max_conn'], 'max_days': r['max_days']}
    return dict(FREE_PLAN)


def check_can_create(user_id: int):
    """Devuelve (ok, texto_error, caps)."""
    if not can_create_account(user_id):
        return False, config.PRIVATE_MESSAGE, None
    caps = caps_for(user_id)
    if caps:
        used = db.count_user_accounts(user_id)
        if used >= caps['max_accounts']:
            return False, (
                f"{header('📦', 'Límite de cuentas alcanzado')}\n"
                f"Tu plan permite {b(caps['max_accounts'])} cuenta(s) y ya tenés {b(used)}.\n"
                f"{bar(used, caps['max_accounts'])}\n\n"
                f"{tip('Borrá una cuenta desde 👤 Mis cuentas o pedí ampliar tu plan.')}"
            ), caps
    if not db.ensure_default_server():
        return False, f"{header('⚠️', 'Servicio no disponible')}\nEl servidor todavía no está configurado.", caps
    return True, '', caps


# ==========================================
# MIS CUENTAS
# ==========================================
async def show_my_accounts(query):
    uid = query.from_user.id
    accounts = db.get_user_accounts(uid)
    if not accounts:
        await safe_edit(query,
                        f"{header('👤', 'Mis cuentas')}\n"
                        "Todavía no tenés cuentas.\n"
                        f"{tip('Creá una con 🚀 VayDNS (redes restringidas) o 🛡️ WireGuard (máxima velocidad).')}",
                        Kb([[Btn("🚀 Crear VayDNS", callback_data='create_account'),
                             Btn("🛡️ Crear WireGuard", callback_data='create_wg')],
                            [Btn("🏠 Inicio", callback_data='back_to_main')]]))
        return

    lines = [header('👤', 'Mis cuentas', f"{len(accounts)} cuenta(s) · tocá una para ver sus datos")]
    kb = []
    for a in accounts:
        is_wg = a.get('conn_type') == 'wireguard'
        icon = "🛡️" if is_wg else "🚀"
        lines.append(f"{icon} {b(a['username'])} — {expiry(a['expires_at'])}")
        kb.append([Btn(f"{icon} {a['username'][:20]}", callback_data=f"myacc_view_{a['id']}"),
                   Btn("🗑️", callback_data=f"myacc_del_{a['id']}")])
    kb.append([Btn("🏠 Inicio", callback_data='back_to_main')])
    await safe_edit(query, "\n".join(lines), Kb(kb))


def _owned(query, account_id: int):
    a = db.get_user_by_id(account_id)
    if a and (a.get('telegram_id') == query.from_user.id or is_admin(query.from_user.id)):
        return a
    return None


async def show_myacc_view(query):
    a = _owned(query, int(query.data.rsplit('_', 1)[1]))
    if not a:
        await query.answer("⛔ Esa cuenta no existe o no es tuya", show_alert=True)
        return
    if a.get('conn_type') == 'wireguard':
        kb = Kb([[Btn("📄 Enviar .conf + QR", callback_data=f"myacc_conf_{a['id']}")],
                 app_buttons('wireguard'),
                 [Btn("🗑️ Eliminar", callback_data=f"myacc_del_{a['id']}"),
                  Btn("◀️ Mis cuentas", callback_data='my_account')]])
        await safe_edit(query, wg_card(a), kb)
    else:
        kb = Kb([app_buttons('vaydns'),
                 [Btn("🗑️ Eliminar", callback_data=f"myacc_del_{a['id']}"),
                  Btn("◀️ Mis cuentas", callback_data='my_account')]])
        await safe_edit(query, vaydns_card(a), kb)


async def myacc_send_conf(query):
    a = _owned(query, int(query.data.rsplit('_', 1)[1]))
    if not a or a.get('conn_type') != 'wireguard':
        await query.answer("⛔ Cuenta no encontrada", show_alert=True)
        return
    await send_wg_files(query.message, a, Kb([[Btn("👤 Mis cuentas", callback_data='my_account'),
                                               Btn("🏠 Inicio", callback_data='back_to_main')]]))


async def myacc_delete_ask(query):
    a = _owned(query, int(query.data.rsplit('_', 1)[1]))
    if not a:
        await query.answer("⛔ Cuenta no encontrada", show_alert=True)
        return
    await safe_edit(query,
                    f"{header('🗑️', 'Eliminar cuenta')}\n"
                    f"¿Seguro que querés eliminar {b(a['username'])}?\n"
                    f"{warn('Se desconecta al instante y no se puede deshacer.')}",
                    Kb([[Btn("✅ Sí, eliminar", callback_data=f"myacc_delok_{a['id']}"),
                         Btn("✖️ No", callback_data=f"myacc_view_{a['id']}")]]))


async def delete_account(a: dict):
    """Borra una cuenta del servidor y de la DB (SSH o WireGuard)."""
    db.delete_user_by_id(a['id'])
    try:
        if a.get('conn_type') == 'wireguard':
            if a.get('server_id'):
                await bg(wireguard.rebuild, a['server_id'])
        elif a.get('username') and a.get('server_id'):
            await bg(ssh_accounts.delete_user, a['server_id'], a['username'])
    except Exception as e:
        print(f"[delete_account] {e}")


async def myacc_delete(query):
    a = _owned(query, int(query.data.rsplit('_', 1)[1]))
    if not a:
        await query.answer("⛔ Cuenta no encontrada", show_alert=True)
        return
    await safe_edit(query, "⏳ <b>Eliminando...</b>")
    await delete_account(a)
    db.add_log('USER_DELETE_OWN', f"Borró su cuenta {a.get('username')}", query.from_user.id)
    await query.answer("✅ Cuenta eliminada")
    await show_my_accounts(query)


# ==========================================
# PLAN / AYUDA
# ==========================================
async def show_my_plan(query):
    uid = query.from_user.id
    used = db.count_user_accounts(uid)
    lines = [header('⭐', 'Mi plan')]
    if is_admin(uid):
        lines.append("👑 Sos <b>administrador</b>: sin límites de cuentas, días ni conexiones.")
    elif db.is_reseller_active(uid):
        r = db.get_reseller(uid)
        lines += [
            kv("🏷️", "Plan", b("Premium")),
            kv("📦", "Cuentas", f"{bar(used, r['max_accounts'])} {used}/{r['max_accounts']}"),
            kv("📱", "Conexiones por cuenta", b(r['max_conn'])),
            kv("📅", "Días máx. por cuenta", b(r['max_days'])),
            kv("⏳", "Tu plan vence", f"{b(fmt_date(r['expires_at']))} · {expiry(r['expires_at'])}"),
        ]
    else:
        lines += [
            kv("🏷️", "Plan", b("Gratis")),
            kv("📦", "Cuentas", f"{bar(used, FREE_PLAN['max_accounts'])} {used}/{FREE_PLAN['max_accounts']}"),
            kv("📱", "Conexiones por cuenta", b(FREE_PLAN['max_conn'])),
            kv("📅", "Días máx. por cuenta", b(FREE_PLAN['max_days'])),
            tip(f"¿Querés más? Escribile a {esc(config.OWNER_CONTACT)} y pasale tu ID: {code(uid)}"),
        ]
    kb = [[Btn("🏠 Inicio", callback_data='back_to_main')]]
    url = owner_url()
    if url and not is_admin(uid):
        kb.insert(0, [Btn("💬 Pedir más", url=url)])
    await safe_edit(query, "\n".join(lines), Kb(kb))


HELP_VAYDNS = "\n".join([
    header('🚀', 'Cómo conectar VayDNS', 'Túnel por DNS — funciona donde otras VPN no'),
    "<b>1.</b> Descargá e instalá la app.",
    "<b>2.</b> Abrí 👤 <b>Mis cuentas</b> y tocá tu cuenta VayDNS.",
    "<b>3.</b> Tocá el <b>link</b> para copiarlo.",
    "<b>4.</b> En la app: <b>Importar</b> / <b>+</b> → pegá el link.",
    "<b>5.</b> Tocá <b>Conectar</b> ✅",
    "",
    quote("✍️ <b>Si cargás los datos a mano</b>, copiá exactamente:\n"
          "Dominio · Public key · Record type · Protocolo (SSH/SOCKS) · Usuario · Contraseña"),
    tip("Si el admin cambia el <b>Record type</b>, volvé a copiar el link desde Mis cuentas."),
])

HELP_WG = "\n".join([
    header('🛡️', 'Cómo conectar WireGuard', 'VPN directa — la más rápida'),
    "<b>1.</b> Instalá la app oficial <b>WireGuard</b>.",
    "<b>2.</b> Abrí 👤 <b>Mis cuentas</b> → tu cuenta → <b>📄 Enviar .conf + QR</b>.",
    "<b>3.</b> En WireGuard tocá <b>+</b>:",
    "     • <b>Escanear QR</b> (desde otro teléfono/pantalla), o",
    "     • <b>Importar desde archivo</b> y elegí el <code>.conf</code>.",
    "<b>4.</b> Activá el interruptor ✅",
    "",
    tip("Un archivo .conf funciona en <b>un solo dispositivo</b> a la vez."),
])

HELP_TROUBLE = "\n".join([
    header('❓', 'No me conecta', 'Revisá esto en orden'),
    "<b>VayDNS</b>",
    "• Copiá de nuevo el link desde 👤 Mis cuentas (puede haber cambiado).",
    "• Verificá que la cuenta no esté 🔴 vencida.",
    "• Probá otra red (datos / Wi-Fi): algunas bloquean ciertos tipos de DNS.",
    "• No uses más conexiones que las de tu plan.",
    "",
    "<b>WireGuard</b>",
    "• Pedí el .conf de nuevo desde 👤 Mis cuentas e importalo otra vez.",
    "• Si la red bloquea VPN, usá VayDNS.",
    "• El mismo .conf en dos teléfonos a la vez se desconectan entre sí.",
    "",
    tip(f"¿Sigue sin andar? Escribile a {esc(config.OWNER_CONTACT)}."),
])


def _help_kb(kind: str) -> Kb:
    rows = []
    download = app_buttons(kind)[:-1]
    if download:
        rows.append(download)
    rows.append([Btn("◀️ Ayuda", callback_data='help_menu'), Btn("🏠 Inicio", callback_data='back_to_main')])
    return Kb(rows)


# ==========================================
# ROUTER DE BOTONES PÚBLICOS
# ==========================================
async def button_handler_public(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    try:
        await query.answer()
    except Exception:
        pass

    if data in ('back_to_main', 'flow_cancel', 'cancel_action'):
        await send_home(update, context, edit=True)
    elif data == 'my_account':
        await show_my_accounts(query)
    elif data == 'my_plan':
        await show_my_plan(query)
    elif data.startswith('myacc_view_'):
        await show_myacc_view(query)
    elif data.startswith('myacc_conf_'):
        await myacc_send_conf(query)
    elif data.startswith('myacc_delok_'):
        await myacc_delete(query)
    elif data.startswith('myacc_del_'):
        await myacc_delete_ask(query)
    elif data == 'help_menu':
        await safe_edit(query, f"{header('📖', 'Centro de ayuda')}\nElegí una guía:", get_help_menu())
    elif data == 'help_vaydns':
        await safe_edit(query, HELP_VAYDNS, _help_kb('vaydns'))
    elif data == 'help_wg':
        await safe_edit(query, HELP_WG, _help_kb('wireguard'))
    elif data == 'help_trouble':
        await safe_edit(query, HELP_TROUBLE, get_help_back())
    elif data == 'status':
        await send_home(update, context, edit=True)


# ==========================================
# CREAR VAYDNS (conversación)
# ==========================================
async def start_create_ssh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    ok, err, caps = check_can_create(uid)
    if not ok:
        await safe_edit(query, err, get_main_menu(is_admin(uid)))
        return ConversationHandler.END

    context.user_data['f_caps'] = caps
    await safe_edit(query,
                    f"{header('🚀', 'Nueva cuenta VayDNS', steps(1, 4))}\n"
                    "📝 Escribí un <b>nombre de usuario</b>:\n\n"
                    + quote("3 a 31 caracteres · minúsculas, números, - o _ · empieza con letra\n"
                            "Ej: <code>juan</code>, <code>maria22</code>"),
                    get_cancel_menu())
    return CREATE_SSH_USER


async def create_ssh_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip().lower()
    if not ssh_accounts._valid_username(name):
        await update.message.reply_text(
            "❌ Nombre inválido.\nUsá 3-31 caracteres: minúsculas, números, - o _, y que empiece con letra.\n\n"
            "✍️ Probá otro:", reply_markup=get_cancel_menu())
        return CREATE_SSH_USER
    if db.get_user_by_name(name):
        await update.message.reply_text("❌ Ese nombre ya está en uso. ✍️ Probá otro:", reply_markup=get_cancel_menu())
        return CREATE_SSH_USER
    context.user_data['f_user'] = name
    await update.message.reply_text(
        f"{header('🚀', 'Nueva cuenta VayDNS', steps(2, 4))}\n"
        f"{kv('👤', 'Usuario', code(name))}\n\n"
        "🔐 Escribí una <b>contraseña</b> (4-64 caracteres) o generá una segura:",
        parse_mode='HTML', reply_markup=get_password_menu())
    return CREATE_SSH_PASSWORD


def _days_kb(caps):
    opts = [d for d in DAY_OPTS if not caps or d <= caps['max_days']] or [caps['max_days']]
    if caps and caps['max_days'] not in opts:
        opts.append(caps['max_days'])
    return options_menu('sd_', opts, per_row=4, suffix='d')


def _conn_kb(caps):
    opts = [c for c in CONN_OPTS if not caps or c <= caps['max_conn']] or [caps['max_conn']]
    return options_menu('sc_', opts, per_row=3)


async def _ask_days(send, context):
    caps = context.user_data.get('f_caps')
    limit = f" (máx. {caps['max_days']})" if caps else ""
    await send(f"{header('🚀', 'Nueva cuenta VayDNS', steps(3, 4))}\n"
               f"{kv('👤', 'Usuario', code(context.user_data['f_user']))}\n"
               f"{kv('🔑', 'Contraseña', code(context.user_data['f_pass']))}\n\n"
               f"📅 ¿Cuántos <b>días</b> durará?{limit}\n<i>Elegí o escribí un número.</i>",
               parse_mode='HTML', reply_markup=_days_kb(caps))
    return CREATE_SSH_DAYS


async def create_ssh_password_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🎲 Contraseña generada")
    context.user_data['f_pass'] = ssh_accounts.generate_password(10)
    return await _ask_days(query.edit_message_text, context)


async def create_ssh_password_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pw = update.message.text.strip()
    if not ssh_accounts._valid_password(pw) or ' ' in pw:
        await update.message.reply_text("❌ Contraseña inválida (4-64 caracteres, sin espacios ni \":\").\n"
                                        "✍️ Probá otra:", reply_markup=get_password_menu())
        return CREATE_SSH_PASSWORD
    context.user_data['f_pass'] = pw
    return await _ask_days(update.message.reply_text, context)


async def _set_days(days: int, send, context):
    caps = context.user_data.get('f_caps')
    if days <= 0 or days > 3650:
        await send("❌ Número inválido. Elegí una opción:", reply_markup=_days_kb(caps))
        return CREATE_SSH_DAYS
    if caps and days > caps['max_days']:
        await send(f"❌ Tu plan permite máximo <b>{caps['max_days']}</b> días.", parse_mode='HTML',
                   reply_markup=_days_kb(caps))
        return CREATE_SSH_DAYS
    context.user_data['f_days'] = days
    limit = f" (máx. {caps['max_conn']})" if caps else ""
    await send(f"{header('🚀', 'Nueva cuenta VayDNS', steps(4, 4))}\n"
               f"{kv('👤', 'Usuario', code(context.user_data['f_user']))}\n"
               f"{kv('📅', 'Duración', b(f'{days} días'))}\n\n"
               f"📱 ¿Cuántos <b>dispositivos a la vez</b>?{limit}",
               parse_mode='HTML', reply_markup=_conn_kb(caps))
    return CREATE_SSH_DEVICES


async def create_ssh_days_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await _set_days(int(query.data[3:]), query.edit_message_text, context)


async def create_ssh_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
    except ValueError:
        days = 0
    return await _set_days(days, update.message.reply_text, context)


async def create_ssh_devices_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ <b>Creando tu cuenta...</b>\n<i>Esto tarda unos segundos.</i>",
                                  parse_mode='HTML')
    return await _finish_ssh(int(query.data[3:]), query.message, update.effective_user.id, context)


async def create_ssh_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        devices = int(update.message.text.strip())
    except ValueError:
        devices = 0
    if devices <= 0 or devices > 100:
        await update.message.reply_text("❌ Número inválido. Elegí una opción:",
                                        reply_markup=_conn_kb(context.user_data.get('f_caps')))
        return CREATE_SSH_DEVICES
    msg = await update.message.reply_text("⏳ <b>Creando tu cuenta...</b>", parse_mode='HTML')
    return await _finish_ssh(devices, msg, update.effective_user.id, context)


async def _finish_ssh(devices: int, msg, user_id: int, context):
    caps = context.user_data.get('f_caps')
    if caps and devices > caps['max_conn']:
        devices = caps['max_conn']
    name = context.user_data.get('f_user')
    password = context.user_data.get('f_pass')
    days = context.user_data.get('f_days', 30)
    for k in ('f_caps', 'f_user', 'f_pass', 'f_days'):
        context.user_data.pop(k, None)

    server = db.ensure_default_server()
    if not server or not name or not password:
        await msg.edit_text("❌ Se perdieron los datos del formulario. Empezá de nuevo.",
                            reply_markup=get_home_only())
        return ConversationHandler.END
    if not server.get('pubkey'):
        await msg.edit_text(f"{header('⚠️', 'VayDNS no está listo')}\n"
                            "El administrador todavía no instaló VayDNS en el servidor.",
                            parse_mode='HTML', reply_markup=get_home_only())
        return ConversationHandler.END

    result = await bg(ssh_accounts.create_user, server['id'], name, password, days, devices)
    if not result['success']:
        await msg.edit_text(f"{header('❌', 'No se pudo crear la cuenta')}\n{esc(result.get('error', 'Error'))}",
                            parse_mode='HTML', reply_markup=get_home_only())
        return ConversationHandler.END

    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    cfg = ssh_accounts.client_config(server, name, password)
    acc_id = db.add_user(user_id, name, server['id'], cfg['url'], expires_at, password=password, max_conn=devices)
    db.add_log('CREATE_SSH', f"VayDNS {name} ({days}d, {devices} conex, {cfg['record_type']}/{cfg['backend']})",
               user_id)

    account = db.get_user_by_id(acc_id)
    await msg.edit_text(vaydns_card(account, title="¡Cuenta VayDNS lista! 🎉"), parse_mode='HTML',
                        reply_markup=created_keyboard('vaydns'), disable_web_page_preview=True)
    return ConversationHandler.END


OWN = ('sd_', 'sc_', 'slip_pass_random', 'create_account')

create_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_create_ssh, pattern='^create_account$')],
    states={
        CREATE_SSH_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_ssh_user)],
        CREATE_SSH_PASSWORD: [
            CallbackQueryHandler(create_ssh_password_random, pattern='^slip_pass_random$'),
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_ssh_password_manual),
        ],
        CREATE_SSH_DAYS: [
            CallbackQueryHandler(create_ssh_days_btn, pattern=r'^sd_\d+$'),
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_ssh_days),
        ],
        CREATE_SSH_DEVICES: [
            CallbackQueryHandler(create_ssh_devices_btn, pattern=r'^sc_\d+$'),
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_ssh_devices),
        ],
    },
    fallbacks=fallbacks(OWN),
    allow_reentry=True,
    conversation_timeout=FLOW_TIMEOUT,
)
