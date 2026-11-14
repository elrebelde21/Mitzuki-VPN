"""
ssh_accounts_manager.py
=======================

Núcleo de "cuentas reales" para VayDNS/Soar.

VayDNS/dnstt solo transporta: no tiene usuarios. Las cuentas viven en el
upstream. Acá montamos un sshd DEDICADO (solo para túnel) escuchando en
127.0.0.1:2222 — no expuesto a internet, solo accesible a través del túnel.
Cada cliente del bot es una cuenta SSH real:

  - usuario + contraseña
  - vencimiento nativo con `chage -E` (al expirar, el login se rechaza)
  - tope de conexiones simultáneas con un limitador que cuenta sesiones por
    usuario y mata las que pasen del límite
  - shell bloqueada: solo sirve para forwarding (SOCKS), no da acceso al VPS
"""

import random
import string
import paramiko
import config
import os
from typing import Dict, Optional, Tuple
from database import RECORD_TYPES


# Puerto interno del sshd dedicado a túnel (solo 127.0.0.1)
SSH_TUNNEL_PORT = 2222
SSH_GROUP = "vaydns-ssh"
SSH_DIR = "/etc/vaydns-ssh"
LIMITS_DIR = "/etc/vaydns-ssh/limits"


class SSHAccountsManager:
    def __init__(self, db):
        self.db = db

    def generate_password(self, length: int = 12) -> str:
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(length))

    def _connect(self, server: Dict) -> Optional[paramiko.SSHClient]:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=server['ip'],
                port=server['ssh_port'],
                username=server['username'],
                password=server['password'],
                timeout=30,
                allow_agent=False,
                look_for_keys=False
            )
            return ssh
        except Exception as e:
            print(f"Error SSH (accounts): {e}")
            return None

    def run_cmd(self, ssh: paramiko.SSHClient, cmd: str, password: str,
                user: str = 'root', hide_output: bool = False) -> Tuple[int, str, str]:
        if user != 'root':
            cmd = f"sudo -S -p '' bash -c '{cmd}'"

        stdin, stdout, stderr = ssh.exec_command(cmd)

        if user != 'root':
            stdin.write(password + '\n')
            stdin.flush()

        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='ignore').strip()
        err = stderr.read().decode('utf-8', errors='ignore').strip()
        return exit_status, out, err

    def _is_ubuntu(self, ssh, pwd, user) -> bool:
        _, out, _ = self.run_cmd(ssh, "cat /etc/os-release", pwd, user, hide_output=True)
        low = out.lower()
        return "ubuntu" in low or "debian" in low

    def _dante_info(self, is_ubuntu):
        if is_ubuntu:
            return "/etc/danted.conf", "danted"
        return "/etc/sockd.conf", "sockd"

    def _valid_username(self, name: str) -> bool:
        """Linux username seguro: minúsculas, dígitos, guion/guion bajo, empieza con letra."""
        if not name or len(name) > 31:
            return False
        if name[0] not in string.ascii_lowercase:
            return False
        allowed = set(string.ascii_lowercase + string.digits + "_-")
        return all(c in allowed for c in name)

    # ------------------------------------------------------------------
    # 1. Montar el backend (sshd dedicado + limitador)
    # ------------------------------------------------------------------
    def setup_backend(self, server_id: int, repoint_vaydns: bool = True) -> Dict[str, any]:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        pwd = server['password']
        user = server['username']

        try:
            is_ubuntu = self._is_ubuntu(ssh, pwd, user)

            if is_ubuntu:
                self.run_cmd(ssh, "dpkg -s openssh-server >/dev/null 2>&1 || "
                                  "(export DEBIAN_FRONTEND=noninteractive && apt-get install -y openssh-server)",
                             pwd, user)
            else:
                self.run_cmd(ssh, "rpm -q openssh-server >/dev/null 2>&1 || dnf install -y openssh-server",
                             pwd, user)

            self.run_cmd(ssh, f"getent group {SSH_GROUP} >/dev/null || groupadd {SSH_GROUP}", pwd, user)
            self.run_cmd(ssh, f"mkdir -p {SSH_DIR} {LIMITS_DIR}", pwd, user)

            self.run_cmd(ssh,
                         f"test -f {SSH_DIR}/ssh_host_ed25519_key || "
                         f"ssh-keygen -t ed25519 -f {SSH_DIR}/ssh_host_ed25519_key -N '' -q",
                         pwd, user)
            self.run_cmd(ssh, f"chmod 600 {SSH_DIR}/ssh_host_ed25519_key", pwd, user)

            noshell = "#!/bin/sh\necho 'Tunnel only. Shell disabled.'\nsleep 3\nexit 0\n"
            self.run_cmd(ssh, f"cat > /usr/local/bin/vaydns-noshell << 'EOF'\n{noshell}EOF", pwd, user)
            self.run_cmd(ssh, "chmod 755 /usr/local/bin/vaydns-noshell", pwd, user)

            sshd_config = f"""Port {SSH_TUNNEL_PORT}
ListenAddress 127.0.0.1
Protocol 2
HostKey {SSH_DIR}/ssh_host_ed25519_key
PidFile /run/vaydns-sshd.pid
UsePAM yes
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin no
AllowGroups {SSH_GROUP}
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding yes
PermitTTY no
PrintMotd no
PrintLastLog no
ClientAliveInterval 30
ClientAliveCountMax 3
LoginGraceTime 20
MaxStartups 200:30:500

Match Group {SSH_GROUP}
    ForceCommand /usr/local/bin/vaydns-noshell
    AllowTcpForwarding yes
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
"""
            self.run_cmd(ssh, f"cat > {SSH_DIR}/sshd_config << 'EOF'\n{sshd_config}EOF", pwd, user)

            code, _, err = self.run_cmd(ssh, f"/usr/sbin/sshd -t -f {SSH_DIR}/sshd_config", pwd, user, hide_output=True)
            if code != 0:
                ssh.close()
                return {'success': False, 'error': f'Config sshd inválida:\n{err}'}

            sshd_service = f"""[Unit]
Description=VayDNS dedicated SSH (tunnel accounts)
After=network.target

[Service]
Type=simple
ExecStartPre=/usr/sbin/sshd -t -f {SSH_DIR}/sshd_config
ExecStart=/usr/sbin/sshd -D -f {SSH_DIR}/sshd_config
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target"""
            self.run_cmd(ssh, f"cat > /etc/systemd/system/vaydns-sshd.service << 'EOF'\n{sshd_service}\nEOF", pwd, user)

            limiter = f"""#!/bin/bash
LIMDIR="{LIMITS_DIR}"
while true; do
    for f in "$LIMDIR"/*; do
        [ -e "$f" ] || continue
        u=$(basename "$f")
        lim=$(cat "$f" 2>/dev/null)
        case "$lim" in ''|*[!0-9]*) continue;; esac
        [ "$lim" -le 0 ] && continue
        pids=$(pgrep -u "$u" sshd 2>/dev/null | tr '\\n' ',' | sed 's/,$//')
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
            self.run_cmd(ssh, f"cat > /usr/local/bin/vaydns-limiter.sh << 'EOF'\n{limiter}EOF", pwd, user)
            self.run_cmd(ssh, "chmod 755 /usr/local/bin/vaydns-limiter.sh", pwd, user)

            limiter_service = """[Unit]
Description=VayDNS connection limiter
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/vaydns-limiter.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"""
            self.run_cmd(ssh, f"cat > /etc/systemd/system/vaydns-limiter.service << 'EOF'\n{limiter_service}\nEOF", pwd, user)

            self.run_cmd(ssh, "systemctl daemon-reload", pwd, user)
            self.run_cmd(ssh, "systemctl enable vaydns-sshd vaydns-limiter", pwd, user)
            self.run_cmd(ssh, "systemctl restart vaydns-sshd", pwd, user)
            self.run_cmd(ssh, "systemctl restart vaydns-limiter", pwd, user)

            _, sshd_status, _ = self.run_cmd(ssh, "systemctl is-active vaydns-sshd", pwd, user, hide_output=True)
            if sshd_status.strip() != 'active':
                _, logs, _ = self.run_cmd(ssh, "journalctl -u vaydns-sshd -n 20 --no-pager", pwd, user, hide_output=True)
                ssh.close()
                return {'success': False, 'error': f'El sshd dedicado no arrancó:\n{logs}'}

            ssh.close()
            return {'success': True, 'message': 'Backend SSH listo (sshd dedicado + limitador)'}

        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}

    def is_backend_installed(self, server_id: int) -> bool:
        server = self.db.get_server(server_id)
        if not server:
            return False
        ssh = self._connect(server)
        if not ssh:
            return False
        try:
            _, out, _ = self.run_cmd(ssh, "systemctl is-active vaydns-sshd",
                                     server['password'], server['username'], hide_output=True)
            ssh.close()
            return out.strip() == "active"
        except Exception:
            ssh.close()
            return False

    def apply_backend(self, server_id: int, backend: str) -> Dict[str, any]:
        self.db.set_backend(backend)
        return {'success': True, 'message': f'Backend {backend} activo'}

    # ------------------------------------------------------------------
    # 2. CRUD de usuarios
    # ------------------------------------------------------------------
    def create_user(self, server_id: int, username: str, password: str,
                    days: int, max_conn: int = 3) -> Dict[str, any]:
        if not self._valid_username(username):
            return {'success': False, 'error': 'Usuario inválido (usá minúsculas, dígitos, - o _, empieza con letra)'}
        if not password or len(password) < 4:
            return {'success': False, 'error': 'Contraseña muy corta (mínimo 4)'}
        if days <= 0:
            return {'success': False, 'error': 'Días inválidos'}
        max_conn = max_conn if max_conn and max_conn > 0 else 3

        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        pwd = server['password']
        user = server['username']

        try:
            _, exists, _ = self.run_cmd(ssh, f"id -u {username} >/dev/null 2>&1 && echo yes || echo no",
                                        pwd, user, hide_output=True)
            if exists.strip() == 'yes':
                ssh.close()
                return {'success': False, 'error': f'El usuario "{username}" ya existe'}

            code, _, err = self.run_cmd(
                ssh,
                f"useradd -M -N -g {SSH_GROUP} -s /usr/sbin/nologin {username}",
                pwd, user
            )
            if code != 0:
                ssh.close()
                return {'success': False, 'error': f'useradd falló: {err}'}

            self.run_cmd(ssh, f"echo '{username}:{password}' | chpasswd", pwd, user)
            self.run_cmd(ssh, f"chage -E $(date -d '+{days} days' +%Y-%m-%d) {username}", pwd, user)
            self.run_cmd(ssh, f"echo '{max_conn}' > {LIMITS_DIR}/{username}", pwd, user)

            ssh.close()
            return {
                'success': True,
                'username': username,
                'password': password,
                'days': days,
                'max_conn': max_conn,
                'message': 'Cuenta creada'
            }

        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}

    def delete_user(self, server_id: int, username: str) -> Dict[str, any]:
        if not self._valid_username(username):
            return {'success': False, 'error': 'Usuario inválido'}
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}
        pwd = server['password']
        user = server['username']
        try:
            self.run_cmd(ssh, f"pkill -u {username} 2>/dev/null || true", pwd, user)
            self.run_cmd(ssh, f"userdel {username} 2>/dev/null || true", pwd, user)
            self.run_cmd(ssh, f"rm -f {LIMITS_DIR}/{username}", pwd, user)
            ssh.close()
            return {'success': True, 'message': f'Cuenta "{username}" eliminada'}
        except Exception as e:
            ssh.close()
            return {'success': False, 'error': str(e)}

    def list_online(self, server_id: int, username: str) -> int:
        if not self._valid_username(username):
            return 0
        server = self.db.get_server(server_id)
        if not server:
            return 0
        ssh = self._connect(server)
        if not ssh:
            return 0
        try:
            _, out, _ = self.run_cmd(ssh, f"pgrep -u {username} sshd 2>/dev/null | wc -l",
                                     server['password'], server['username'], hide_output=True)
            ssh.close()
            try:
                return int(out.strip())
            except ValueError:
                return 0
        except Exception:
            ssh.close()
            return 0

    # ------------------------------------------------------------------
    # 3. Config del cliente (URL + campos para la app)
    # ------------------------------------------------------------------
    def effective_record_type(self) -> Tuple[str, bool]:
        rt = (self.db.get_record_type() or 'txt').lower()
        if rt not in RECORD_TYPES:
            rt = 'txt'
        dnstt_compat = (rt == 'txt')
        return rt, dnstt_compat

    def client_config(self, server: Dict, username: str, password: str,
                      record_type: str = None) -> Dict[str, any]:
        """Arma el config del cliente (string importable + campos sueltos)."""
        d = config.DEFAULT_SERVER
        tunnel = d.get('tunnel_domain',
                       f"d.{'.'.join(server['domain'].split('.')[1:])}")
        pubkey = server.get('pubkey') or ''
        clientid_size = d.get('clientid_size', 8)

        if record_type and record_type.lower() in RECORD_TYPES:
            rt = record_type.lower()
        else:
            rt, _ = self.effective_record_type()
        dnstt_compat = (rt == 'txt')
        compat_s = 'true' if dnstt_compat else 'false'
        keepalive, idle_timeout = ('10s', '2m') if dnstt_compat else ('2s', '10s')

        backend = self.db.get_backend()
        slug = 'ssh' if backend == 'ssh' else 'socks5'

        # ⚠️ SIEMPRE USAMOS dnst:// Y LA MISMA RUTA PARA QUE CONECTE
        url = (
            f"dnst://{tunnel}/vaydns/{slug}?"
            f"record-type={rt}&clientid-size={clientid_size}"
            f"&keepalive={keepalive}&idle-timeout={idle_timeout}"
            f"&dnstt-compat={compat_s}&pubkey={pubkey}"
            f"&user={username}&password={password}#vaydns"
        )

        return {
            'url': url,
            'tunnel': tunnel,
            'pubkey': pubkey,
            'record_type': rt,
            'clientid_size': clientid_size,
            'dnstt_compat': compat_s,
            'keepalive': keepalive,
            'idle_timeout': idle_timeout,
            'backend': backend,
            'auth_proto': 'ssh' if backend == 'ssh' else 'socks',
            'user': username,
            'password': password,
        }

    def set_server_record_type(self, server_id: int, record_type: str) -> Dict[str, any]:
        record_type = (record_type or '').lower()
        if record_type not in RECORD_TYPES:
            return {'success': False, 'error': 'record_type inválido'}

        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        pwd, user = server['password'], server['username']
        unit = "/etc/systemd/system/vaydns-server.service"
        try:
            _, exists, _ = self.run_cmd(ssh, f"test -f {unit} && echo yes || echo no", pwd, user, hide_output=True)
            if exists.strip() != 'yes':
                ssh.close()
                return {'success': False, 'error': 'vaydns-server no está instalado'}

            self.run_cmd(ssh, f"sed -i 's/ -dnstt-compat//g' {unit}", pwd, user)
            self.run_cmd(ssh, f"sed -i -E 's/-record-type [a-zA-Z]+/-record-type {record_type}/' {unit}", pwd, user)
            if record_type == 'txt':
                self.run_cmd(ssh, f"sed -i -E 's/(-record-type txt)/\\1 -dnstt-compat/' {unit}", pwd, user)

            self.run_cmd(ssh, "systemctl daemon-reload", pwd, user)
            self.run_cmd(ssh, "systemctl restart vaydns-server", pwd, user)
            _, status, _ = self.run_cmd(ssh, "systemctl is-active vaydns-server", pwd, user, hide_output=True)
            ssh.close()
            if status.strip() != 'active':
                return {'success': False, 'error': 'vaydns-server no quedó activo tras el cambio'}
            return {'success': True, 'record_type': record_type}
        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}

    def get_traffic(self, server_id: int) -> Optional[Dict[str, any]]:
        server = self.db.get_server(server_id)
        if not server:
            return None
        ssh = self._connect(server)
        if not ssh:
            return None
        pwd, user = server['password'], server['username']
        try:
            cmd = ("awk 'NR>2{gsub(/:/,\"\"); if($1!=\"lo\"){rx+=$2; tx+=$10}} "
                   "END{printf \"%d %d\", rx, tx}' /proc/net/dev")
            _, out, _ = self.run_cmd(ssh, cmd, pwd, user, hide_output=True)
            _, vnstat, _ = self.run_cmd(ssh, "vnstat --oneline 2>/dev/null || true", pwd, user, hide_output=True)
            ssh.close()

            rx = tx = 0
            parts = out.split()
            if len(parts) == 2:
                try:
                    rx, tx = int(parts[0]), int(parts[1])
                except ValueError:
                    pass
            return {'rx': rx, 'tx': tx, 'vnstat': vnstat.strip()}
        except Exception:
            try:
                ssh.close()
            except Exception:
                pass
            return None