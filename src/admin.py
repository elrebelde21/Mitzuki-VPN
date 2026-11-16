"""
src/admin.py  —  Panel de administración.

Todo lo que toca la VPS corre en segundo plano (bg) para no congelar el bot.
"""
from telegram import Update, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb
from telegram.ext import ContextTypes

import config
from database import Database, RECORD_TYPES
from lib.helpers import is_admin
from lib.runtime import uptime_str
from lib.ui import (header, kv, code, b, esc, tip, warn, quote, dot, bar, expiry, fmt_date,
                    days_left, human_bytes, bg, safe_edit)
from lib.vaydns_manager import VayDNSManager, tunnel_domain_for
from lib.slipstream_manager import SlipstreamManager
from lib.soar_manager import SoarManager
from lib.masterdnsvpn_manager import MasterDnsVPNManager
from lib.ssh_accounts_manager import SSHAccountsManager
from lib.wireguard_manager import WireGuardManager, WG_PORT
from lib.diagnostics import run_diagnostics, services_status
from src.menus import (get_admin_menu, get_back_admin, get_confirm_menu, get_settings_menu, get_record_menu,
                       get_backend_menu, get_services_menu, get_diag_menu, get_vaydns_conflict_menu,
                       get_slipstream_conflict_menu, ADMIN_HOME)
from src.cards import vaydns_card, wg_card, send_wg_files
from src.public import delete_account

db = Database(config.DB_PATH)
vaydns = VayDNSManager(db)
slipstream = SlipstreamManager(db)
masterdns = MasterDnsVPNManager(db)
soar = SoarManager(db)
ssh_accounts = SSHAccountsManager(db)
wireguard = WireGuardManager(db)

PAGE = 8


def _server():
    return db.ensure_default_server()


def _no_server_text() -> str:
    return (f"{header('⚠️', 'Servidor no configurado')}\n"
            "Completá en el <code>.env</code>:\n"
            "<code>DEFAULT_SERVER_IP</code>, <code>DEFAULT_SERVER_PASSWORD</code>, "
            "<code>DEFAULT_SERVER_DOMAIN</code> y reiniciá el bot.")


def regenerate_links(server) -> int:
    """Rearma el link de TODAS las cuentas VayDNS con la config actual del servidor."""
    n = 0
    for u in db.get_vaydns_users():
        if u.get('password'):
            cfg = ssh_accounts.client_config(server, u['username'], u['password'])
            db.update_user_url(u['id'], cfg['url'])
            n += 1
    return n


# ==========================================
# ROUTER
# ==========================================
async def button_handler_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Solo administradores", show_alert=True)
        return
    try:
        await query.answer()
    except Exception:
        pass

    routes = {
        'admin_panel': show_panel,
        'admin_dashboard': show_dashboard,
        'admin_diag': show_diag,
        'admin_check_dns': show_dns,
        'admin_repair': do_repair,
        'admin_services': show_services,
        'admin_settings': show_settings,
        'admin_mode_public': lambda q: set_mode(q, True),
        'admin_mode_private': lambda q: set_mode(q, False),
        'admin_toggle_mode': lambda q: set_mode(q, not db.is_public_mode()),
        'admin_traffic': show_traffic,
        'admin_record_menu': show_record_menu,
        'admin_backend_menu': show_backend_menu,
        'admin_set_ssh': lambda q: set_backend(q, 'ssh'),
        'admin_set_socks': lambda q: set_backend(q, 'socks'),
        'admin_logs': show_logs,
        'admin_users': lambda q: show_users(q, 0),
        'admin_create_account': show_new_account,
        'admin_update_links': do_update_links,
        'admin_premium_menu': show_premium_menu,
        'admin_install_vaydns': ask_install_vaydns,
        'admin_install_wg': ask_install_wg,
        'admin_install_soar': ask_install_soar,
        'admin_install_slipstream': ask_install_slipstream,
        'admin_install_masterdns': ask_install_masterdns,
        'admin_uninstall_menu': show_services,
        'slip_uninstall_vaydns': lambda q: ask_uninstall(q, 'vaydns'),
        'vaydns_uninstall_slipstream': lambda q: ask_uninstall(q, 'slipstream'),
        'vaydns_uninstall_masterdns': lambda q: ask_uninstall(q, 'masterdns'),
        'noop': None,
    }
    if data in routes:
        if routes[data]:
            await routes[data](query)
        return

    if data.startswith('admin_set_rt_'):
        await set_record(query, data[len('admin_set_rt_'):])
    elif data.startswith('admin_uninstall_'):
        await ask_uninstall(query, data[len('admin_uninstall_'):])
    elif data.startswith('admin_users_p'):
        await show_users(query, int(data[len('admin_users_p'):]))
    elif data.startswith('admin_detail_'):
        await show_user_detail(query, int(data[len('admin_detail_'):]))
    elif data.startswith('admin_renew_'):
        _, _, acc_id, days = data.split('_')
        await renew_user(query, int(acc_id), int(days))
    elif data.startswith('admin_send_'):
        await resend_account(query, int(data[len('admin_send_'):]))
    elif data.startswith('del_user_'):
        await ask_delete_user(query, int(data[len('del_user_'):]))
    elif data.startswith('admin_delok_'):
        await delete_user(query, int(data[len('admin_delok_'):]))
    elif data.startswith('admin_unprem_'):
        await revoke_premium(query, int(data[len('admin_unprem_'):]))
    elif data.startswith('confirm_'):
        await handle_confirm_action(query, data[len('confirm_'):])


# ==========================================
# PANEL / DASHBOARD
# ==========================================
def panel_text() -> str:
    counts = db.count_by_type()
    server = db.get_all_servers()
    s = server[0] if server else None
    lines = [
        header('🛠️', 'Panel de administración', config.BOT_NAME),
        kv("🖥️", "VPS", code(s['ip']) if s else "<i>sin configurar</i>"),
        kv("👥", "Cuentas", f"{b(counts['vaydns'])} VayDNS · {b(counts['wireguard'])} WireGuard"),
        kv("🔀", "Record", b(db.get_record_type().upper())) + "   " + kv("🔐", "Backend", b(db.get_backend().upper())),
        tip("¿Alguien no conecta? Abrí <b>🩺 Diagnóstico</b> y tocá <b>🔧 Reparar todo</b>."),
    ]
    return "\n".join(lines)


async def show_panel(query):
    _server()
    await safe_edit(query, panel_text(), get_admin_menu())


async def show_dashboard(query):
    counts = db.count_by_type()
    total = counts['vaydns'] + counts['wireguard']
    expiring = db.count_expiring(3)
    s = _server()
    logs = db.get_logs(limit=5)
    lines = [
        header('📊', 'Dashboard'),
        "<b>Cuentas</b>",
        kv("🚀", "VayDNS", b(counts['vaydns'])),
        kv("🛡️", "WireGuard", b(counts['wireguard'])),
        kv("⏰", "Vencen en ≤3 días", b(expiring)),
        kv("⭐", "Premium activos", b(db.count_resellers())),
        "",
        "<b>Servidor</b>",
        kv("🖥️", "IP", code(s['ip']) if s else '—'),
        kv("🌐", "Túnel", code(tunnel_domain_for(s)) if s else '—'),
        kv("🔀", "Record / Backend", b(f"{db.get_record_type().upper()} / {db.get_backend().upper()}")),
        kv("⚙️", "Modo", b("Público" if db.is_public_mode() else "Privado")),
        kv("⏱️", "Bot activo hace", b(uptime_str())),
        "",
        "<b>Últimas acciones</b>",
    ]
    for log in logs:
        lines.append(f"• <code>{esc(str(log['created_at'])[5:16])}</code> {esc(log['action'])} "
                     f"<i>{esc((log.get('details') or '')[:45])}</i>")
    if not total:
        lines.append(tip("Todavía no hay cuentas. Creá una desde <b>➕ Nueva cuenta</b>."))
    await safe_edit(query, "\n".join(lines), Kb([[Btn("🔄 Actualizar", callback_data='admin_dashboard'), ADMIN_HOME]]))


# ==========================================
# DIAGNÓSTICO / REPARAR
# ==========================================
def _render_checks(title: str, checks) -> str:
    lines = [header('🩺', title)]
    bad = 0
    for c in checks:
        if c['ok'] is False:
            bad += 1
        detail = f" — <i>{esc(c['detail'])}</i>" if c['detail'] else ""
        lines.append(f"{dot(c['ok'])} {esc(c['name'])}{detail}")
        if c['ok'] is False and c.get('fix'):
            lines.append(f"      ↳ {esc(c['fix'])}")
    lines.append("")
    if bad:
        lines.append(warn(f"Hay <b>{bad}</b> problema(s). Tocá <b>🔧 Reparar todo</b>; si queda algo en rojo, "
                          "seguí la indicación de esa línea."))
    else:
        lines.append(quote("✅ <b>Todo en orden.</b> Si un cliente no conecta, que copie de nuevo su link "
                           "desde 👤 Mis cuentas."))
    return "\n".join(lines)


async def show_diag(query):
    s = _server()
    if not s:
        await safe_edit(query, _no_server_text(), get_back_admin())
        return
    await safe_edit(query, f"{header('🩺', 'Diagnóstico')}\n⏳ Revisando VPS, servicios, DNS y firewall...")
    res = await bg(run_diagnostics, db, s)
    await safe_edit(query, _render_checks('Diagnóstico', res['checks']), get_diag_menu())


async def show_dns(query):
    s = _server()
    if not s:
        await safe_edit(query, _no_server_text(), get_back_admin())
        return
    await safe_edit(query, f"{header('🌐', 'DNS')}\n⏳ Consultando registros...")
    res = await bg(run_diagnostics, db, s)
    checks = [c for c in res['checks'] if c['name'].startswith(('DNS', 'Prueba', 'Conexión'))]
    tunnel = tunnel_domain_for(s)
    text = _render_checks('Verificación DNS', checks or res['checks'])
    text += "\n\n" + quote(
        "<b>Registros que tenés que tener</b>\n"
        f"A   <code>{esc(s['domain'])}</code> → <code>{esc(s['ip'])}</code>  (Cloudflare: nube gris)\n"
        f"NS  <code>{esc(tunnel)}</code> → <code>{esc(s['domain'])}</code>")
    await safe_edit(query, text, Kb([[Btn("🔄 Verificar", callback_data='admin_check_dns'), ADMIN_HOME]]))


async def do_repair(query):
    s = _server()
    if not s:
        await safe_edit(query, _no_server_text(), get_back_admin())
        return
    await safe_edit(query, f"{header('🔧', 'Reparando')}\n⏳ Reaplicando VayDNS, backend, WireGuard y firewall...\n"
                           "<i>Puede tardar hasta un minuto.</i>")
    lines = [header('🔧', 'Reparación')]
    r = await bg(vaydns.apply_service, s['id'])
    if r['success']:
        lines.append("🟢 VayDNS + backend reaplicados")
        status = await bg(vaydns.get_server_status, s['id'])
        if status.get('pubkey') and status['pubkey'] != s.get('pubkey'):
            db.update_server_pubkey(s['id'], status['pubkey'])
            s = db.get_server(s['id'])
        n = regenerate_links(s)
        lines.append(f"🟢 {n} link(s) VayDNS regenerados")
    elif 'no está instalado' in r.get('error', ''):
        lines.append("⚪ VayDNS no instalado")
    else:
        lines.append(f"🔴 VayDNS: {esc(r.get('error', ''))[:400]}")

    r = await bg(wireguard.rebuild, s['id'], True)
    if r['success']:
        lines.append(f"🟢 WireGuard reiniciado ({len(db.get_wg_users(s['id']))} clientes)")
    elif 'no está instalado' in r.get('error', ''):
        lines.append("⚪ WireGuard no instalado")
    else:
        lines.append(f"🔴 WireGuard: {esc(r.get('error', ''))[:400]}")

    db.add_log('REPAIR', "Reparación completa", query.from_user.id)
    lines.append(tip("Corré <b>🩺 Diagnóstico</b> otra vez para confirmar que todo quedó en verde."))
    await safe_edit(query, "\n".join(lines),
                    Kb([[Btn("🩺 Diagnóstico", callback_data='admin_diag'), ADMIN_HOME]]))


# ==========================================
# SERVICIOS (instalar / quitar)
# ==========================================
async def show_services(query):
    s = _server()
    if not s:
        await safe_edit(query, _no_server_text(), get_back_admin())
        return
    await safe_edit(query, f"{header('🧩', 'Servicios')}\n⏳ Consultando la VPS...")
    st = await bg(services_status, s)
    if not st['ssh_ok']:
        await safe_edit(query, f"{header('🧩', 'Servicios')}\n🔴 No se pudo conectar a la VPS por SSH.\n"
                               + tip("Revisá IP, puerto y contraseña en el <code>.env</code>."),
                        Kb([[Btn("🔄 Reintentar", callback_data='admin_services'), ADMIN_HOME]]))
        return
    text = "\n".join([
        header('🧩', 'Servicios', f"VPS {s['ip']}"),
        f"{dot(st['vaydns'] or None)} <b>VayDNS</b> — túnel DNS (puerto 53)",
        f"{dot(st['wg'] or None)} <b>WireGuard</b> — VPN directa (puerto {WG_PORT})",
        f"{dot(st['soar'] or None)} <b>Soar</b> — túnel DNS alternativo",
        f"{dot(st['slip'] or None)} <b>Slipstream</b> — túnel alternativo",
        f"{dot(st['master'] or None)} <b>MasterDnsVPN</b> — túnel DNS alternativo",
        "",
        warn("VayDNS, Soar, Slipstream y MasterDnsVPN usan el puerto 53: <b>solo uno a la vez</b>. "
             "WireGuard convive con cualquiera."),
    ])
    await safe_edit(query, text, get_services_menu(st))


async def ask_install_vaydns(query):
    s = _server()
    if not s:
        await safe_edit(query, _no_server_text(), get_back_admin())
        return
    tunnel = tunnel_domain_for(s)
    await safe_edit(query, "\n".join([
        header('🚀', 'Instalar VayDNS'),
        kv("🖥️", "VPS", code(s['ip'])),
        kv("🅰️", "Dominio A", code(s['domain'])),
        kv("🌐", "Túnel (NS)", code(tunnel)),
        kv("🔀", "Record", b(db.get_record_type().upper())),
        kv("🔐", "Backend", b(db.get_backend().upper())),
        "",
        quote("Se instala el servidor, el backend de cuentas, se libera el puerto 53 y se abre el firewall.\n"
              "Si ya estaba instalado, se <b>actualiza</b> conservando la clave (los links siguen sirviendo)."),
        tip("Tarda 1-3 minutos."),
    ]), get_confirm_menu('install_vaydns', 'admin_services'))


async def ask_install_wg(query):
    await safe_edit(query, "\n".join([
        header('🛡️', 'Instalar WireGuard'),
        kv("🔌", "Puerto", b(f"UDP {WG_PORT}")),
        quote("Convive con VayDNS. Se configura NAT, reenvío IPv4 y firewall automáticamente.\n"
              "Si ya estaba instalado, se repara sin perder clientes."),
        warn(f"Si tu proveedor (Oracle, AWS, Google...) tiene firewall propio, abrí ahí el <b>UDP {WG_PORT}</b>."),
    ]), get_confirm_menu('install_wg', 'admin_services'))


async def ask_install_soar(query):
    await safe_edit(query, f"{header('🦅', 'Instalar Soar')}\n"
                           + warn("Esto <b>apaga VayDNS</b>: Soar necesita el puerto 53."),
                    get_confirm_menu('install_soar', 'admin_services'))


async def ask_install_slipstream(query):
    await safe_edit(query, f"{header('🌀', 'Instalar Slipstream')}\n"
                           + warn("Usa el puerto 53: si VayDNS está activo, quitalo primero."),
                    get_confirm_menu('install_slipstream', 'admin_services'))


async def ask_install_masterdns(query):
    await safe_edit(query, f"{header('🌐', 'Instalar MasterDnsVPN')}\n"
                           + warn("Usa el puerto 53 y <b>detiene VayDNS</b>."),
                    get_confirm_menu('install_masterdns', 'admin_services'))


UNINSTALL_NAMES = {'vaydns': '🚀 VayDNS', 'wg': '🛡️ WireGuard', 'soar': '🦅 Soar',
                   'slipstream': '🌀 Slipstream', 'masterdns': '🌐 MasterDnsVPN'}


async def ask_uninstall(query, what: str):
    name = UNINSTALL_NAMES.get(what)
    if not name:
        await show_services(query)
        return
    extra = ""
    if what == 'vaydns':
        extra = warn("Las cuentas VayDNS dejan de conectar hasta que lo vuelvas a instalar.")
    elif what == 'wg':
        extra = warn("Los clientes WireGuard dejan de conectar. Las llaves se conservan.")
    await safe_edit(query, f"{header('🗑️', 'Quitar ' + name)}\n¿Confirmás?\n{extra}",
                    get_confirm_menu(f'uninstall_{what}', 'admin_services'))


async def _result(query, ok: bool, title: str, body: str = '', back='admin_services'):
    icon = '✅' if ok else '❌'
    await safe_edit(query, f"{header(icon, title)}\n{body}",
                    Kb([[Btn("◀️ Servicios", callback_data=back), ADMIN_HOME]]))


async def handle_confirm_action(query, action: str):
    uid = query.from_user.id
    s = _server()
    if not s:
        await safe_edit(query, _no_server_text(), get_back_admin())
        return
    sid = s['id']

    if action == 'install_vaydns':
        await safe_edit(query, f"{header('🚀', 'Instalando VayDNS')}\n⏳ Instalando paquetes, binario y servicios...\n"
                               "<i>No cierres el chat, tarda 1-3 minutos.</i>")
        await bg(_stop_masterdns, s)
        r = await bg(vaydns.install_vaydns, sid)
        if r['success']:
            s = db.get_server(sid)
            n = regenerate_links(s)
            db.add_log('INSTALL_VAYDNS', f"VayDNS instalado ({db.get_record_type()}/{db.get_backend()})", uid)
            await _result(query, True, '¡VayDNS instalado!', "\n".join([
                kv("🌐", "Túnel", code(tunnel_domain_for(s))),
                kv("🗝️", "Public key", code(r['pubkey'])),
                kv("🔀", "Record", b(db.get_record_type().upper())),
                kv("🔐", "Backend", b(db.get_backend().upper())),
                kv("🔄", "Links actualizados", b(n)),
                tip("Corré <b>🩺 Diagnóstico</b> para confirmar DNS y conexión de punta a punta."),
            ]))
        else:
            await _result(query, False, 'No se pudo instalar VayDNS', f"<code>{esc(r.get('error'))[:1500]}</code>")

    elif action == 'install_wg':
        await safe_edit(query, f"{header('🛡️', 'Instalando WireGuard')}\n⏳ Tarda menos de un minuto...")
        r = await bg(wireguard.setup_wireguard, sid)
        if r['success']:
            db.add_log('INSTALL_WG', "WireGuard instalado", uid)
            await _result(query, True, '¡WireGuard instalado!',
                          f"{kv('🔌', 'Puerto', b(f'UDP {WG_PORT}'))}\n"
                          f"{kv('🗝️', 'Llave pública', code(r['server_pubkey']))}\n"
                          + tip("Ya se pueden crear cuentas con 🛡️ Crear WireGuard."))
        else:
            await _result(query, False, 'No se pudo instalar WireGuard', f"<code>{esc(r.get('error'))[:1500]}</code>")

    elif action == 'install_soar':
        await safe_edit(query, f"{header('🦅', 'Instalando Soar')}\n⏳ ...")
        await bg(_stop_masterdns, s)
        r = await bg(soar.install_soar, sid)
        if r['success']:
            db.add_log('INSTALL_SOAR', "Soar instalado", uid)
            await _result(query, True, '¡Soar instalado!', kv("🗝️", "Pubkey", code(r.get('pubkey', ''))))
        else:
            await _result(query, False, 'No se pudo instalar Soar', f"<code>{esc(r.get('error'))[:1500]}</code>")

    elif action == 'install_slipstream':
        if await bg(vaydns.is_vaydns_installed, sid):
            await safe_edit(query, f"{header('🌀', 'Slipstream')}\n" + warn("VayDNS está activo en el puerto 53."),
                            get_slipstream_conflict_menu())
            return
        await safe_edit(query, f"{header('🌀', 'Instalando Slipstream')}\n⏳ ...")
        r = await bg(slipstream.install_slipstream, sid)
        db.add_log('INSTALL_SLIPSTREAM', "Slipstream instalado" if r.get('success') else "Falló", uid)
        await _result(query, r.get('success', False), 'Slipstream ' + ('instalado' if r.get('success') else 'falló'),
                      esc(r.get('message') or r.get('error') or ''))

    elif action == 'install_masterdns':
        if await bg(slipstream.is_slipgate_installed, sid):
            await safe_edit(query, f"{header('🌐', 'MasterDnsVPN')}\n" + warn("Slipstream está instalado."),
                            get_vaydns_conflict_menu())
            return
        await safe_edit(query, f"{header('🌐', 'Instalando MasterDnsVPN')}\n⏳ Tarda 1-2 minutos...")
        r = await bg(masterdns.install_masterdnsvpn, sid, s.get('domain'))
        if r['success']:
            db.add_log('INSTALL_MASTERDNS', "MasterDnsVPN instalado", uid)
            await _result(query, True, '¡MasterDnsVPN instalado!',
                          f"{kv('🌐', 'Dominio', code(r.get('domain', '')))}\n"
                          f"{kv('🔑', 'Encryption key', code(r.get('key', '')))}")
        else:
            await _result(query, False, 'No se pudo instalar MasterDnsVPN', f"<code>{esc(r.get('error'))[:1500]}</code>")

    elif action in ('uninstall_vaydns_first', 'vaydns_uninstall_slipstream', 'uninstall_masterdns_first'):
        # compat con botones viejos
        await handle_confirm_action(query, {'uninstall_vaydns_first': 'uninstall_vaydns',
                                            'vaydns_uninstall_slipstream': 'uninstall_slipstream',
                                            'uninstall_masterdns_first': 'uninstall_masterdns'}[action])

    elif action.startswith('uninstall_'):
        what = action[len('uninstall_'):]
        await safe_edit(query, f"{header('🗑️', 'Quitando ' + UNINSTALL_NAMES.get(what, what))}\n⏳ ...")
        fn = {'vaydns': vaydns.uninstall_vaydns, 'wg': wireguard.uninstall_wireguard,
              'soar': soar.uninstall_soar, 'slipstream': slipstream.uninstall_slipstream,
              'masterdns': masterdns.uninstall_masterdnsvpn}.get(what)
        if not fn:
            await show_services(query)
            return
        r = await bg(fn, sid)
        db.add_log(f'UNINSTALL_{what.upper()}', "Desinstalado" if r.get('success') else "Falló", uid)
        await _result(query, r.get('success', False),
                      f"{UNINSTALL_NAMES.get(what)} " + ('quitado' if r.get('success') else 'no se pudo quitar'),
                      esc(r.get('message') or r.get('error') or ''))


def _stop_masterdns(server):
    ssh = vaydns._connect(server)
    if ssh:
        try:
            vaydns.run_cmd(ssh, "systemctl stop masterdnsvpn 2>/dev/null; killall -9 MasterDnsVPN_Se 2>/dev/null; true",
                           server['password'], server['username'])
        finally:
            ssh.close()


# ==========================================
# RECORD TYPE / BACKEND / MODO
# ==========================================
RT_INFO = {
    'txt': "el más estable y rápido · DNSTT compat ⭐ recomendado",
    'caa': "evasión para redes que bloquean TXT",
    'null': "mucha capacidad por respuesta · evasión",
    'cname': "alternativa cuando TXT/CAA están filtrados",
    'mx': "alternativa", 'ns': "alternativa", 'srv': "alternativa",
    'a': "muy común (difícil de bloquear) pero lento",
    'aaaa': "muy común, algo más rápido que A",
}


async def show_record_menu(query):
    current = db.get_record_type()
    lines = [header('🔀', 'Record type', f"Actual: {current.upper()}")]
    for rt in RECORD_TYPES:
        mark = "✅" if rt == current else "▫️"
        lines.append(f"{mark} <b>{rt.upper()}</b> — {RT_INFO.get(rt, '')}")
    lines.append(warn("Al cambiarlo se reinicia VayDNS. Los clientes deben <b>copiar de nuevo su link</b> "
                      "desde 👤 Mis cuentas (se actualiza solo)."))
    await safe_edit(query, "\n".join(lines), get_record_menu())


async def set_record(query, record_type: str):
    record_type = (record_type or '').lower()
    if record_type not in RECORD_TYPES:
        await show_record_menu(query)
        return
    s = _server()
    if not s:
        await safe_edit(query, _no_server_text(), get_back_admin())
        return
    await safe_edit(query, f"{header('🔀', 'Cambiando record type')}\n⏳ Aplicando {b(record_type.upper())} en la VPS...")
    r = await bg(ssh_accounts.set_server_record_type, s['id'], record_type)
    if not r['success']:
        await safe_edit(query, f"{header('❌', 'No se pudo cambiar')}\n<code>{esc(r.get('error'))[:1200]}</code>",
                        get_record_menu())
        return
    n = regenerate_links(db.get_server(s['id']))
    db.add_log('SET_RECORD', f"Record type → {record_type.upper()}", query.from_user.id)
    await safe_edit(query, "\n".join([
        header('✅', f"Record type: {record_type.upper()}"),
        kv("🧩", "DNSTT compat", b('Sí' if record_type == 'txt' else 'No')),
        kv("🔄", "Links actualizados", b(n)),
        tip("Avisá a tus clientes que copien de nuevo su link desde 👤 Mis cuentas."),
    ]), Kb([[Btn("🔀 Record type", callback_data='admin_record_menu'), ADMIN_HOME]]))


async def show_backend_menu(query):
    current = db.get_backend()
    await safe_edit(query, "\n".join([
        header('🔐', 'Backend de autenticación', f"Actual: {current.upper()}"),
        f"{'✅' if current == 'ssh' else '▫️'} <b>SSH</b> — límite real de conexiones por cuenta.",
        f"{'✅' if current == 'socks' else '▫️'} <b>SOCKS</b> — más liviano y estable en redes difíciles; "
        "el límite de conexiones queda informativo.",
        "",
        quote("Usuarios y contraseñas son los mismos en los dos."),
        warn("Al cambiar, los clientes deben copiar de nuevo su link (cambia el protocolo)."),
    ]), get_backend_menu())


async def set_backend(query, backend: str):
    s = _server()
    if not s:
        await safe_edit(query, _no_server_text(), get_back_admin())
        return
    await safe_edit(query, f"{header('🔐', 'Cambiando backend')}\n⏳ Aplicando {b(backend.upper())}...")
    r = await bg(ssh_accounts.apply_backend, s['id'], backend)
    if not r['success']:
        await safe_edit(query, f"{header('❌', 'No se pudo cambiar')}\n<code>{esc(r.get('error'))[:1200]}</code>",
                        get_backend_menu())
        return
    n = regenerate_links(db.get_server(s['id']))
    db.add_log('SET_BACKEND', f"Backend → {backend.upper()}", query.from_user.id)
    await safe_edit(query, "\n".join([
        header('✅', f"Backend: {backend.upper()}"),
        kv("🔄", "Links actualizados", b(n)),
        tip(f"En la app: <b>Authentication Protocol = {'SSH' if backend == 'ssh' else 'SOCKS'}</b> "
            "(si importan el link nuevo, se configura solo)."),
    ]), Kb([[Btn("🔐 Backend", callback_data='admin_backend_menu'), ADMIN_HOME]]))


async def show_settings(query):
    public = db.is_public_mode()
    await safe_edit(query, "\n".join([
        header('⚙️', 'Modo de acceso', f"Actual: {'Público' if public else 'Privado'}"),
        f"{'✅' if public else '▫️'} <b>🌐 Público</b> — cualquiera crea 1 cuenta gratis (30 días, 3 conexiones).",
        f"{'✅' if not public else '▫️'} <b>🔒 Privado</b> — solo admins y usuarios ⭐ Premium.",
    ]), get_settings_menu())


async def set_mode(query, public: bool):
    db.set_public_mode(public)
    db.add_log('TOGGLE_MODE', "Público" if public else "Privado", query.from_user.id)
    await query.answer(f"Modo {'🌐 Público' if public else '🔒 Privado'}")
    await show_settings(query)


# ==========================================
# TRÁFICO / LOGS / LINKS
# ==========================================
async def show_traffic(query):
    s = _server()
    if not s:
        await safe_edit(query, _no_server_text(), get_back_admin())
        return
    await safe_edit(query, f"{header('📡', 'Tráfico')}\n⏳ Consultando...")
    data = await bg(ssh_accounts.get_traffic, s['id'])
    kb = Kb([[Btn("🔄 Actualizar", callback_data='admin_traffic'), ADMIN_HOME]])
    if not data:
        await safe_edit(query, f"{header('📡', 'Tráfico')}\n🔴 No se pudo leer el tráfico de la VPS.", kb)
        return
    lines = [header('📡', 'Tráfico de red', 'Desde el último reinicio de la VPS'),
             kv("⬇️", "Descarga", b(human_bytes(data['rx']))),
             kv("⬆️", "Subida", b(human_bytes(data['tx'])))]
    v = data.get('vnstat', '')
    if v and ';' in v:
        p = v.split(';')
        if len(p) >= 12:
            lines += ["", "<b>📊 vnstat</b>",
                      f"Hoy   ⬇️ {esc(p[3])} · ⬆️ {esc(p[4])}",
                      f"Mes   ⬇️ {esc(p[7])} · ⬆️ {esc(p[8])}",
                      f"Total ⬇️ {esc(p[10])} · ⬆️ {esc(p[11])}"]
    await safe_edit(query, "\n".join(lines), kb)


async def show_logs(query):
    logs = db.get_logs(limit=15)
    lines = [header('📋', 'Actividad reciente')]
    if not logs:
        lines.append("<i>Sin registros todavía.</i>")
    for log in logs:
        lines.append(f"<code>{esc(str(log['created_at'])[5:16])}</code> <b>{esc(log['action'])}</b>\n"
                     f"      <i>{esc((log.get('details') or '')[:70])}</i>")
    await safe_edit(query, "\n".join(lines)[:4000],
                    Kb([[Btn("🔄 Actualizar", callback_data='admin_logs'), ADMIN_HOME]]))


async def do_update_links(query):
    s = _server()
    if not s:
        await safe_edit(query, _no_server_text(), get_back_admin())
        return
    await safe_edit(query, f"{header('🔄', 'Regenerando links')}\n⏳ Leyendo la clave de la VPS...")
    status = await bg(vaydns.get_server_status, s['id'])
    pubkey = status.get('pubkey') or s.get('pubkey') or ''
    if not pubkey:
        await safe_edit(query, f"{header('❌', 'Sin clave pública')}\nVayDNS no parece instalado.",
                        get_back_admin())
        return
    db.update_server_pubkey(s['id'], pubkey)
    n = regenerate_links(db.get_server(s['id']))
    db.add_log('UPDATE_LINKS', f"{n} links regenerados", query.from_user.id)
    await safe_edit(query, "\n".join([
        header('✅', 'Links regenerados'),
        kv("🔄", "Cuentas", b(n)),
        kv("🗝️", "Public key", code(pubkey)),
        kv("🔀", "Record / Backend", b(f"{db.get_record_type().upper()} / {db.get_backend().upper()}")),
    ]), get_back_admin())


# ==========================================
# CUENTAS
# ==========================================
async def show_new_account(query):
    await safe_edit(query, "\n".join([
        header('➕', 'Nueva cuenta'),
        "¿Qué tipo de cuenta querés crear?",
        quote("Como admin no tenés límites de días ni conexiones.\n"
              "La cuenta queda en <b>tus</b> cuentas y en 👥 Cuentas."),
    ]), Kb([[Btn("🚀 VayDNS", callback_data='create_account'),
             Btn("🛡️ WireGuard", callback_data='create_wg')], [ADMIN_HOME]]))


async def show_users(query, page: int = 0):
    users = db.get_all_users()
    if not users:
        await safe_edit(query, f"{header('👥', 'Cuentas')}\n<i>No hay cuentas todavía.</i>",
                        Kb([[Btn("➕ Nueva cuenta", callback_data='admin_create_account'), ADMIN_HOME]]))
        return
    pages = max(1, (len(users) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = users[page * PAGE:(page + 1) * PAGE]
    counts = db.count_by_type()
    lines = [header('👥', 'Cuentas', f"🚀 {counts['vaydns']} VayDNS · 🛡️ {counts['wireguard']} WireGuard · "
                                     f"página {page + 1}/{pages}")]
    kb = []
    for u in chunk:
        icon = "🛡️" if u.get('conn_type') == 'wireguard' else "🚀"
        lines.append(f"{icon} {b(u['username'])} — {expiry(u['expires_at'])}")
        kb.append([Btn(f"{icon} {u['username'][:22]}", callback_data=f"admin_detail_{u['id']}")])
    nav = []
    if page > 0:
        nav.append(Btn("⬅️", callback_data=f"admin_users_p{page - 1}"))
    if page < pages - 1:
        nav.append(Btn("➡️", callback_data=f"admin_users_p{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([Btn("➕ Nueva", callback_data='admin_create_account'), ADMIN_HOME])
    await safe_edit(query, "\n".join(lines), Kb(kb))


def _detail_kb(u) -> Kb:
    aid = u['id']
    send_label = "📄 Enviar .conf + QR" if u.get('conn_type') == 'wireguard' else "📤 Enviar datos"
    return Kb([
        [Btn("➕ 7 días", callback_data=f"admin_renew_{aid}_7"),
         Btn("➕ 30 días", callback_data=f"admin_renew_{aid}_30")],
        [Btn(send_label, callback_data=f"admin_send_{aid}"),
         Btn("🗑️ Eliminar", callback_data=f"del_user_{aid}")],
        [Btn("◀️ Cuentas", callback_data='admin_users'), ADMIN_HOME],
    ])


async def show_user_detail(query, account_id: int):
    u = db.get_user_by_id(account_id)
    if not u:
        await safe_edit(query, "❌ Cuenta no encontrada.", Kb([[Btn("◀️ Cuentas", callback_data='admin_users')]]))
        return
    owner = u.get('telegram_id') or 0
    owner_line = kv("🙋", "Dueño", code(owner) if owner else "<i>creada por admin</i>")
    if u.get('conn_type') == 'wireguard':
        text = wg_card(u) + "\n" + owner_line
    else:
        await safe_edit(query, "⏳ Consultando conexiones...")
        online = await bg(ssh_accounts.list_online, u['server_id'], u['username'])
        text = (vaydns_card(u) + "\n" + owner_line + "\n" +
                kv("🔌", "Conectados ahora", f"{bar(online, u.get('max_conn') or 3, 6)} {online}/{u.get('max_conn') or 3}"))
    await safe_edit(query, text, _detail_kb(u))


async def renew_user(query, account_id: int, days: int):
    u = db.get_user_by_id(account_id)
    if not u:
        await query.answer("Cuenta no encontrada", show_alert=True)
        return
    new_exp = db.add_days_to_user(account_id, days)
    if u.get('conn_type') != 'wireguard':
        remaining = max(days_left(new_exp), 0) + 1
        await bg(ssh_accounts.renew_user, u['server_id'], u['username'], remaining)
    db.add_log('RENEW', f"{u['username']} +{days}d → {new_exp[:10]}", query.from_user.id)
    await query.answer(f"✅ +{days} días · vence {fmt_date(new_exp)}", show_alert=True)
    await show_user_detail(query, account_id)


async def resend_account(query, account_id: int):
    u = db.get_user_by_id(account_id)
    if not u:
        await query.answer("Cuenta no encontrada", show_alert=True)
        return
    if u.get('conn_type') == 'wireguard':
        await send_wg_files(query.message, u)
    else:
        await query.message.reply_text(vaydns_card(u), parse_mode='HTML', disable_web_page_preview=True)
    await query.answer("📤 Enviado abajo — reenvialo al cliente")


async def ask_delete_user(query, account_id: int):
    u = db.get_user_by_id(account_id)
    if not u:
        await safe_edit(query, "❌ Cuenta no encontrada.", Kb([[Btn("◀️ Cuentas", callback_data='admin_users')]]))
        return
    await safe_edit(query, f"{header('🗑️', 'Eliminar cuenta')}\n¿Eliminar {b(u['username'])}?\n"
                           + warn("Se borra del servidor y se desconecta al instante."),
                    Kb([[Btn("✅ Sí, eliminar", callback_data=f"admin_delok_{account_id}"),
                         Btn("✖️ No", callback_data=f"admin_detail_{account_id}")]]))


async def delete_user(query, account_id: int):
    u = db.get_user_by_id(account_id)
    if u:
        await safe_edit(query, "⏳ <b>Eliminando...</b>")
        await delete_account(u)
        db.add_log('DELETE_USER', f"Eliminó {u['username']}", query.from_user.id)
        await query.answer("✅ Cuenta eliminada")
    await show_users(query, 0)


# ==========================================
# PREMIUM
# ==========================================
async def show_premium_menu(query):
    rs = db.get_active_resellers()
    lines = [header('⭐', 'Usuarios Premium', f"{len(rs)} activo(s)")]
    kb = [[Btn("➕ Dar Premium", callback_data='admin_premium')]]
    for r in rs[:15]:
        used = db.count_user_accounts(r['telegram_id'])
        lines.append(f"• {code(r['telegram_id'])} — 📦 {used}/{r['max_accounts']} · 📱 {r['max_conn']} · "
                     f"📅 {r['max_days']}d · {expiry(r['expires_at'])}")
        kb.append([Btn(f"🗑️ Quitar {r['telegram_id']}", callback_data=f"admin_unprem_{r['telegram_id']}")])
    if not rs:
        lines.append("<i>Nadie tiene Premium todavía.</i>")
    lines.append(tip("El usuario ve su ID con /id. También podés usar <code>/premium</code> y <code>/unpremium</code>."))
    kb.append([ADMIN_HOME])
    await safe_edit(query, "\n".join(lines), Kb(kb))


async def revoke_premium(query, tgid: int):
    db.remove_reseller(tgid)
    db.add_log('REVOKE_PREMIUM', f"Plan quitado a {tgid}", query.from_user.id)
    await query.answer("✅ Premium quitado")
    await show_premium_menu(query)
