import config
import paramiko
import re
import random
import string
from typing import Dict, Optional, Tuple, List


class SlipstreamManager:
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

    def is_slipgate_installed(self, server_id: int) -> bool:
        """Verifica si SlipGate está instalado"""
        server = self.db.get_server(server_id)
        if not server:
            return False

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return False

        try:
            _, output, _ = self.run_cmd(ssh, "which slipgate",
                                        server['password'], server['username'], hide_output=True)
            ssh.close()
            return bool(output.strip())
        except:
            ssh.close()
            return False

    def is_slipstream_installed(self, server_id: int) -> bool:
        """Verifica si SlipGate tiene túneles activos"""
        server = self.db.get_server(server_id)
        if not server:
            return False

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return False

        try:
            _, output, _ = self.run_cmd(ssh, "systemctl is-active slipgate-dnsrouter",
                                        server['password'], server['username'], hide_output=True)
            ssh.close()
            return output.strip() == "active"
        except:
            ssh.close()
            return False

    def install_slipstream(self, server_id: int) -> Dict:
        """Instala SlipGate automáticamente en el VPS"""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            print("Instalando dependencias...")
            # Detectar OS
            _, os_info, _ = self.run_cmd(ssh, "cat /etc/os-release",
                                         server['password'], server['username'], hide_output=True)
            is_ubuntu = "ubuntu" in os_info.lower() or "debian" in os_info.lower()

            if is_ubuntu:
                self.run_cmd(ssh, "export DEBIAN_FRONTEND=noninteractive && apt-get update -y",
                             server['password'], server['username'])
                self.run_cmd(ssh, "export DEBIAN_FRONTEND=noninteractive && apt-get install -y curl wget tar expect",
                             server['password'], server['username'])
            else:
                self.run_cmd(ssh, "dnf install -y curl wget tar expect",
                             server['password'], server['username'])

            print("Instalando SlipGate...")
            install_cmd = "bash <(curl -Ls https://raw.githubusercontent.com/anonvector/slipgate/main/install.sh)"
            exit_code, out, err = self.run_cmd(ssh, install_cmd, server['password'], server['username'])

            ssh.close()

            # Verificar si quedó instalado
            ssh2 = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
            if ssh2:
                _, check, _ = self.run_cmd(ssh2, "which slipgate",
                                           server['password'], server['username'], hide_output=True)
                ssh2.close()
                if check.strip():
                    return {'success': True, 'message': 'SlipGate instalado correctamente'}

            return {
                'success': False,
                'error': f'No se pudo verificar la instalación.\nOutput:\n{out[-500:]}\nError:\n{err[-500:]}'
            }

        except Exception as e:
            try:
                ssh.close()
            except:
                pass
            return {'success': False, 'error': str(e)}

    def uninstall_slipstream(self, server_id: int) -> Dict:
        """Desinstala SlipGate del VPS"""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            print("Parando servicios de SlipGate...")
            self.run_cmd(ssh, "systemctl stop slipgate-dnsrouter 2>/dev/null || true",
                         server['password'], server['username'])
            self.run_cmd(ssh, "systemctl disable slipgate-dnsrouter 2>/dev/null || true",
                         server['password'], server['username'])

            # Matar procesos sueltos
            self.run_cmd(ssh, "pkill -f slipstream-serv 2>/dev/null || true",
                         server['password'], server['username'])
            self.run_cmd(ssh, "pkill -f slipgate 2>/dev/null || true",
                         server['password'], server['username'])

            print("Eliminando archivos...")
            self.run_cmd(ssh, "rm -f /etc/systemd/system/slipgate-dnsrouter.service",
                         server['password'], server['username'])
            self.run_cmd(ssh, "rm -f /usr/local/bin/slipgate",
                         server['password'], server['username'])
            self.run_cmd(ssh, "rm -rf /etc/slipgate",
                         server['password'], server['username'])
            self.run_cmd(ssh, "rm -rf /var/lib/slipgate",
                         server['password'], server['username'])
            self.run_cmd(ssh, "systemctl daemon-reload",
                         server['password'], server['username'])

            ssh.close()

            return {
                'success': True,
                'message': 'Slipstream desinstalado correctamente'
            }

        except Exception as e:
            try:
                ssh.close()
            except:
                pass
            return {'success': False, 'error': str(e)}

    def list_slipgate_tunnels(self, server_id: int) -> List[Dict]:
        """Lista los túneles de SlipGate"""
        server = self.db.get_server(server_id)
        if not server:
            return []

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return []

        try:
            _, output, _ = self.run_cmd(ssh, "slipgate tunnel status",
                                        server['password'], server['username'], hide_output=True)
            ssh.close()

            tunnels = []
            for line in output.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    tunnels.append({
                        'name': parts[0],
                        'type': parts[1],
                        'backend': parts[2],
                        'domain': parts[3],
                        'status': parts[4] if len(parts) > 4 else 'unknown'
                    })
            return tunnels
        except:
            try:
                ssh.close()
            except:
                pass
            return []

    def create_user(self, server_id: int, username: str, password: str) -> Dict:
        """Crea un usuario en SlipGate usando expect"""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            # Verificar si el usuario ya existe
            _, check, _ = self.run_cmd(
                ssh,
                f"id -u {username} 2>/dev/null && echo EXISTS",
                server['password'], server['username'], hide_output=True
            )
            if "EXISTS" in check:
                ssh.close()
                return {'success': False, 'error': f'El usuario {username} ya existe'}

            # Comando expect para SlipGate
            expect_cmd = (
                f"expect -c '"
                f"spawn sudo slipgate users --action add --username {username}; "
                f"expect \"Password\"; "
                f"send \"{password}\\r\"; "
                f"expect eof"
                f"'"
            )

            _, output, err = self.run_cmd(ssh, expect_cmd,
                                          server['password'], server['username'], hide_output=True)
            ssh.close()

            # Extraer TODOS los enlaces slipnet://
            links = re.findall(r'slipnet://[A-Za-z0-9+/=]+', output)

            if not links:
                return {
                    'success': False,
                    'error': f'No se generó el enlace.\n\nOutput:\n{output}\n\nError:\n{err}'
                }

            # El segundo enlace (índice 1) es el de slipstream-2 (backend SSH)
            ssh_link = links[1] if len(links) >= 2 else links[0]

            return {
                'success': True,
                'username': username,
                'password': password,
                'url': ssh_link,
                'all_links': links
            }

        except Exception as e:
            try:
                ssh.close()
            except:
                pass
            return {'success': False, 'error': str(e)}

    def delete_user(self, server_id: int, username: str) -> Dict:
        """Elimina un usuario de SlipGate"""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            expect_cmd = (
                f"expect -c '"
                f"spawn sudo slipgate users --action remove --username {username}; "
                f"expect {{"
                f"  \"Are you sure\" {{ send \"y\\r\" ; exp_continue }} "
                f"  \"confirm\" {{ send \"y\\r\" ; exp_continue }} "
                f"  \"yes/no\" {{ send \"y\\r\" ; exp_continue }} "
                f"  eof"
                f"}}"
                f"'"
            )
            self.run_cmd(ssh, expect_cmd, server['password'], server['username'], hide_output=True)

            self.run_cmd(
                ssh,
                f"sed -i '/^{username} /d' /etc/security/limits.d/slipgate-users.conf 2>/dev/null || true",
                server['password'], server['username'], hide_output=True
            )

            ssh.close()

            return {
                'success': True,
                'message': f'Usuario {username} eliminado'
            }
        except Exception as e:
            try:
                ssh.close()
            except:
                pass
            return {'success': False, 'error': str(e)}

    def list_users(self, server_id: int) -> List[str]:
        """Lista los usuarios de SlipGate"""
        server = self.db.get_server(server_id)
        if not server:
            return []

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return []

        try:
            _, output, _ = self.run_cmd(ssh, "slipgate users --action list",
                                        server['password'], server['username'], hide_output=True)
            ssh.close()

            users = []
            for line in output.splitlines():
                line = line.strip()
                if line and not line.startswith('[') and not line.startswith('Show') and not line.startswith('Choice'):
                    users.append(line)
            return users
        except:
            try:
                ssh.close()
            except:
                pass
            return []

    def set_user_limit(self, server_id: int, username: str, max_conns: int) -> Dict:
        """Añade límite de conexiones simultáneas con pam_limits"""
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            self.run_cmd(
                ssh,
                f"sed -i '/^{username} /d' /etc/security/limits.d/slipgate-users.conf 2>/dev/null || true",
                server['password'], server['username'], hide_output=True
            )

            cmd = (
                f"echo '{username} hard maxlogins {max_conns}' "
                f">> /etc/security/limits.d/slipgate-users.conf"
            )
            exit_code, out, err = self.run_cmd(ssh, cmd,
                                               server['password'], server['username'], hide_output=True)
            ssh.close()

            if exit_code != 0:
                return {'success': False, 'error': f'Error: {err}'}

            return {'success': True, 'message': f'Límite de {max_conns} conexiones aplicado'}

        except Exception as e:
            try:
                ssh.close()
            except:
                pass
            return {'success': False, 'error': str(e)}