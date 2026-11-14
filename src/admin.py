from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, CommandHandler
from lib.masterdnsvpn_manager import MasterDnsVPNManager

import config
from database import Database, RECORD_TYPES
from lib.helpers import is_admin, escape_html
from lib.vaydns_manager import VayDNSManager
from lib.slipstream_manager import SlipstreamManager
from lib.soar_manager import SoarManager
from lib.ssh_accounts_manager import SSHAccountsManager
from lib.wireguard_manager import WireGuardManager
from lib.dns_manager import DNSManager
from src.menus import (
    get_main_menu, get_admin_menu, get_confirm_menu,
    get_uninstall_menu, get_settings_menu, get_record_menu, get_backend_menu,
    get_slipstream_conflict_menu, get_vaydns_conflict_menu
)

db = Database(config.DB_PATH)
vaydns = VayDNSManager(db)
slipstream = SlipstreamManager(db)
masterdns = MasterDnsVPNManager(db)
soar = SoarManager(db)
ssh_accounts = SSHAccountsManager(db)
wireguard = WireGuardManager(db)
dns_manager = DNSManager()

# Estados
ADMIN_CREATE_NAME = 2
ADMIN_CREATE_DAYS = 3

def _human_bytes(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"

def get_server():
    servers = db.get_all_servers()
    if servers:
        return servers[0]

    default = config.DEFAULT_SERVER
    return {
        'id': 0,
        'name': default['name'],
        'ip': default['ip'],
        'ssh_port': default['ssh_port'],
        'username': default['username'],
        'password': default['password'],
        'domain': default['domain'],
        'pubkey': '',
        'is_active': 1,
    }

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
    elif data == 'admin_traffic':
        await show_traffic(query)
    elif data == 'admin_record_menu':
        await show_record_menu(query)
    elif data.startswith('admin_set_rt_'):
        await set_record(query, data[len('admin_set_rt_'):])
    elif data in ('admin_set_txt', 'admin_set_caa'):  # botones viejos
        await set_record(query, data[len('admin_set_'):])
    elif data == 'admin_backend_menu':
        await show_backend_menu(query)
    elif data == 'admin_set_ssh':
        await set_backend(query, 'ssh')
    elif data == 'admin_set_socks':
        await set_backend(query, 'socks')
    elif data == 'noop':
        pass
    elif data == 'admin_install_vaydns':
        return await show_install_vaydns_start(update, context)
    elif data == 'admin_install_soar':
        await query.edit_message_text(
            "🦅 <b>Instalar Soar</b>\n\n"
            "⚠️ Esto apagará VayDNS para usar el puerto 53.\n"
            "Soar y VayDNS no pueden correr al mismo tiempo.\n\n"
            "¿Confirmas la instalación?",
            parse_mode='HTML', reply_markup=get_confirm_menu('install_soar')
        )
    elif data == 'admin_install_wg':
        await show_install_wg_start(query)
    elif data == 'admin_install_slipstream':
        return await show_install_slipstream_start(update, context)
    elif data == 'admin_install_masterdns':
        return await show_install_masterdns_start(update, context)
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
    elif data == 'admin_uninstall_soar':
        await query.edit_message_text(
            "🗑️ <b>Desinstalar Soar</b>\n\n⚠️ ¿Estás seguro?",
            parse_mode='HTML',
            reply_markup=get_confirm_menu('uninstall_soar')
        )
    elif data == 'admin_uninstall_slipstream':
        await query.edit_message_text(
            "🗑️ <b>Desinstalar Slipstream</b>\n\n⚠️ ¿Estás seguro?",
            parse_mode='HTML',
            reply_markup=get_confirm_menu('uninstall_slipstream')
        )
    elif data == 'admin_uninstall_masterdns':
        await query.edit_message_text(
            "🗑️ <b>Desinstalar MasterDnsVPN</b>\n\n⚠️ ¿Estás seguro?",
            parse_mode='HTML',
            reply_markup=get_confirm_menu('uninstall_masterdns')
        )
    elif data == 'admin_check_dns':
        await check_dns(query)
    elif data == 'admin_dashboard':
        await show_dashboard(query)
    elif data == 'admin_logs':
        await show_logs(query)
    elif data == 'admin_users':
        await show_users(query)
    elif data.startswith('admin_detail_'):
        await show_user_detail(query)
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
    elif data == 'vaydns_uninstall_masterdns':
        await query.edit_message_text(
            "🗑️ <b>Desinstalar MasterDnsVPN</b>\n\n"
            "⚠️ Esto eliminará MasterDnsVPN.\n"
            "Después podrás instalar VayDNS.\n\n"
            "¿Confirmas?",
            parse_mode='HTML',
            reply_markup=get_confirm_menu('uninstall_masterdns_first')
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
# TRÁFICO GLOBAL
# ==========================================
async def show_traffic(query):
    servers = db.get_all_servers()
    if not servers:
        await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
        return

    await query.edit_message_text("📡 <b>Consultando tráfico...</b>", parse_mode='HTML')
    data = ssh_accounts.get_traffic(servers[0]['id'])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Actualizar", callback_data='admin_traffic')],
        [InlineKeyboardButton("◀️ Volver", callback_data='admin_panel')]
    ])

    if not data:
        await query.edit_message_text("❌ No se pudo leer el tráfico.", reply_markup=kb)
        return

    text = f"""
📡 <b>Tráfico de Red (total desde el arranque)</b>

⬇️ <b>Descarga:</b> {_human_bytes(data['rx'])}
⬆️ <b>Subida:</b> {_human_bytes(data['tx'])}
"""
    v = data.get('vnstat', '')
    if v and ';' in v:
        p = v.split(';')
        if len(p) >= 12:
            text += (
                "\n━━━━━━━━━━━━━━━━━━━\n"
                "📊 <b>vnstat</b>\n"
                f"• Hoy: ⬇️ {escape_html(p[3])}  ⬆️ {escape_html(p[4])}\n"
                f"• Mes: ⬇️ {escape_html(p[7])}  ⬆️ {escape_html(p[8])}\n"
                f"• Total: ⬇️ {escape_html(p[10])}  ⬆️ {escape_html(p[11])}\n"
            )

    await query.edit_message_text(text, parse_mode='HTML', reply_markup=kb)

# ==========================================
# RECORD TYPE (todos los soportados por VayDNS)
# ==========================================
async def show_record_menu(query):
    current = db.get_record_type().upper()
    text = f"""
🔀 <b>Tipo de Registro DNS</b>

📋 <b>Actual:</b> {current}

• <b>TXT</b> → más estable y rápido (con DNSTT compat). Recomendado.
• <b>CAA</b> / <b>NULL</b> → evasión, para redes que bloquean TXT.
• <b>CNAME</b> / <b>MX</b> / <b>NS</b> / <b>SRV</b> → alternativas cuando otros tipos están filtrados.
• <b>A</b> / <b>AAAA</b> → muy comunes (difíciles de bloquear) pero más lentos.

ℹ️ Solo TXT usa DNSTT compat; el resto va sin compat.
⚠️ Al cambiarlo se reinicia VayDNS y <b>todos los clientes</b> deben usar ese tipo.
"""
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_record_menu())

async def set_record(query, record_type):
    record_type = (record_type or '').lower()
    if record_type not in RECORD_TYPES:
        await query.edit_message_text("❌ Record type inválido.", reply_markup=get_record_menu())
        return

    servers = db.get_all_servers()
    if not servers:
        await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
        return

    await query.edit_message_text(
        f"🔀 <b>Cambiando a {record_type.upper()}...</b>\n\n⏳", parse_mode='HTML')

    result = ssh_accounts.set_server_record_type(servers[0]['id'], record_type)
    if not result['success']:
        await query.edit_message_text(
            f"❌ Error: {escape_html(result.get('error', 'Error'))}",
            parse_mode='HTML', reply_markup=get_admin_menu()
        )
        return

    db.set_record_type(record_type)
    db.add_log('SET_RECORD', f"Record type cambiado a {record_type.upper()}", query.from_user.id)

    await query.edit_message_text(
        f"✅ <b>Servidor ahora en {record_type.upper()}</b>\n\n"
        "Las cuentas nuevas saldrán con este tipo.\n"
        "⚠️ Los clientes actuales deben cambiar su Record Type en la app.",
        parse_mode='HTML', reply_markup=get_admin_menu()
    )

# ==========================================
# BACKEND SSH / SOCKS
# ==========================================
async def show_backend_menu(query):
    current = db.get_backend().upper()
    text = f"""
🔐 <b>Backend de Autenticación</b>

📋 <b>Actual:</b> {current}

• <b>SSH</b> → tope de conexiones real por cuenta. Puede fallar en redes que rompen SSH.
• <b>SOCKS</b> → usuario/contraseña + vencimiento, más estable (ideal Cuba).
  ⚠️ El tope de conexiones queda informativo (no se puede forzar con SOCKS).

En ambos, las cuentas y contraseñas son las mismas.
⚠️ Al cambiar, los clientes deben poner ese protocolo en la app (Authentication Protocol).
"""
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_backend_menu())

async def set_backend(query, backend):
    servers = db.get_all_servers()
    if not servers:
        await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
        return

    await query.edit_message_text(
        f"🔐 <b>Cambiando a {backend.upper()}...</b>\n\n⏳", parse_mode='HTML')

    result = ssh_accounts.apply_backend(servers[0]['id'], backend)
    if not result['success']:
        await query.edit_message_text(
            f"❌ Error: {escape_html(result.get('error', 'Error'))}",
            parse_mode='HTML', reply_markup=get_admin_menu()
        )
        return

    db.add_log('SET_BACKEND', f"Backend cambiado a {backend.upper()}", query.from_user.id)

    proto = 'ssh' if backend == 'ssh' else 'socks'
    await query.edit_message_text(
        f"✅ <b>Backend ahora: {backend.upper()}</b>\n\n"
        "Las cuentas nuevas saldrán con este backend.\n"
        f"⚠️ En la app, los clientes deben poner <b>Authentication Protocol: {proto}</b>.",
        parse_mode='HTML', reply_markup=get_admin_menu()
    )

# ==========================================
# WIREGUARD
# ==========================================
async def show_install_wg_start(query):
    server = get_server()
    server_id = server['id']
    if server_id == 0:
        server_id = db.add_server(
            name=server['name'], ip=server['ip'], ssh_port=server['ssh_port'],
            username=server['username'], password=server['password'], domain=server['domain'],
        )
        db.add_log('AUTO_CREATE_SERVER', f"Servidor auto-creado: {server['name']}", 0)

    if wireguard.is_wireguard_installed(server_id):
        await query.edit_message_text(
            "🛡️ <b>WireGuard</b>\n\n📶 <b>Estado:</b> ✅ Instalado\n\n"
            "Ya podés crear cuentas con el botón 🛡️ WireGuard.",
            parse_mode='HTML', reply_markup=get_admin_menu()
        )
        return

    await query.edit_message_text(
        "🛡️ <b>Instalar WireGuard</b>\n\n"
        "🔌 <b>Puerto:</b> UDP 51820\n"
        "ℹ️ Convive con VayDNS (no se pisan).\n\n"
        "¿Confirmas la instalación?",
        parse_mode='HTML', reply_markup=get_confirm_menu('install_wg')
    )

# ==========================================
# VAYDNS
# ==========================================
async def show_install_vaydns_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    server = get_server()
    server_id = server['id']

    if server_id == 0:
        server_id = db.add_server(
            name=server['name'], ip=server['ip'], ssh_port=server['ssh_port'],
            username=server['username'], password=server['password'], domain=server['domain'],
        )
        db.add_log('AUTO_CREATE_SERVER', f"Servidor auto-creado: {server['name']}", 0)

    if vaydns.is_vaydns_installed(server_id):
        await query.edit_message_text(
            "🚀 <b>VayDNS</b>\n\n📶 <b>Estado:</b> ✅ Instalado\n\n"
            "Si quieres reinstalar, ve a <b>Desinstalar</b> primero.",
            parse_mode='HTML', reply_markup=get_vaydns_conflict_menu()
        )
        return ConversationHandler.END

    if slipstream.is_slipgate_installed(server_id):
        await query.edit_message_text(
            "🚀 <b>Instalar VayDNS</b>\n\n⚠️ <b>Slipstream ya está instalado</b>\n\n"
            "Slipstream usa el puerto <b>53</b>.\n"
            "Para instalar VayDNS, desinstala Slipstream primero.",
            parse_mode='HTML', reply_markup=get_vaydns_conflict_menu()
        )
        return ConversationHandler.END

    default = config.DEFAULT_SERVER
    tunnel = default.get('tunnel_domain', f"d.{'.'.join(default['domain'].split('.')[1:])}")

    await query.edit_message_text(
        f"🚀 <b>Instalación de VayDNS</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Túnel:</b> {escape_html(tunnel)}\n"
        f"🔌 <b>Puerto:</b> 53\n\n"
        f"¿Confirmas la instalación?",
        parse_mode='HTML', reply_markup=get_confirm_menu('install_vaydns')
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
            username=default['username'], password=default['password'], domain=default['domain']
        )
    else:
        server_id = servers[0]['id']

    if slipstream.is_slipgate_installed(server_id):
        await query.edit_message_text(
            "🌀 <b>Slipstream</b>\n\n📶 <b>Estado:</b> ✅ Instalado\n\n"
            "Si quieres reinstalar, ve a <b>Desinstalar</b> primero.",
            parse_mode='HTML', reply_markup=get_admin_menu()
        )
        return ConversationHandler.END

    await query.edit_message_text(
        f"🌀 <b>Instalación de Slipstream</b>\n\n"
        f"📦 <b>Método:</b> Instalación automática\n\n"
        f"¿Confirmas la instalación?",
        parse_mode='HTML', reply_markup=get_confirm_menu('install_slipstream')
    )
    return ConversationHandler.END

# ==========================================
# CONFIRMAR
# ==========================================
async def handle_confirm_action(query, action, context):
    user_id = query.from_user.id

    if action == 'install_wg':
        await query.edit_message_text("🛡️ <b>Instalando WireGuard...</b>\n\n⏳", parse_mode='HTML')
        servers = db.get_all_servers()
        if not servers:
            await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
            return
        result = wireguard.setup_wireguard(servers[0]['id'])
        if result['success']:
            db.add_log('INSTALL_WG', "WireGuard instalado", user_id)
            await query.edit_message_text(
                "✅ <b>¡WireGuard Instalado!</b>\n\n"
                "🔌 UDP 51820 · convive con VayDNS.\n"
                "Creá cuentas con el botón 🛡️ WireGuard.",
                parse_mode='HTML', reply_markup=get_admin_menu()
            )
        else:
            await query.edit_message_text(
                f"❌ <b>Error:</b>\n<code>{escape_html(result.get('error', 'Error'))[:1000]}</code>",
                parse_mode='HTML', reply_markup=get_admin_menu()
            )
        return

    if action == 'install_soar':
        await query.edit_message_text("🦅 <b>Instalando Soar...</b>\n\n⏳", parse_mode='HTML')
        servers = db.get_all_servers()
        if not servers:
            await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
            return
        
        # EL BOT LIMPIA EL PUERTO 53 ANTES DE INSTALAR SOAR
        ssh = soar.connect_ssh(servers[0]['ip'], servers[0]['ssh_port'], servers[0]['username'], servers[0]['password'])
        if ssh:
            soar.run_cmd(ssh, "killall -9 MasterDnsVPN_Se || true", servers[0]['password'], servers[0]['username'])
            soar.run_cmd(ssh, "systemctl stop masterdnsvpn || true", servers[0]['password'], servers[0]['username'])
            ssh.close()

        result = soar.install_soar(servers[0]['id'])
        
        if result['success']:
            db.add_log('INSTALL_SOAR', "Soar instalado", user_id)
            await query.edit_message_text(
                f"✅ <b>¡Soar Instalado!</b>\n\n"
                f"🔑 <b>Pubkey:</b>\n<code>{escape_html(result['pubkey'])}</code>\n\n"
                f"⚠️ Configura el pubkey en Phoenix VPN.",
                parse_mode='HTML', reply_markup=get_admin_menu()
            )
        else:
            await query.edit_message_text(
                f"❌ <b>Error:</b>\n<code>{escape_html(result.get('error', 'Error'))[:1000]}</code>",
                parse_mode='HTML', reply_markup=get_admin_menu()
            )
        return

    if action == 'uninstall_soar':
        await query.edit_message_text("🗑️ <b>Desinstalando Soar...</b>", parse_mode='HTML')
        servers = db.get_all_servers()
        if not servers:
            await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
            return
        
        from lib.soar_manager import SoarManager
        result = soar.uninstall_soar(servers[0]['id'])
        
        if result['success']:
            db.add_log('UNINSTALL_SOAR', "Soar desinstalado", user_id)
            await query.edit_message_text(
                f"✅ {escape_html(result['message'])}",
                parse_mode='HTML', reply_markup=get_admin_menu()
            )
        else:
            await query.edit_message_text(
                f"❌ Error: {escape_html(result.get('error', 'Error'))}",
                parse_mode='HTML', reply_markup=get_admin_menu()
            )
        return

    if action == 'install_vaydns':
        await query.edit_message_text("🚀 <b>Instalando VayDNS...</b>\n\n⏳", parse_mode='HTML')

        default = config.DEFAULT_SERVER
        servers = db.get_all_servers()
        if not servers:
            server_id = db.add_server(
                name=default['name'], ip=default['ip'], ssh_port=default['ssh_port'],
                username=default['username'], password=default['password'], domain=default['domain']
            )
        else:
            server_id = servers[0]['id']

        # EL BOT LIMPIA EL PUERTO 53 ANTES DE INSTALAR VAYDNS
        ssh = vaydns.connect_ssh(servers[0]['ip'], servers[0]['ssh_port'], servers[0]['username'], servers[0]['password'])
        if ssh:
            vaydns.run_cmd(ssh, "killall -9 MasterDnsVPN_Se || true", servers[0]['password'], servers[0]['username'])
            vaydns.run_cmd(ssh, "systemctl stop masterdnsvpn || true", servers[0]['password'], servers[0]['username'])
            ssh.close()

        result = vaydns.install_vaydns(server_id)

        if result['success']:
            ssh_accounts.setup_backend(server_id)
            tunnel = default.get('tunnel_domain', f"d.{'.'.join(default['domain'].split('.')[1:])}")
            db.add_log('INSTALL_VAYDNS', "VayDNS + backend SSH instalado", user_id)

            text = f"""
✅ <b>¡VayDNS Instalado!</b>

🔗 <b>Túnel:</b> {escape_html(tunnel)}
🔌 <b>Puerto DNS:</b> 53
🔐 <b>Backend:</b> SSH (cuentas reales)

Ya podés crear cuentas desde 👥 Cuentas o el botón Crear SSH.
"""
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_admin_menu())
        else:
            await query.edit_message_text(
                f"❌ Error:\n{escape_html(result.get('error', 'Error'))}",
                reply_markup=get_admin_menu()
            )

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
                parse_mode='HTML', reply_markup=get_admin_menu()
            )

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
                parse_mode='HTML', reply_markup=get_admin_menu()
            )

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
                parse_mode='HTML', reply_markup=get_admin_menu()
            )

    elif action == 'install_masterdns':
        await query.edit_message_text(
            "🌐 <b>Instalando MasterDnsVPN...</b>\n\n⏳ Esto puede tardar 1-2 minutos.",
            parse_mode='HTML'
        )
        servers = db.get_all_servers()
        if not servers:
            await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
            return
        default = config.DEFAULT_SERVER
        domain = default.get('domain', '')
        result = masterdns.install_masterdnsvpn(servers[0]['id'], domain=domain)

        if result['success']:
            db.add_log('INSTALL_MASTERDNS', "MasterDnsVPN instalado", user_id)
            text = f"""
✅ <b>¡MasterDnsVPN Instalado!</b>

🌐 <b>Dominio:</b> {escape_html(result.get('domain', 'N/A'))}
🔌 <b>Puerto:</b> 53

🔑 <b>Encryption Key:</b>
<code>{escape_html(result.get('key', 'N/A'))}</code>
"""
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_admin_menu())
        else:
            await query.edit_message_text(
                f"❌ <b>Error instalando MasterDnsVPN:</b>\n\n<code>{escape_html(result.get('error', 'Error'))[:1000]}</code>",
                parse_mode='HTML', reply_markup=get_admin_menu()
            )

    elif action == 'uninstall_masterdns':
        await query.edit_message_text("🗑️ <b>Desinstalando MasterDnsVPN...</b>", parse_mode='HTML')
        servers = db.get_all_servers()
        if not servers:
            await query.edit_message_text("❌ No hay servidor.", reply_markup=get_admin_menu())
            return
        result = masterdns.uninstall_masterdnsvpn(servers[0]['id'])
        if result['success']:
            db.add_log('UNINSTALL_MASTERDNS', "MasterDnsVPN desinstalado", user_id)
            await query.edit_message_text(
                f"✅ {escape_html(result['message'])}",
                parse_mode='HTML', reply_markup=get_admin_menu()
            )
        else:
            await query.edit_message_text(
                f"❌ Error: {escape_html(result.get('error', 'Error'))}",
                parse_mode='HTML', reply_markup=get_admin_menu()
            )

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
                parse_mode='HTML', reply_markup=get_admin_menu()
            )

# ==========================================
# MASTERDNSVPN
# ==========================================
async def show_install_masterdns_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    server = get_server()
    server_id = server['id']

    if server_id == 0:
        server_id = db.add_server(
            name=server['name'], ip=server['ip'], ssh_port=server['ssh_port'],
            username=server['username'], password=server['password'], domain=server['domain'],
        )
        db.add_log('AUTO_CREATE_SERVER', f"Servidor auto-creado: {server['name']}", 0)

    if masterdns.is_masterdns_installed(server_id):
        await query.edit_message_text(
            "🌐 <b>MasterDnsVPN</b>\n\n📶 <b>Estado:</b> ✅ Instalado\n\n"
            "Si quieres reinstalar, desinstálalo primero.",
            parse_mode='HTML', reply_markup=get_admin_menu()
        )
        return ConversationHandler.END

    if vaydns.is_vaydns_installed(server_id):
        await query.edit_message_text(
            "🌐 <b>Instalar MasterDnsVPN</b>\n\n⚠️ <b>VayDNS ya está instalado</b>\n\n"
            "Ambos usan el puerto <b>53</b>. Para instalar MasterDnsVPN, desinstala VayDNS primero.",
            parse_mode='HTML', reply_markup=get_vaydns_conflict_menu()
        )
        return ConversationHandler.END

    if slipstream.is_slipgate_installed(server_id):
        await query.edit_message_text(
            "🌐 <b>Instalar MasterDnsVPN</b>\n\n⚠️ <b>Slipstream ya está instalado</b>\n\n"
            "Desinstálalo primero.",
            parse_mode='HTML', reply_markup=get_admin_menu()
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "🌐 <b>Instalación de MasterDnsVPN</b>\n\n"
        "📦 <b>Método:</b> Instalación automática\n"
        "🔌 <b>Puerto:</b> 53\n\n"
        "¿Confirmas la instalación?",
        parse_mode='HTML', reply_markup=get_confirm_menu('install_masterdns')
    )
    return ConversationHandler.END

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
    record = db.get_record_type().upper()
    logs = db.get_logs(limit=3)
    mode_text = "🌐 Público" if public_mode else "🔒 Privado"

    text = f"""
📊 <b>Dashboard</b>

👥 Cuentas activas: {total_users}
🖥️ Servidores: {total_servers}
⚙️ Modo: {mode_text}
🔀 Record: {record}

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
    text = "👥 <b>Cuentas Registradas</b>\n\nTocá 👁️ para ver el detalle.\n\n"
    keyboard = []
    for user in users[:20]:
        try:
            days = (datetime.fromisoformat(user['expires_at']) - datetime.now()).days
        except (ValueError, TypeError):
            days = 0
        emoji = "🟢" if days > 0 else "🔴"
        text += f"{emoji} <b>{escape_html(user['username'])}</b> — {days}d\n"
        keyboard.append([
            InlineKeyboardButton(f"👁️ {user['username'][:14]}", callback_data=f'admin_detail_{user["id"]}'),
            InlineKeyboardButton("🗑️", callback_data=f'del_user_{user["id"]}'),
        ])

    keyboard.append([InlineKeyboardButton("◀️ Volver", callback_data='admin_panel')])
    await query.edit_message_text(text[:4000], parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def show_user_detail(query):
    account_id = int(query.data.replace('admin_detail_', ''))
    user = db.get_user_by_id(account_id)
    if not user:
        await query.edit_message_text("❌ Cuenta no encontrada.", reply_markup=get_admin_menu())
        return

    try:
        days = (datetime.fromisoformat(user['expires_at']) - datetime.now()).days
    except (ValueError, TypeError):
        days = 0
    estado = "🟢 Activa" if days > 0 else "🔴 Vencida"

    online = ssh_accounts.list_online(user['server_id'], user['username']) if user.get('server_id') else 0
    pass_line = f"🔑 Contraseña: <code>{escape_html(user['password'])}</code>\n" if user.get('password') else ""

    text = f"""
👁️ <b>Detalle de Cuenta</b>

👤 Usuario: <code>{escape_html(user['username'])}</code>
{pass_line}📶 Estado: {estado}
📆 Días restantes: <b>{days}</b>
📱 Conexiones máx: {user.get('max_conn', 3)}
🔌 Conexiones ahora: <b>{online}</b>
📅 Creado: {escape_html(str(user.get('created_at', '')))}
⏳ Expira: {escape_html(str(user.get('expires_at', '')))}

🔗 <b>Config:</b>
<code>{escape_html(user.get('vaydns_url') or 'N/A')}</code>
"""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Eliminar", callback_data=f'del_user_{account_id}')],
        [InlineKeyboardButton("◀️ Volver a cuentas", callback_data='admin_users')],
    ])
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=kb)

async def delete_user_callback(update, context):
    query = update.callback_query
    await query.answer()
    account_id = int(query.data.replace('del_user_', ''))
    user = db.get_user_by_id(account_id)
    if user and user.get('server_id'):
        try:
            if user.get('conn_type') == 'wireguard':
                db.delete_user_by_id(account_id)
                wireguard.rebuild(user['server_id'])
            else:
                ssh_accounts.delete_user(user['server_id'], user['username'])
                db.delete_user_by_id(account_id)
        except Exception as e:
            print(f"Error borrando cuenta: {e}")
            db.delete_user_by_id(account_id)
    else:
        db.delete_user_by_id(account_id)
    db.add_log('DELETE_USER', f"Eliminó cuenta ID {account_id}", query.from_user.id)
    await query.edit_message_text("✅ Cuenta eliminada (bot y servidor).", reply_markup=get_admin_menu())

async def toggle_premium_callback(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.replace('premium_', '').split('_')
    account_id = int(parts[0])
    enabled = parts[1] == '1'
    user = db.get_user_by_id(account_id)
    if user:
        db.set_premium(user['telegram_id'], enabled)
        status = "Premium activado (plan básico)" if enabled else "Premium removido"
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
        "➕ <b>Crear Cuenta (Admin)</b>\n\nEscribe el <b>nombre de usuario</b> (minúsculas):",
        parse_mode='HTML'
    )
    return ADMIN_CREATE_NAME

async def admin_create_name(update, context):
    context.user_data['admin_name'] = update.message.text.strip().lower()
    await update.message.reply_text(
        f"Usuario: <b>{escape_html(context.user_data['admin_name'])}</b>\n\nAhora los <b>días</b>:",
        parse_mode='HTML'
    )
    return ADMIN_CREATE_DAYS

async def admin_create_days(update, context):
    try:
        days = int(update.message.text.strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Número inválido:")
        return ADMIN_CREATE_DAYS

    servers = db.get_all_servers()
    if not servers:
        await update.message.reply_text("❌ Sin servidor.")
        return ConversationHandler.END

    server = servers[0]
    server_id = server['id']
    name = context.user_data.get('admin_name', 'sinnombre')

    if not ssh_accounts.is_backend_installed(server_id):
        await update.message.reply_text("❌ Backend SSH no instalado. Instalá VayDNS primero.")
        return ConversationHandler.END

    password = ssh_accounts.generate_password(12)
    result = ssh_accounts.create_user(server_id, name, password, days, 3)
    if not result['success']:
        await update.message.reply_text(
            f"❌ {escape_html(result.get('error', 'Error'))}",
            parse_mode='HTML', reply_markup=get_admin_menu()
        )
        return ConversationHandler.END

    cfg = ssh_accounts.client_config(server, name, password)
    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    db.add_user_admin(name, server_id, cfg['url'], expires_at, password=password, max_conn=3)
    db.add_log('ADMIN_NEW_USER', f"Admin creó {name} por {days} días", update.effective_user.id)

    text = f"""
✅ <b>Cuenta Creada</b>

👤 <b>Usuario:</b> <code>{escape_html(name)}</code>
🔑 <b>Contraseña:</b> <code>{escape_html(password)}</code>
📅 <b>Días:</b> {days}
📱 <b>Conexiones máx:</b> 3
⏳ <b>Expira:</b> {expires_at[:10]}

🔗 <b>Config:</b>
<code>{escape_html(cfg['url'])}</code>
"""
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=get_admin_menu())
    return ConversationHandler.END

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