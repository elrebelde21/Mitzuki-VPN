import paramiko
import config
from telegram import Update
from telegram.ext import ContextTypes
from database import Database
from lib.helpers import is_admin, escape_html

db = Database(config.DB_PATH)


def _get_ssh():
    """Conecta al servidor y devuelve el cliente SSH"""
    servers = db.get_all_servers()
    if not servers:
        return None, None
    server = servers[0]
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=server['ip'],
            port=server['ssh_port'],
            username=server['username'],
            password=server['password'],
            timeout=15,
            allow_agent=False,
            look_for_keys=False
        )
        return ssh, server
    except Exception as e:
        print(f"SSH error: {e}")
        return None, None


def _run(ssh, cmd):
    _, stdout, _ = ssh.exec_command(cmd)
    return stdout.read().decode('utf-8', errors='ignore').strip()


def _human_bytes(n):
    """Convierte bytes a formato legible"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def _human_speed(bps):
    """Convierte bytes/s a formato legible"""
    try:
        bps = float(bps)
    except (TypeError, ValueError):
        return str(bps)
    units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
    for unit in units:
        if abs(bps) < 1024:
            return f"{bps:.2f} {unit}"
        bps /= 1024
    return f"{bps:.2f} TB/s"


def _parse_traffic(ssh):
    """Lee /proc/net/dev y devuelve dict {iface: (rx_bytes, tx_bytes)}"""
    out = _run(ssh, "cat /proc/net/dev | tail -n +3")
    result = {}
    for line in out.splitlines():
        if ':' not in line:
            continue
        iface, data = line.split(':', 1)
        iface = iface.strip()
        if iface == 'lo':
            continue
        parts = data.split()
        if len(parts) >= 9:
            try:
                rx = int(parts[0])
                tx = int(parts[8])
                result[iface] = (rx, tx)
            except ValueError:
                continue
    return result


async def system_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra CPU, RAM, disco, red y tráfico del servidor"""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("⛔ Solo admin.")
        return

    msg = await update.message.reply_text("🔍 <b>Consultando sistema...</b>", parse_mode='HTML')

    ssh, server = _get_ssh()
    if not ssh:
        await msg.edit_text("❌ <b>No se pudo conectar al servidor SSH</b>", parse_mode='HTML')
        return

    try:
        # ─── CPU ───
        cpu_cores = _run(ssh, "nproc")
        cpu_model = _run(ssh, "grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | sed 's/^ *//'") or "N/A"
        load = _run(ssh, "cat /proc/loadavg | awk '{print $1, $2, $3}'")
        cpu_usage = _run(ssh, "top -bn1 | grep '%Cpu' | head -1 | awk '{print $2}'")

        # ─── RAM ───
        mem = _run(ssh, "free -b | grep Mem | awk '{print $2, $3, $4, $7}'")
        try:
            mem_total, mem_used, mem_free, mem_avail = mem.split()
            mem_total_h = _human_bytes(mem_total)
            mem_used_h = _human_bytes(mem_used)
            mem_free_h = _human_bytes(mem_free)
            mem_avail_h = _human_bytes(mem_avail)
            mem_pct = (int(mem_used) / int(mem_total) * 100) if int(mem_total) > 0 else 0
        except Exception:
            mem_total_h = mem_used_h = mem_free_h = mem_avail_h = "N/A"
            mem_pct = 0

        # ─── Swap ───
        swap = _run(ssh, "free -b | grep Swap | awk '{print $2, $3}'")
        try:
            swap_total, swap_used = swap.split()
            swap_total_h = _human_bytes(swap_total)
            swap_used_h = _human_bytes(swap_used)
            swap_pct = (int(swap_used) / int(swap_total) * 100) if int(swap_total) > 0 else 0
        except Exception:
            swap_total_h = swap_used_h = "N/A"
            swap_pct = 0

        # ─── Disco ───
        disk = _run(ssh, "df -B1 / | tail -1 | awk '{print $2, $3, $4, $5}'")
        try:
            disk_total, disk_used, disk_free, disk_pct = disk.split()
            disk_total_h = _human_bytes(disk_total)
            disk_used_h = _human_bytes(disk_used)
            disk_free_h = _human_bytes(disk_free)
        except Exception:
            disk_total_h = disk_used_h = disk_free_h = "N/A"
            disk_pct = "N/A"

        # ─── Uptime / OS / Kernel ───
        uptime = _run(ssh, "uptime -p") or _run(ssh, "uptime")
        os_name = _run(ssh, "grep PRETTY_NAME /etc/os-release | cut -d'\"' -f2")
        kernel = _run(ssh, "uname -r")
        hostname = _run(ssh, "hostname")

        # ─── Red / Tráfico ───
        # Primera lectura
        traffic_before = _parse_traffic(ssh)

        # Esperar 1.5 segundos
        import asyncio
        await asyncio.sleep(1.5)

        # Segunda lectura
        traffic_after = _parse_traffic(ssh)

        # Calcular velocidad por interfaz
        net_lines = []
        for iface in sorted(traffic_before.keys()):
            if iface not in traffic_after:
                continue
            rx_b, tx_b = traffic_before[iface]
            rx_a, tx_a = traffic_after[iface]
            rx_speed = (rx_a - rx_b) / 1.5
            tx_speed = (tx_a - tx_b) / 1.5

            # Tráfico total (desde boot)
            rx_total_h = _human_bytes(rx_a)
            tx_total_h = _human_bytes(tx_a)

            net_lines.append(
                f"📡 <b>{escape_html(iface)}</b>\n"
                f"   ⬇️ {_human_speed(rx_speed)} (total: {rx_total_h})\n"
                f"   ⬆️ {_human_speed(tx_speed)} (total: {tx_total_h})"
            )

        # IPs de las interfaces
        ips = _run(ssh, "ip -4 -o addr show | awk '{print $2\": \"$4}' | grep -v ' lo '")
        ips_lines = "\n".join(f"• <code>{escape_html(l)}</code>" for l in ips.splitlines()[:6])

        # IP pública
        public_ip = _run(ssh, "curl -s --max-time 3 ifconfig.me || echo 'N/A'")

        # Conexiones activas
        conn_est = _run(ssh, "ss -tun state established 2>/dev/null | tail -n +2 | wc -l")
        conn_listen = _run(ssh, "ss -tln 2>/dev/null | tail -n +2 | wc -l")
        conn_udp = _run(ssh, "ss -uln 2>/dev/null | tail -n +2 | wc -l")

        # ─── Procesos top 3 CPU ───
        top_procs_raw = _run(ssh, "ps -eo pcpu,pmem,comm --sort=-pcpu | head -4 | tail -3")
        top_procs_lines = []
        for line in top_procs_raw.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3:
                top_procs_lines.append(f"• <code>{escape_html(parts[2])}</code> — {parts[0]}% CPU, {parts[1]}% RAM")
        top_procs = "\n".join(top_procs_lines) or "N/A"

        # ─── Zombies ───
        zombies = _run(ssh, "ps aux | awk '$8 ~ /^Z/ {c++} END {print c+0}'")

        # ─── Temperatura (si disponible) ───
        temp = _run(ssh, "sensors 2>/dev/null | grep -m1 'Package id 0' | awk '{print $4}' || echo 'N/A'")

        # ─── Servicios ───
        vaydns_status = _run(ssh, "systemctl is-active vaydns-server 2>/dev/null || echo inactive")
        vaydns_emoji = "✅" if vaydns_status == "active" else "❌"

        dante_status = _run(ssh, "systemctl is-active danted 2>/dev/null || echo inactive")
        dante_emoji = "✅" if dante_status == "active" else "❌"

        # ─── Contadores ───
        active_users = db.get_active_users_count()

        # ─── Armar mensaje ───
        text = f"""
🖥️ <b>Sistema del Servidor</b>
<code>{escape_html(hostname)}</code>

━━━━━━━━━━━━━━━━━━━
💻 <b>CPU</b>
━━━━━━━━━━━━━━━━━━━
🔧 <b>Modelo:</b> <code>{escape_html(cpu_model[:60])}</code>
🧠 <b>Núcleos:</b> {cpu_cores}
📊 <b>Uso:</b> {escape_html(cpu_usage or 'N/A')}%
📈 <b>Load:</b> <code>{escape_html(load)}</code>
🌡️ <b>Temp:</b> {escape_html(temp)}

━━━━━━━━━━━━━━━━━━━
🧠 <b>Memoria RAM</b>
━━━━━━━━━━━━━━━━━━━
📦 <b>Total:</b> {mem_total_h}
📊 <b>Usada:</b> {mem_used_h} ({mem_pct:.1f}%)
🆓 <b>Libre:</b> {mem_free_h}
✅ <b>Disponible:</b> {mem_avail_h}
🔄 <b>Swap:</b> {swap_used_h} / {swap_total_h} ({swap_pct:.1f}%)

━━━━━━━━━━━━━━━━━━━
💾 <b>Disco (/)</b>
━━━━━━━━━━━━━━━━━━━
📦 <b>Total:</b> {disk_total_h}
📊 <b>Usado:</b> {disk_used_h} ({disk_pct})
🆓 <b>Libre:</b> {disk_free_h}

━━━━━━━━━━━━━━━━━━━
🌐 <b>Red</b>
━━━━━━━━━━━━━━━━━━━
🌍 <b>IP pública:</b> <code>{escape_html(public_ip)}</code>

{ips_lines}

<b>Velocidad actual / Total:</b>
{chr(10).join(net_lines) if net_lines else 'N/A'}

━━━━━━━━━━━━━━━━━━━
🔌 <b>Conexiones</b>
━━━━━━━━━━━━━━━━━━━
✅ Establecidas: {conn_est}
👂 Escuchando (TCP): {conn_listen}
📡 UDP abiertos: {conn_udp}
🧟 Zombies: {zombies}

━━━━━━━━━━━━━━━━━━━
🔥 <b>Top 3 procesos (CPU)</b>
━━━━━━━━━━━━━━━━━━━
{top_procs}

━━━━━━━━━━━━━━━━━━━
⚙️ <b>Software</b>
━━━━━━━━━━━━━━━━━━━
🐧 <b>OS:</b> {escape_html(os_name)}
🔧 <b>Kernel:</b> <code>{escape_html(kernel)}</code>
⏱️ <b>Uptime:</b> {escape_html(uptime)}

━━━━━━━━━━━━━━━━━━━
🚀 <b>Servicios</b>
━━━━━━━━━━━━━━━━━━━
{vaydns_emoji} VayDNS: <code>{vaydns_status}</code>
{dante_emoji} Dante: <code>{dante_status}</code>
👥 Cuentas activas: {active_users}

━━━━━━━━━━━━━━━━━━━
🌐 <b>Servidor:</b> {escape_html(server['name'])}
📡 <b>IP:</b> <code>{escape_html(server['ip'])}</code>
"""
        await msg.edit_text(text, parse_mode='HTML')

    except Exception as e:
        await msg.edit_text(f"❌ <b>Error:</b>\n<code>{escape_html(str(e))}</code>", parse_mode='HTML')
    finally:
        try:
            ssh.close()
        except Exception:
            pass