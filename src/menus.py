from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb

import config
from database import Database, RECORD_TYPES
from lib.ui import owner_url

db = Database(config.DB_PATH)

HOME = Btn("🏠 Inicio", callback_data='back_to_main')
ADMIN_HOME = Btn("◀️ Panel", callback_data='admin_panel')


def back(cb: str, label: str = "◀️ Volver") -> Btn:
    return Btn(label, callback_data=cb)


# ==========================================
# USUARIO
# ==========================================
def get_main_menu(is_admin_user: bool = False) -> Kb:
    rows = [
        [Btn("🚀 Crear VayDNS", callback_data='create_account'),
         Btn("🛡️ Crear WireGuard", callback_data='create_wg')],
        [Btn("👤 Mis cuentas", callback_data='my_account'),
         Btn("⭐ Mi plan", callback_data='my_plan')],
        [Btn("📖 Cómo conectar", callback_data='help_menu')],
    ]
    url = owner_url()
    if url:
        rows[-1].append(Btn("💬 Soporte", url=url))
    if is_admin_user:
        rows.append([Btn("🛠️ Panel de administración", callback_data='admin_panel')])
    return Kb(rows)


def get_home_only() -> Kb:
    return Kb([[HOME]])


def get_help_menu() -> Kb:
    return Kb([
        [Btn("🚀 Guía VayDNS", callback_data='help_vaydns'),
         Btn("🛡️ Guía WireGuard", callback_data='help_wg')],
        [Btn("❓ No me conecta", callback_data='help_trouble')],
        [HOME],
    ])


def get_help_back() -> Kb:
    return Kb([[back('help_menu'), HOME]])


def get_password_menu() -> Kb:
    return Kb([
        [Btn("🎲 Generar contraseña segura", callback_data='slip_pass_random')],
        [Btn("✖️ Cancelar", callback_data='flow_cancel')],
    ])


def get_cancel_menu() -> Kb:
    return Kb([[Btn("✖️ Cancelar", callback_data='flow_cancel')]])


def options_menu(prefix: str, opts, per_row: int = 4, suffix: str = '') -> Kb:
    rows, row = [], []
    for o in opts:
        row.append(Btn(f"{o}{suffix}", callback_data=f"{prefix}{o}"))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn("✖️ Cancelar", callback_data='flow_cancel')])
    return Kb(rows)


# ==========================================
# ADMIN
# ==========================================
def get_admin_menu() -> Kb:
    rt = db.get_record_type().upper()
    backend = db.get_backend().upper()
    mode = "🌐 Público" if db.is_public_mode() else "🔒 Privado"
    return Kb([
        [Btn("📊 Dashboard", callback_data='admin_dashboard'),
         Btn("🩺 Diagnóstico", callback_data='admin_diag')],
        [Btn("👥 Cuentas", callback_data='admin_users'),
         Btn("➕ Nueva cuenta", callback_data='admin_create_account')],
        [Btn("🧩 Servicios", callback_data='admin_services'),
         Btn("⭐ Premium", callback_data='admin_premium_menu')],
        [Btn(f"🔀 Record: {rt}", callback_data='admin_record_menu'),
         Btn(f"🔐 Backend: {backend}", callback_data='admin_backend_menu')],
        [Btn("🌐 DNS", callback_data='admin_check_dns'),
         Btn("📡 Tráfico", callback_data='admin_traffic')],
        [Btn("🔄 Regenerar links", callback_data='admin_update_links'),
         Btn("📋 Logs", callback_data='admin_logs')],
        [Btn(f"⚙️ Modo: {mode}", callback_data='admin_settings')],
        [HOME],
    ])


def get_back_admin() -> Kb:
    return Kb([[ADMIN_HOME]])


def get_confirm_menu(action: str, back_cb: str = 'admin_panel') -> Kb:
    return Kb([
        [Btn("✅ Confirmar", callback_data=f'confirm_{action}'),
         Btn("✖️ Cancelar", callback_data=back_cb)],
    ])


def get_services_menu(status: dict) -> Kb:
    """status: {'vaydns': bool, 'wg': bool, 'soar': bool, 'slip': bool, 'master': bool}"""
    def row(key, label, install_cb, uninstall_cb):
        if status.get(key):
            return [Btn(f"🟢 {label}", callback_data='noop'),
                    Btn("🗑️ Quitar", callback_data=uninstall_cb)]
        return [Btn(f"⚪ {label}", callback_data='noop'),
                Btn("📥 Instalar", callback_data=install_cb)]

    return Kb([
        row('vaydns', "VayDNS", 'admin_install_vaydns', 'admin_uninstall_vaydns'),
        row('wg', "WireGuard", 'admin_install_wg', 'admin_uninstall_wg'),
        row('soar', "Soar", 'admin_install_soar', 'admin_uninstall_soar'),
        row('slip', "Slipstream", 'admin_install_slipstream', 'admin_uninstall_slipstream'),
        row('master', "MasterDnsVPN", 'admin_install_masterdns', 'admin_uninstall_masterdns'),
        [Btn("🔄 Actualizar", callback_data='admin_services'), ADMIN_HOME],
    ])


def get_uninstall_menu() -> Kb:
    return Kb([
        [Btn("🗑️ VayDNS", callback_data='admin_uninstall_vaydns'),
         Btn("🗑️ WireGuard", callback_data='admin_uninstall_wg')],
        [Btn("🗑️ Soar", callback_data='admin_uninstall_soar'),
         Btn("🗑️ Slipstream", callback_data='admin_uninstall_slipstream')],
        [Btn("🗑️ MasterDnsVPN", callback_data='admin_uninstall_masterdns')],
        [ADMIN_HOME],
    ])


def get_settings_menu() -> Kb:
    public = db.is_public_mode()
    return Kb([
        [Btn(("✅ " if public else "") + "🌐 Público", callback_data='admin_mode_public'),
         Btn(("✅ " if not public else "") + "🔒 Privado", callback_data='admin_mode_private')],
        [ADMIN_HOME],
    ])


def get_record_menu() -> Kb:
    current = db.get_record_type()
    rows, row = [], []
    for rt in RECORD_TYPES:
        label = f"✅ {rt.upper()}" if rt == current else rt.upper()
        row.append(Btn(label, callback_data=f'admin_set_rt_{rt}'))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([ADMIN_HOME])
    return Kb(rows)


def get_backend_menu() -> Kb:
    current = db.get_backend()
    return Kb([
        [Btn(("✅ " if current == 'ssh' else "") + "🔑 SSH", callback_data='admin_set_ssh'),
         Btn(("✅ " if current == 'socks' else "") + "🧦 SOCKS", callback_data='admin_set_socks')],
        [ADMIN_HOME],
    ])


def get_diag_menu() -> Kb:
    return Kb([
        [Btn("🔧 Reparar todo", callback_data='admin_repair'),
         Btn("🔄 Repetir", callback_data='admin_diag')],
        [ADMIN_HOME],
    ])


def get_vaydns_conflict_menu() -> Kb:
    return Kb([
        [Btn("🗑️ Quitar Slipstream", callback_data='vaydns_uninstall_slipstream')],
        [Btn("🗑️ Quitar MasterDnsVPN", callback_data='vaydns_uninstall_masterdns')],
        [Btn("◀️ Servicios", callback_data='admin_services')],
    ])


def get_slipstream_conflict_menu() -> Kb:
    return Kb([
        [Btn("🗑️ Quitar VayDNS", callback_data='slip_uninstall_vaydns')],
        [Btn("◀️ Servicios", callback_data='admin_services')],
    ])
