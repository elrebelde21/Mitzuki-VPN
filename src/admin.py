from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, CommandHandler

import config
from database import Database
from lib.helpers import is_admin, escape_html
from lib.vaydns_manager import VayDNSManager
from lib.slipstream_manager import SlipstreamManager
from lib.dns_manager import DNSManager
from src.menus import (
    get_main_menu, get_admin_menu, get_confirm_menu,
    get_uninstall_menu, get_settings_menu,
    get_slipstream_conflict_menu, get_vaydns_conflict_menu
)

db = Database(config.DB_PATH)
vaydns = VayDNSManager(db)
slipstream = SlipstreamManager(db)
dns_manager = DNSManager()

# Estados
ADMIN_CREATE_NAME = 2
ADMIN_CREATE_DAYS = 3

# ==========================================
# BOTONES ADMIN
# ==========================================
async def button_handler_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)
    data = query.data

    if not is_admin_user:
        await query.answer("⛔ Solo admin", show_alert=True)
        return

    if data == 'admin_panel':
        await query.edit_message_text(
            "⚙️ <b>Panel de Administración</b>\n\nSelecciona una opción:",
            parse_mode='HTML',
            reply_markup=get_admin_menu()
        )
    elif data == 'admin_settings':
        await show_settings(query)
    elif data == 'admin_toggle_mode':
        await toggle_mode(query)
    elif data == 'admin_install_vaydns':
        return await show_install_vaydns_start(update, context)
    elif data == 'admin_install_slipstream':
        return await show_install_slipstream_start(update, context)
    elif data == 'admin_uninstall_menu':
        await query.edit_message_text(
            "🗑️ <b>Desinstalar</b>\n\n¿Qué quieres desinstalar?",
            parse_mode='HTML',
            reply_markup=get_uninstall_menu()
        )
    elif data == 'admin_uninstall_vaydns':
        await query.edit_message_text(
            "🗑️ <b>Desinstalar VayDNS</b>\n\n⚠️ ¿Estás seguro?",
            parse_mode='HTML',
            reply_markup=get_confirm_menu('uninstall_vaydns')
        )
    elif data == 'admin_uninstall_slipstream':
        await query.edit_message_text(
            "🗑️ <b>Desinstalar Slipstream</b>\n\n⚠️ ¿Estás seguro?",
            parse_mode='HTML',
            reply_markup=get_confirm_menu('uninstall_slipstream')
        )
    elif data == 'admin_check_dns':
        await check_dns(query)
    elif data == 'admin_dashboard':
        await show_dashboard(query)
    elif data == 'admin_logs':
        await show_logs(query)
    elif data == 'admin_users':
        await show_users(query)
    elif data == 'admin_create_account':
        return await admin_start_create(update, context)
    elif data == 'admin_update_links':
        await admin_update_links(update, context)
    elif data.startswith('del_user_'):
        await delete_user_callback(update, context)
    elif data.startswith('premium_'):
        await toggle_premium_callback(update, context)
    elif data == 'slip_uninstall_vaydns':
        await query.edit_message_text(
            "🗑️ <b>Desinstalar VayDNS</b>\n\n"
            "⚠️ Esto eliminará VayDNS.\n"
            "Después podrás instalar Slipstream.\n\n"
            "¿Confirmas?",
            parse_mode='HTML',
            reply_markup=get_confirm_menu('uninstall_vaydns_first')
        )
    elif data == 'vaydns_uninstall_slipstream':
        await query.edit_message_text(
            "🗑️ <b>Desinstalar Slipstream</b>\n\n"
            "⚠️ Esto eliminará Slipstream.\n"
            "Después podrás instalar VayDNS.\n\n"
            "¿Confirmas?",
            parse_mode='HTML',
            reply_markup=get_confirm_menu('vaydns_uninstall_slipstream')
        )
    elif data.startswith('confirm_'):
        action = data.replace('confirm_', '')
        await handle_confirm_action(query, action, context)
    elif data == 'cancel_action':
        await query.edit_message_text(
            "❌ Acción cancelada.",
            reply_markup=get_main_menu(is_admin_user)
        )


# ==========================================
# SETTINGS
# ==========================================
async def show_settings(query):
    public_mode = db.is_public_mode()
    mode_text = "🌐 Público" if public_mode else "🔒 Privado"

    text = f"""
⚙️ <b>Configuración del Bot</b>

━━━━━━━━━━━━━━━━━━━
📋 <b>Modo Actual:</b> {mode_text}
━━━━━━━━━━━━━━━━━━━

<b>🌐 Modo Público:</b> Cualquiera puede crear cuenta
<b>🔒 Modo Privado:</b> Solo admin y premium
"""
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_settings_menu())


async def toggle_mode(query):
    current = db.is_public_mode()
    new_mode = not current
    db.set_public_mode(new_mode)
    mode_text = "🌐 Público" if new_mode else "🔒 Privado"
    db.add_log('TOGGLE_MODE', f"Modo cambiado a {mode_text}", query.from_user.id)
    await query.answer(f"Modo cambiado a {mode_text}", show_alert=True)
    await show_settings(query)


# ==========================================
# VAYDNS
# ==========================================
async def show_install_vaydns_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    servers = db.get_all_servers()
    server_id = None

    if servers:
        server_id = servers[0]['id']

        # ¿Ya está VayDNS instalado?
        vaydns_installed = vaydns.is_vaydns_installed(server_id)
        if vaydns_installed:
            await query.edit_message_text(
                "🚀 <b>VayDNS</b>\n\n"
                "📶 <b>Estado:</b> ✅ Instalado\n\n"
                "Si quieres reinstalar, ve a <b>Desinstalar</b> primero.",
                parse_mode='HTML',
                reply_markup=get_vaydns_conflict_menu()
            )
            return ConversationHandler.END

        # ¿Slipstream instalado? Conflicto
        slipstream_installed = slipstream.is_slipstream_installed(server_id)
        if slipstream_installed:
            await query.edit_message_text(
                "🚀 <b>Instalar VayDNS</b>\n\n"
                "⚠️ <b>Slipstream ya está instalado</b>\n\n"
                "Slipstream usa el puerto <b>53</b>.\n"
                "Para instalar VayDNS, desinstala Slipstream primero.",
                parse_mode='HTML',
                reply_markup=get_vaydns_conflict_menu()
            )
            return ConversationHandler.END

    # Mostrar confirmación
    default = config.DEFAULT_SERVER
    tunnel = default.get('tunnel_domain', f"d.{'.'.join(default['domain'].split('.')[1:])}")

    await query.edit_message_text(
        f"🚀 <b>Instalación de VayDNS</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Configuración</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>IP:</b> {escape_html(default['ip'])}\n"
        f"🖥️ <b>Servidor:</b> {escape_html(default['domain'])}\n"
        f"🔗 <b>Túnel:</b> {escape_html(tunnel)}\n"
        f"🔌 <b>Puerto:</b> 53\n\n"
        f"¿Confirmas la instalación?",
        parse_mode='HTML',
        reply_markup=get_confirm_menu('install_vaydns')
    )
    return ConversationHandler.END


# ==========================================
# SLIPSTREAM
# ==========================================
async def show_install_slipstream_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    servers = db.get_all_servers()
    if not servers:
        default = config.DEFAULT_SERVER
        server_id = db.add_server(
            name=default['name'], ip=default['ip'], ssh_port=default['ssh_port'],
            username=default['username'], password=default['password'],
            domain=default['domain']
        )
    else:
        server_id = servers[0]['id']

    slipgate_installed = slipstream.is_slipgate_installed(server_id)

    # ─── Si YA está instalado → solo muestra estado ───
    if slipgate_installed:
        await query.edit_message_text(
            "🌀 <b>Slipstream</b>\n\n"
            "📶 <b>Estado:</b> ✅ Instalado\n\n"
            "Si quieres reinstalar, ve a <b>Desinstalar</b> primero.",
            parse_mode='HTML',
            reply_markup=get_admin_menu()
        )
        return ConversationHandler.END

    # ─── Si NO está instalado → mostrar confirmación de instalación ───
    default = config.DEFAULT_SERVER
    await query.edit_message_text(
        f"🌀 <b>Instalación de Slipstream</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Configuración</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>IP:</b> {escape_html(default['ip'])}\n"
        f"🖥️ <b>Servidor:</b> {escape_html(default['domain'])}\n"
        f"📦 <b>Método:</b> Instalación automática\n\n"
        f"¿Confirmas la instalación?",
        parse_mode='HTML',
        reply_markup=get_confirm_menu('install_slipstream')
    )
    return ConversationHandler.END


# ==========================================
# CONFIRMAR
# ==========================================
async def handle_confirm_action(query, action, context):
    user_id = query.from_user.id

    # ==========================================
    # INSTALAR VAYDNS
    # ==========================================
    if action == 'install_vaydns':
        await query.edit_message_text("🚀 <b>Instalando VayDNS...</b>\n\n⏳", parse_mode='HTML')

        default = config.DEFAULT_SERVER
        servers = db.get_all_servers()
        if not servers:
            server_id = db.add_server(
                name=default['name'], ip=default['ip'], ssh_port=default['ssh_port'],
                username=default['username'], password=default['password'],
                domain=default['domain']
            )
        else:
            server_id = servers[0]['id']

        result = vaydns.install_vaydns(server_id)

        if result['success']:
            tunnel = default.get('tunnel_domain', f"d.{'.'.join(default['domain'].split('.')[1:])}")
            urls = result.get('urls', [])
            db.add_log('INSTALL_VAYDNS', "VayDNS instalado", user_id)

            text = f"""
✅ <b>¡VayDNS Instalado!</b>

━━━━━━━━━━━━━━━━━━━
📋 <b>Datos del Servidor</b>
━━━━━━━━━━━━━━━━━━━
🌐 <b>Dominio:</b> {escape_html(default['domain'])}
📡 <b>IP:</b> {escape_html(default['ip'])}
🔗 <b>Túnel:</b> {escape_html(tunnel)}
🔌 <b>Puerto DNS:</b> 53

━━━━━━━━━━━━━━━━━━━
🔗 <b>URL Cliente:</b>
<code>{escape_html(urls[0]) if urls else 'No disponible'}</code>
"""
            await query.edit_message_text(text, parse_mode='HTML')
        else:
            await query.edit_message_text(
                f"❌ Error:\n{escape_html(result.get('error', 'Error'))}",
            )

    # ==========================================
    # DESINSTALAR VAYDNS
    # ==========================================
    elif action == 'uninstall_vaydns':
        await query.edit_message_text("🗑️ <b>Desinstalando VayDNS...</b>", parse_mode='HTML')
        servers = db.get_all_servers()
        if not servers:
            await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
            return
        result = vaydns.uninstall_vaydns(servers[0]['id'])
        if result['success']:
            db.add_log('UNINSTALL_VAYDNS', "VayDNS desinstalado", user_id)
            await query.edit_message_text(
                f"✅ {escape_html(result['message'])}",
                parse_mode='HTML',
                reply_markup=get_admin_menu()
            )

    # ==========================================
    # DESINSTALAR SLIPSTREAM
    # ==========================================
    elif action == 'uninstall_slipstream':
        await query.edit_message_text("🗑️ <b>Desinstalando Slipstream...</b>", parse_mode='HTML')
        servers = db.get_all_servers()
        if not servers:
            await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
            return
        result = slipstream.uninstall_slipstream(servers[0]['id'])
        if result['success']:
            db.add_log('UNINSTALL_SLIPSTREAM', "Slipstream desinstalado", user_id)
            await query.edit_message_text(
                f"✅ {escape_html(result['message'])}",
                parse_mode='HTML',
                reply_markup=get_admin_menu()
            )

    # ==========================================
    # DESINSTALAR VAYDNS (para instalar Slipstream)
    # ==========================================
    elif action == 'uninstall_vaydns_first':
        await query.edit_message_text("🗑️ <b>Desinstalando VayDNS...</b>", parse_mode='HTML')
        servers = db.get_all_servers()
        if not servers:
            await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
            return
        result = vaydns.uninstall_vaydns(servers[0]['id'])
        if result['success']:
            db.add_log('UNINSTALL_VAYDNS', "VayDNS desinstalado para Slipstream", user_id)
            await query.edit_message_text(
                "✅ <b>VayDNS desinstalado</b>\n\nAhora instala Slipstream.",
                parse_mode='HTML',
                reply_markup=get_admin_menu()
            )

    # ==========================================
    # DESINSTALAR SLIPSTREAM (para instalar VayDNS)
    # ==========================================
    elif action == 'vaydns_uninstall_slipstream':
        await query.edit_message_text("🗑️ <b>Desinstalando Slipstream...</b>", parse_mode='HTML')
        servers = db.get_all_servers()
        if not servers:
            await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
            return
        result = slipstream.uninstall_slipstream(servers[0]['id'])
        if result['success']:
            db.add_log('UNINSTALL_SLIPSTREAM', "Slipstream desinstalado para VayDNS", user_id)
            await query.edit_message_text(
                "✅ <b>Slipstream desinstalado</b>\n\nAhora instala VayDNS.",
                parse_mode='HTML',
                reply_markup=get_admin_menu()
            )


# ==========================================
# DNS / LOGS / USERS
# ==========================================
async def check_dns(query):
    servers = db.get_all_servers()
    if not servers:
        await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
        return

    server = servers[0]
    domain = server['domain']
    ip = server['ip']
    tunnel = config.DEFAULT_SERVER.get('tunnel_domain', f"d.{'.'.join(domain.split('.')[1:])}")

    await query.edit_message_text("🔍 <b>Verificando DNS...</b>", parse_mode='HTML')
    result = dns_manager.verify_dns_records(domain, ip, tunnel)
    a_status = "✅" if result['a_record'] else "❌"
    ns_status = "✅" if result['ns_record'] else "❌"

    text = f"""
🌐 <b>Verificación DNS</b>

<b>Registro A</b> ({escape_html(domain)})
{a_status} {escape_html(result['a_record_value'] or 'No configurado')}

<b>Registro NS</b> ({escape_html(tunnel)})
{ns_status} {escape_html(result['ns_record_value'] or 'No configurado')}
"""
    if result['errors']:
        text += "\n⚠️ <b>Errores:</b>\n"
        for error in result['errors']:
            text += f"• {escape_html(error)}\n"

    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Verificar", callback_data='admin_check_dns')],
        [InlineKeyboardButton("◀️ Volver", callback_data='admin_panel')]
    ]))


async def show_logs(query):
    logs = db.get_logs(limit=10)
    if not logs:
        await query.edit_message_text("📋 Sin logs.", reply_markup=get_admin_menu())
        return
    text = "📋 <b>Últimos Logs</b>\n\n"
    for log in logs[:10]:
        text += f"📌 {escape_html(log['action'])}\n   🕐 {escape_html(log['created_at'])}\n\n"
    await query.edit_message_text(text[:4000], parse_mode='HTML', reply_markup=get_admin_menu())


async def show_dashboard(query):
    total_users = db.get_active_users_count()
    total_servers = len(db.get_all_servers())
    public_mode = db.is_public_mode()
    logs = db.get_logs(limit=3)
    mode_text = "🌐 Público" if public_mode else "🔒 Privado"

    text = f"""
📊 <b>Dashboard</b>

👥 Cuentas activas: {total_users}
🖥️ Servidores: {total_servers}
⚙️ Modo: {mode_text}

📌 <b>Últimas acciones:</b>
"""
    for log in logs:
        text += f"\n• {escape_html(log['action'])} - {escape_html(log['created_at'])}"
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_admin_menu())


async def show_users(query):
    users = db.get_all_users()
    if not users:
        await query.edit_message_text("👥 Sin cuentas.", reply_markup=get_admin_menu())
        return
    text = "👥 <b>Cuentas Registradas</b>\n\n"
    keyboard = []
    for user in users[:15]:
        expires = datetime.fromisoformat(user['expires_at'])
        days = (expires - datetime.now()).days
        emoji = "🟢" if days > 0 else "🔴"
        premium = "⭐" if user.get('is_premium') else ""
        text += f"{emoji}{premium} <b>{escape_html(user['username'])}</b> - {days}d (ID:{user['id']})\n"

        row = [InlineKeyboardButton(f"🗑️ {user['username'][:10]}", callback_data=f'del_user_{user["id"]}')]
        if user.get('is_premium'):
            row.append(InlineKeyboardButton("❌ Quitar Premium", callback_data=f'premium_{user["id"]}_0'))
        else:
            row.append(InlineKeyboardButton("⭐ Premium", callback_data=f'premium_{user["id"]}_1'))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("◀️ Volver", callback_data='admin_panel')])
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def delete_user_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.replace('del_user_', ''))
    db.delete_user_by_id(user_id)
    db.add_log('DELETE_USER', f"Eliminó cuenta ID {user_id}", query.from_user.id)
    await query.edit_message_text("✅ Cuenta eliminada.", reply_markup=get_admin_menu())


async def toggle_premium_callback(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.replace('premium_', '').split('_')
    user_id = int(parts[0])
    enabled = parts[1] == '1'
    user = db.get_user_by_id(user_id)
    if user:
        db.set_premium(user['telegram_id'], enabled)
        status = "Premium activado" if enabled else "Premium removido"
        db.add_log('TOGGLE_PREMIUM', f"{status} para {user['username']}", query.from_user.id)
        await query.answer(f"✅ {status}", show_alert=True)
    await show_users(query)


# ==========================================
# ADMIN CREAR CUENTA
# ==========================================
async def admin_start_create(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "➕ <b>Crear Cuenta (Admin)</b>\n\nEscribe el <b>nombre</b>:",
        parse_mode='HTML'
    )
    return ADMIN_CREATE_NAME


async def admin_create_name(update, context):
    context.user_data['admin_name'] = update.message.text.strip()
    await update.message.reply_text(
        f"Nombre: <b>{escape_html(context.user_data['admin_name'])}</b>\n\nAhora los <b>días</b>:",
        parse_mode='HTML'
    )
    return ADMIN_CREATE_DAYS


async def admin_create_days(update, context):
    try:
        days = int(update.message.text.strip())
        if days <= 0:
            raise ValueError

        servers = db.get_all_servers()
        if not servers:
            await update.message.reply_text("❌ Sin servidor.")
            return ConversationHandler.END

        server = servers[0]
        name = context.user_data.get('admin_name', 'SinNombre')
        pubkey = server.get('pubkey') or ''
        if not pubkey:
            await update.message.reply_text("❌ Sin pubkey.")
            return ConversationHandler.END

        default = config.DEFAULT_SERVER
        tunnel = default.get('tunnel_domain', f"d.{'.'.join(server['domain'].split('.')[1:])}")
        url = f"dnst://{tunnel}/vaydns/socks5?pubkey={pubkey}&record-type={default.get('record_type', 'txt')}&clientid-size={default.get('clientid_size', 8)}&keepalive=2s&idle-timeout=10s&dnstt-compat={'true' if default.get('dnstt_compat', True) else 'false'}#vaydns"
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()

        db.add_user_admin(name, server['id'], url, expires_at)
        db.add_log('ADMIN_NEW_USER', f"Admin creó {name} por {days} días", update.effective_user.id)

        text = f"""
✅ <b>Cuenta Creada</b>

👤 {escape_html(name)}
📅 {days} días
⏳ {escape_html(expires_at)}

🔗 <code>{escape_html(url)}</code>
"""
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=get_admin_menu())
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Número inválido:")
        return ADMIN_CREATE_DAYS


# ==========================================
# UPDATE LINKS
# ==========================================
async def admin_update_links(update, context):
    query = update.callback_query
    await query.answer()
    servers = db.get_all_servers()
    if not servers:
        await query.edit_message_text("❌ Sin servidor.", reply_markup=get_admin_menu())
        return

    server = servers[0]
    pubkey = server.get('pubkey') or ''
    if not pubkey:
        result = vaydns.get_server_status(server['id'])
        pubkey = result.get('pubkey', '')
    if not pubkey:
        await query.edit_message_text("❌ Sin pubkey.", reply_markup=get_admin_menu())
        return

    db.update_all_user_urls(pubkey)
    db.update_server_pubkey(server['id'], pubkey)
    db.add_log('UPDATE_LINKS', "Links actualizados", query.from_user.id)

    await query.edit_message_text(
        f"✅ <b>Links actualizados</b>\n\nPubkey: <code>{escape_html(pubkey[:40])}...</code>",
        parse_mode='HTML', reply_markup=get_admin_menu()
    )


# ==========================================
# CONVERSACIONES
# ==========================================
admin_create_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_start_create, pattern='^admin_create_account$')],
    states={
        ADMIN_CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_create_name)],
        ADMIN_CREATE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_create_days)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: u.message.reply_text("❌ Cancelado."))],
)