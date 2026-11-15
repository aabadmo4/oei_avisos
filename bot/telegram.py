"""Envío de mensajes por la API de bots de Telegram."""
from __future__ import annotations

import json
import time

import requests


class ErrorTelegram(Exception):
    pass


def enviar(token: str, chat_id: str, texto: str, botones: list[tuple[str, str]] | None = None, intentos: int = 3) -> None:
    """Envía un mensaje HTML. Nunca incluye el token en las excepciones
    (la URL de la API lo lleva y `requests` la pone en sus mensajes de error)."""
    datos = {"chat_id": chat_id, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": True}
    if botones:
        datos["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": t, "url": u} for t, u in botones]]})
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i in range(1, intentos + 1):
        try:
            r = requests.post(url, data=datos, timeout=20)
        except requests.RequestException as e:
            if i == intentos:
                raise ErrorTelegram(f"Sin conexión con Telegram ({type(e).__name__})") from None
            time.sleep(2 * i)
            continue
        if r.status_code == 429 and i < intentos:
            try:
                espera = int(r.json().get("parameters", {}).get("retry_after", 5))
            except ValueError:
                espera = 5
            time.sleep(min(espera, 30))
            continue
        if r.status_code >= 500 and i < intentos:
            time.sleep(2 * i)
            continue
        if not r.ok:
            try:
                desc = r.json().get("description", "")
            except ValueError:
                desc = ""
            raise ErrorTelegram(f"Telegram respondió {r.status_code}: {desc}")
        return
