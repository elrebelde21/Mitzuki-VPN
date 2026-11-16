"""
diagnostics.py  —  Revisa de punta a punta por qué un cliente no conecta.

Una sola conexión SSH a la VPS y devuelve una lista de chequeos:
    {'ok': True/False/None, 'name': str, 'detail': str, 'fix': str}
ok=None significa "no aplica / informativo".
"""
from typing import Dict, List

from lib.remote import connect, run
from lib.vaydns_manager import service_params_from
from lib.wireguard_manager import WG_PORT, WG_IFACE, WG_DIR


def _strip_dot(s: str) -> str:
    return s.strip().rstrip('.').lower()


def run_diagnostics(db, server: Dict) -> Dict:
    checks: List[Dict] = []

    def add(ok, name, detail='', fix=''):
        checks.append({'ok': ok, 'name': name, 'detail': detail, 'fix': fix})

    ssh = connect(server, timeout=20)
    if not ssh:
        add(False, 'Conexión SSH a la VPS', f"{server.get('ip')}:{server.get('ssh_port')}",
            'Revisá DEFAULT_SERVER_IP / SSH_PORT / PASSWORD en el .env')
        return {'checks': checks, 'vaydns': False, 'wg': False}
    add(True, 'Conexión SSH a la VPS', f"{server['ip']}")

    pwd, user = server['password'], server['username']

    def sh(cmd):
        return run(ssh, cmd, pwd, user)[1].strip()

    p = service_params_from(db, server)
    vaydns_installed = sh("test -x /usr/local/bin/vaydns-server && echo y") == 'y'
    wg_installed = sh(f"test -s {WG_DIR}/server_private.key && echo y") == 'y'

    try:
        # ---------------- VayDNS ----------------
        if vaydns_installed:
            st = sh("systemctl is-active vaydns-server")
            add(st == 'active', 'VayDNS en ejecución', st, 'Tocá 🔧 Reparar')

            owner = sh(f"ss -H -ulnp | awk '$4 ~ /:{p['port']}$/'")
            listening = 'vaydns' in owner
            add(listening, f"Escuchando en {p['port']}/udp",
                'vaydns-server' if listening else (owner[:120] or 'nadie escucha'),
                'Otro programa ocupa el puerto' if owner and not listening else 'Tocá 🔧 Reparar')

            redir = sh("iptables -t nat -S PREROUTING 2>/dev/null | grep -cE -- '--dport 53( |$).*REDIRECT'")
            add(redir in ('', '0'), 'Sin redirecciones viejas del 53',
                'ok' if redir in ('', '0') else f"{redir} regla(s) de Soar/otro desvían el tráfico",
                'Tocá 🔧 Reparar')

            unit = sh("grep -o 'ExecStart=.*' /etc/systemd/system/vaydns-server.service")
            rt_ok = f"-record-type {p['record_type']}" in unit
            up_ok = f"-upstream {p['upstream']}" in unit
            add(rt_ok and up_ok, 'Servicio alineado con el bot',
                f"record {p['record_type'].upper()} · backend {p['backend'].upper()}",
                'El servicio tiene otra config. Tocá 🔧 Reparar')

            if p['backend'] == 'ssh':
                st = sh("systemctl is-active vaydns-sshd")
                lst = bool(sh("ss -H -tlnp | awk '$4 ~ /127.0.0.1:2222$/'"))
                add(st == 'active' and lst, 'Backend SSH (127.0.0.1:2222)', st, 'Tocá 🔧 Reparar')
            else:
                st = sh("systemctl is-active danted 2>/dev/null || systemctl is-active sockd")
                lst = bool(sh("ss -H -tlnp | awk '$4 ~ /127.0.0.1:8000$/'"))
                add(st == 'active' and lst, 'Backend SOCKS (127.0.0.1:8000)', st, 'Tocá 🔧 Reparar')

            vps_pub = sh("cat /etc/vaydns/server.pub 2>/dev/null")
            add(bool(vps_pub) and vps_pub == (server.get('pubkey') or ''), 'Clave pública de los links',
                'coincide' if vps_pub == server.get('pubkey') else 'distinta a la guardada',
                'Tocá 🔄 Regenerar links')

            # DNS (se consulta desde la VPS contra 1.1.1.1)
            sh("command -v dig >/dev/null || (DEBIAN_FRONTEND=noninteractive apt-get install -y -q dnsutils "
               ">/dev/null 2>&1 || dnf install -y bind-utils >/dev/null 2>&1)")
            domain = server.get('domain') or ''
            a = sh(f"dig +short +time=3 +tries=1 {domain} A @1.1.1.1 | tail -n1")
            add(a == server['ip'], f"DNS A  {domain}", a or 'sin registro',
                f"Creá un registro A: {domain} → {server['ip']} (nube gris en Cloudflare)")
            ns = sh(f"dig +short +time=3 +tries=1 {p['tunnel_domain']} NS @1.1.1.1")
            ns_ok = _strip_dot(domain) in [_strip_dot(x) for x in ns.splitlines()]
            add(ns_ok, f"DNS NS {p['tunnel_domain']}", _strip_dot(ns.splitlines()[0]) if ns else 'sin registro',
                f"Creá un registro NS: {p['tunnel_domain']} → {domain}")

            # Prueba real: una consulta que entra por internet hasta VayDNS
            out = sh(f"dig +time=4 +tries=2 @8.8.8.8 mitzuki-test.{p['tunnel_domain']} TXT | grep -o 'status: [A-Z]*'")
            e2e = out.replace('status: ', '')
            add(e2e in ('NOERROR', 'NXDOMAIN', 'REFUSED', 'FORMERR', 'NOTIMP'), 'Prueba de punta a punta (DNS público → VayDNS)',
                e2e or 'sin respuesta',
                'Las consultas no llegan a la VPS: revisá el NS y el firewall del proveedor (UDP 53 abierto)')
        else:
            add(None, 'VayDNS', 'no instalado')

        # ---------------- WireGuard ----------------
        if wg_installed:
            st = sh(f"systemctl is-active wg-quick@{WG_IFACE}")
            add(st == 'active', 'WireGuard en ejecución', st, 'Tocá 🔧 Reparar')
            lst = bool(sh(f"ss -H -ulnp | awk '$4 ~ /:{WG_PORT}$/'"))
            add(lst, f"Escuchando en {WG_PORT}/udp", 'sí' if lst else 'no', 'Tocá 🔧 Reparar')
            fwd = sh("sysctl -n net.ipv4.ip_forward")
            add(fwd == '1', 'Reenvío IPv4 (ip_forward)', fwd, 'Tocá 🔧 Reparar')
            nat = sh("iptables -t nat -S POSTROUTING 2>/dev/null | grep -c MASQUERADE")
            add(nat not in ('', '0'), 'NAT (MASQUERADE)', f"{nat or 0} reglas", 'Tocá 🔧 Reparar')
            peers = sh(f"wg show {WG_IFACE} peers 2>/dev/null | wc -l") or '0'
            want = len(db.get_wg_users(server['id']))
            add(int(peers) == want, 'Clientes cargados en wg0', f"{peers}/{want}", 'Tocá 🔧 Reparar')
            pub = sh(f"cat {WG_DIR}/server_private.key | wg pubkey")
            add(pub == (db.get_config('wg_pubkey') or ''), 'Llave pública WireGuard',
                'coincide' if pub == db.get_config('wg_pubkey') else 'distinta', 'Tocá 🔧 Reparar')
        else:
            add(None, 'WireGuard', 'no instalado')

        # ---------------- Firewall ----------------
        ufw = sh("command -v ufw >/dev/null && ufw status 2>/dev/null | head -1")
        if 'active' in ufw and 'inactive' not in ufw:
            rules = sh("ufw status")
            need = [str(p['port'])] if vaydns_installed else []
            need += [str(WG_PORT)] if wg_installed else []
            missing = [n for n in need if f"{n}/udp" not in rules]
            add(not missing, 'Firewall ufw', 'puertos abiertos' if not missing else f"faltan: {', '.join(missing)}",
                'Tocá 🔧 Reparar')
        else:
            add(None, 'Firewall ufw', 'inactivo')
    finally:
        ssh.close()

    return {'checks': checks, 'vaydns': vaydns_installed, 'wg': wg_installed}


def services_status(server: Dict) -> Dict:
    """Estado de todos los servicios en UNA conexión SSH."""
    res = {'vaydns': False, 'wg': False, 'soar': False, 'slip': False, 'master': False, 'ssh_ok': False}
    ssh = connect(server, timeout=20) if server else None
    if not ssh:
        return res
    try:
        _, out, _ = run(ssh, "for s in vaydns-server wg-quick@wg0 soar-server masterdnsvpn; do "
                             "systemctl is-active $s 2>/dev/null || true; done; "
                             "command -v slipgate >/dev/null 2>&1 && echo active || echo no",
                        server['password'], server['username'])
        lines = [x.strip() for x in out.splitlines()]
        keys = ['vaydns', 'wg', 'soar', 'master', 'slip']
        for k, v in zip(keys, lines):
            res[k] = v == 'active'
        res['ssh_ok'] = True
    finally:
        ssh.close()
    return res
