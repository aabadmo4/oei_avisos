"""Textos de los mensajes de Telegram (HTML)."""
from __future__ import annotations

import datetime
from html import escape

from .dgt import MADRID, Aviso

WEB = "https://obraseincidenciaszaragoza.es/#"
ICONOS = {"Accidente": "💥", "Corte": "⛔", "Retención": "🚦", "Vehículo detenido": "🚗",
          "Vehículo en llamas": "🔥", "Vehículo averiado": "🚗", "Obras": "🚧"}


def icono(categoria: str) -> str:
    return ICONOS.get(categoria, "⚠️")


def _desde(inicio: datetime.datetime | None, ahora: datetime.datetime) -> str:
    if not inicio:
        return ""
    i, a = inicio.astimezone(MADRID), ahora.astimezone(MADRID)
    if i.date() == a.date():
        return f"🕒 Desde las {i:%H:%M}"
    return f"🕒 Desde el {i:%d/%m} a las {i:%H:%M}"


def formatear(a: Aviso, ahora: datetime.datetime) -> tuple[str, list[tuple[str, str]]]:
    lineas = [f"{icono(a.categoria)} <b>{escape(a.categoria)}</b> · {escape(a.via)}"]
    if a.detalle_via:
        lineas.append(escape(a.detalle_via))
    if a.comentario and a.comentario.lower() not in {e.lower() for e in a.etiquetas}:
        lineas.append(f"<i>{escape(a.comentario)}</i>")
    desde = _desde(a.inicio, ahora)
    if desde:
        lineas.append(desde)
    botones = [("📍 Mapa", f"https://www.google.com/maps?q={a.lat},{a.lon}"), ("🌐 Web", WEB + a.id)]
    return "\n".join(lineas), botones


def resumen(avisos: list[Aviso]) -> str:
    lineas = [f"{icono(a.categoria)} {escape(a.categoria)} · {escape(a.via)}"
              + (f" · {escape(a.detalle_via)}" if a.detalle_via else "") for a in avisos]
    return f"➕ <b>{len(avisos)} avisos más</b>\n" + "\n".join(lineas)


def inicio(vigentes: list[Aviso]) -> str:
    if not vigentes:
        return "🟢 <b>oei_avisos_bot activo.</b> Ahora mismo no hay avisos vigentes en la zona."
    cuenta: dict[str, int] = {}
    for a in vigentes:
        cuenta[a.categoria] = cuenta.get(a.categoria, 0) + 1
    detalle = ", ".join(f"{n} {escape(c.lower())}" for c, n in sorted(cuenta.items()))
    return (f"🟢 <b>oei_avisos_bot activo.</b> Vigentes ahora: {len(vigentes)} ({detalle}). "
            "Solo te escribiré de los avisos nuevos.")


def dgt_caida(fallos: int) -> str:
    return f"⚠️ <b>La DGT no responde</b> desde hace {fallos} consultas seguidas. No puedo avisarte de nada hasta que vuelva."


def dgt_recuperada() -> str:
    return "✅ La DGT vuelve a responder. Reanudo los avisos."
