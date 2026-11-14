from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

import config
from database import Database
from lib.helpers import is_admin, escape_html, can_create_account
from src.menus import get_main_menu, get_password_menu
from lib.vaydns_manager import VayDNSManager
from lib.ssh_accounts_manager import SSHAccountsManager
from lib.wireguard_manager import WireGuardManager

db = Database(config.DB_PATH)
vaydns = VayDNSManager(db)
ssh_accounts = SSHAccountsManager(db)
wireguard = WireGuardManager(db)

# Estados
CREATE_SSH_USER = 1
CREATE_SSH_PASSWORD = 2
CREATE_SSH_DAYS = 3
CREATE_SSH_DEVICES = 4


# ==========================================
# MOSTRAR
# ==========================================
async def show_status(query, is_admin_user):
    servers = db.get_all_servers()
    if not servers:
        await query.edit_message_text("❌ Sin servidor.", reply_markup=get_main_menu(is_admin_user))
        return

    server = servers[0]
    result = vaydns.get_server_status(server['id'])

    text = f"""
🖥️ <b>Estado del Servidor</b>

🏷️ Nombre: {escape_html(server['name'])}
🌐 IP: {escape_html(server['ip'])}
🔑 Dominio: {escape_html(server['domain'])}
👥 Cuentas: {db.get_active_users_count()}
"""
    if result['success']:
        text += f"\n📶 Estado: ✅ {escape_html(result['status'])}"
        if result['ports']:
            text += f"\n🔌 Puertos:\n<code>{escape_html(result['ports'][:200])}</code>"
    else:
        text += f"\n❌ Error: {escape_html(result['error'])}"

    await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_main_menu(is_admin_user))


async def show_my_accounts(query):
    """Lista todas las cuentas del usuario con botones ver/borrar."""
    accounts = db.get_user_accounts(query.from_user.id)
    is_admin_user = is_admin(query.from_user.id)

    if not accounts:
        await query.edit_message_text(
            "❌ <b>No tenés cuentas activas</b>\n\n💡 Usá ➕ Crear SSH o 🛡️ WireGuard.",
            parse_mode='HTML',
            reply_markup=get_main_menu(is_admin_user)
        )
        return

    text = "👤 <b>Mis Cuentas</b>\n\nTocá 👁️ para ver el config o 🗑️ para borrar.\n\n"
    keyboard = []
    for a in accounts:
        try:
            days = (datetime.fromisoformat(a['expires_at']) - datetime.now()).days
        except (ValueError, TypeError):
            days = 0
        emoji = "🟢" if days > 0 else "🔴"
        typ = "🛡️WG" if a.get('conn_type') == 'wireguard' else "🔑SSH"
        text += f"{emoji} {typ} <b>{escape_html(a['username'])}</b> — {days}d\n"
        keyboard.append([
            InlineKeyboardButton(f"👁️ {a['username'][:12]}", callback_data=f"myacc_view_{a['id']}"),
            InlineKeyboardButton("🗑️", callback_data=f"myacc_del_{a['id']}"),
        ])

    keyboard.append([InlineKeyboardButton("◀️ Menú", callback_data='back_to_main')])
    await query.edit_message_text(text[:4000], parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


def _owns(query, account):
    return account and account.get('telegram_id') == query.from_user.id


async def show_myacc_view(query):
    account_id = int(query.data.replace('myacc_view_', ''))
    a = db.get_user_by_id(account_id)
    if not _owns(query, a):
        await query.answer("⛔ Esa cuenta no es tuya", show_alert=True)
        return

    try:
        days = (datetime.fromisoformat(a['expires_at']) - datetime.now()).days
    except (ValueError, TypeError):
        days = 0

    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data='my_account')]])

    if a.get('conn_type') == 'wireguard':
        server = db.get_server(a['server_id'])
        endpoint = f"{server['ip']}:51820" if server else ""
        conf = wireguard.client_conf(a.get('wg_privkey', ''), a.get('wg_ip', ''),
                                     db.get_config('wg_pubkey') or '', endpoint)
        text = (f"🛡️ <b>WireGuard: {escape_html(a['username'])}</b>\n"
                f"📆 Días: <b>{days}</b> · 🌐 IP: <code>{escape_html(a.get('wg_ip', ''))}</code>\n\n"
                f"🔗 <b>Config:</b>\n<pre>{escape_html(conf)}</pre>")
    else:
        pass_line = f"🔑 Contraseña: <code>{escape_html(a['password'])}</code>\n" if a.get('password') else ""
        text = (f"🔑 <b>SSH: {escape_html(a['username'])}</b>\n"
                f"{pass_line}📆 Días: <b>{days}</b>\n\n"
                f"🔗 <b>Config:</b>\n<code>{escape_html(a.get('vaydns_url') or 'N/A')}</code>")

    await query.edit_message_text(text, parse_mode='HTML', reply_markup=back_kb)


async def myacc_delete(query):
    account_id = int(query.data.replace('myacc_del_', ''))
    a = db.get_user_by_id(account_id)
    if not _owns(query, a):
        await query.answer("⛔ Esa cuenta no es tuya", show_alert=True)
        return

    try:
        if a.get('conn_type') == 'wireguard':
            db.delete_user_by_id(account_id)
            if a.get('server_id'):
                wireguard.rebuild(a['server_id'])
        else:
            if a.get('username') and a.get('server_id'):
                ssh_accounts.delete_user(a['server_id'], a['username'])
            db.delete_user_by_id(account_id)
    except Exception as e:
        print(f"Error borrando cuenta propia: {e}")
        db.delete_user_by_id(account_id)

    db.add_log('USER_DELETE_OWN', f"Usuario borró su cuenta {a.get('username')}", query.from_user.id)
    await query.answer("✅ Cuenta eliminada", show_alert=True)
    await show_my_accounts(query)


# ==========================================
# BOTONES PÚBLICOS
# ==========================================
async def button_handler_public(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)
    data = query.data

    if data == 'status':
        await show_status(query, is_admin_user)
    elif data == 'my_account':
        await show_my_accounts(query)
    elif data.startswith('myacc_view_'):
        await show_myacc_view(query)
    elif data.startswith('myacc_del_'):
        await myacc_delete(query)
    elif data == 'create_account':
        return await start_create_ssh(update, context)
    elif data == 'back_to_main':
        await query.edit_message_text(
            "📋 <b>Menú Principal</b>\n\nSelecciona una opción:",
            parse_mode='HTML',
            reply_markup=get_main_menu(is_admin_user)
        )


# ==========================================
# CREAR SSH
# ==========================================
async def start_create_ssh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        reply = query.edit_message_text
    else:
        user_id = update.effective_user.id
        reply = update.message.reply_text

    if not can_create_account(user_id):
        await reply(
            config.PRIVATE_MESSAGE,
            parse_mode='HTML',
            reply_markup=get_main_menu(is_admin(user_id))
        )
        return ConversationHandler.END

    # Límites según el plan. Admin = sin límite.
    if is_admin(user_id):
        context.user_data['caps'] = None  # sin límite
    else:
        if db.is_reseller_active(user_id):
            r = db.get_reseller(user_id)
            caps = {
                'max_accounts': r['max_accounts'],
                'max_conn': r['max_conn'],
                'max_days': r['max_days'],
            }
        else:
            # Modo público sin plan: plan libre por defecto
            caps = {'max_accounts': 1, 'max_conn': 3, 'max_days': 30}
        context.user_data['caps'] = caps

        used = db.count_user_accounts(user_id)
        if used >= caps['max_accounts']:
            await reply(
                f"❌ <b>Llegaste a tu límite de cuentas</b>\n\n"
                f"Tu plan permite <b>{caps['max_accounts']}</b> cuenta(s) y ya tenés <b>{used}</b>.\n"
                f"Borrá una o pedí ampliar tu plan.",
                parse_mode='HTML',
                reply_markup=get_main_menu(is_admin(user_id))
            )
            return ConversationHandler.END

    servers = db.get_all_servers()
    if not servers:
        await reply(
            "❌ <b>No hay servidor disponible</b>",
            parse_mode='HTML',
            reply_markup=get_main_menu(is_admin(user_id))
        )
        return ConversationHandler.END

    await reply(
        "🔧 <b>Crear SSH</b>\n\n"
        "📝 Escribe el <b>nombre de usuario</b>:\n"
        "(minúsculas, números, - o _ ; ejemplo: cliente1, juan, maria)",
        parse_mode='HTML'
    )
    return CREATE_SSH_USER


async def create_ssh_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.text.strip().lower()
    # Validación local rápida (la real la hace el manager)
    if not ssh_accounts._valid_username(user):
        await update.message.reply_text(
            "❌ Usuario inválido. Usá minúsculas, números, - o _, y que empiece con letra. Intenta de nuevo:"
        )
        return CREATE_SSH_USER
    context.user_data['ssh_user'] = user
    await update.message.reply_text(
        f"👤 Usuario: <b>{escape_html(user)}</b>\n\n"
        "🔐 Escribe la <b>contraseña</b> o pulsa <b>Aleatoria</b>:",
        parse_mode='HTML',
        reply_markup=get_password_menu()
    )
    return CREATE_SSH_PASSWORD


async def create_ssh_password_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    password = ssh_accounts.generate_password(12)
    context.user_data['ssh_password'] = password
    await query.edit_message_text(
        f"🎲 <b>Contraseña generada:</b> <code>{escape_html(password)}</code>\n\n"
        "📅 ¿Cuántos <b>días</b> durará?\n"
        "(Ejemplo: 30)",
        parse_mode='HTML'
    )
    return CREATE_SSH_DAYS


async def create_ssh_password_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    if len(password) < 4:
        await update.message.reply_text("❌ Mínimo 4 caracteres. Intenta de nuevo:")
        return CREATE_SSH_PASSWORD
    context.user_data['ssh_password'] = password
    await update.message.reply_text(
        f"🔐 Contraseña: <code>{escape_html(password)}</code>\n\n"
        "📅 ¿Cuántos <b>días</b> durará?\n"
        "(Ejemplo: 30)",
        parse_mode='HTML'
    )
    return CREATE_SSH_DAYS


async def create_ssh_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
        if days <= 0:
            raise ValueError

        caps = context.user_data.get('caps')
        if caps and days > caps['max_days']:
            await update.message.reply_text(
                f"❌ Tu plan permite <b>máximo {caps['max_days']} días</b>.\n"
                f"Escribí <b>{caps['max_days']}</b> o menos:",
                parse_mode='HTML'
            )
            return CREATE_SSH_DAYS

        context.user_data['ssh_days'] = days
        await update.message.reply_text(
            f"📅 Días: <b>{days}</b>\n\n"
            "📱 ¿Cuántas <b>conexiones simultáneas</b> permitir?\n"
            "(Ejemplo: 3)",
            parse_mode='HTML'
        )
        return CREATE_SSH_DEVICES
    except ValueError:
        await update.message.reply_text("❌ Número inválido (ej: 30):")
        return CREATE_SSH_DAYS


async def create_ssh_devices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        devices = int(update.message.text.strip())
        if devices <= 0:
            raise ValueError
    except ValueError:
        devices = 3

    capped_note = ""
    caps = context.user_data.get('caps')
    if caps and devices > caps['max_conn']:
        devices = caps['max_conn']
        capped_note = f"⚠️ Tu plan permite máximo {caps['max_conn']} conexiones; se ajustó a {devices}.\n\n"

    user = context.user_data.get('ssh_user', 'user')
    days = context.user_data.get('ssh_days', 30)
    password = context.user_data.get('ssh_password', ssh_accounts.generate_password(12))
    user_id = update.effective_user.id

    servers = db.get_all_servers()
    if not servers:
        await update.message.reply_text("❌ No hay servidor.")
        context.user_data.clear()
        return ConversationHandler.END

    server = servers[0]
    server_id = server['id']

    if not ssh_accounts.is_backend_installed(server_id):
        await update.message.reply_text(
            "❌ <b>El backend SSH no está instalado</b>\n\n"
            "Pedile al admin que instale VayDNS (con backend SSH) primero.",
            parse_mode='HTML',
            reply_markup=get_main_menu(is_admin(user_id))
        )
        context.user_data.clear()
        return ConversationHandler.END

    creando = await update.message.reply_text(
        f"{capped_note}🌀 <b>Creando cuenta '{escape_html(user)}'...</b>\n\n⏳",
        parse_mode='HTML'
    )

    result = ssh_accounts.create_user(server_id, user, password, days, devices)
    if not result['success']:
        try:
            await creando.delete()
        except Exception:
            pass
        await update.message.reply_text(
            f"❌ <b>Error creando la cuenta:</b>\n\n{escape_html(result.get('error', 'Error'))}",
            parse_mode='HTML',
            reply_markup=get_main_menu(is_admin(user_id))
        )
        context.user_data.clear()
        return ConversationHandler.END

    # El record type lo define el servidor, no la cuenta
    cfg = ssh_accounts.client_config(server, user, password)
    expires_at = (datetime.now() + timedelta(days=days)).isoformat()

    db.add_user(user_id, user, server_id, cfg['url'], expires_at, password=password, max_conn=devices)
    db.add_log('CREATE_SSH', f"Cuenta {user} creada ({days}d, {devices} conex, {cfg['record_type']})", user_id)

    app_url = getattr(config, 'APP_DOWNLOAD_URL', 'https://play.google.com/store')
    download_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Descargar App", url=app_url)]
    ])

    text = f"""
✅ <b>¡Cuenta Creada!</b>

━━━━━━━━━━━━━━━━━━━
📋 <b>Datos</b>
━━━━━━━━━━━━━━━━━━━
👤 <b>Usuario:</b> <code>{escape_html(user)}</code>
🔑 <b>Contraseña:</b> <code>{escape_html(password)}</code>
💻 <b>Tunnel Domain:</b> <code>{escape_html(cfg['tunnel'])}</code>
🔑 <b>Public Key:</b> <code>{escape_html(cfg['pubkey'])}</code>
📅 <b>Días:</b> {days}
📱 <b>Conexiones máx:</b> {devices}
⏳ <b>Expira:</b> {expires_at[:10]}

━━━━━━━━━━━━━━━━━━━
🔗 <b>Config (importar en la app):</b>
<code>{escape_html(cfg['url'])}</code>
━━━━━━━━━━━━━━━━━━━
"""
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=download_kb)
    try:
        await creando.delete()
    except Exception:
        pass

    context.user_data.clear()
    return ConversationHandler.END


# ==========================================
# CONVERSACIÓN
# ==========================================
create_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_create_ssh, pattern='^create_account$')],
    states={
        CREATE_SSH_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_ssh_user)],
        CREATE_SSH_PASSWORD: [
            CallbackQueryHandler(create_ssh_password_random, pattern='^slip_pass_random$'),
            MessageHandler(filters.TEXT & ~filters.COMMAND, create_ssh_password_manual),
        ],
        CREATE_SSH_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_ssh_days)],
        CREATE_SSH_DEVICES: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_ssh_devices)],
    },
    fallbacks=[]
)