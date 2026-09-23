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
    'ip': '89.777777',
    'ssh_port': 22,
    'username': 'root',
    'password': 'TU_CONTRASEÑA_AQUI',
    'domain': 'TU_DNS_TIPO_A_AQUI',
    'tunnel_domain': 'TU_DNS_TIPO_NS_AQUI',
    'record_type': 'txt',
    'dnstt_compat': True,
    'clientid_size': 8,
    'port': 53
}

# Configuración de VayDNS
VAYDNS_BINARY_URL = 'https://raw.githubusercontent.com/phoenixdnsvpn/phoenix-vpn/main/scripts/vaydns-server'

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