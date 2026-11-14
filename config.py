import os
from dotenv import load_dotenv

load_dotenv()

# Configuración del Bot
BOT_TOKEN = os.getenv('BOT_TOKEN', 'TU_TOKEN_AQUI')
ADMIN_IDS = [int(i) for i in os.getenv('ADMIN_IDS', '123456789').replace(' ', '').split(',') if i.strip().isdigit()]

# Configuración de la Base de Datos
DB_PATH = os.getenv('DB_PATH', 'vaydns.db')

# ============================================
# CONFIGURACIÓN DEL SERVIDOR
# ============================================

def _env_int(name: str, default: int) -> int:
    """Lee un entero del .env (ignora comentarios/valores raros)."""
    value = (os.getenv(name) or '').split('#')[0].strip()
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = (os.getenv(name) or '').split('#')[0].strip().lower()
    if not value:
        return default
    return value in ('1', 'true', 'yes', 'si', 'sí', 'on')


def _env_str(name: str, default: str = '') -> str:
    value = os.getenv(name)
    return value.strip() if value else default


DEFAULT_SERVER = {
    'name': 'Servidor Principal',
    'ip': _env_str('DEFAULT_SERVER_IP'),
    'ssh_port': _env_int('DEFAULT_SERVER_SSH_PORT', 22),
    'username': _env_str('DEFAULT_SERVER_USERNAME', 'root'),
    'password': _env_str('DEFAULT_SERVER_PASSWORD'),
    'domain': _env_str('DEFAULT_SERVER_DOMAIN'),
    'tunnel_domain': _env_str('DEFAULT_SERVER_TUNNEL_DOMAIN'),
    'record_type': _env_str('DEFAULT_SERVER_RECORD_TYPE', 'txt').lower(),
    'dnstt_compat': _env_bool('DEFAULT_SERVER_DNSTT', True),
    'clientid_size': _env_int('DEFAULT_SERVER_CLIENT', 8),
    'port': _env_int('DEFAULT_SERVER_PORT', 53),
}

# Si no se definió dominio de túnel, quitarlo para que el código use el automático (d.<dominio>)
if not DEFAULT_SERVER['tunnel_domain']:
    DEFAULT_SERVER.pop('tunnel_domain')

# Configuración de VayDNS
VAYDNS_BINARY_URL = 'https://raw.githubusercontent.com/phoenixdnsvpn/phoenix-vpn/main/scripts/vaydns-server'
APP_DOWNLOAD_URL = _env_str('APP_DOWNLOAD_URL', 'https://tu-link-de-descarga.com')
WG_APP_DOWNLOAD_URL = 'https://play.google.com/store/apps/details?id=com.wireguard.android'

# ============================================
# MODO PÚBLICO / PRIVADO
# ============================================
# True = Cualquiera puede crear cuenta
# False = Solo admin y usuarios premium
PUBLIC_MODE = _env_bool('PUBLIC_MODE', False)

# Contacto para usuarios sin acceso
OWNER_CONTACT = _env_str('OWNER_CONTACT', '@itschinitaofc')

# Mensaje para usuarios sin acceso
PRIVATE_MESSAGE = f"""
🔒 <b>SISTEMA PRIVADO</b>

Este bot está en modo privado.

Para obtener acceso, contacta al owner:

👤 <b>Owner:</b> {OWNER_CONTACT}

¡Gracias por tu interés! 🙏
"""