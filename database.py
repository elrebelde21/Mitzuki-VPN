import config
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any



# Record types soportados por vaydns-server (-record-type).
# Solo TXT usa -dnstt-compat (DNSTT clásico solo habla TXT).
RECORD_TYPES = ('txt', 'caa', 'null', 'cname', 'a', 'aaaa', 'mx', 'ns', 'srv')

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # Tabla de servidores
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip TEXT NOT NULL,
                ssh_port INTEGER DEFAULT 22,
                username TEXT DEFAULT 'root',
                password TEXT,
                domain TEXT,
                proxy_type TEXT DEFAULT 'socks5',
                pubkey TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')

        # Tabla de cuentas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT,
                server_id INTEGER,
                vaydns_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                is_premium BOOLEAN DEFAULT 0,
                FOREIGN KEY (server_id) REFERENCES servers (id)
            )
        ''')

        # Tabla de configuración
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Tabla de logs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                details TEXT,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Tabla de revendedores / planes premium (por telegram_id)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS resellers (
                telegram_id INTEGER PRIMARY KEY,
                max_accounts INTEGER DEFAULT 1,
                max_conn INTEGER DEFAULT 3,
                max_days INTEGER DEFAULT 30,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # --- Migraciones: columnas nuevas en users (cuentas SSH / WireGuard) ---
        for ddl in (
            "ALTER TABLE users ADD COLUMN password TEXT",
            "ALTER TABLE users ADD COLUMN max_conn INTEGER DEFAULT 3",
            "ALTER TABLE users ADD COLUMN conn_type TEXT DEFAULT 'vaydns'",
            "ALTER TABLE users ADD COLUMN wg_ip TEXT",
            "ALTER TABLE users ADD COLUMN wg_pubkey TEXT",
            "ALTER TABLE users ADD COLUMN wg_privkey TEXT",
        ):
            try:
                cursor.execute(ddl)
            except sqlite3.OperationalError:
                pass  # la columna ya existe

        conn.commit()
        conn.close()

    # --- Servidores ---
    def add_server(self, name: str, ip: str, ssh_port: int, username: str,
                   password: str, domain: str, proxy_type: str = 'socks5') -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO servers (name, ip, ssh_port, username, password, domain, proxy_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, ip, ssh_port, username, password, domain, proxy_type))
        server_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return server_id

    def get_server(self, server_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM servers WHERE id = ? AND is_active = 1', (server_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_servers(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM servers WHERE is_active = 1 ORDER BY created_at DESC')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def update_server_pubkey(self, server_id: int, pubkey: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE servers SET pubkey = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                       (pubkey, server_id))
        conn.commit()
        conn.close()

    def delete_server(self, server_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE servers SET is_active = 0 WHERE id = ?', (server_id,))
        conn.commit()
        conn.close()

    # --- Cuentas ---
    def add_user(self, telegram_id: int, username: str, server_id: int,
                 vaydns_url: str, expires_at: str,
                 password: str = None, max_conn: int = 3) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (telegram_id, username, server_id, vaydns_url, expires_at, password, max_conn)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (telegram_id, username, server_id, vaydns_url, expires_at, password, max_conn))
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id

    def add_user_admin(self, name: str, server_id: int, vaydns_url: str, expires_at: str,
                       password: str = None, max_conn: int = 3) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (telegram_id, username, server_id, vaydns_url, expires_at, password, max_conn)
            VALUES (0, ?, ?, ?, ?, ?, ?)
        ''', (name, server_id, vaydns_url, expires_at, password, max_conn))
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.*, s.name as server_name, s.domain, s.ip
            FROM users u
            JOIN servers s ON u.server_id = s.id
            WHERE u.telegram_id = ? AND u.is_active = 1
        ''', (telegram_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ? AND is_active = 1', (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user_by_name(self, username: str) -> Optional[Dict[str, Any]]:
        """Busca una cuenta activa por su nombre de usuario (el de la cuenta SSH)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ? AND is_active = 1', (username,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user_accounts(self, telegram_id: int) -> List[Dict[str, Any]]:
        """Todas las cuentas activas de un usuario de Telegram (SSH + WireGuard)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.*, s.name as server_name, s.domain, s.ip
            FROM users u
            JOIN servers s ON u.server_id = s.id
            WHERE u.telegram_id = ? AND u.is_active = 1
            ORDER BY u.created_at DESC
        ''', (telegram_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # --- WireGuard ---
    def add_wg_user(self, telegram_id: int, username: str, server_id: int,
                    expires_at: str, wg_ip: str, wg_pubkey: str, wg_privkey: str,
                    max_conn: int = 1) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (telegram_id, username, server_id, vaydns_url, expires_at,
                               max_conn, conn_type, wg_ip, wg_pubkey, wg_privkey)
            VALUES (?, ?, ?, '', ?, ?, 'wireguard', ?, ?, ?)
        ''', (telegram_id, username, server_id, expires_at, max_conn, wg_ip, wg_pubkey, wg_privkey))
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id

    def get_wg_users(self, server_id: int) -> List[Dict[str, Any]]:
        """Peers WireGuard activos de un servidor (para reconstruir wg0.conf)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM users
            WHERE is_active = 1 AND conn_type = 'wireguard' AND server_id = ?
        ''', (server_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_all_users(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.*, s.name as server_name
            FROM users u
            JOIN servers s ON u.server_id = s.id
            WHERE u.is_active = 1
            ORDER BY u.created_at DESC
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_expired_users(self) -> List[Dict[str, Any]]:
        """Cuentas activas cuyo vencimiento ya pasó (para borrarlas del servidor)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            SELECT * FROM users
            WHERE is_active = 1 AND expires_at IS NOT NULL AND expires_at < ?
        ''', (now,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def extend_user_expiry(self, user_id: int, days: int) -> Optional[str]:
        """Renueva el vencimiento a hoy + days y devuelve la nueva fecha ISO."""
        new_expiry = (datetime.now() + timedelta(days=days)).isoformat()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET expires_at = ?, is_active = 1 WHERE id = ?',
                       (new_expiry, user_id))
        conn.commit()
        conn.close()
        return new_expiry

    def deactivate_user(self, telegram_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_active = 0 WHERE telegram_id = ?', (telegram_id,))
        conn.commit()
        conn.close()

    def delete_user_by_id(self, user_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_active = 0 WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()

    def get_active_users_count(self) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def update_all_user_urls(self, new_pubkey: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, vaydns_url FROM users WHERE is_active = 1')
        rows = cursor.fetchall()

        import re
        for row in rows:
            old_url = row['vaydns_url']
            if old_url and 'pubkey=' in old_url:
                new_url = re.sub(r'pubkey=[a-f0-9]+', f'pubkey={new_pubkey}', old_url)
                cursor.execute('UPDATE users SET vaydns_url = ? WHERE id = ?', (new_url, row['id']))

        conn.commit()
        conn.close()

    # --- Logs ---
    def add_log(self, action: str, details: str, user_id: int = None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO logs (action, details, user_id) VALUES (?, ?, ?)',
                       (action, details, user_id))
        conn.commit()
        conn.close()

    def get_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM logs ORDER BY created_at DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # --- Config ---
    def set_config(self, key: str, value: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO config (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (key, value))
        conn.commit()
        conn.close()

    def get_config(self, key: str) -> Optional[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM config WHERE key = ?', (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    # --- Modo Público/Privado ---
    def is_public_mode(self) -> bool:
        value = self.get_config('public_mode')
        if value is None:
            return config.PUBLIC_MODE
        return value == '1'

    def set_public_mode(self, enabled: bool):
        self.set_config('public_mode', '1' if enabled else '0')

    # --- Record type persistido (todos los que soporta VayDNS) ---
    def get_record_type(self) -> str:
        """Record type activo. Default seguro = txt (lo que funciona con compat)."""
        value = (self.get_config('record_type') or '').lower()
        if value in RECORD_TYPES:
            return value
        return 'txt'

    def set_record_type(self, record_type: str):
        self.set_config('record_type', record_type)

    # --- Backend de autenticación: ssh o socks ---
    def get_backend(self) -> str:
        value = self.get_config('backend')
        return value if value in ('ssh', 'socks') else 'ssh'

    def set_backend(self, backend: str):
        self.set_config('backend', backend)

    # --- Premium / Revendedores (planes) ---
    def set_reseller(self, telegram_id: int, max_accounts: int, max_conn: int,
                     max_days: int, premium_days: int):
        """Crea/actualiza el plan premium de un usuario. Vence en hoy + premium_days."""
        expires_at = (datetime.now() + timedelta(days=premium_days)).isoformat()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO resellers (telegram_id, max_accounts, max_conn, max_days, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                max_accounts = excluded.max_accounts,
                max_conn = excluded.max_conn,
                max_days = excluded.max_days,
                expires_at = excluded.expires_at
        ''', (telegram_id, max_accounts, max_conn, max_days, expires_at))
        conn.commit()
        conn.close()

    def get_reseller(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM resellers WHERE telegram_id = ?', (telegram_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def is_reseller_active(self, telegram_id: int) -> bool:
        r = self.get_reseller(telegram_id)
        if not r or not r.get('expires_at'):
            return False
        try:
            return datetime.fromisoformat(r['expires_at']) > datetime.now()
        except (ValueError, TypeError):
            return False

    def remove_reseller(self, telegram_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM resellers WHERE telegram_id = ?', (telegram_id,))
        conn.commit()
        conn.close()

    def count_user_accounts(self, telegram_id: int) -> int:
        """Cuántas cuentas SSH activas creó este usuario."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users WHERE telegram_id = ? AND is_active = 1',
                       (telegram_id,))
        count = cursor.fetchone()[0]
        conn.close()
        return count

    # Compat: "premium" ahora significa "tiene plan de revendedor activo"
    def is_premium(self, telegram_id: int) -> bool:
        return self.is_reseller_active(telegram_id)

    def set_premium(self, telegram_id: int, enabled: bool):
        """Compat: activar = plan básico 30d; desactivar = quitar plan."""
        if enabled:
            self.set_reseller(telegram_id, max_accounts=1, max_conn=3, max_days=30, premium_days=30)
        else:
            self.remove_reseller(telegram_id)

    def update_server_credentials(self, server_id: int, username: str, password: str):
        """Actualiza usuario y contraseña de un servidor"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE servers
            SET username = ?, password = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (username, password, server_id))
        conn.commit()
        conn.close()