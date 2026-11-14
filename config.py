import os
from dotenv import load_dotenv

load_dotenv()

# Configuración del Bot
BOT_TOKEN = os.getenv('BOT_TOKEN', 'TU_TOKEN_AQUI')
ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS', '123456789').split(',')]

# Configuración de la Base de Datos
DB_PATH = os.getenv('DB_PATH', 'vaydns.db')

# ============================================
# CONFIGURACIÓN DEL SERVIDOR
# ============================================

DEFAULT_SERVER = {
    'name': 'Servidor Principal',
    'ip': process.env.DEFAULT_SERVER_IP,
    'ssh_port': process.env.DEFAULT_SERVER_SSH_PORT,
    'username': process.env.DEFAULT_SERVER_USERNAME,
    'password': process.env.DEFAULT_SERVER_PASSWORD,
    'domain': process.env.DEFAULT_SERVER_DOMAIN,
    'tunnel_domain': process.env.DEFAULT_SERVER_TUNNEL_DOMAIN,
    'record_type': process.env.DEFAULT_SERVER_RECORD_TYPE,
    'dnstt_compat': process.env.DEFAULT_SERVER_DNSTT,
    'clientid_size': process.env.DEFAULT_SERVER_CLIENT
    'port': process.env.DEFAULT_SERVER_PORT
}

# Configuración de VayDNS
VAYDNS_BINARY_URL = 'https://raw.githubusercontent.com/phoenixdnsvpn/phoenix-vpn/main/scripts/vaydns-server'
APP_DOWNLOAD_URL = 'https://tu-link-de-descarga.com'
WG_APP_DOWNLOAD_URL = 'https://play.google.com/store/apps/details?id=com.wireguard.android'

# ============================================
# MODO PÚBLICO / PRIVADO
# ============================================
# True = Cualquiera puede crear cuenta
# False = Solo admin y usuarios premium
PUBLIC_MODE = False

# Contacto para usuarios sin acceso
OWNER_CONTACT = '@itschinitaofc'

# Mensaje para usuarios sin acceso
PRIVATE_MESSAGE = f"""
🔒 <b>SISTEMA PRIVADO</b>

Este bot está en modo privado.

Para obtener acceso, contacta al owner:

👤 <b>Owner:</b> {OWNER_CONTACT}

¡Gracias por tu interés! 🙏
"""