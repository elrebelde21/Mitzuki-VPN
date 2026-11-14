import paramiko
import config
from typing import Dict, Optional, Tuple


class MasterDnsVPNManager:
    def __init__(self, db):
        self.db = db

    def connect_ssh(self, ip: str, port: int, username: str, password: str) -> Optional[paramiko.SSHClient]:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=ip, port=port, username=username, password=password,
                timeout=30, allow_agent=False, look_for_keys=False
            )
            return ssh
        except Exception as e:
            print(f"Error SSH: {e}")
            return None

    def run_cmd(self, ssh, cmd, password, user='root', hide_output=False) -> Tuple[int, str, str]:
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

    def install_masterdnsvpn(self, server_id: int, domain: str = None) -> Dict:
        """Instala MasterDnsVPN desde el script oficial"""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            # 1. Detectar y detener conflictos con puerto 53
            print("Deteniendo servicios que usan puerto 53...")
            for svc in ('vaydns-server', 'vaydns', 'slowdns', 'danted', 'systemd-resolved', 'named', 'bind9'):
                self.run_cmd(ssh, f"systemctl stop {svc} 2>/dev/null || true",
                             server['password'], server['username'])
                self.run_cmd(ssh, f"systemctl disable {svc} 2>/dev/null || true",
                             server['password'], server['username'])

            # 2. Quitar reglas de redirect 53→5300
            self.run_cmd(ssh,
                "while iptables -t nat -S PREROUTING 2>/dev/null | grep -q -- '--dport 53.*REDIRECT'; do "
                "iptables -t nat -D PREROUTING -p udp --dport 53 -j REDIRECT --to-ports 5300 2>/dev/null || break; "
                "done",
                server['password'], server['username'])

            # 3. Crear directorio de instalación
            install_dir = "/opt/masterdnsvpn"
            self.run_cmd(ssh, f"mkdir -p {install_dir}", server['password'], server['username'])

            # 4. Descargar el script de instalación
            print("Descargando instalador de MasterDnsVPN...")
            script_url = "https://raw.githubusercontent.com/masterking32/MasterDnsVPN/main/server_linux_install.sh"
            self.run_cmd(ssh,
                f"cd {install_dir} && curl -sL {script_url} -o install.sh && chmod +x install.sh",
                server['password'], server['username'])

            # 5. Ejecutar el instalador (con dominio si se proporciona)
            print("Ejecutando instalador...")
            if domain:
                # El instalador pregunta interactivamente por el dominio
                # Le pasamos el dominio via stdin
                install_cmd = f"cd {install_dir} && echo '{domain}' | bash install.sh"
            else:
                install_cmd = f"cd {install_dir} && bash install.sh"

            exit_code, out, err = self.run_cmd(ssh, install_cmd,
                                               server['password'], server['username'])

            # 6. Verificar que el servicio arrancó
            import time
            time.sleep(3)
            _, status, _ = self.run_cmd(ssh, "systemctl is-active masterdnsvpn",
                                        server['password'], server['username'], hide_output=True)

            if status.strip() != 'active':
                _, logs, _ = self.run_cmd(ssh, "journalctl -u masterdnsvpn -n 30 --no-pager",
                                          server['password'], server['username'], hide_output=True)
                ssh.close()
                return {
                    'success': False,
                    'error': f'Servicio no arrancó ({status}). Logs:\n{logs[-800:]}'
                }

            # 7. Leer la clave de encriptación generada
            _, key, _ = self.run_cmd(ssh, f"cat {install_dir}/encrypt_key.txt 2>/dev/null",
                                     server['password'], server['username'], hide_output=True)

            # 8. Guardar en DB
            self.db.set_config('masterdns_domain', domain or '')
            self.db.set_config('masterdns_key', key.strip())

            ssh.close()
            return {
                'success': True,
                'message': 'MasterDnsVPN instalado correctamente',
                'domain': domain,
                'key': key.strip(),
            }

        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}

    def is_masterdns_installed(self, server_id: int) -> bool:
        """Verifica si MasterDnsVPN está instalado y activo"""
        server = self.db.get_server(server_id)
        if not server:
            return False
        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return False
        try:
            _, output, _ = self.run_cmd(ssh, "systemctl is-active masterdnsvpn",
                                        server['password'], server['username'], hide_output=True)
            ssh.close()
            return output.strip() in ('active', 'activating')
        except Exception:
            try:
                ssh.close()
            except Exception:
                pass
            return False

    def uninstall_masterdnsvpn(self, server_id: int) -> Dict:
        """Desinstala MasterDnsVPN del servidor"""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            script_url = "https://raw.githubusercontent.com/masterking32/MasterDnsVPN/main/server_linux_install.sh"
            self.run_cmd(ssh,
                f"cd /opt/masterdnsvpn 2>/dev/null && curl -sL {script_url} -o install.sh && bash install.sh --uninstall",
                server['password'], server['username'])

            self.db.set_config('masterdns_domain', '')
            self.db.set_config('masterdns_key', '')

            ssh.close()
            return {'success': True, 'message': 'MasterDnsVPN desinstalado correctamente'}
        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}

    def get_masterdns_status(self, server_id: int) -> Dict:
        """Obtiene estado de MasterDnsVPN (activo, puertos, key)"""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}
        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}
        try:
            _, status, _ = self.run_cmd(ssh, "systemctl is-active masterdnsvpn",
                                        server['password'], server['username'], hide_output=True)
            _, ports, _ = self.run_cmd(ssh, "ss -ulnp | grep ':53 '",
                                       server['password'], server['username'], hide_output=True)
            _, key, _ = self.run_cmd(ssh, "cat /opt/masterdnsvpn/encrypt_key.txt 2>/dev/null",
                                     server['password'], server['username'], hide_output=True)
            ssh.close()
            return {
                'success': True,
                'status': status.strip(),
                'ports': ports or 'N/A',
                'key': key.strip() or 'N/A',
                'domain': self.db.get_config('masterdns_domain') or 'N/A',
            }
        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            return {'success': False, 'error': str(e)}