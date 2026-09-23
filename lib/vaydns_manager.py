import config
import paramiko
import random
import string
from typing import Dict, List, Optional, Tuple


class VayDNSManager:
    def __init__(self, db):
        self.db = db

    def generate_password(self, length: int = 12) -> str:
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(length))

    def connect_ssh(self, ip: str, port: int, username: str, password: str) -> Optional[paramiko.SSHClient]:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=ip,
                port=port,
                username=username,
                password=password,
                timeout=30,
                allow_agent=False,
                look_for_keys=False
            )
            return ssh
        except Exception as e:
            print(f"Error SSH: {e}")
            return None

    def run_cmd(self, ssh: paramiko.SSHClient, cmd: str, password: str, user: str = 'root', hide_output: bool = False) -> Tuple[int, str, str]:
        if user != 'root':
            cmd = f"sudo -S -p '' bash -c '{cmd}'"

        stdin, stdout, stderr = ssh.exec_command(cmd)

        if user != 'root':
            stdin.write(password + '\n')
            stdin.flush()

        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8').strip()
        err = stderr.read().decode('utf-8').strip()

        return exit_status, out, err

    def detect_os(self, ssh: paramiko.SSHClient, password: str, user: str = 'root') -> Dict[str, str]:
        _, os_info, _ = self.run_cmd(ssh, "cat /etc/os-release", password, user, hide_output=True)
        os_info_lower = os_info.lower()

        is_ubuntu = "ubuntu" in os_info_lower or "debian" in os_info_lower

        version_id = ""
        for line in os_info.splitlines():
            if line.startswith("VERSION_ID="):
                version_id = line.split("=")[1].strip('"').strip("'")
                break

        if is_ubuntu:
            dante_config_path = "/etc/danted.conf"
            dante_service = "danted"
        else:
            dante_config_path = "/etc/sockd.conf"
            dante_service = "sockd"

        return {
            'is_ubuntu': is_ubuntu,
            'version': version_id,
            'dante_config_path': dante_config_path,
            'dante_service': dante_service
        }

    def install_vaydns(self, server_id: int) -> Dict[str, any]:
        """Instala VayDNS con configuración DNSTT (compatible con Cuba)"""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            os_info = self.detect_os(ssh, server['password'], server['username'])
            default = config.DEFAULT_SERVER

            print("Actualizando sistema...")
            if os_info['is_ubuntu']:
                self.run_cmd(ssh, "export DEBIAN_FRONTEND=noninteractive && apt-get update -y",
                             server['password'], server['username'])
                self.run_cmd(ssh, "export DEBIAN_FRONTEND=noninteractive && apt-get install -y tar dante-server iptables iptables-persistent curl vnstat sed tcpdump net-tools bind9-dnsutils wget xz-utils",
                             server['password'], server['username'])
            else:
                self.run_cmd(ssh, "dnf update -y", server['password'], server['username'])
                self.run_cmd(ssh, "dnf install -y epel-release", server['password'], server['username'])
                self.run_cmd(ssh, "dnf install -y tar dante-server firewalld curl tcpdump net-tools bind-utils vnstat sed wget xz",
                             server['password'], server['username'])

            print("Creando usuario vaydns...")
            self.run_cmd(ssh, "id -u vaydns &>/dev/null || useradd -r -M -s /bin/false -c 'vaydns service user' -d /nonexistent vaydns",
                         server['password'], server['username'])

            print("Descargando y configurando VayDNS...")
            binary_url = "https://raw.githubusercontent.com/phoenixdnsvpn/phoenix-vpn/main/scripts/vaydns-server"
            setup_cmds = f"""
                cd /tmp
                curl -sL {binary_url} -o vaydns-server
                chmod +x vaydns-server
                ./vaydns-server -gen-key -privkey-file server.key -pubkey-file server.pub
                mkdir -p /etc/vaydns
                mv server.key server.pub /etc/vaydns/
                chown -R vaydns:vaydns /etc/vaydns
                mv vaydns-server /usr/local/bin/
                chmod 755 /usr/local/bin/vaydns-server
            """
            self.run_cmd(ssh, setup_cmds, server['password'], server['username'])

            print("Configurando proxy SOCKS5...")
            _, primary_interface, _ = self.run_cmd(ssh, "ip route | awk '/default/ {print $5}' | head -n1",
                                                   server['password'], server['username'], hide_output=True)
            if not primary_interface:
                primary_interface = "eth0"

            sockd_content = f"""logoutput: stderr
internal: 127.0.0.1 port = 8000
external: {primary_interface}
socksmethod: none
clientmethod: none

client pass {{
        from: 127.0.0.1/32 to: 0.0.0.0/0
        log: connect error
}}

socks pass {{
        from: 127.0.0.1/32 to: 0.0.0.0/0
        protocol: tcp udp
        log: connect error
}}"""

            config_path = os_info['dante_config_path']
            self.run_cmd(ssh, f"mv {config_path} {config_path}.1 || true", server['password'], server['username'])
            write_cmd = f"cat > {config_path} << 'EOF'\n{sockd_content}\nEOF"
            self.run_cmd(ssh, write_cmd, server['password'], server['username'])

            self.run_cmd(ssh, "systemctl daemon-reload", server['password'], server['username'])
            self.run_cmd(ssh, f"systemctl start {os_info['dante_service']}", server['password'], server['username'])
            self.run_cmd(ssh, f"systemctl enable {os_info['dante_service']}", server['password'], server['username'])

            print("Arreglando DNS del sistema...")
            self.run_cmd(ssh, "rm -f /etc/resolv.conf", server['password'], server['username'])
            self.run_cmd(ssh, "echo 'nameserver 1.1.1.1' > /etc/resolv.conf", server['password'], server['username'])
            self.run_cmd(ssh, "echo 'nameserver 8.8.8.8' >> /etc/resolv.conf", server['password'], server['username'])

            print("Creando servicio systemd...")
            tunnel_domain = default.get('tunnel_domain', f"d.{'.'.join(server['domain'].split('.')[1:])}")
            port = default.get('port', 53)
            record_type = default.get('record_type', 'txt')
            dnstt_compat = default.get('dnstt_compat', True)
            dnstt_flag = '-dnstt-compat' if dnstt_compat else ''

            vaydns_service = f"""[Unit]
Description=VayDNS Tunnel Server
After=network.target
Wants=network.target

[Service]
Type=simple
User=vaydns
Group=vaydns
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
ExecStart=/usr/local/bin/vaydns-server -udp :{port} -privkey-file /etc/vaydns/server.key -mtu 1232 -record-type {record_type} {dnstt_flag} -idle-timeout 10s -keepalive 2s -domain {tunnel_domain} -upstream 127.0.0.1:8000
Restart=always
RestartSec=5
KillMode=mixed
TimeoutStopSec=5

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
WantedBy=multi-user.target"""

            write_cmd = f"cat > /etc/systemd/system/vaydns-server.service << 'EOF'\n{vaydns_service}\nEOF"
            self.run_cmd(ssh, write_cmd, server['password'], server['username'])

            self.run_cmd(ssh, "systemctl daemon-reload", server['password'], server['username'])
            self.run_cmd(ssh, "systemctl start vaydns-server", server['password'], server['username'])
            self.run_cmd(ssh, "systemctl enable vaydns-server", server['password'], server['username'])

            print("Obteniendo clave pública...")
            _, pubkey, _ = self.run_cmd(ssh, "cat /etc/vaydns/server.pub", server['password'], server['username'],
                                        hide_output=True)
            pubkey = pubkey.strip()

            if pubkey:
                self.db.update_server_pubkey(server_id, pubkey)

            urls = self.generate_client_urls(tunnel_domain, pubkey)

            ssh.close()

            return {
                'success': True,
                'message': 'VayDNS instalado correctamente',
                'pubkey': pubkey,
                'urls': urls
            }

        except Exception as e:
            ssh.close()
            return {'success': False, 'error': str(e)}

    def generate_client_urls(self, domain: str, pubkey: str) -> List[str]:
        """Genera URL con configuración DNSTT (compatible con Cuba)"""
        if not pubkey:
            return []

        default = config.DEFAULT_SERVER
        tunnel = default.get('tunnel_domain', domain)
        record_type = default.get('record_type', 'txt')
        clientid_size = default.get('clientid_size', 8)
        dnstt_compat = 'true' if default.get('dnstt_compat', True) else 'false'

        url = f"dnst://{tunnel}/vaydns/socks5?pubkey={pubkey}&record-type={record_type}&clientid-size={clientid_size}&keepalive=2s&idle-timeout=10s&dnstt-compat={dnstt_compat}#vaydns"
        return [url]

    def get_server_status(self, server_id: int) -> Dict[str, any]:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            _, status, _ = self.run_cmd(ssh, "systemctl is-active vaydns-server", server['password'], server['username'],
                                        hide_output=True)
            _, ports, _ = self.run_cmd(ssh, "ss -tlnp | grep -E ':53|:5300|:8000'", server['password'],
                                       server['username'], hide_output=True)
            _, pubkey, _ = self.run_cmd(ssh, "cat /etc/vaydns/server.pub", server['password'], server['username'],
                                        hide_output=True)

            ssh.close()

            return {
                'success': True,
                'status': status.strip() if status else 'unknown',
                'ports': ports if ports else 'No hay puertos activos',
                'pubkey': pubkey.strip() if pubkey else 'No disponible'
            }
        except Exception as e:
            ssh.close()
            return {'success': False, 'error': str(e)}

    def uninstall_vaydns(self, server_id: int) -> Dict[str, any]:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            self.run_cmd(ssh, "systemctl stop vaydns-server", server['password'], server['username'])
            self.run_cmd(ssh, "systemctl disable vaydns-server", server['password'], server['username'])
            self.run_cmd(ssh, "rm -f /etc/systemd/system/vaydns-server.service", server['password'], server['username'])
            self.run_cmd(ssh, "systemctl daemon-reload", server['password'], server['username'])
            self.run_cmd(ssh, "rm -rf /etc/vaydns", server['password'], server['username'])
            self.run_cmd(ssh, "rm -f /usr/local/bin/vaydns-server", server['password'], server['username'])

            ssh.close()
            self.db.delete_server(server_id)

            return {
                'success': True,
                'message': 'VayDNS desinstalado correctamente'
            }
        except Exception as e:
            ssh.close()
            return {'success': False, 'error': str(e)}

    def is_port_in_use(self, server_id: int, port: int) -> bool:
        """Verifica si un puerto está en uso en el servidor"""
        server = self.db.get_server(server_id)
        if not server:
            return False

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return False

        try:
            _, output, _ = self.run_cmd(ssh, f"ss -ulnp | grep ':{port} '",
                                        server['password'], server['username'], hide_output=True)
            ssh.close()
            return bool(output.strip())
        except:
            ssh.close()
            return False

    def is_vaydns_installed(self, server_id: int) -> bool:
        """Verifica si VayDNS está instalado"""
        server = self.db.get_server(server_id)
        if not server:
            return False

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return False

        try:
            _, output, _ = self.run_cmd(ssh, "systemctl is-active vaydns-server",
                                        server['password'], server['username'], hide_output=True)
            ssh.close()
            return output.strip() == "active"
        except:
            ssh.close()
            return False