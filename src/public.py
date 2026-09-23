from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ConversationHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

import config
from database import Database
from lib.helpers import is_admin, escape_html, can_create_account
from src.menus import get_main_menu, get_password_menu
from lib.vaydns_manager import VayDNSManager
from lib.slipstream_manager import SlipstreamManager

db = Database(config.DB_PATH)
vaydns = VayDNSManager(db)
slipstream = SlipstreamManager(db)

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


async def show_my_account(query):
    data = db.get_user(query.from_user.id)
    if not data:
        await query.edit_message_text(
            "❌ <b>No tienes un SSH activo</b>\n\n💡 Usa el botón Crear SSH.",
            parse_mode='HTML',
            reply_markup=get_main_menu(False)
        )
        return

    expires = datetime.fromisoformat(data['expires_at'])
    days = (expires - datetime.now()).days

    if days < 0:
        db.deactivate_user(query.from_user.id)
        await query.edit_message_text(
            "⛔ <b>Tu SSH ha expirado</b>",
            parse_mode='HTML',
            reply_markup=get_main_menu(False)
        )
        return

    text = f"""
👤 <b>Mi SSH</b>

👤 Usuario: {escape_html(data['username'])}
🖥️ Servidor: {escape_html(data['server_name'])}
📅 Creado: {escape_html(data['created_at'])}
⏳ Expira: {escape_html(data['expires_at'])}
📆 Días restantes: <b>{days}</b>

🔗 <b>Link:</b>
<code>{escape_html(data['vaydns_url'])}</code>
"""
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_main_menu(False))


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
        await show_my_account(query)
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

    # Admin NO tiene límite: puede crear múltiples SSH
    # Usuarios normales: solo 1 activo
    if not is_admin(user_id):
        if db.get_user(user_id):
            await reply(
                "❌ <b>Ya tienes un SSH activo</b>\n\nUsa el botón Mi SSH.",
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
        "(Ejemplo: cliente1, juan, maria)",
        parse_mode='HTML'
    )
    return CREATE_SSH_USER


async def create_ssh_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.text.strip()
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
    password = slipstream.generate_password(12)
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

    user = context.user_data.get('ssh_user', 'user')
    days = context.user_data.get('ssh_days', 30)
    password = context.user_data.get('ssh_password', slipstream.generate_password(12))

    servers = db.get_all_servers()
    if not servers:
        await update.message.reply_text("❌ No hay servidor.")
        return ConversationHandler.END

    server = servers[0]
    server_id = server['id']
    user_id = update.effective_user.id

    # Detectar qué backend está instalado
    vaydns_ok = vaydns.is_vaydns_installed(server_id)
    slipgate_ok = slipstream.is_slipgate_installed(server_id)

    if not vaydns_ok and not slipgate_ok:
        await update.message.reply_text(
            "❌ <b>No hay backend instalado</b>\n\n"
            "Pide al admin que instale VayDNS o Slipstream.",
            parse_mode='HTML',
            reply_markup=get_main_menu(is_admin(user_id))
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"🌀 <b>Creando SSH '{escape_html(user)}'...</b>\n\n⏳",
        parse_mode='HTML'
    )

    # ─── SLIPSTREAM ───
    if slipgate_ok:
        result = slipstream.create_user(server_id, user, password)

        if not result['success']:
            await update.message.reply_text(
                f"❌ <b>Error creando SSH:</b>\n\n{escape_html(result.get('error', 'Error'))}",
                parse_mode='HTML',
                reply_markup=get_main_menu(is_admin(user_id))
            )
            context.user_data.clear()
            return ConversationHandler.END

        # Aplicar límite de conexiones
        slipstream.set_user_limit(server_id, user, devices)

        # Guardar en DB
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()
        db.add_user(user_id, user, server_id, result['url'], expires_at)
        db.add_log('CREATE_SSH_SLIP', f"SSH {user} creado ({days}d, {devices} conexiones) - Slipstream", user_id)

        text = f"""
✅ <b>¡SSH Creado!</b>

━━━━━━━━━━━━━━━━━━━
📋 <b>Datos</b>
━━━━━━━━━━━━━━━━━━━
👤 <b>Usuario:</b> <code>{escape_html(user)}</code>
🔑 <b>Contraseña:</b> <code>{escape_html(password)}</code>
📅 <b>Días:</b> {days}
📱 <b>Conexiones máx:</b> {devices}
⏳ <b>Expira:</b> {expires_at[:10]}

━━━━━━━━━━━━━━━━━━━
🔗 <b>Enlace SlipNet:</b>
<code>{escape_html(result['url'])}</code>

━━━━━━━━━━━━━━━━━━━
📱 <b>Instrucciones:</b>
1️⃣ Abrir SlipNet
2️⃣ Menú (3 puntos) → Import Profiles
3️⃣ Pegar el enlace
4️⃣ Guardar y conectar
"""
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=get_main_menu(is_admin(user_id)))

    # ─── VAYDNS ───
    else:
        pubkey = server.get('pubkey') or ''
        if not pubkey:
            await update.message.reply_text(
                "❌ Servidor sin pubkey. Reinstala VayDNS.",
                reply_markup=get_main_menu(is_admin(user_id))
            )
            context.user_data.clear()
            return ConversationHandler.END

        default = config.DEFAULT_SERVER
        tunnel = default.get('tunnel_domain', f"d.{'.'.join(server['domain'].split('.')[1:])}")
        url = (
            f"dnst://{tunnel}/vaydns/socks5?"
            f"pubkey={pubkey}&record-type={default.get('record_type', 'txt')}"
            f"&clientid-size={default.get('clientid_size', 8)}"
            f"&keepalive=2s&idle-timeout=10s"
            f"&dnstt-compat={'true' if default.get('dnstt_compat', True) else 'false'}"
            f"#vaydns"
        )
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()

        db.add_user(user_id, user, server_id, url, expires_at)
        db.add_log('CREATE_SSH_VAYDNS', f"SSH {user} creado ({days}d) - VayDNS", user_id)

        text = f"""
✅ <b>¡SSH Creado!</b>

━━━━━━━━━━━━━━━━━━━
📋 <b>Datos</b>
━━━━━━━━━━━━━━━━━━━
👤 <b>Usuario:</b> <code>{escape_html(user)}</code>
🔑 <b>Contraseña:</b> <code>{escape_html(password)}</code>
📅 <b>Días:</b> {days}
📱 <b>Conexiones máx:</b> {devices}
⏳ <b>Expira:</b> {expires_at[:10]}

━━━━━━━━━━━━━━━━━━━
🔗 <b>Enlace VayDNS:</b>
<code>{escape_html(url)}</code>
"""
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=get_main_menu(is_admin(user_id)))

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