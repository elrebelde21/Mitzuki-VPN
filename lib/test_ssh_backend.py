"""
diag.py  —  Diagnóstico del servidor VayDNS (sin argumentos)
============================================================

Poné este archivo en lib/ (al lado de ssh_accounts_manager.py).
En Pterodactyl: Startup -> `python3 lib/diag.py` -> Start -> screenshot.
Después volvé el startup al bot.

Imprime la config REAL del servidor para dejar de adivinar:
qué record-type y dnstt-compat corre vaydns, a dónde manda el upstream,
si el sshd dedicado escucha, y si llegan queries del cliente.
"""

import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
for p in (_here, os.path.dirname(_here)):
    if p not in sys.path:
        sys.path.insert(0, p)

import config
from database import Database

try:
    from lib.ssh_accounts_manager import SSHAccountsManager
except ImportError:
    from ssh_accounts_manager import SSHAccountsManager

db = Database(config.DB_PATH)
mgr = SSHAccountsManager(db)


def main():
    servers = db.get_all_servers()
    if not servers:
        print("[!] No hay servidor en la DB")
        return
    server = servers[0]

    ssh = mgr._connect(server)
    if not ssh:
        print("[!] No se pudo conectar al servidor")
        return
    pwd, user = server['password'], server['username']

    def run(c):
        _, o, _ = mgr.run_cmd(ssh, c, pwd, user, hide_output=True)
        return o.strip()

    print("\n===== DIAGNOSTICO DEL SERVIDOR =====\n")

    print("[ExecStart vaydns-server] (el cliente debe coincidir con esto):")
    print(run("grep ExecStart /etc/systemd/system/vaydns-server.service || echo 'NO EXISTE el service'"))

    print("\nvaydns-server activo:", run("systemctl is-active vaydns-server 2>/dev/null || echo inactive"))
    print("vaydns-sshd  activo:", run("systemctl is-active vaydns-sshd 2>/dev/null || echo inactive"))
    print("limitador    activo:", run("systemctl is-active vaydns-limiter 2>/dev/null || echo inactive"))

    print("\nEscucha UDP :53   ->", run("ss -ulnp 2>/dev/null | grep ':53' || echo NO"))
    print("Escucha TCP :2222 ->", run("ss -tlnp 2>/dev/null | grep '127.0.0.1:2222' || echo NO"))

    print("\n[Log vaydns-server] (ultimas lineas; que llegan queries?):")
    print(run("journalctl -u vaydns-server -n 20 --no-pager 2>/dev/null || echo 'sin logs'"))

    print("\n[Log sshd dedicado] (ultimas lineas; intentos de login?):")
    print(run("journalctl -u vaydns-sshd -n 15 --no-pager 2>/dev/null || echo 'sin logs'"))

    print("\n===== FIN =====")
    ssh.close()


if __name__ == "__main__":
    main()