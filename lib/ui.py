"""
lib/ui.py  —  Estilo visual único del bot (textos HTML de Telegram).

Todas las pantallas usan estos helpers para verse iguales:

    header("🚀", "Crear cuenta", "Paso 1 de 4")
    kv("👤", "Usuario", code("juan"))
    tip("Tocá el link para copiarlo")
"""
import asyncio
import html
import math
from datetime import datetime
from typing import Optional

import config

LINE = "━━━━━━━━━━━━━━━━━━━━"
BRAND = getattr(config, 'BOT_NAME', 'Mitzuki VPN')

_MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


def esc(text) -> str:
    return html.escape(str(text if text is not None else ''))


def code(text) -> str:
    return f"<code>{esc(text)}</code>"


def b(text) -> str:
    return f"<b>{esc(text)}</b>"


def header(icon: str, title: str, subtitle: Optional[str] = None) -> str:
    out = f"{icon} <b>{esc(title)}</b>"
    if subtitle:
        out += f"\n<i>{esc(subtitle)}</i>"
    return f"{out}\n{LINE}"


def section(title: str) -> str:
    return f"\n<b>{esc(title)}</b>"


def kv(icon: str, label: str, value_html: str) -> str:
    """value_html ya debe venir escapado (usar code()/b()/esc())."""
    return f"{icon} {esc(label)}: {value_html}"


def tip(text_html: str) -> str:
    return f"<blockquote>💡 {text_html}</blockquote>"


def warn(text_html: str) -> str:
    return f"<blockquote>⚠️ {text_html}</blockquote>"


def quote(text_html: str) -> str:
    return f"<blockquote>{text_html}</blockquote>"


def steps(step: int, total: int) -> str:
    return f"Paso {step} de {total}  " + "●" * step + "○" * (total - step)


def bar(used: int, total: int, width: int = 10) -> str:
    total = max(total, 1)
    filled = min(width, round(width * used / total))
    return "▰" * filled + "▱" * (width - filled)


def dot(ok) -> str:
    return "🟢" if ok is True else ("🔴" if ok is False else "⚪")


def days_left(expires_at) -> int:
    """Días que quedan (redondeando hacia arriba). 0 = vence en menos de 24 h. -1 = vencida."""
    try:
        secs = (datetime.fromisoformat(str(expires_at)) - datetime.now()).total_seconds()
    except (ValueError, TypeError):
        return -1
    if secs <= 0:
        return -1
    if secs < 86400:
        return 0
    return math.ceil(secs / 86400)


def expiry(expires_at) -> str:
    d = days_left(expires_at)
    if d < 0:
        return "🔴 Vencida"
    if d == 0:
        return "🟠 Vence en menos de 24 h"
    if d <= 3:
        return f"🟡 {d} día{'s' if d != 1 else ''}"
    return f"🟢 {d} días"


def fmt_date(iso) -> str:
    try:
        dt = datetime.fromisoformat(str(iso))
        return f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year}"
    except (ValueError, TypeError):
        return str(iso or '—')[:10]


def human_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def owner_url() -> Optional[str]:
    contact = (getattr(config, 'OWNER_CONTACT', '') or '').strip()
    if contact.startswith('@') and len(contact) > 1:
        return f"https://t.me/{contact[1:]}"
    if contact.startswith('https://'):
        return contact
    return None


async def bg(func, *args, **kwargs):
    """Corre una tarea bloqueante (SSH) sin congelar el bot para los demás usuarios."""
    return await asyncio.to_thread(func, *args, **kwargs)


async def safe_edit(query, text: str, reply_markup=None):
    """edit_message_text que no explota si el mensaje no cambió o era una foto/documento."""
    try:
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup,
                                      disable_web_page_preview=True)
    except Exception as e:
        if 'not modified' in str(e).lower():
            return
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup,
                                       disable_web_page_preview=True)
