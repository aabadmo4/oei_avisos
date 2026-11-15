# 🚨 oei_avisos_bot

Bot que consulta periódicamente el feed DATEX II de la DGT y te escribe por **Telegram** cuando aparece un aviso nuevo en la zona de Zaragoza: sobre todo **accidentes**, **vehículos detenidos** y **retenciones / tráfico lento**.

Reutiliza de [oi_zgz](https://github.com/aabadmo4/oi_zgz) la misma caja de coordenadas y la misma clasificación de avisos, así que lo que te llega coincide con lo que se ve en <https://obraseincidenciaszaragoza.es> (cada mensaje lleva un botón a ese aviso en la web). El boletín diario de [DGT_Incidencias](https://github.com/aabadmo4/DGT_Incidencias) sigue siendo independiente.

```
cron externo (cada 5 min) ─> GitHub Actions (avisos.yml, workflow_dispatch)
                                      │
DGT NAP (DATEX II) ──> python -m bot ─┼─> Telegram (solo avisos nuevos)
                                      └─> data/estado.json (commit solo si cambia)
```

Ejemplo de mensaje:

```
💥 Accidente · A-2
pk 312.4 · sentido creciente · orientación este
Accidente con varios vehículos
🕒 Desde las 13:25
[📍 Mapa] [🌐 Web]
```

## Puesta en marcha

### 1. Bot de Telegram

1. En Telegram, habla con [@BotFather](https://t.me/BotFather) → `/newbot` → copia el **token**.
2. Abre un chat con tu bot y pulsa **Iniciar** (si no, no puede escribirte).
3. Obtén tu **chat id**: escribe cualquier cosa al bot y abre `https://api.telegram.org/bot<TOKEN>/getUpdates`; está en `message.chat.id`.

### 2. Repositorio

Crea el repo `oei_avisos_bot`, sube este contenido y añade en *Settings → Secrets and variables → Actions*:

| Secreto | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token de BotFather |
| `TELEGRAM_CHAT_ID` | tu chat id |

### 3. Cron externo

Como en oi_zgz, el disparo fiable es un servicio fuera de GitHub que lanza el workflow por la API. Con [cron-job.org](https://cron-job.org) (o cualquiera que permita cabeceras y cuerpo):

- **URL:** `https://api.github.com/repos/<usuario>/oei_avisos_bot/actions/workflows/avisos.yml/dispatches`
- **Método:** `POST`, **frecuencia:** cada 5 minutos
- **Cabeceras:** `Accept: application/vnd.github+json` · `Authorization: Bearer <TOKEN>` · `X-GitHub-Api-Version: 2022-11-28`
- **Cuerpo:** `{"ref":"main","inputs":{"origen":"cron-externo"}}`
- GitHub responde `204 No Content` si lo acepta.

El `<TOKEN>` es un *fine-grained token* limitado a **este repo** con permiso *Actions: Read and write*. Guárdalo solo en el servicio de cron, nunca en el repo.

Tiene también un `schedule` de GitHub (`7,37 * * * *`) solo como respaldo; no provoca duplicados porque el estado recuerda qué se ha avisado. En *Actions* el nombre de cada ejecución indica quién la lanzó (`⏱ cron externo`, `🖐 manual`, `🕐 cron GitHub`), para comprobar que el cron externo funciona.

### 4. Primera ejecución

Lanza el workflow a mano (*Actions → Avisos DGT → Run workflow*). La primera vez el bot **no te inunda**: marca como ya conocido lo que hay vigente y te manda un único mensaje («🟢 activo, vigentes ahora: …»). A partir de ahí solo avisa de lo nuevo.

## Configuración (`config/avisos.json`)

| Clave | Qué hace | Por defecto |
|---|---|---|
| `caja` | Rango de coordenadas (el mismo que oi_zgz) | lat 41.55–41.76, lon −1.08 – −0.78 |
| `avisar` | Etiquetas que generan aviso (ver abajo) | `Accidente`, `Retención`, `Vehículo detenido` |
| `olvidar_tras_horas` | Un aviso que desaparece se recuerda este tiempo por si la DGT lo reabre; si vuelve dentro de la ventana, no se repite | 6 |
| `max_mensajes_por_ejecucion` | Tope de mensajes sueltos por pasada; el resto va en un único mensaje resumen | 8 |
| `fallos_dgt_para_alertar` | Consultas seguidas fallidas antes de avisarte de que la DGT no responde (y otro aviso al recuperarse) | 6 (≈30 min a 5 min/consulta) |

Etiquetas disponibles para `avisar`: `Accidente`, `Retención`, `Tráfico lento`, `Corte` (calzada cerrada), `Vehículo detenido`, `Vehículo averiado`, `Vehículo abandonado`, `Vehículo en llamas`, `Vehículo con mercancías peligrosas`, `Objeto en la calzada`, `Animales en la vía`, `Obstáculo en la vía`, `Obras`. Un aviso puede tener varias (p. ej. un corte por vehículo detenido tiene `Corte` y `Vehículo detenido`) y basta con que una esté en `avisar`.

## Cómo evita duplicados y ruido

- `data/estado.json` guarda los ids de los avisos ya enviados. Se **commitea solo si cambia** (aviso nuevo o desaparecido), con `[skip ci]`.
- Si un envío a Telegram falla, ese aviso no se marca y se reintenta en la siguiente pasada; el workflow termina en rojo para que GitHub te avise.
- Si la **DGT** no responde, no es un fallo del bot: se cuenta, y solo si dura `fallos_dgt_para_alertar` pasadas te llega un aviso (y otro al recuperarse).
- Se ignoran los registros ya caducados (`overallEndTime` pasado).

## Probar en local

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v           # tests, sin red
python -m bot --dry-run                            # feed real de la DGT; imprime, no envía ni guarda
python -m bot --dry-run --xml tests/fixtures/dgt_ejemplo.xml
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python -m bot   # envío real
```

## Estructura

```
bot/dgt.py        descarga + clasificación DATEX II (misma lógica que oi_zgz)
bot/nucleo.py     qué avisar, deduplicación, tope, caídas de la DGT
bot/mensajes.py   textos de Telegram (HTML)
bot/telegram.py   envío (reintentos, 429, sin filtrar el token)
bot/estado.py     data/estado.json
tests/            unittest + XML de ejemplo
config/avisos.json
.github/workflows/avisos.yml
```

> Servicio independiente y no oficial: la información es orientativa. Origen de los datos: Dirección General de Tráfico (DGT).
