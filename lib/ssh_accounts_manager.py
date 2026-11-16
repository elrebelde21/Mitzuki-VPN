"""
ssh_accounts_manager.py  —  Cuentas reales para VayDNS.

VayDNS solo transporta: no tiene usuarios. Las cuentas viven en el upstream:

  - Backend SSH  : sshd DEDICADO en 127.0.0.1:2222 (solo alcanzable por el túnel).
                   Tope real de conexiones por cuenta (limitador).
  - Backend SOCKS: Dante en 127.0.0.1:8000 con usuario/contraseña del sistema.

En ambos casos cada cliente es un usuario Linux del grupo `vaydns-ssh`:
  - usuario + contraseña, vencimiento con `chage -E`
  - shell bloqueada (no da acceso a la VPS): solo sirve para túnel
"""
import random
import shlex
import string
from typing import Dict, Optional, Tuple

import config
from database import RECORD_TYPES
from lib.remote import RemoteMixin, write_file

SSH_TUNNEL_PORT = 2222
SSH_GROUP = "vaydns-ssh"
SSH_DIR = "/etc/vaydns-ssh"
LIMITS_DIR = "/etc/vaydns-ssh/limits"
NOSHELL = "/usr/local/bin/vaydns-noshell"

# Mantiene viva la sesión (algunas apps abren un "shell" además del túnel).
NOSHELL_SCRIPT = """#!/bin/sh
# Mitzuki VPN: cuenta solo para túnel. Mantiene la sesión abierta sin dar shell.
while :; do sleep 3600; done
"""

SSHD_CONFIG = f"""Port {SSH_TUNNEL_PORT}
ListenAddress 127.0.0.1
HostKey {SSH_DIR}/ssh_host_ed25519_key
PidFile /run/vaydns-sshd.pid
UsePAM yes
PasswordAuthentication yes
KbdInteractiveAuthentication yes
PubkeyAuthentication no
PermitRootLogin no
AllowGroups {SSH_GROUP}
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding yes
PermitTunnel no
PrintMotd no
PrintLastLog no
UseDNS no
TCPKeepAlive yes
ClientAliveInterval 30
ClientAliveCountMax 4
LoginGraceTime 60
MaxAuthTries 6
MaxSessions 20
MaxStartups 200:30:500

Match Group {SSH_GROUP}
    ForceCommand {NOSHELL}
    AllowTcpForwarding yes
    X11Forwarding no
    AllowAgentForwarding no
"""

LIMITER = f"""#!/bin/bash
# Mitzuki VPN: corta las conexiones que pasan el tope de cada cuenta.
LIMDIR="{LIMITS_DIR}"
while true; do
    for f in "$LIMDIR"/*; do
        [ -e "$f" ] || continue
        u=$(basename "$f")
        lim=$(cat "$f" 2>/dev/null)
        case "$lim" in ''|*[!0-9]*) continue;; esac
        [ "$lim" -le 0 ] && continue
        pids=$(pgrep -u "$u" -f "^sshd(-session)?: $u"  2>/dev/null | tr '\\n' ',' | sed 's/,$//')
        [ -z "$pids" ] && continue
        sorted=$(ps -o pid= --sort=start_time -p "$pids" 2>/dev/null | awk 'NF')
        count=$(printf '%s\\n' "$sorted" | awk 'NF' | wc -l)
        if [ "$count" -gt "$lim" ]; then
            excess=$((count - lim))
            printf '%s\\n' "$sorted" | tail -n "$excess" | while read -r p; do
                [ -n "$p" ] && kill "$p" 2>/dev/null
            done
        fi
    done
    sleep 5
done
"""

SSHD_SERVICE = f"""[Unit]
Description=Mitzuki VPN dedicated SSH (tunnel accounts)
After=network.target

[Service]
Type=simple
ExecStartPre=/usr/bin/mkdir -p /run/sshd
ExecStartPre=/usr/sbin/sshd -t -f {SSH_DIR}/sshd_config
ExecStart=/usr/sbin/sshd -D -e -f {SSH_DIR}/sshd_config
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

LIMITER_SERVICE = """[Unit]
Description=Mitzuki VPN connection limiter
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/vaydns-limiter.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


class SSHAccountsManager(RemoteMixin):
    def __init__(self, db):
        self.db = db

    def generate_password(self, length: int = 10) -> str:
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(length))

    def _valid_username(self, name: str) -> bool:
        """Usuario Linux seguro: minúsculas, dígitos, - o _, empieza con letra, 3-31 chars."""
        if not name or len(name) < 3 or len(name) > 31:
            return False
        if name[0] not in string.ascii_lowercase:
            return False
        allowed = set(string.ascii_lowercase + string.digits + "_-")
        return all(c in allowed for c in name)

    @staticmethod
    def _valid_password(pw: str) -> bool:
        return bool(pw) and 4 <= len(pw) <= 64 and ':' not in pw and '\n' not in pw

    # ------------------------------------------------------------------
    # 1. Backend (sshd dedicado + limitador)
    # ------------------------------------------------------------------
    def setup_backend_on(self, ssh, pwd: str, user: str) -> Dict:
        """Instala/actualiza el sshd dedicado usando una conexión ya abierta."""
        self.run_cmd(ssh, "command -v sshd >/dev/null 2>&1 || test -x /usr/sbin/sshd || "
                          "(export DEBIAN_FRONTEND=noninteractive; apt-get install -y -q openssh-server "
                          "|| dnf install -y openssh-server)", pwd, user)
        self.run_cmd(ssh, f"getent group {SSH_GROUP} >/dev/null || groupadd {SSH_GROUP}; "
                          f"mkdir -p {SSH_DIR} {LIMITS_DIR} /run/sshd; "
                          f"test -f {SSH_DIR}/ssh_host_ed25519_key || "
                          f"ssh-keygen -t ed25519 -f {SSH_DIR}/ssh_host_ed25519_key -N '' -q; "
                          f"chmod 600 {SSH_DIR}/ssh_host_ed25519_key", pwd, user)

        write_file(ssh, NOSHELL, NOSHELL_SCRIPT, pwd, user, mode='755')
        self.run_cmd(ssh, f"grep -qx '{NOSHELL}' /etc/shells || echo '{NOSHELL}' >> /etc/shells", pwd, user)
        # Cuentas viejas creadas con /usr/sbin/nologin → pasar a la shell de túnel
        self.run_cmd(ssh,
                     f"gid=$(getent group {SSH_GROUP} | cut -d: -f3); "
                     f"for u in $(awk -F: -v g=\"$gid\" '$4==g {{print $1}}' /etc/passwd); do "
                     f"usermod -s {NOSHELL} \"$u\" 2>/dev/null; done; true", pwd, user)

        write_file(ssh, f"{SSH_DIR}/sshd_config", SSHD_CONFIG, pwd, user, mode='600')
        code, _, err = self.run_cmd(ssh, f"mkdir -p /run/sshd; /usr/sbin/sshd -t -f {SSH_DIR}/sshd_config", pwd, user)
        if code != 0:
            return {'success': False, 'error': f'Config del sshd inválida:\n{err}'}

        write_file(ssh, "/etc/systemd/system/vaydns-sshd.service", SSHD_SERVICE, pwd, user)
        write_file(ssh, "/usr/local/bin/vaydns-limiter.sh", LIMITER, pwd, user, mode='755')
        write_file(ssh, "/etc/systemd/system/vaydns-limiter.service", LIMITER_SERVICE, pwd, user)
        self.run_cmd(ssh, "systemctl daemon-reload; systemctl enable vaydns-sshd vaydns-limiter >/dev/null 2>&1; "
                          "systemctl restart vaydns-sshd vaydns-limiter; sleep 1", pwd, user)

        _, st, _ = self.run_cmd(ssh, "systemctl is-active vaydns-sshd", pwd, user)
        if st.strip() != 'active':
            _, logs, _ = self.run_cmd(ssh, "journalctl -u vaydns-sshd -n 15 --no-pager", pwd, user)
            return {'success': False, 'error': f'El sshd de túnel no arrancó:\n{logs[-1500:]}'}
        return {'success': True}

    def setup_backend(self, server_id: int, repoint_vaydns: bool = True) -> Dict:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        try:
            return self.setup_backend_on(ssh, server['password'], server['username'])
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            ssh.close()

    def is_backend_installed(self, server_id: int) -> bool:
        """Hay backend listo para crear cuentas (grupo creado en la VPS)."""
        server = self.db.get_server(server_id)
        ssh = self._connect(server) if server else None
        if not ssh:
            return False
        try:
            code, _, _ = self.run_cmd(ssh, f"getent group {SSH_GROUP} >/dev/null && test -x /usr/local/bin/vaydns-server",
                                      server['password'], server['username'])
            return code == 0
        finally:
            ssh.close()

    def apply_backend(self, server_id: int, backend: str) -> Dict:
        """Cambia SSH/SOCKS y re-apunta VayDNS al upstream correcto."""
        if backend not in ('ssh', 'socks'):
            return {'success': False, 'error': 'Backend inválido'}
        old = self.db.get_backend()
        self.db.set_backend(backend)
        from lib.vaydns_manager import VayDNSManager
        res = VayDNSManager(self.db).apply_service(server_id)
        if not res['success']:
            self.db.set_backend(old)
        return res

    def set_server_record_type(self, server_id: int, record_type: str) -> Dict:
        record_type = (record_type or '').lower()
        if record_type not in RECORD_TYPES:
            return {'success': False, 'error': 'Record type inválido'}
        old = self.db.get_record_type()
        self.db.set_record_type(record_type)
        from lib.vaydns_manager import VayDNSManager
        res = VayDNSManager(self.db).apply_service(server_id)
        if not res['success']:
            self.db.set_record_type(old)
            return res
        return {'success': True, 'record_type': record_type}

    # ------------------------------------------------------------------
    # 2. Cuentas
    # ------------------------------------------------------------------
    def create_user(self, server_id: int, username: str, password: str,
                    days: int, max_conn: int = 3) -> Dict:
        if not self._valid_username(username):
            return {'success': False, 'error': 'Usuario inválido: 3-31 caracteres, minúsculas, números, - o _, '
                                               'y que empiece con letra.'}
        if not self._valid_password(password):
            return {'success': False, 'error': 'Contraseña inválida (4-64 caracteres, sin ":").'}
        if days <= 0:
            return {'success': False, 'error': 'Días inválidos'}
        max_conn = max_conn if max_conn and max_conn > 0 else 3

        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        pwd, user = server['password'], server['username']
        try:
            code, _, _ = self.run_cmd(ssh, f"id -u {username} >/dev/null 2>&1", pwd, user)
            if code == 0:
                return {'success': False, 'error': f'El usuario "{username}" ya existe. Elegí otro nombre.'}

            code, _, err = self.run_cmd(ssh, f"getent group {SSH_GROUP} >/dev/null || groupadd {SSH_GROUP}; "
                                             f"useradd -M -N -g {SSH_GROUP} -s {NOSHELL} {username}", pwd, user)
            if code != 0:
                return {'success': False, 'error': f'No se pudo crear el usuario: {err}'}

            creds = shlex.quote(f"{username}:{password}")
            self.run_cmd(ssh, f"echo {creds} | chpasswd", pwd, user)
            self.run_cmd(ssh, f"chage -E $(date -d '+{days} days' +%Y-%m-%d) {username}", pwd, user)
            self.run_cmd(ssh, f"mkdir -p {LIMITS_DIR}; echo '{max_conn}' > {LIMITS_DIR}/{username}", pwd, user)
            return {'success': True, 'username': username, 'password': password,
                    'days': days, 'max_conn': max_conn, 'message': 'Cuenta creada'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            ssh.close()

    def renew_user(self, server_id: int, username: str, days: int) -> Dict:
        if not self._valid_username(username):
            return {'success': False, 'error': 'Usuario inválido'}
        server = self.db.get_server(server_id)
        ssh = self._connect(server) if server else None
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        try:
            code, _, err = self.run_cmd(ssh, f"chage -E $(date -d '+{int(days)} days' +%Y-%m-%d) {username}",
                                        server['password'], server['username'])
            if code != 0:
                return {'success': False, 'error': err or 'chage falló'}
            return {'success': True}
        finally:
            ssh.close()

    def delete_user(self, server_id: int, username: str) -> Dict:
        if not self._valid_username(username):
            return {'success': False, 'error': 'Usuario inválido'}
        server = self.db.get_server(server_id)
        ssh = self._connect(server) if server else None
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        try:
            self.run_cmd(ssh, f"pkill -KILL -u {username} 2>/dev/null; userdel -f {username} 2>/dev/null; "
                              f"rm -f {LIMITS_DIR}/{username}; true", server['password'], server['username'])
            return {'success': True, 'message': f'Cuenta "{username}" eliminada'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            ssh.close()

    def list_online(self, server_id: int, username: str) -> int:
        if not self._valid_username(username):
            return 0
        server = self.db.get_server(server_id)
        ssh = self._connect(server) if server else None
        if not ssh:
            return 0
        try:
            _, out, _ = self.run_cmd(ssh, f"pgrep -u {username} -f '^sshd(-session)?: {username}' 2>/dev/null | wc -l",
                                     server['password'], server['username'])
            return int(out.strip() or 0)
        except Exception:
            return 0
        finally:
            ssh.close()

    def online_summary(self, server_id: int) -> Dict[str, int]:
        """{usuario: conexiones} de todas las cuentas conectadas por SSH."""
        server = self.db.get_server(server_id)
        ssh = self._connect(server) if server else None
        if not ssh:
            return {}
        try:
            _, out, _ = self.run_cmd(ssh, "ps -eo user:32,args | awk '$2 ~ /^sshd(-session)?:/ && $1 != \"root\" "
                                          "&& $1 != \"sshd\" {print $1}' | sort | uniq -c",
                                     server['password'], server['username'])
            res = {}
            for line in out.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[0].isdigit():
                    res[parts[1]] = int(parts[0])
            return res
        except Exception:
            return {}
        finally:
            ssh.close()

    # ------------------------------------------------------------------
    # 3. Config del cliente
    # ------------------------------------------------------------------
    def effective_record_type(self) -> Tuple[str, bool]:
        rt = self.db.get_record_type()
        return rt, rt == 'txt'

    def client_config(self, server: Dict, username: str, password: str,
                      record_type: str = None) -> Dict:
        """Config del cliente: string importable + campos sueltos (idéntico al servicio)."""
        from lib.vaydns_manager import tunnel_domain_for, timeouts_for
        tunnel = tunnel_domain_for(server)
        pubkey = server.get('pubkey') or ''
        clientid_size = config.DEFAULT_SERVER.get('clientid_size', 8)

        rt = record_type.lower() if record_type and record_type.lower() in RECORD_TYPES else self.db.get_record_type()
        compat, idle_timeout, keepalive = timeouts_for(rt)
        compat_s = 'true' if compat else 'false'

        backend = self.db.get_backend()
        slug = 'ssh' if backend == 'ssh' else 'socks5'

        url = (
            f"dnst://{tunnel}/vaydns/{slug}?"
            f"record-type={rt}&clientid-size={clientid_size}"
            f"&keepalive={keepalive}&idle-timeout={idle_timeout}"
            f"&dnstt-compat={compat_s}&pubkey={pubkey}"
            f"&user={username}&password={password}#{username}"
        )
        return {
            'url': url, 'tunnel': tunnel, 'pubkey': pubkey, 'record_type': rt,
            'clientid_size': clientid_size, 'dnstt_compat': compat_s,
            'keepalive': keepalive, 'idle_timeout': idle_timeout,
            'backend': backend, 'auth_proto': 'ssh' if backend == 'ssh' else 'socks',
            'user': username, 'password': password,
        }

    # ------------------------------------------------------------------
    # 4. Tráfico
    # ------------------------------------------------------------------
    def get_traffic(self, server_id: int) -> Optional[Dict]:
        server = self.db.get_server(server_id)
        ssh = self._connect(server) if server else None
        if not ssh:
            return None
        pwd, user = server['password'], server['username']
        try:
            _, out, _ = self.run_cmd(ssh, "awk 'NR>2{gsub(/:/,\" \"); if($1!=\"lo\"){rx+=$2; tx+=$10}} "
                                          "END{printf \"%d %d\", rx, tx}' /proc/net/dev", pwd, user)
            _, vnstat, _ = self.run_cmd(ssh, "vnstat --oneline 2>/dev/null || true", pwd, user)
            rx = tx = 0
            parts = out.split()
            if len(parts) == 2:
                try:
                    rx, tx = int(parts[0]), int(parts[1])
                except ValueError:
                    pass
            return {'rx': rx, 'tx': tx, 'vnstat': vnstat.strip()}
        except Exception:
            return None
        finally:
            ssh.close()
