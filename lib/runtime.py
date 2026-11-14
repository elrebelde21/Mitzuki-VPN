"""
lib/runtime.py  —  Marca de arranque del bot para calcular uptime.
Se importa al inicio, así START_TIME ~ momento de arranque del proceso.
"""
from datetime import datetime

START_TIME = datetime.now()


def uptime_str() -> str:
    delta = datetime.now() - START_TIME
    total = int(delta.total_seconds())
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)