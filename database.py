import config
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any


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
                 vaydns_url: str, expires_at: str) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (telegram_id, username, server_id, vaydns_url, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (telegram_id, username, server_id, vaydns_url, expires_at))
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id

    def add_user_admin(self, name: str, server_id: int, vaydns_url: str, expires_at: str) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (telegram_id, username, server_id, vaydns_url, expires_at)
            VALUES (0, ?, ?, ?, ?)
        ''', (name, server_id, vaydns_url, expires_at))
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

    # --- Premium ---
    def set_premium(self, telegram_id: int, enabled: bool):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_premium = ? WHERE telegram_id = ?',
                       (1 if enabled else 0, telegram_id))
        conn.commit()
        conn.close()

    def is_premium(self, telegram_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT is_premium FROM users WHERE telegram_id = ? AND is_active = 1',
                       (telegram_id,))
        row = cursor.fetchone()
        conn.close()
        return bool(row[0]) if row else False

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