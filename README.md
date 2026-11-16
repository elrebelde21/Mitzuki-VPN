# 🚀 Mitzuki VPN Bot

Bot de Telegram para administrar un servidor VPN por DNS (**VayDNS**) y vender o regalar cuentas SSH/SOCKS y WireGuard desde Telegram, sin tocar la terminal.

> ⚠️ Proyecto en desarrollo.

---

## ✨ Funciones

**Para los usuarios**
- 🚀 **Crear VayDNS** (túnel DNS, ideal para redes restringidas) y 🛡️ **Crear WireGuard** (VPN directa, la más rápida), paso a paso y con botones.
- 👤 **Mis cuentas**: datos, link de importación (siempre actualizado), `.conf` + QR de WireGuard, eliminar.
- ⭐ **Mi plan**: límites y vencimiento. 📖 **Cómo conectar**: guías y "No me conecta".
- 🔔 Aviso automático cuando la cuenta está por vencer y cuando vence.

**Para el admin (🛠️ Panel de administración)**
- 🩺 **Diagnóstico** de punta a punta (VPS, servicios, puerto 53, backend, DNS, firewall, WireGuard) y 🔧 **Reparar todo** con un toque.
- 🧩 **Servicios**: estado e instalación/desinstalación de VayDNS, WireGuard, Soar, Slipstream y MasterDnsVPN.
- 👥 **Cuentas**: lista paginada, detalle con conexiones en vivo, ➕ renovar 7/30 días, reenviar datos, eliminar.
- 🔀 **Record type** (los 9 tipos) y 🔐 **Backend** SSH/SOCKS: se aplican en la VPS y regeneran todos los links.
- ⭐ **Premium**: dar planes paso a paso, ver activos y quitarlos.
- 📊 Dashboard, 🌐 DNS, 📡 tráfico, 📋 actividad y ⚙️ modo Público/Privado.
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

Después puedes comprobarlo desde el bot con **🛠️ Panel → 🌐 DNS**.

> ☁️ Si tu proveedor tiene firewall propio (Oracle Cloud, AWS, Google Cloud, Azure...), abre ahí **UDP 53** (VayDNS) y **UDP 51820** (WireGuard). El bot abre el firewall de la VPS, pero no el del proveedor.

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
| `BOT_NAME` | Nombre que se muestra en el bot |
| `APP_DOWNLOAD_URL` | Link de descarga de la app cliente de VayDNS |
| `WG_APP_DOWNLOAD_URL` | Link de descarga de la app WireGuard |
| `WG_ENDPOINT` | Host para WireGuard (vacío = IP de la VPS) |

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
2. **🛠️ Panel → 🧩 Servicios → 📥 Instalar** VayDNS (y WireGuard si lo quieres).
3. **🛠️ Panel → 🩺 Diagnóstico**: todo debe quedar en 🟢. Si algo sale en 🔴, toca **🔧 Reparar todo** y sigue la indicación de esa línea.
4. Crea una cuenta con **🚀 Crear VayDNS** o **🛡️ Crear WireGuard** y pruébala.
5. Elige **⚙️ Modo** → Público o Privado.

### ¿Actualizaste el bot y tenías VayDNS instalado?
Toca una vez **🛠️ Panel → 🩺 Diagnóstico → 🔧 Reparar todo**. Esto reescribe el servicio en la VPS con la configuración nueva y regenera los links. Después, los clientes deben copiar de nuevo su link desde **👤 Mis cuentas**.

---

## 🔀 Record Type

Es el tipo de registro DNS por donde viaja el túnel. Si en tu red un tipo está bloqueado o va lento, cámbialo a otro desde **🛠️ Panel → 🔀 Record**.

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
- Los links de **todas** las cuentas se regeneran solos: los clientes solo tienen que copiar de nuevo el suyo desde **👤 Mis cuentas**.

---

## 💬 Comandos

| Comando | Quién | Qué hace |
|---------|-------|----------|
| `/start` | Todos | Menú principal |
| `/cancel` | Todos | Cancela lo que estés haciendo |
| `/id` | Todos | Muestra tu ID de Telegram |
| `/plan` | Todos | Muestra tu plan premium |
| `/system` | Admin | Estado de la VPS |
| `/speedtest` | Todos | Test de velocidad de la VPS |
| `/premium <id> <cuentas> <conex> <días> <días_plan>` | Admin | Da premium. Ej: `/premium 123456789 3 5 30 30` |
| `/unpremium <id>` | Admin | Quita el premium |

---

## ❓ Problemas comunes

Lo primero siempre: **🛠️ Panel → 🩺 Diagnóstico**. Te dice qué falla y cómo arreglarlo.

- **`NameError: name 'process' is not defined`** → `config.py` viejo; usa el del repo y pon tus datos en `.env`.
- **El bot no responde a los botones de admin** → tu ID no está en `ADMIN_IDS`.
- **"Prueba de punta a punta" en 🔴** → las consultas DNS no llegan a la VPS: revisa el registro **NS** y que el firewall del **proveedor** deje pasar **UDP 53**.
- **VayDNS conecta y se corta / no conecta** → toca **🔧 Reparar todo** y que el cliente copie de nuevo su link. Si la red bloquea el tipo actual, prueba otro **Record type**.
- **WireGuard importa pero no navega** → **🔧 Reparar todo**; abre **UDP 51820** en el firewall del proveedor. Un mismo `.conf` en dos dispositivos a la vez se desconectan entre sí.
- **Puerto 53 ocupado** → quita Soar / Slipstream / MasterDnsVPN desde **🧩 Servicios** (el bot ya libera `systemd-resolved` solo).
