"""
src/cards.py  —  Tarjetas de cuenta (lo que ve el cliente) reutilizadas por usuario y admin.
"""
from io import BytesIO

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb

import config
from database import Database
from lib.ui import header, kv, code, esc, b, expiry, fmt_date, tip, quote
from lib.ssh_accounts_manager import SSHAccountsManager
from lib.wireguard_manager import WireGuardManager, WG_PORT

try:
    import qrcode
    HAS_QR = True
except Exception:
    HAS_QR = False

db = Database(config.DB_PATH)
ssh_accounts = SSHAccountsManager(db)
wg = WireGuardManager(db)


def vaydns_cfg(account: dict) -> dict:
    """Config del cliente SIEMPRE con la config actual del servidor (record, backend, pubkey)."""
    server = db.get_server(account['server_id']) or {}
    return ssh_accounts.client_config(server, account['username'], account.get('password') or '')


def vaydns_card(account: dict, title: str = None) -> str:
    cfg = vaydns_cfg(account)
    proto = "SSH" if cfg['auth_proto'] == 'ssh' else "SOCKS"
    lines = [
        header("🚀", title or f"VayDNS · {account['username']}", "Túnel DNS — ideal para redes restringidas"),
        kv("👤", "Usuario", code(account['username'])),
        kv("🔑", "Contraseña", code(account.get('password') or '—')),
        kv("📅", "Vence", f"{b(fmt_date(account['expires_at']))} · {expiry(account['expires_at'])}"),
        kv("📱", "Conexiones", b(account.get('max_conn') or 3)),
        "",
        "<b>⚙️ Datos para la app</b>",
        kv("🌐", "Dominio", code(cfg['tunnel'])),
        kv("🗝️", "Public key", code(cfg['pubkey'] or 'pendiente')),
        kv("🔀", "Record type", b(cfg['record_type'].upper())),
        kv("🔐", "Protocolo", b(proto)),
        kv("🧩", "DNSTT compat", b('Sí' if cfg['dnstt_compat'] == 'true' else 'No')),
        "",
        "<b>🔗 Link de importación</b> <i>(tocá para copiar)</i>",
        code(cfg['url']),
        tip("Copiá el link y en la app tocá <b>Importar</b>. Se cargan todos los datos solos."),
    ]
    return "\n".join(lines)


def wg_conf_for(account: dict) -> str:
    server = db.get_server(account['server_id']) or {'ip': ''}
    endpoint = f"{wg.endpoint_host(server)}:{WG_PORT}"
    return wg.client_conf(account.get('wg_privkey', ''), account.get('wg_ip', ''),
                          db.get_config('wg_pubkey') or '', endpoint)


def wg_card(account: dict, title: str = None) -> str:
    return "\n".join([
        header("🛡️", title or f"WireGuard · {account['username']}", "VPN directa — máxima velocidad"),
        kv("👤", "Nombre", code(account['username'])),
        kv("🌐", "IP interna", code(account.get('wg_ip', ''))),
        kv("📅", "Vence", f"{b(fmt_date(account['expires_at']))} · {expiry(account['expires_at'])}"),
        "",
        quote("📱 <b>Cómo conectar</b>\n"
              "1. Instalá la app <b>WireGuard</b>.\n"
              "2. Tocá <b>+</b> → <b>Escanear QR</b> (o <b>Importar</b> el archivo .conf).\n"
              "3. Activá el interruptor y listo ✅"),
    ])


async def send_wg_files(message, account: dict, reply_markup=None):
    """Manda el .conf y el QR al chat."""
    conf = wg_conf_for(account)
    name = account['username']
    doc = BytesIO(conf.encode())
    doc.name = f"{name}.conf"
    await message.reply_document(document=doc, filename=f"{name}.conf",
                                 caption=f"📄 <b>{esc(name)}.conf</b> — importalo en la app WireGuard",
                                 parse_mode='HTML')
    if HAS_QR:
        img = qrcode.make(conf)
        bio = BytesIO()
        img.save(bio, format='PNG')
        bio.seek(0)
        await message.reply_photo(photo=bio, caption="📷 Escaneá este QR desde WireGuard (+ → Escanear QR)",
                                  reply_markup=reply_markup)
    elif reply_markup:
        await message.reply_text("📱 Importá el archivo .conf en la app WireGuard.", reply_markup=reply_markup)


def app_buttons(kind: str):
    if kind == 'wireguard':
        url = getattr(config, 'WG_APP_DOWNLOAD_URL', '')
        guide = 'help_wg'
    else:
        url = getattr(config, 'APP_DOWNLOAD_URL', '')
        guide = 'help_vaydns'
    row = []
    if url and url.startswith('http') and 'tu-link' not in url:
        row.append(Btn("📥 Descargar app", url=url))
    row.append(Btn("📖 Guía", callback_data=guide))
    return row


def created_keyboard(kind: str) -> Kb:
    return Kb([app_buttons(kind), [Btn("👤 Mis cuentas", callback_data='my_account'),
                                   Btn("🏠 Inicio", callback_data='back_to_main')]])
