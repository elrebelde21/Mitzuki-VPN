import os
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
        """Instala VayDNS subiendo el binario local lib/vaydns-server (como deploy_vaydns_local.py).

        Núcleo: dependencias, binario, claves, Dante SOCKS5, servicio systemd y verificación.
        NO toca firewall ni el puerto SSH.
        """
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        # Binario local en la misma carpeta que este módulo (lib/vaydns-server)
        local_binary = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vaydns-server')
        if not os.path.exists(local_binary):
            return {'success': False, 'error': f'No se encontró el binario local: {local_binary}'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            os_info = self.detect_os(ssh, server['password'], server['username'])
            default = config.DEFAULT_SERVER
            port = default.get('port', 53)
            user = server['username']
            pwd = server['password']

            # Parámetros del servicio (deben coincidir con la URL del cliente)
            record_type = default.get('record_type', 'txt')
            dnstt_compat = default.get('dnstt_compat', True)
            dnstt_flag = '-dnstt-compat ' if dnstt_compat else ''
            idle_timeout = '10s'
            keepalive = '2s'
            mtu = '1232'

            # ---- 0. Puerto libre ----
            _, out, _ = self.run_cmd(
                ssh,
                f"ss -ulnp 2>/dev/null | grep -E ':{port}([[:space:]]|$)' || true",
                pwd, user, hide_output=True
            )
            if out.strip():
                ssh.close()
                return {'success': False, 'error': f'Puerto {port}/udp ya está en uso:\n{out}'}

            # ---- 1. Dependencias (sin Go ni git: ya no compilamos) ----
            print("Actualizando sistema e instalando dependencias...")
            if os_info['is_ubuntu']:
                self.run_cmd(ssh, "export DEBIAN_FRONTEND=noninteractive && apt-get update -y", pwd, user)
                self.run_cmd(ssh, "export DEBIAN_FRONTEND=noninteractive && apt-get install -y "
                                  "dante-server curl vnstat net-tools bind9-dnsutils ca-certificates",
                             pwd, user)
            else:
                self.run_cmd(ssh, "dnf install -y epel-release", pwd, user)
                self.run_cmd(ssh, "dnf install -y dante-server curl net-tools bind-utils vnstat "
                                  "ca-certificates policycoreutils-python-utils",
                             pwd, user)

            # ---- 2. Subir binario local por SFTP ----
            print("Subiendo binario vaydns-server...")
            # Paramos un servicio previo para evitar "text file busy" al mover el binario
            self.run_cmd(ssh, "systemctl stop vaydns-server 2>/dev/null || true", pwd, user)
            try:
                sftp = ssh.open_sftp()
                sftp.put(local_binary, "/tmp/vaydns-server")
                sftp.close()
            except Exception as e:
                ssh.close()
                return {'success': False, 'error': f'No se pudo subir el binario: {e}'}

            self.run_cmd(ssh,
                         "chmod +x /tmp/vaydns-server && "
                         "mv /tmp/vaydns-server /usr/local/bin/vaydns-server && "
                         "chmod 755 /usr/local/bin/vaydns-server",
                         pwd, user)

            _, ftype, _ = self.run_cmd(ssh, "file /usr/local/bin/vaydns-server 2>/dev/null || true", pwd, user, hide_output=True)
            if 'ELF' not in ftype:
                ssh.close()
                return {'success': False, 'error': f'El binario subido no es válido (ELF):\n{ftype}'}

            # SELinux (RHEL/Rocky/Alma): marcar el binario como ejecutable
            if not os_info['is_ubuntu']:
                self.run_cmd(ssh, 'semanage fcontext -a -t bin_t "/usr/local/bin/vaydns-server" 2>/dev/null || true', pwd, user)
                self.run_cmd(ssh, "restorecon -v /usr/local/bin/vaydns-server 2>/dev/null || true", pwd, user)

            # ---- 3. Usuario vaydns ----
            print("Creando usuario vaydns...")
            self.run_cmd(ssh,
                         "id -u vaydns &>/dev/null || "
                         "useradd -r -M -s /bin/false -c 'vaydns service user' -d /nonexistent vaydns",
                         pwd, user)

            # ---- 4. Claves ----
            print("Generando claves...")
            self.run_cmd(ssh, "rm -rf /etc/vaydns && mkdir -p /etc/vaydns", pwd, user)
            exit_code, out, err = self.run_cmd(
                ssh,
                "/usr/local/bin/vaydns-server -gen-key "
                "-privkey-file /etc/vaydns/server.key "
                "-pubkey-file /etc/vaydns/server.pub",
                pwd, user
            )
            if exit_code != 0:
                ssh.close()
                return {'success': False, 'error': f'-gen-key falló: {err}\n{out}'}

            _, pubkey, err = self.run_cmd(ssh, "cat /etc/vaydns/server.pub", pwd, user, hide_output=True)
            pubkey = pubkey.strip()
            if not pubkey:
                ssh.close()
                return {'success': False, 'error': f'server.pub vacío: {err}'}

            self.run_cmd(ssh, "chown -R vaydns:vaydns /etc/vaydns", pwd, user)

            # ---- 5. SOCKS5 dante ----
            print("Configurando SOCKS5...")
            _, primary_interface, _ = self.run_cmd(
                ssh, "ip route | awk '/default/ {print $5}' | head -n1", pwd, user, hide_output=True
            )
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
            self.run_cmd(ssh, f"mv {config_path} {config_path}.1 || true", pwd, user)
            self.run_cmd(ssh, f"cat > {config_path} << 'EOF'\n{sockd_content}\nEOF", pwd, user)
            self.run_cmd(ssh, "systemctl daemon-reload", pwd, user)
            self.run_cmd(ssh, f"systemctl restart {os_info['dante_service']}", pwd, user)
            self.run_cmd(ssh, f"systemctl enable {os_info['dante_service']}", pwd, user)

            # ---- 6. DNS sistema ----
            self.run_cmd(ssh, "rm -f /etc/resolv.conf", pwd, user)
            self.run_cmd(ssh, "echo 'nameserver 1.1.1.1' > /etc/resolv.conf", pwd, user)
            self.run_cmd(ssh, "echo 'nameserver 8.8.8.8' >> /etc/resolv.conf", pwd, user)

            # ---- 7. Servicio systemd (sintaxis VayDNS: -domain / -upstream) ----
            print("Creando servicio systemd...")
            tunnel_domain = default.get('tunnel_domain',
                                        f"d.{'.'.join(server['domain'].split('.')[1:])}")
            upstream = "127.0.0.1:8000"

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
ExecStart=/usr/local/bin/vaydns-server -udp :{port} -privkey-file /etc/vaydns/server.key -mtu {mtu} -record-type {record_type} {dnstt_flag}-idle-timeout {idle_timeout} -keepalive {keepalive} -domain {tunnel_domain} -upstream {upstream}
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

            self.run_cmd(ssh, "rm -rf /etc/systemd/system/vaydns-server.service.d", pwd, user)
            self.run_cmd(ssh, f"cat > /etc/systemd/system/vaydns-server.service << 'EOF'\n{vaydns_service}\nEOF", pwd, user)

            self.run_cmd(ssh, "systemctl daemon-reload", pwd, user)
            self.run_cmd(ssh, "systemctl enable vaydns-server", pwd, user)
            self.run_cmd(ssh, "systemctl restart vaydns-server", pwd, user)

            # ---- 8. Verificar ----
            _, status, _ = self.run_cmd(ssh, "systemctl is-active vaydns-server", pwd, user, hide_output=True)
            if status.strip() != 'active':
                _, logs, _ = self.run_cmd(ssh, "journalctl -u vaydns-server -n 20 --no-pager", pwd, user, hide_output=True)
                ssh.close()
                return {'success': False, 'error': f'Servicio no arrancó:\n{logs}'}

            _, ss_out, _ = self.run_cmd(
                ssh,
                f"ss -ulnp 2>/dev/null | grep -E ':{port}([[:space:]]|$)' || true",
                pwd, user, hide_output=True
            )
            if not ss_out.strip():
                print(f"[WARN] Servicio activo pero ss no muestra :{port}/udp. Salida: {ss_out!r}")

            # ---- 9. Guardar pubkey + URLs ----
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
            try:
                ssh.close()
            except:
                pass
            return {'success': False, 'error': str(e)}

    def generate_client_urls(self, domain: str, pubkey: str) -> List[str]:
        """Genera URL completa compatible con Phoenix VPN / VayDNS."""
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
            _, ports, _ = self.run_cmd(ssh, "ss -tulnp | grep -E ':53|:5300|:8000'", server['password'],
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
            self.run_cmd(ssh, "rm -rf /etc/systemd/system/vaydns-server.service.d", server['password'], server['username'])
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
            _, output, _ = self.run_cmd(
                ssh,
                f"ss -ulnp 2>/dev/null | grep -E ':{port}([[:space:]]|$)' || true",
                server['password'], server['username'], hide_output=True
            )
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
