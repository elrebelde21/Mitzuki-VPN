"""
vaydns_manager.py  —  Instalación y configuración de VayDNS en la VPS.

Todo el servicio se genera desde UNA fuente de verdad (service_params), así el
servidor y los links de los clientes nunca quedan desalineados:

  record type  → db.get_record_type()
  dnstt compat → solo con TXT
  timeouts     → compat: idle 2m / keepalive 10s · sin compat: idle 10s / keepalive 2s
  upstream     → backend SSH  : 127.0.0.1:2222 (sshd dedicado, cuentas reales)
                 backend SOCKS: 127.0.0.1:8000 (Dante con usuario/contraseña)
"""
import os
import random
import string
from typing import Dict, List

import config
from database import RECORD_TYPES
from lib.remote import RemoteMixin, write_file, open_udp_port, free_port_53, udp_port_owner

SSH_UPSTREAM = "127.0.0.1:2222"
SOCKS_UPSTREAM = "127.0.0.1:8000"
UNIT_PATH = "/etc/systemd/system/vaydns-server.service"
MTU = 1232


def tunnel_domain_for(server: Dict) -> str:
    d = config.DEFAULT_SERVER
    if d.get('tunnel_domain'):
        return d['tunnel_domain']
    domain = (server or {}).get('domain') or d.get('domain') or ''
    return f"d.{'.'.join(domain.split('.')[1:])}" if domain else ''


def timeouts_for(record_type: str):
    """(dnstt_compat, idle_timeout, keepalive) — iguales en server y cliente."""
    compat = record_type == 'txt'
    return (compat, '2m', '10s') if compat else (compat, '10s', '2s')


def service_params_from(db, server: Dict) -> Dict:
    return VayDNSManager(db).service_params(server)


class VayDNSManager(RemoteMixin):
    def __init__(self, db):
        self.db = db

    def generate_password(self, length: int = 12) -> str:
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(length))

    def detect_os(self, ssh, password: str, user: str = 'root') -> Dict[str, str]:
        _, os_info, _ = self.run_cmd(ssh, "cat /etc/os-release", password, user)
        low = os_info.lower()
        is_ubuntu = "ubuntu" in low or "debian" in low
        return {
            'is_ubuntu': is_ubuntu,
            'dante_config_path': "/etc/danted.conf" if is_ubuntu else "/etc/sockd.conf",
            'dante_service': "danted" if is_ubuntu else "sockd",
        }

    # ------------------------------------------------------------------
    # Parámetros y plantillas
    # ------------------------------------------------------------------
    def service_params(self, server: Dict) -> Dict:
        rt = self.db.get_record_type()
        compat, idle, keepalive = timeouts_for(rt)
        backend = self.db.get_backend()
        return {
            'port': int(config.DEFAULT_SERVER.get('port') or 53),
            'mtu': MTU,
            'record_type': rt,
            'compat': compat,
            'idle_timeout': idle,
            'keepalive': keepalive,
            'tunnel_domain': tunnel_domain_for(server),
            'backend': backend,
            'upstream': SSH_UPSTREAM if backend == 'ssh' else SOCKS_UPSTREAM,
        }

    @staticmethod
    def render_unit(p: Dict) -> str:
        compat_flag = '-dnstt-compat ' if p['compat'] else ''
        return f"""[Unit]
Description=VayDNS Tunnel Server (Mitzuki)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vaydns
Group=vaydns
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
ExecStart=/usr/local/bin/vaydns-server -udp :{p['port']} -privkey-file /etc/vaydns/server.key -mtu {p['mtu']} -record-type {p['record_type']} {compat_flag}-idle-timeout {p['idle_timeout']} -keepalive {p['keepalive']} -domain {p['tunnel_domain']} -upstream {p['upstream']}
Restart=always
RestartSec=3
KillMode=mixed
TimeoutStopSec=5
LimitNOFILE=1048576

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/
ReadWritePaths=/etc/vaydns
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

[Install]
WantedBy=multi-user.target
"""

    @staticmethod
    def render_dante(iface: str, with_auth: bool) -> str:
        method = 'username' if with_auth else 'none'
        return f"""logoutput: syslog
user.privileged: root
user.unprivileged: nobody
internal: 127.0.0.1 port = 8000
external: {iface}
clientmethod: none
socksmethod: {method}

client pass {{
        from: 127.0.0.1/32 to: 0.0.0.0/0
        log: error
}}

socks pass {{
        from: 127.0.0.1/32 to: 0.0.0.0/0
        protocol: tcp udp
        log: error
}}
"""

    # ------------------------------------------------------------------
    # Aplicar config (record type / backend / reparar)
    # ------------------------------------------------------------------
    def apply_service(self, server_id: int) -> Dict:
        """Regenera el servicio VayDNS + Dante según la config actual y reinicia."""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        pwd, user = server['password'], server['username']
        try:
            code, _, _ = self.run_cmd(ssh, "test -x /usr/local/bin/vaydns-server && test -f /etc/vaydns/server.key",
                                      pwd, user)
            if code != 0:
                return {'success': False, 'error': 'VayDNS no está instalado'}
            return self._apply(ssh, server, pwd, user)
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            ssh.close()

    def _apply(self, ssh, server, pwd, user) -> Dict:
        p = self.service_params(server)
        if not p['tunnel_domain']:
            return {'success': False, 'error': 'Falta el dominio del túnel (DEFAULT_SERVER_TUNNEL_DOMAIN)'}
        os_info = self.detect_os(ssh, pwd, user)

        # Upstream según backend
        if p['backend'] == 'ssh':
            from lib.ssh_accounts_manager import SSHAccountsManager
            res = SSHAccountsManager(self.db).setup_backend_on(ssh, pwd, user)
            if not res['success']:
                return res
        _, iface, _ = self.run_cmd(ssh, "ip route | awk '/default/ {print $5}' | head -n1", pwd, user)
        dante = self.render_dante(iface.strip() or 'eth0', with_auth=(p['backend'] == 'socks'))
        write_file(ssh, os_info['dante_config_path'], dante, pwd, user)
        self.run_cmd(ssh, f"systemctl enable {os_info['dante_service']} >/dev/null 2>&1; "
                          f"systemctl restart {os_info['dante_service']}", pwd, user)

        # Quitar redirecciones viejas 53→otro puerto (Soar/otros) que le roban el tráfico a VayDNS
        self.run_cmd(ssh, "for i in $(seq 1 20); do "
                          "r=$(iptables -t nat -S PREROUTING 2>/dev/null | grep -E -- '--dport 53( |$).*REDIRECT' | head -n1); "
                          "[ -z \"$r\" ] && break; iptables -t nat ${r/-A/-D} || break; done; "
                          "command -v netfilter-persistent >/dev/null && netfilter-persistent save >/dev/null 2>&1; true",
                     pwd, user)

        # Servicio VayDNS
        write_file(ssh, UNIT_PATH, self.render_unit(p), pwd, user)
        self.run_cmd(ssh, "rm -rf /etc/systemd/system/vaydns-server.service.d; systemctl daemon-reload; "
                          "systemctl enable vaydns-server >/dev/null 2>&1; systemctl restart vaydns-server",
                     pwd, user)
        open_udp_port(ssh, p['port'], pwd, user)

        self.run_cmd(ssh, "sleep 1", pwd, user)
        _, status, _ = self.run_cmd(ssh, "systemctl is-active vaydns-server", pwd, user)
        if status.strip() != 'active':
            _, logs, _ = self.run_cmd(ssh, "journalctl -u vaydns-server -n 15 --no-pager", pwd, user)
            return {'success': False, 'error': f'vaydns-server no arrancó:\n{logs[-1500:]}'}
        return {'success': True, 'params': p}

    # ------------------------------------------------------------------
    # Instalación
    # ------------------------------------------------------------------
    def install_vaydns(self, server_id: int) -> Dict:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        local_binary = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vaydns-server')
        if not os.path.exists(local_binary):
            return {'success': False, 'error': f'No se encontró el binario local: {local_binary}'}

        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        pwd, user = server['password'], server['username']

        # Record type inicial: el del .env si todavía no se eligió uno desde el bot
        if self.db.get_config('record_type') is None:
            env_rt = (config.DEFAULT_SERVER.get('record_type') or 'txt').lower()
            self.db.set_record_type(env_rt if env_rt in RECORD_TYPES else 'txt')
        port = int(config.DEFAULT_SERVER.get('port') or 53)

        try:
            os_info = self.detect_os(ssh, pwd, user)

            # 1. Dependencias
            if os_info['is_ubuntu']:
                self.run_cmd(ssh, "export DEBIAN_FRONTEND=noninteractive; apt-get update -y -q; "
                                  "apt-get install -y -q dante-server openssh-server curl vnstat net-tools "
                                  "dnsutils file iptables ca-certificates", pwd, user)
            else:
                self.run_cmd(ssh, "dnf install -y epel-release; dnf install -y dante-server openssh-server curl "
                                  "net-tools bind-utils vnstat file iptables ca-certificates "
                                  "policycoreutils-python-utils", pwd, user)

            # 2. Liberar el puerto 53 (systemd-resolved) y comprobar que esté libre
            self.run_cmd(ssh, "systemctl stop vaydns-server 2>/dev/null; true", pwd, user)
            free_port_53(ssh, pwd, user)
            owner = udp_port_owner(ssh, port, pwd, user)
            if owner:
                return {'success': False,
                        'error': f'El puerto {port}/udp está ocupado por otro programa:\n{owner}\n\n'
                                 f'Desinstalá Soar / Slipstream / MasterDnsVPN primero.'}

            # 3. Binario
            sftp = ssh.open_sftp()
            try:
                sftp.put(local_binary, "/tmp/vaydns-server")
            finally:
                sftp.close()
            self.run_cmd(ssh, "install -m 755 /tmp/vaydns-server /usr/local/bin/vaydns-server && "
                              "rm -f /tmp/vaydns-server", pwd, user)
            _, ftype, _ = self.run_cmd(ssh, "file /usr/local/bin/vaydns-server 2>/dev/null || true", pwd, user)
            if ftype and 'ELF' not in ftype:
                return {'success': False, 'error': f'El binario subido no es válido:\n{ftype}'}
            if not os_info['is_ubuntu']:
                self.run_cmd(ssh, 'semanage fcontext -a -t bin_t "/usr/local/bin/vaydns-server" 2>/dev/null; '
                                  'restorecon -v /usr/local/bin/vaydns-server 2>/dev/null; true', pwd, user)

            # 4. Usuario de servicio
            self.run_cmd(ssh, "id -u vaydns >/dev/null 2>&1 || "
                              "useradd -r -M -s /usr/sbin/nologin -d /nonexistent vaydns", pwd, user)

            # 5. Claves: se CONSERVAN si ya existían (así los links de los clientes siguen sirviendo)
            self.run_cmd(ssh, "mkdir -p /etc/vaydns", pwd, user)
            code, _, _ = self.run_cmd(ssh, "test -s /etc/vaydns/server.key && test -s /etc/vaydns/server.pub",
                                      pwd, user)
            if code != 0:
                code, out, err = self.run_cmd(ssh, "/usr/local/bin/vaydns-server -gen-key "
                                                   "-privkey-file /etc/vaydns/server.key "
                                                   "-pubkey-file /etc/vaydns/server.pub", pwd, user)
                if code != 0:
                    return {'success': False, 'error': f'No se pudieron generar las claves:\n{err or out}'}
            _, pubkey, _ = self.run_cmd(ssh, "cat /etc/vaydns/server.pub", pwd, user)
            pubkey = pubkey.strip()
            if not pubkey:
                return {'success': False, 'error': 'server.pub vacío'}
            self.run_cmd(ssh, "chown -R vaydns:vaydns /etc/vaydns && chmod 600 /etc/vaydns/server.key", pwd, user)

            # 6. Servicio + upstream + firewall
            res = self._apply(ssh, server, pwd, user)
            if not res['success']:
                return res

            self.db.update_server_pubkey(server_id, pubkey)
            return {'success': True, 'pubkey': pubkey, 'params': res['params'],
                    'message': 'VayDNS instalado correctamente'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            ssh.close()

    def generate_client_urls(self, domain: str, pubkey: str) -> List[str]:
        """Compat: URL base sin credenciales."""
        if not pubkey:
            return []
        rt = self.db.get_record_type()
        compat, idle, ka = timeouts_for(rt)
        tunnel = config.DEFAULT_SERVER.get('tunnel_domain', domain)
        cid = config.DEFAULT_SERVER.get('clientid_size', 8)
        return [f"dnst://{tunnel}/vaydns/socks5?pubkey={pubkey}&record-type={rt}&clientid-size={cid}"
                f"&keepalive={ka}&idle-timeout={idle}&dnstt-compat={'true' if compat else 'false'}#vaydns"]

    # ------------------------------------------------------------------
    # Estado / desinstalar
    # ------------------------------------------------------------------
    def get_server_status(self, server_id: int) -> Dict:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        pwd, user = server['password'], server['username']
        try:
            _, status, _ = self.run_cmd(ssh, "systemctl is-active vaydns-server", pwd, user)
            _, ports, _ = self.run_cmd(ssh, "ss -tulnp | grep -E ':53 |:2222 |:8000 |:51820 ' || true", pwd, user)
            _, pubkey, _ = self.run_cmd(ssh, "cat /etc/vaydns/server.pub 2>/dev/null", pwd, user)
            return {'success': True, 'status': status.strip() or 'unknown',
                    'ports': ports or '', 'pubkey': pubkey.strip()}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            ssh.close()

    def uninstall_vaydns(self, server_id: int) -> Dict:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        pwd, user = server['password'], server['username']
        try:
            self.run_cmd(ssh, "systemctl disable --now vaydns-server 2>/dev/null; "
                              "rm -f /etc/systemd/system/vaydns-server.service; "
                              "rm -rf /etc/systemd/system/vaydns-server.service.d; "
                              "systemctl daemon-reload; rm -rf /etc/vaydns; "
                              "rm -f /usr/local/bin/vaydns-server; true", pwd, user)
            # El servidor queda en la DB (las cuentas y WireGuard lo siguen usando)
            self.db.update_server_pubkey(server_id, '')
            return {'success': True, 'message': 'VayDNS desinstalado correctamente'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            ssh.close()

    def is_port_in_use(self, server_id: int, port: int) -> bool:
        server = self.db.get_server(server_id)
        ssh = self._connect(server) if server else None
        if not ssh:
            return False
        try:
            return bool(udp_port_owner(ssh, port, server['password'], server['username']))
        finally:
            ssh.close()

    def is_vaydns_installed(self, server_id: int) -> bool:
        server = self.db.get_server(server_id)
        ssh = self._connect(server) if server else None
        if not ssh:
            return False
        try:
            _, out, _ = self.run_cmd(ssh, "systemctl is-active vaydns-server", server['password'], server['username'])
            return out.strip() == "active"
        finally:
            ssh.close()
