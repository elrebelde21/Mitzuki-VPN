import config
import paramiko
import os
from typing import Dict, Optional, Tuple


class SoarManager:
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

    def install_soar(self, server_id: int) -> Dict[str, any]:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        local_binary_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'soar-server')
        if not os.path.exists(local_binary_path):
            return {'success': False, 'error': f'No se encontró el binario en: {local_binary_path}'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            user = server['username']
            pwd = server['password']
            domain = server['domain']

            print("Deteniendo VayDNS...")
            self.run_cmd(ssh, "systemctl stop vaydns-server || true", pwd, user)
            self.run_cmd(ssh, "systemctl disable vaydns-server || true", pwd, user)
            
            # Limpiamos cualquier regla de iptables vieja que haya roto el internet
            self.run_cmd(ssh, "iptables -t nat -F", pwd, user)
            self.run_cmd(ssh, "netfilter-persistent save || true", pwd, user)

            print("Subiendo binario por SFTP...")
            sftp = ssh.open_sftp()
            sftp.put(local_binary_path, "/tmp/soar-server")
            sftp.close()

            print("Creando script de instalación y servicio...")
            
            # Script SIN IPTABLES
            setup_script = f"""#!/bin/bash
id -u vaydns &>/dev/null || useradd -r -M -s /bin/false -c "vaydns service user" -d /nonexistent vaydns

mkdir -p /etc/soar
cp /tmp/soar-server /usr/local/bin/
chmod +x /usr/local/bin/soar-server

/usr/local/bin/soar-server keygen | awk '
  $1 == "private" {{ print $2 > "/etc/soar/server.key" }}
  $1 == "public"  {{ print $2 > "/etc/soar/server.pub" }}
'
chown vaydns:vaydns /etc/soar/*

cat > /etc/systemd/system/soar-server.service << 'EOF'
[Unit]
Description=Soar Tunnel Server
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/soar-server -udp :53 -privkey-file /etc/soar/server.key -domain {domain} -upstream 127.0.0.1:8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable soar-server.service
systemctl start soar-server.service
"""
            self.run_cmd(ssh, f"cat > /tmp/soar_setup.sh << 'EOF'\n{setup_script}\nEOF", pwd, user)

            print("Ejecutando el instalador de Soar...")
            exit_code, out, err = self.run_cmd(ssh, "chmod +x /tmp/soar_setup.sh && bash /tmp/soar_setup.sh", pwd, user)
            
            if exit_code != 0:
                ssh.close()
                return {'success': False, 'error': f'Error en setup de Soar:\n{err}\n{out}'}

            print("Obteniendo llave pública...")
            _, pubkey, _ = self.run_cmd(ssh, "cat /etc/soar/server.pub", pwd, user, hide_output=True)
            pubkey = pubkey.strip()

            ssh.close()

            if not pubkey:
                return {'success': False, 'error': 'No se pudo generar la llave pública de Soar'}

            # ⚠️ ESTA LÍNEA ES LA QUE FALTABA PARA GUARDAR LA LLAVE EN EL BOT
            self.db.update_server_pubkey(server_id, pubkey)

            return {
                'success': True,
                'message': 'Soar instalado correctamente. VayDNS fue detenido.',
                'pubkey': pubkey,
                'domain': domain
            }

        except Exception as e:
            try:
                ssh.close()
            except:
                pass
            return {'success': False, 'error': str(e)}

    def uninstall_soar(self, server_id: int) -> Dict[str, any]:
        server = self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Servidor no encontrado'}

        ssh = self.connect_ssh(server['ip'], server['ssh_port'], server['username'], server['password'])
        if not ssh:
            return {'success': False, 'error': 'No se pudo conectar al servidor'}

        try:
            user = server['username']
            pwd = server['password']

            print("Deteniendo y eliminando Soar...")
            self.run_cmd(ssh, "systemctl stop soar-server || true", pwd, user)
            self.run_cmd(ssh, "systemctl disable soar-server || true", pwd, user)
            self.run_cmd(ssh, "rm -f /etc/systemd/system/soar-server.service", pwd, user)
            self.run_cmd(ssh, "systemctl daemon-reload", pwd, user)
            self.run_cmd(ssh, "rm -rf /etc/soar /usr/local/bin/soar-server", pwd, user)

            # Quitamos reglas de iptables que hayan quedado
            self.run_cmd(ssh, "iptables -t nat -D PREROUTING -p udp --dport 53 -j REDIRECT --to-ports 5300 || true", pwd, user)
            self.run_cmd(ssh, "netfilter-persistent save || true", pwd, user)

            ssh.close()
            return {'success': True, 'message': 'Soar desinstalado correctamente.'}

        except Exception as e:
            try:
                ssh.close()
            except:
                pass
            return {'success': False, 'error': str(e)}