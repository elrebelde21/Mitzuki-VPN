from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config
from database import Database

db = Database(config.DB_PATH)


def get_main_menu(is_admin_user: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("👤 Account", callback_data='my_account')],
        [InlineKeyboardButton("➕ Crear SSH", callback_data='create_account')],
        [InlineKeyboardButton("🛡️ WireGuard", callback_data='create_wg')],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("⚙️ Panel Admin", callback_data='admin_panel')])
    return InlineKeyboardMarkup(keyboard)


def get_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 VayDNS", callback_data='admin_install_vaydns')],
        [InlineKeyboardButton("🦅 Soar", callback_data='admin_install_soar')],
        [InlineKeyboardButton("🛡️ WireGuard", callback_data='admin_install_wg')],
        [InlineKeyboardButton("🌀 Slipstream", callback_data='admin_install_slipstream')],
        [InlineKeyboardButton("🌐 MasterDnsVPN", callback_data='admin_install_masterdns')],
        [InlineKeyboardButton("🗑️ Desinstalar", callback_data='admin_uninstall_menu')],
        [InlineKeyboardButton("🌐 Verificar DNS", callback_data='admin_check_dns')],
        [InlineKeyboardButton("📊 Dashboard", callback_data='admin_dashboard')],
        [InlineKeyboardButton("⭐ Dar Premium", callback_data='admin_premium')],
        [InlineKeyboardButton("📡 Tráfico", callback_data='admin_traffic')],
        [InlineKeyboardButton("🔀 Record", callback_data='admin_record_menu')],
        [InlineKeyboardButton("🔐 Backend", callback_data='admin_backend_menu')],
        [InlineKeyboardButton("📋 Ver Logs", callback_data='admin_logs')],
        [InlineKeyboardButton("👥 Cuentas", callback_data='admin_users')],
        [InlineKeyboardButton("🔄 Actualizar Links", callback_data='admin_update_links')],
        [InlineKeyboardButton("⚙️ Configuración", callback_data='admin_settings')],
        [InlineKeyboardButton("◀️ Volver", callback_data='back_to_main')],
    ])


def get_confirm_menu(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar", callback_data=f'confirm_{action}')],
        [InlineKeyboardButton("❌ Cancelar", callback_data='cancel_action')],
    ])


def get_uninstall_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ VayDNS", callback_data='admin_uninstall_vaydns')],
        [InlineKeyboardButton("🗑️ Soar", callback_data='admin_uninstall_soar')],
        [InlineKeyboardButton("🗑️ Slipstream", callback_data='admin_uninstall_slipstream')],
        [InlineKeyboardButton("🗑️ MasterDnsVPN", callback_data='admin_uninstall_masterdns')],
        [InlineKeyboardButton("◀️ Volver", callback_data='admin_panel')],
    ])


def get_settings_menu() -> InlineKeyboardMarkup:
    public_mode = db.is_public_mode()
    mode_text = "🌐 Público" if public_mode else "🔒 Privado"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Modo: {mode_text}", callback_data='admin_toggle_mode')],
        [InlineKeyboardButton("◀️ Volver", callback_data='admin_panel')],
    ])


def get_record_menu() -> InlineKeyboardMarkup:
    """Toggle TXT/CAA del servidor (admin)."""
    current = db.get_record_type().upper()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Actual: {current}", callback_data='noop')],
        [InlineKeyboardButton("📄 Usar TXT", callback_data='admin_set_txt'),
         InlineKeyboardButton("🔤 Usar CAA", callback_data='admin_set_caa')],
        [InlineKeyboardButton("◀️ Volver", callback_data='admin_panel')],
    ])


def get_backend_menu() -> InlineKeyboardMarkup:
    """Toggle de backend de autenticación: SSH o SOCKS."""
    current = db.get_backend().upper()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Actual: {current}", callback_data='noop')],
        [InlineKeyboardButton("🔑 Usar SSH", callback_data='admin_set_ssh'),
         InlineKeyboardButton("🧦 Usar SOCKS", callback_data='admin_set_socks')],
        [InlineKeyboardButton("◀️ Volver", callback_data='admin_panel')],
    ])


def get_slipstream_conflict_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ VayDNS", callback_data='slip_uninstall_vaydns')],
        [InlineKeyboardButton("❌ Cancelar", callback_data='cancel_action')],
    ])


def get_vaydns_conflict_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Slipstream", callback_data='vaydns_uninstall_slipstream')],
        [InlineKeyboardButton("❌ Cancelar", callback_data='cancel_action')],
    ])


def get_password_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Generar Aleatoria", callback_data='slip_pass_random')],
        [InlineKeyboardButton("❌ Cancelar", callback_data='cancel_action')],
    ])