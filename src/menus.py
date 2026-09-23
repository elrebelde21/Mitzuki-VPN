from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config
from database import Database

db = Database(config.DB_PATH)


def get_main_menu(is_admin_user: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📊 Estado", callback_data='status')],
        [InlineKeyboardButton("👤 Account", callback_data='my_account')],
        [InlineKeyboardButton("➕ Crear SSH", callback_data='create_account')],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("⚙️ Panel Admin", callback_data='admin_panel')])
    return InlineKeyboardMarkup(keyboard)


def get_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 VayDNS", callback_data='admin_install_vaydns')],
        [InlineKeyboardButton("🌀 Slipstream", callback_data='admin_install_slipstream')],
        [InlineKeyboardButton("🗑️ Desinstalar", callback_data='admin_uninstall_menu')],
        [InlineKeyboardButton("🌐 Verificar DNS", callback_data='admin_check_dns')],
        [InlineKeyboardButton("📊 Dashboard", callback_data='admin_dashboard')],
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
        [InlineKeyboardButton("🗑️ Slipstream", callback_data='admin_uninstall_slipstream')],
        [InlineKeyboardButton("◀️ Volver", callback_data='admin_panel')],
    ])


def get_settings_menu() -> InlineKeyboardMarkup:
    public_mode = db.is_public_mode()
    mode_text = "🌐 Público" if public_mode else "🔒 Privado"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Modo: {mode_text}", callback_data='admin_toggle_mode')],
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