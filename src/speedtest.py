import asyncio
import os
import re
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from lib.helpers import escape_html


SPEED_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'speed.py'
)


def _extract(text, pattern):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


async def _wait_image_ready(url, max_attempts=15, delay=1.0):
    """Espera a que el PNG de Ookla esté disponible (HEAD request)."""
    import urllib.request
    for attempt in range(max_attempts):
        try:
            req = urllib.request.Request(
                url,
                method='HEAD',
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    print(f"[speedtest] imagen lista tras {attempt+1} intentos")
                    return True
        except Exception as e:
            print(f"[speedtest] intento {attempt+1}/{max_attempts}: {e}")
        await asyncio.sleep(delay)
    return False


async def speedtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test de velocidad Ookla — público, con imagen y link"""

    msg = await update.message.reply_text(
        "🚀 <b>Iniciando Speedtest...</b>\n\n⏳ Esto puede tardar 30-60 segundos.",
        parse_mode='HTML'
    )

    # ─── Ejecutar speed.py --share ───
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, SPEED_SCRIPT, '--share',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=150)

    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        await msg.edit_text("❌ <b>Timeout:</b> el test tardó demasiado.", parse_mode='HTML')
        return
    except FileNotFoundError:
        await msg.edit_text(
            f"❌ <b>No se encontró el script</b>\n<code>{escape_html(SPEED_SCRIPT)}</code>",
            parse_mode='HTML'
        )
        return
    except Exception as e:
        await msg.edit_text(
            f"❌ <b>Error:</b>\n<code>{escape_html(str(e))}</code>",
            parse_mode='HTML'
        )
        return

    stdout_text = stdout.decode('utf-8', errors='ignore').strip()
    stderr_text = stderr.decode('utf-8', errors='ignore').strip()

    if not stdout_text and proc.returncode != 0:
        error_text = stderr_text or 'Error desconocido'
        await msg.edit_text(
            f"❌ <b>Speedtest falló:</b>\n\n<code>{escape_html(error_text[:800])}</code>",
            parse_mode='HTML'
        )
        return

    # ─── Parsear resultado ───
    isp = _extract(stdout_text, r'\*ISP:\*\s*(.+)')
    server_name = _extract(stdout_text, r'\*Servidor:\*\s*(.+)')
    location = _extract(stdout_text, r'\*Ubicación:\*\s*(.+)')
    latency = _extract(stdout_text, r'\*Latencia:\*\s*([\d.]+)\s*ms')
    download = _extract(stdout_text, r'\*Descarga:\*\s*([\d.]+\s*\S+)')
    upload = _extract(stdout_text, r'\*Subida:\*\s*([\d.]+\s*\S+)')

    # URL para compartir
    share_url = None
    m = re.search(r'(https?://www\.speedtest\.net/result/\d+)', stdout_text)
    if m:
        share_url = m.group(1)

    # URL del PNG
    image_url = None
    if share_url:
        mid = re.search(r'/result/(\d+)', share_url)
        if mid:
            image_url = f"https://www.speedtest.net/result/{mid.group(1)}.png"

    # ─── Caption ───
    caption_lines = ["🚀 <b>Speedtest Result</b>", ""]
    if isp:
        caption_lines.append(f"🌐 <b>ISP:</b> {escape_html(isp)}")
    if server_name:
        caption_lines.append(f"🖥️ <b>Servidor:</b> {escape_html(server_name)}")
    if location:
        caption_lines.append(f"📍 <b>Ubicación:</b> {escape_html(location)}")
    if latency:
        caption_lines.append(f"⚡ <b>Latencia:</b> {latency} ms")
    if download:
        caption_lines.append(f"⬇️ <b>Descarga:</b> {escape_html(download)}")
    if upload:
        caption_lines.append(f"⬆️ <b>Subida:</b> {escape_html(upload)}")
    caption = "\n".join(caption_lines)

    # ─── Botón con link ───
    reply_markup = None
    if share_url:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Ver resultado completo", url=share_url)]
        ])

    # ─── Enviar imagen + caption ───
    if image_url:
        print(f"[speedtest] esperando PNG: {image_url}")
        image_ready = await _wait_image_ready(image_url)

        if image_ready:
            try:
                await update.message.reply_photo(
                    photo=image_url,
                    caption=caption,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
                try:
                    await msg.delete()
                except Exception:
                    pass
                return
            except Exception as e:
                print(f"[speedtest] error reply_photo: {e}")

    # ─── Fallback: solo texto + link ───
    await msg.edit_text(caption, parse_mode='HTML', reply_markup=reply_markup)