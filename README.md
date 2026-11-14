# 🚀 Mitzuki VPN Bot

Bot de Telegram para administrar un servidor VPN por DNS (**VayDNS**) y vender o regalar cuentas SSH/SOCKS y WireGuard desde Telegram, sin tocar la terminal.

> ⚠️ Proyecto en desarrollo.

---

## ✨ Funciones

**Para los usuarios**
- 👤 Ver su cuenta (usuario, contraseña, vencimiento, link de la app).
- ➕ Crear cuenta SSH/SOCKS (túnel DNS con VayDNS).
- 🛡️ Crear cuenta WireGuard.
- Los links salen listos para importar en la app (`dnst://...`).

**Para el admin (⚙️ Panel Admin)**
- 🚀 Instalar **VayDNS**, 🦅 **Soar**, 🛡️ **WireGuard**, 🌀 **Slipstream**, 🌐 **MasterDnsVPN** en la VPS con un botón.
- 🗑️ Desinstalar cualquiera de ellos.
- 🌐 Verificar que los DNS (A y NS) estén bien configurados.
- 📊 Dashboard, 📡 tráfico de la VPS, 📋 logs, 👥 lista de cuentas.
- 🔀 **Record Type**: cambiar el tipo de registro DNS del servidor (ver abajo).
- 🔐 **Backend**: SSH (límite real de conexiones) o SOCKS (más estable en redes difíciles).
- ⭐ Dar **Premium** / revendedores con límites de cuentas, conexiones y días.
- 🔄 Actualizar los links de todas las cuentas tras un cambio.
- ⚙️ Modo **Público** (cualquiera crea cuenta) o **Privado** (solo admin y premium).
- 🧹 Las cuentas vencidas se borran solas cada 5 minutos.

---

## 📋 Requisitos

1. **Una VPS** con Ubuntu/Debian, acceso root por SSH y el puerto **53 UDP** libre.
2. **Un dominio** donde puedas crear registros DNS (Cloudflare, etc.).
3. **Un bot de Telegram**: créalo con [@BotFather](https://t.me/BotFather) y copia el token.
4. **Python 3.10+** donde vaya a correr el bot (puede ser la misma VPS o un hosting tipo Pterodactyl).

### Registros DNS

| Tipo | Nombre | Valor | Nota |
|------|--------|-------|------|
| **A** | `ns.tudominio.com` | IP de tu VPS | En Cloudflare: nube **gris** (sin proxy) |
| **NS** | `d.tudominio.com` | `ns.tudominio.com` | Este es el dominio del túnel |

Después puedes comprobarlo desde el bot con **🌐 Verificar DNS**.

---

## ⚙️ Instalación

```bash
git clone https://github.com/elrebelde21/Mitzuki-VPN.git
cd Mitzuki-VPN
pip install -r requirements.txt
cp .env.example .env
```

Edita el archivo `.env` con tus datos:

| Variable | Qué es |
|----------|--------|
| `BOT_TOKEN` | Token de @BotFather |
| `ADMIN_IDS` | Tu ID de Telegram (varios separados por coma). Lo ves con `/id` en el bot |
| `DEFAULT_SERVER_IP` | IP de la VPS |
| `DEFAULT_SERVER_SSH_PORT` | Puerto SSH de la VPS (normalmente `22`) |
| `DEFAULT_SERVER_USERNAME` | Usuario de la VPS (normalmente `root`) |
| `DEFAULT_SERVER_PASSWORD` | Contraseña de la VPS |
| `DEFAULT_SERVER_DOMAIN` | Dominio tipo **A** (ej. `ns.tudominio.com`) |
| `DEFAULT_SERVER_TUNNEL_DOMAIN` | Dominio tipo **NS** (ej. `d.tudominio.com`) |
| `DEFAULT_SERVER_RECORD_TYPE` | Record type inicial (`txt` recomendado) |
| `DEFAULT_SERVER_DNSTT` | `true` / `false` – DNSTT compat (solo con `txt`) |
| `DEFAULT_SERVER_CLIENT` | ClientID size (por defecto `8`) |
| `DEFAULT_SERVER_PORT` | Puerto DNS (por defecto `53`) |
| `PUBLIC_MODE` | `true` = público, `false` = privado (se puede cambiar desde el bot) |
| `OWNER_CONTACT` | Tu @usuario, se muestra a quien no tiene acceso |
| `APP_DOWNLOAD_URL` | Link de descarga de la app cliente |

> 🔒 Nunca subas tu `.env` a GitHub (ya está en `.gitignore`).

Inicia el bot:

```bash
python3 bot.py
```

### En Pterodactyl
- Sube los archivos (o clona el repo) y crea el `.env` en la carpeta raíz desde **Files**.
- Archivo de inicio: `bot.py`. El panel instala `requirements.txt` solo.
- Si ves `NameError: name 'process' is not defined`, tienes un `config.py` viejo: actualízalo al de este repo.

---

## 🧭 Primeros pasos

1. Abre el bot y manda `/start`.
2. Entra a **⚙️ Panel Admin → 🚀 VayDNS** e instala el servidor.
3. Revisa **🌐 Verificar DNS**.
4. Crea una cuenta con **➕ Crear SSH** y pruébala en la app.
5. Elige **⚙️ Configuración** → Público o Privado.

---

## 🔀 Record Type

Es el tipo de registro DNS por donde viaja el túnel. Si en tu red un tipo está bloqueado o va lento, cámbialo a otro desde **⚙️ Panel Admin → 🔀 Record**.

| Tipo | Uso |
|------|-----|
| **TXT** | ✅ Recomendado. El más estable y rápido. Único con DNSTT compat |
| **CAA** | Evasión, para redes que bloquean TXT |
| **NULL** | Evasión, mucha capacidad por respuesta |
| **CNAME** | Alternativa cuando TXT/CAA están filtrados |
| **MX** | Alternativa |
| **NS** | Alternativa |
| **SRV** | Alternativa |
| **A** | Muy común (difícil de bloquear), pero lento |
| **AAAA** | Muy común, algo más rápido que A |

Al cambiarlo:
- El bot reinicia VayDNS en la VPS con el nuevo tipo.
- Las **cuentas nuevas** salen con ese tipo.
- Los **clientes que ya tienen cuenta** deben poner el mismo Record Type en la app (o usa **🔄 Actualizar Links**).

---

## 💬 Comandos

| Comando | Quién | Qué hace |
|---------|-------|----------|
| `/start` | Todos | Menú principal |
| `/id` | Todos | Muestra tu ID de Telegram |
| `/plan` | Todos | Muestra tu plan premium |
| `/system` | Admin | Estado de la VPS |
| `/speedtest` | Todos | Test de velocidad de la VPS |
| `/premium <id> <cuentas> <conex> <días> <días_plan>` | Admin | Da premium. Ej: `/premium 123456789 3 5 30 30` |
| `/unpremium <id>` | Admin | Quita el premium |

---

## ❓ Problemas comunes

- **`NameError: name 'process' is not defined`** → `config.py` viejo; usa el del repo y pon tus datos en `.env`.
- **El bot no responde a los botones de admin** → tu ID no está en `ADMIN_IDS`.
- **VayDNS no instala: puerto 53 ocupado** → en la VPS: `systemctl disable --now systemd-resolved` (o desinstala Soar desde el bot).
- **La cuenta no conecta** → revisa los registros DNS, que el Record Type de la app sea el mismo que el del servidor, y prueba otro tipo.
