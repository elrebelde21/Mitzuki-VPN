"""
wireguard_manager.py  —  Backend WireGuard (VPN UDP directa).

Convive con VayDNS: WG usa UDP 51820, VayDNS el 53.

- setup_wireguard: instala WG, llaves del server, wg0 con NAT, firewall (ufw/firewalld/iptables).
- prepare_peer: llaves del cliente (X25519, en Python) + IP libre.
- rebuild: reescribe wg0.conf desde la DB y lo aplica (syncconf, o reinicio si hace falta).
- client_conf: el .conf que importa el cliente.
"""
import base64
from typing import Dict, List, Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

import config
from lib.remote import RemoteMixin, write_file, open_udp_port

WG_PORT = 51820
WG_SUBNET = "10.7.0"          # /24
WG_SERVER_IP = "10.7.0.1"
WG_IFACE = "wg0"
WG_DIR = "/etc/wireguard"
CLIENT_DNS = "1.1.1.1, 8.8.8.8"
CLIENT_MTU = 1280             # seguro para datos móviles / redes con MTU baja


class WireGuardManager(RemoteMixin):
    def __init__(self, db):
        self.db = db

    @staticmethod
    def generate_keys() -> Tuple[str, str]:
        priv = X25519PrivateKey.generate()
        priv_raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                      serialization.NoEncryption())
        pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return base64.b64encode(priv_raw).decode(), base64.b64encode(pub_raw).decode()

    def _is_ubuntu(self, ssh, pwd, user) -> bool:
        _, out, _ = self.run_cmd(ssh, "cat /etc/os-release", pwd, user)
        low = out.lower()
        return "ubuntu" in low or "debian" in low

    def endpoint_host(self, server: Dict) -> str:
        return getattr(config, 'WG_ENDPOINT', '') or server['ip']

    # ------------------------------------------------------------------
    # wg0.conf
    # ------------------------------------------------------------------
    def _render_conf(self, server_priv: str, iface: str, peers: List[Dict]) -> str:
        up = (f"iptables -I FORWARD -i {WG_IFACE} -j ACCEPT; iptables -I FORWARD -o {WG_IFACE} -j ACCEPT; "
              f"iptables -t nat -I POSTROUTING -s {WG_SUBNET}.0/24 -o {iface} -j MASQUERADE; "
              f"iptables -t mangle -I FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu")
        down = (f"iptables -D FORWARD -i {WG_IFACE} -j ACCEPT; iptables -D FORWARD -o {WG_IFACE} -j ACCEPT; "
                f"iptables -t nat -D POSTROUTING -s {WG_SUBNET}.0/24 -o {iface} -j MASQUERADE; "
                f"iptables -t mangle -D FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu")
        conf = (f"[Interface]\nAddress = {WG_SERVER_IP}/24\nListenPort = {WG_PORT}\n"
                f"PrivateKey = {server_priv}\nPostUp = {up}\nPostDown = {down}\n")
        for p in peers:
            if p.get('wg_pubkey') and p.get('wg_ip'):
                conf += (f"\n# {p.get('username', '')}\n[Peer]\nPublicKey = {p['wg_pubkey']}\n"
                         f"AllowedIPs = {p['wg_ip']}/32\n")
        return conf

    def _write_and_apply(self, ssh, server_id: int, server_priv: str, pwd: str, user: str,
                         restart: bool = False) -> Dict:
        _, iface, _ = self.run_cmd(ssh, "ip route | awk '/default/ {print $5}' | head -n1", pwd, user)
        iface = iface.strip() or "eth0"
        conf = self._render_conf(server_priv, iface, self.db.get_wg_users(server_id))
        write_file(ssh, f"{WG_DIR}/{WG_IFACE}.conf", conf, pwd, user, mode='600')

        if not restart:
            # Aplica peers sin cortar a nadie; si wg0 no está arriba, se reinicia
            code, _, _ = self.run_cmd(ssh, f"ip link show {WG_IFACE} >/dev/null 2>&1 && "
                                           f"wg syncconf {WG_IFACE} <(wg-quick strip {WG_IFACE})", pwd, user)
            restart = code != 0
        if restart:
            self.run_cmd(ssh, f"systemctl enable wg-quick@{WG_IFACE} >/dev/null 2>&1; "
                              f"systemctl restart wg-quick@{WG_IFACE}", pwd, user)

        _, status, _ = self.run_cmd(ssh, f"systemctl is-active wg-quick@{WG_IFACE}", pwd, user)
        if status.strip() != 'active':
            _, logs, _ = self.run_cmd(ssh, f"journalctl -u wg-quick@{WG_IFACE} -n 15 --no-pager", pwd, user)
            return {'success': False, 'error': f'WireGuard no está activo:\n{logs[-1500:]}'}
        return {'success': True}

    # ------------------------------------------------------------------
    # Instalación
    # ------------------------------------------------------------------
    def setup_wireguard(self, server_id: int) -> Dict:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        pwd, user = server['password'], server['username']
        try:
            if self._is_ubuntu(ssh, pwd, user):
                self.run_cmd(ssh, "export DEBIAN_FRONTEND=noninteractive; apt-get update -y -q; "
                                  "apt-get install -y -q wireguard wireguard-tools iptables", pwd, user)
            else:
                self.run_cmd(ssh, "dnf install -y epel-release; dnf install -y wireguard-tools iptables || "
                                  "yum install -y wireguard-tools iptables", pwd, user)

            code, _, _ = self.run_cmd(ssh, "command -v wg >/dev/null && command -v wg-quick >/dev/null", pwd, user)
            if code != 0:
                return {'success': False, 'error': 'No se pudo instalar wireguard-tools en la VPS'}

            self.run_cmd(ssh, f"mkdir -p {WG_DIR} && chmod 700 {WG_DIR}; "
                              f"test -s {WG_DIR}/server_private.key || "
                              f"(umask 077; wg genkey | tee {WG_DIR}/server_private.key | wg pubkey > {WG_DIR}/server_public.key)",
                         pwd, user)
            _, server_priv, _ = self.run_cmd(ssh, f"cat {WG_DIR}/server_private.key", pwd, user)
            _, server_pub, _ = self.run_cmd(ssh, f"cat {WG_DIR}/server_private.key | wg pubkey", pwd, user)
            server_priv, server_pub = server_priv.strip(), server_pub.strip()
            if not server_priv or not server_pub:
                return {'success': False, 'error': 'No se generaron las llaves del servidor'}

            # Reenvío de paquetes (IPv4) + firewall
            self.run_cmd(ssh, "printf 'net.ipv4.ip_forward=1\\n' > /etc/sysctl.d/99-mitzuki-wg.conf; "
                              "sysctl -w net.ipv4.ip_forward=1 >/dev/null", pwd, user)
            open_udp_port(ssh, WG_PORT, pwd, user)
            self.run_cmd(ssh, "if command -v ufw >/dev/null 2>&1 && ufw status | grep -q 'Status: active'; then "
                              "sed -i 's/^DEFAULT_FORWARD_POLICY=.*/DEFAULT_FORWARD_POLICY=\"ACCEPT\"/' /etc/default/ufw; "
                              "ufw reload >/dev/null 2>&1; fi; "
                              "if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then "
                              "firewall-cmd --permanent --add-masquerade >/dev/null 2>&1; firewall-cmd --reload >/dev/null 2>&1; fi; true",
                         pwd, user)

            res = self._write_and_apply(ssh, server_id, server_priv, pwd, user, restart=True)
            if not res['success']:
                return res
            self.db.set_config('wg_pubkey', server_pub)
            return {'success': True, 'message': 'WireGuard instalado', 'server_pubkey': server_pub}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            ssh.close()

    def uninstall_wireguard(self, server_id: int) -> Dict:
        server = self.db.get_server(server_id)
        ssh = self._connect(server) if server else None
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        try:
            self.run_cmd(ssh, f"systemctl disable --now wg-quick@{WG_IFACE} 2>/dev/null; "
                              f"rm -f {WG_DIR}/{WG_IFACE}.conf; true", server['password'], server['username'])
            return {'success': True, 'message': 'WireGuard desinstalado (las llaves del servidor se conservan)'}
        finally:
            ssh.close()

    def is_wireguard_installed(self, server_id: int) -> bool:
        server = self.db.get_server(server_id)
        ssh = self._connect(server) if server else None
        if not ssh:
            return False
        try:
            _, out, _ = self.run_cmd(ssh, f"systemctl is-active wg-quick@{WG_IFACE}",
                                     server['password'], server['username'])
            return out.strip() == "active"
        finally:
            ssh.close()

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

    def prepare_peer(self, server_id: int, username: str) -> Dict:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ip = self.next_free_ip(server_id)
        if not ip:
            return {'success': False, 'error': 'No hay IPs libres (máximo 253 clientes WireGuard)'}
        server_pub = self.db.get_config('wg_pubkey') or ''
        if not server_pub:
            return {'success': False, 'error': 'WireGuard no está instalado (falta la llave del servidor)'}
        priv, pub = self.generate_keys()
        return {
            'success': True, 'client_priv': priv, 'client_pub': pub, 'ip': ip,
            'server_pub': server_pub,
            'endpoint': f"{self.endpoint_host(server)}:{WG_PORT}",
            'server_ip': server['ip'],
        }

    def rebuild(self, server_id: int, restart: bool = False) -> Dict:
        """Reescribe wg0.conf desde la DB y lo aplica. Sincroniza también la llave pública."""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self._connect(server)
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar a la VPS por SSH'}
        pwd, user = server['password'], server['username']
        try:
            _, server_priv, _ = self.run_cmd(ssh, f"cat {WG_DIR}/server_private.key 2>/dev/null", pwd, user)
            server_priv = server_priv.strip()
            if not server_priv:
                return {'success': False, 'error': 'WireGuard no está instalado'}
            _, server_pub, _ = self.run_cmd(ssh, f"cat {WG_DIR}/server_private.key | wg pubkey", pwd, user)
            if server_pub.strip():
                self.db.set_config('wg_pubkey', server_pub.strip())
            self.run_cmd(ssh, "sysctl -w net.ipv4.ip_forward=1 >/dev/null", pwd, user)
            open_udp_port(ssh, WG_PORT, pwd, user)
            return self._write_and_apply(ssh, server_id, server_priv, pwd, user, restart=restart)
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            ssh.close()

    def client_conf(self, client_priv: str, ip: str, server_pub: str, endpoint: str) -> str:
        return (f"[Interface]\nPrivateKey = {client_priv}\nAddress = {ip}/32\nDNS = {CLIENT_DNS}\n"
                f"MTU = {CLIENT_MTU}\n\n[Peer]\nPublicKey = {server_pub}\nEndpoint = {endpoint}\n"
                f"AllowedIPs = 0.0.0.0/0, ::/0\nPersistentKeepalive = 25\n")
