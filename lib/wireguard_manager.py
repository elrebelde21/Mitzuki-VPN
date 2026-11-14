"""
wireguard_manager.py  —  Backend WireGuard (VPN UDP directa, plano).

Convive con VayDNS: WG usa UDP 51820, VayDNS el 53.

- setup_wireguard: instala WG, genera llaves del server, levanta wg0 con NAT.
- prepare_peer: genera llaves del cliente (X25519) + asigna IP (no toca el server).
- rebuild: reescribe wg0.conf desde la DB (todos los peers activos) y sincroniza.
- client_conf: arma el .conf que importa el cliente.

Las llaves del cliente se generan en Python (cryptography), sin SSH.
"""

import base64
import paramiko
from typing import Dict, Optional, Tuple, List

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization


WG_PORT = 51820
WG_SUBNET = "10.7.0"          # /24
WG_SERVER_IP = "10.7.0.1"
WG_IFACE = "wg0"
WG_DIR = "/etc/wireguard"
CLIENT_DNS = "1.1.1.1, 8.8.8.8"


class WireGuardManager:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Llaves WireGuard (X25519) en Python
    # ------------------------------------------------------------------
    @staticmethod
    def generate_keys() -> Tuple[str, str]:
        priv = X25519PrivateKey.generate()
        priv_raw = priv.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        pub_raw = priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return base64.b64encode(priv_raw).decode(), base64.b64encode(pub_raw).decode()

    # ------------------------------------------------------------------
    # Helpers SSH
    # ------------------------------------------------------------------
    def _connect(self, server: Dict) -> Optional[paramiko.SSHClient]:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=server['ip'], port=server['ssh_port'],
                username=server['username'], password=server['password'],
                timeout=30, allow_agent=False, look_for_keys=False
            )
            return ssh
        except Exception as e:
            print(f"Error SSH (wireguard): {e}")
            return None

    def run_cmd(self, ssh, cmd, password, user='root', hide_output=False) -> Tuple[int, str, str]:
        if user != 'root':
            cmd = f"sudo -S -p '' bash -c '{cmd}'"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        if user != 'root':
            stdin.write(password + '\n')
            stdin.flush()
        code = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='ignore').strip()
        err = stderr.read().decode('utf-8', errors='ignore').strip()
        return code, out, err

    def _is_ubuntu(self, ssh, pwd, user) -> bool:
        _, out, _ = self.run_cmd(ssh, "cat /etc/os-release", pwd, user, hide_output=True)
        low = out.lower()
        return "ubuntu" in low or "debian" in low

    # ------------------------------------------------------------------
    # Render del wg0.conf
    # ------------------------------------------------------------------
    def _render_conf(self, server_priv: str, iface: str, peers: List[Dict]) -> str:
        conf = f"""[Interface]
Address = {WG_SERVER_IP}/24
ListenPort = {WG_PORT}
PrivateKey = {server_priv}
PostUp = iptables -A FORWARD -i {WG_IFACE} -j ACCEPT; iptables -A FORWARD -o {WG_IFACE} -j ACCEPT; iptables -t nat -A POSTROUTING -o {iface} -j MASQUERADE
PostDown = iptables -D FORWARD -i {WG_IFACE} -j ACCEPT; iptables -D FORWARD -o {WG_IFACE} -j ACCEPT; iptables -t nat -D POSTROUTING -o {iface} -j MASQUERADE
"""
        for p in peers:
            if p.get('wg_pubkey') and p.get('wg_ip'):
                conf += f"\n[Peer]\nPublicKey = {p['wg_pubkey']}\nAllowedIPs = {p['wg_ip']}/32\n"
        return conf

    # ------------------------------------------------------------------
    # Instalación
    # ------------------------------------------------------------------
    def setup_wireguard(self, server_id: int) -> Dict[str, any]:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        pwd, user = server['password'], server['username']
        try:
            is_ubuntu = self._is_ubuntu(ssh, pwd, user)

            if is_ubuntu:
                self.run_cmd(ssh, "export DEBIAN_FRONTEND=noninteractive && apt-get update -y", pwd, user)
                self.run_cmd(ssh, "export DEBIAN_FRONTEND=noninteractive && "
                                  "apt-get install -y wireguard wireguard-tools iptables", pwd, user)
            else:
                self.run_cmd(ssh, "dnf install -y epel-release || true", pwd, user)
                self.run_cmd(ssh, "dnf install -y wireguard-tools iptables || "
                                  "yum install -y wireguard-tools iptables", pwd, user)

            self.run_cmd(ssh, f"mkdir -p {WG_DIR} && chmod 700 {WG_DIR}", pwd, user)

            # Llaves del server (si no existen)
            self.run_cmd(ssh,
                         f"test -f {WG_DIR}/server_private.key || "
                         f"(wg genkey | tee {WG_DIR}/server_private.key | wg pubkey > {WG_DIR}/server_public.key)",
                         pwd, user)
            self.run_cmd(ssh, f"chmod 600 {WG_DIR}/server_private.key", pwd, user)

            _, server_priv, _ = self.run_cmd(ssh, f"cat {WG_DIR}/server_private.key", pwd, user, hide_output=True)
            _, server_pub, _ = self.run_cmd(ssh, f"cat {WG_DIR}/server_public.key", pwd, user, hide_output=True)
            server_priv = server_priv.strip()
            server_pub = server_pub.strip()
            if not server_priv or not server_pub:
                ssh.close()
                return {'success': False, 'error': 'No se generaron las llaves del servidor'}

            # Interfaz de salida
            _, iface, _ = self.run_cmd(ssh, "ip route | awk '/default/ {print $5}' | head -n1", pwd, user, hide_output=True)
            iface = iface.strip() or "eth0"

            # Reconstruir conf con los peers que ya existan en DB
            peers = self.db.get_wg_users(server_id)
            conf = self._render_conf(server_priv, iface, peers)
            self.run_cmd(ssh, f"cat > {WG_DIR}/{WG_IFACE}.conf << 'EOF'\n{conf}EOF", pwd, user)
            self.run_cmd(ssh, f"chmod 600 {WG_DIR}/{WG_IFACE}.conf", pwd, user)

            # IP forwarding
            self.run_cmd(ssh, "echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-wireguard.conf", pwd, user)
            self.run_cmd(ssh, "sysctl -w net.ipv4.ip_forward=1", pwd, user)

            # Firewall: abrir UDP 51820
            if is_ubuntu:
                self.run_cmd(ssh, f"iptables -C INPUT -p udp --dport {WG_PORT} -j ACCEPT 2>/dev/null || "
                                  f"iptables -I INPUT -p udp --dport {WG_PORT} -j ACCEPT", pwd, user)
            else:
                self.run_cmd(ssh, f"firewall-cmd --permanent --add-port={WG_PORT}/udp 2>/dev/null || true", pwd, user)
                self.run_cmd(ssh, "firewall-cmd --permanent --add-masquerade 2>/dev/null || true", pwd, user)
                self.run_cmd(ssh, "firewall-cmd --reload 2>/dev/null || true", pwd, user)

            # Levantar
            self.run_cmd(ssh, f"systemctl enable wg-quick@{WG_IFACE}", pwd, user)
            self.run_cmd(ssh, f"systemctl restart wg-quick@{WG_IFACE}", pwd, user)

            _, status, _ = self.run_cmd(ssh, f"systemctl is-active wg-quick@{WG_IFACE}", pwd, user, hide_output=True)
            if status.strip() != 'active':
                _, logs, _ = self.run_cmd(ssh, f"journalctl -u wg-quick@{WG_IFACE} -n 20 --no-pager", pwd, user, hide_output=True)
                ssh.close()
                return {'success': False, 'error': f'WireGuard no arrancó:\n{logs}'}

            ssh.close()
            self.db.set_config('wg_pubkey', server_pub)
            return {'success': True, 'message': 'WireGuard instalado', 'server_pubkey': server_pub}
        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}

    def is_wireguard_installed(self, server_id: int) -> bool:
        server = self.db.get_server(server_id)
        if not server:
            return False
        ssh = self._connect(server)
        if not ssh:
            return False
        try:
            _, out, _ = self.run_cmd(ssh, f"systemctl is-active wg-quick@{WG_IFACE}",
                                     server['password'], server['username'], hide_output=True)
            ssh.close()
            return out.strip() == "active"
        except Exception:
            ssh.close()
            return False

    # ------------------------------------------------------------------
    # Peers
    # ------------------------------------------------------------------
    def next_free_ip(self, server_id: int) -> Optional[str]:
        used = {u.get('wg_ip') for u in self.db.get_wg_users(server_id)}
        for n in range(2, 255):
            ip = f"{WG_SUBNET}.{n}"
            if ip not in used:
                return ip
        return None

    def prepare_peer(self, server_id: int, username: str) -> Dict[str, any]:
        """Genera llaves del cliente y asigna IP. No toca el servidor todavía."""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ip = self.next_free_ip(server_id)
        if not ip:
            return {'success': False, 'error': 'No hay IPs libres en la subred'}

        priv, pub = self.generate_keys()
        server_pub = self.db.get_config('wg_pubkey') or ''
        return {
            'success': True,
            'client_priv': priv,
            'client_pub': pub,
            'ip': ip,
            'server_pub': server_pub,
            'endpoint': f"{server['ip']}:{WG_PORT}",
            'server_ip': server['ip'],
        }

    def rebuild(self, server_id: int) -> Dict[str, any]:
        """Reescribe wg0.conf desde la DB y sincroniza sin cortar los demás peers."""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}
        pwd, user = server['password'], server['username']
        try:
            _, server_priv, _ = self.run_cmd(ssh, f"cat {WG_DIR}/server_private.key", pwd, user, hide_output=True)
            server_priv = server_priv.strip()
            if not server_priv:
                ssh.close()
                return {'success': False, 'error': 'WireGuard no está instalado'}

            _, iface, _ = self.run_cmd(ssh, "ip route | awk '/default/ {print $5}' | head -n1", pwd, user, hide_output=True)
            iface = iface.strip() or "eth0"

            peers = self.db.get_wg_users(server_id)
            conf = self._render_conf(server_priv, iface, peers)
            self.run_cmd(ssh, f"cat > {WG_DIR}/{WG_IFACE}.conf << 'EOF'\n{conf}EOF", pwd, user)
            self.run_cmd(ssh, f"chmod 600 {WG_DIR}/{WG_IFACE}.conf", pwd, user)

            # Aplicar cambios de peers sin tirar las conexiones existentes
            self.run_cmd(ssh, f"bash -c 'wg syncconf {WG_IFACE} <(wg-quick strip {WG_IFACE})'", pwd, user)

            ssh.close()
            return {'success': True}
        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}

    def client_conf(self, client_priv: str, ip: str, server_pub: str, endpoint: str) -> str:
        return f"""[Interface]
PrivateKey = {client_priv}
Address = {ip}/32
DNS = {CLIENT_DNS}

[Peer]
PublicKey = {server_pub}
Endpoint = {endpoint}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""