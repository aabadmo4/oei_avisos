"""Lógica del bot, sin red ni disco: recibe funciones para obtener el XML y enviar."""
from __future__ import annotations

import datetime
from typing import Callable

from . import dgt, mensajes
from .telegram import ErrorTelegram

Enviar = Callable[..., None]  # enviar(texto, botones=None)

CONFIG_POR_DEFECTO = {
    "caja": {"lat_min": 41.55, "lat_max": 41.76, "lon_min": -1.08, "lon_max": -0.78},
    "avisar": ["Accidente", "Retención", "Vehículo detenido"],
    "olvidar_tras_horas": 6,
    "max_mensajes_por_ejecucion": 8,
    "fallos_dgt_para_alertar": 6,
}


def _iso(d: datetime.datetime) -> str:
    return d.astimezone(dgt.MADRID).isoformat(timespec="seconds")


def _orden(a: dgt.Aviso):
    p = dgt.PRIORIDAD
    return (p.index(a.categoria) if a.categoria in p else len(p), a.id)


def _registrar(estado: dict, a: dgt.Aviso, ahora: datetime.datetime) -> None:
    estado["avisados"][a.id] = {"categoria": a.categoria, "desde": _iso(ahora), "fuera": None}


def _fallo_dgt(estado: dict, cfg: dict, enviar: Enviar, error: Exception) -> int:
    estado["fallos_dgt"] += 1
    print(f"DGT no disponible ({estado['fallos_dgt']}): {error}")
    if estado["fallos_dgt"] >= cfg["fallos_dgt_para_alertar"] and not estado["alerta_dgt_enviada"]:
        try:
            enviar(mensajes.dgt_caida(estado["fallos_dgt"]))
            estado["alerta_dgt_enviada"] = True
        except ErrorTelegram as e:
            print(f"No se pudo enviar la alerta de caída: {e}")
            return 1
    return 0  # caída transitoria de la DGT: no es un fallo del bot


def ejecutar(cfg: dict, obtener_xml: Callable[[], bytes], estado: dict, enviar: Enviar, ahora: datetime.datetime) -> int:
    """Una pasada: consulta la DGT, avisa de lo nuevo y actualiza `estado` (se muta).
    Devuelve el código de salida: 0 correcto (incluida una caída puntual de la DGT), 1 si Telegram falló."""
    try:
        avisos = dgt.parsear(obtener_xml(), cfg["caja"], ahora)
    except dgt.ErrorDGT as e:
        return _fallo_dgt(estado, cfg, enviar, e)

    if estado["fallos_dgt"]:
        if estado["alerta_dgt_enviada"]:
            try:
                enviar(mensajes.dgt_recuperada())
            except ErrorTelegram as e:
                print(f"No se pudo enviar la recuperación: {e}")
        estado["fallos_dgt"], estado["alerta_dgt_enviada"] = 0, False

    avisar = set(cfg["avisar"])
    vigentes = {a.id: a for a in avisos if a.etiquetas & avisar}
    registro = estado["avisados"]

    # Primera ejecución: se marca todo lo vigente como ya conocido, sin inundar el chat.
    if not estado["inicializado"]:
        try:
            enviar(mensajes.inicio(sorted(vigentes.values(), key=_orden)))
        except ErrorTelegram as e:
            print(f"Error de Telegram en el mensaje de inicio: {e}")
            return 1  # no se inicializa: se reintenta en la siguiente pasada
        for a in vigentes.values():
            _registrar(estado, a, ahora)
        estado["inicializado"] = True
        return 0

    for id_ in vigentes:
        if id_ in registro:
            registro[id_]["fuera"] = None
    nuevos = sorted((a for id_, a in vigentes.items() if id_ not in registro), key=_orden)

    errores = 0
    tope = cfg["max_mensajes_por_ejecucion"]
    for a in nuevos[:tope]:
        try:
            texto, botones = mensajes.formatear(a, ahora)
            enviar(texto, botones)
            _registrar(estado, a, ahora)
        except ErrorTelegram as e:
            errores += 1
            print(f"No se pudo enviar {a.id}: {e}")  # sin registrar: se reintenta en la siguiente pasada
    resto = nuevos[tope:]
    if resto:
        try:
            enviar(mensajes.resumen(resto))
            for a in resto:
                _registrar(estado, a, ahora)
        except ErrorTelegram as e:
            errores += 1
            print(f"No se pudo enviar el resumen: {e}")

    # Un aviso que desaparece se recuerda `olvidar_tras_horas` por si la DGT lo reabre (sin volver a avisar).
    limite = datetime.timedelta(hours=cfg["olvidar_tras_horas"])
    for id_, reg in list(registro.items()):
        if id_ in vigentes:
            continue
        if reg.get("fuera") is None:
            reg["fuera"] = _iso(ahora)
        elif ahora - datetime.datetime.fromisoformat(reg["fuera"]) > limite:
            del registro[id_]
    return 1 if errores else 0
