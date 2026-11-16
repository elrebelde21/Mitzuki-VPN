"""
lib/remote.py  —  Utilidades SSH compartidas por los managers.

- connect(): conexión paramiko a la VPS.
- run(): ejecuta un comando (con sudo bien escapado si el usuario no es root).
- write_file(): escribe un archivo remoto por SFTP (sin pelear con comillas/heredocs).
- open_udp_port(): abre un puerto UDP en ufw / firewalld / iptables, según lo que haya.
- free_port_53(): libera el 53/udp de systemd-resolved (necesario para VayDNS).
"""
import io
import secrets
import shlex
from typing import Dict, Optional, Tuple

import paramiko


def connect(server: Dict, timeout: int = 30) -> Optional[paramiko.SSHClient]:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=server['ip'],
            port=int(server.get('ssh_port') or 22),
            username=server['username'],
            password=server['password'],
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        return ssh
    except Exception as e:
        print(f"[SSH] No se pudo conectar a {server.get('ip')}: {e}")
        return None


def run(ssh: paramiko.SSHClient, cmd: str, password: str = '', user: str = 'root',
        timeout: int = 600) -> Tuple[int, str, str]:
    """Ejecuta `cmd` en bash. Si el usuario no es root, lo envuelve en sudo con escape seguro."""
    if user != 'root':
        cmd = f"sudo -S -p '' bash -c {shlex.quote(cmd)}"
    else:
        cmd = f"bash -c {shlex.quote(cmd)}"
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    if user != 'root':
        stdin.write(password + '\n')
        stdin.flush()
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='ignore').strip()
    err = stderr.read().decode('utf-8', errors='ignore').strip()
    return code, out, err


def write_file(ssh: paramiko.SSHClient, path: str, content: str, password: str = '',
               user: str = 'root', mode: str = '644') -> None:
    """Sube `content` a /tmp por SFTP y lo mueve a `path` (con sudo si hace falta)."""
    tmp = f"/tmp/.mitzuki_{secrets.token_hex(6)}"
    sftp = ssh.open_sftp()
    try:
        sftp.putfo(io.BytesIO(content.encode('utf-8')), tmp)
    finally:
        sftp.close()
    run(ssh, f"install -m {mode} {shlex.quote(tmp)} {shlex.quote(path)} && rm -f {shlex.quote(tmp)}",
        password, user)


def open_udp_port(ssh: paramiko.SSHClient, port: int, password: str = '', user: str = 'root') -> None:
    """Abre el puerto UDP en el firewall que esté activo (ufw, firewalld) + iptables."""
    run(ssh,
        f"if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q 'Status: active'; then "
        f"  ufw allow {port}/udp >/dev/null 2>&1; fi; "
        f"if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then "
        f"  firewall-cmd --permanent --add-port={port}/udp >/dev/null 2>&1; firewall-cmd --reload >/dev/null 2>&1; fi; "
        f"if command -v iptables >/dev/null 2>&1; then "
        f"  iptables -C INPUT -p udp --dport {port} -j ACCEPT 2>/dev/null || "
        f"  iptables -I INPUT -p udp --dport {port} -j ACCEPT; fi; true",
        password, user)


def free_port_53(ssh: paramiko.SSHClient, password: str = '', user: str = 'root') -> None:
    """Desactiva el stub DNS de systemd-resolved (ocupa 127.0.0.53:53) y fija resolv.conf."""
    run(ssh,
        "if systemctl is-active --quiet systemd-resolved; then "
        "  mkdir -p /etc/systemd/resolved.conf.d && "
        "  printf '[Resolve]\\nDNSStubListener=no\\n' > /etc/systemd/resolved.conf.d/mitzuki.conf && "
        "  systemctl restart systemd-resolved; fi; "
        "rm -f /etc/resolv.conf; "
        "printf 'nameserver 1.1.1.1\\nnameserver 8.8.8.8\\n' > /etc/resolv.conf; true",
        password, user)


def udp_port_owner(ssh: paramiko.SSHClient, port: int, password: str = '', user: str = 'root') -> str:
    """Devuelve la línea de `ss` del proceso que escucha en ese UDP (vacío si está libre)."""
    _, out, _ = run(ssh, f"ss -H -ulnp 2>/dev/null | awk '$4 ~ /:{port}$/' || true", password, user)
    return out.strip()


class RemoteMixin:
    """Mixin para los managers: da _connect y run_cmd con la firma vieja."""

    def _connect(self, server: Dict) -> Optional[paramiko.SSHClient]:
        return connect(server)

    def connect_ssh(self, ip: str, port: int, username: str, password: str) -> Optional[paramiko.SSHClient]:
        return connect({'ip': ip, 'ssh_port': port, 'username': username, 'password': password})

    def run_cmd(self, ssh, cmd, password='', user='root', hide_output=False) -> Tuple[int, str, str]:
        return run(ssh, cmd, password, user)
