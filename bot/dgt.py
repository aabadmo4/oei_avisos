"""Descarga y clasificación de avisos DATEX II de la DGT.

La clasificación (tipo_dgt, causa_dgt, caja de coordenadas) es la misma que usa
oi_zgz (scripts/actualizar_datos.py), para que los avisos coincidan con lo que
se ve en https://obraseincidenciaszaragoza.es.
"""
from __future__ import annotations

import datetime
import re
import time
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import requests
from lxml import etree

URL_DGT = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml"
UA = {"User-Agent": "Mozilla/5.0 (compatible; oei_avisos_bot)"}
XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"
MADRID = ZoneInfo("Europe/Madrid")

# Causa DATEX II (<cause><causeType> + <detailedCauseType>): primero el detalle, luego el tipo general.
CAUSAS = {
    "vehiclestuck": "Vehículo detenido", "brokendownvehicle": "Vehículo averiado",
    "abandonedvehicle": "Vehículo abandonado", "vehicleonfire": "Vehículo en llamas",
    "vehiclecarryingdangerousmaterials": "Vehículo con mercancías peligrosas",
    "objectontheroad": "Objeto en la calzada", "animalpresence": "Animales en la vía",
    "vehicleobstruction": "Vehículo detenido", "accident": "Accidente",
    "abnormaltraffic": "Tráfico lento", "obstruction": "Obstáculo en la vía",
    "roadmaintenance": "Obras en la vía", "poorroadinfrastructure": "Mal estado de la vía",
    "environmentalobstruction": "Obstáculo en la vía", "animalpresenceobstruction": "Animales en la vía",
}
SENTIDOS = {"POSITIVE": "sentido creciente", "NEGATIVE": "sentido decreciente", "BOTH": "ambos sentidos"}
ORIENTACIONES = {"northbound": "norte", "southbound": "sur", "eastbound": "este", "westbound": "oeste",
                 "northeastbound": "noreste", "northwestbound": "noroeste",
                 "southeastbound": "sureste", "southwestbound": "suroeste"}

# Orden para elegir la etiqueta que encabeza el mensaje cuando un aviso tiene varias.
PRIORIDAD = ["Accidente", "Corte", "Vehículo en llamas", "Retención", "Vehículo detenido"]


class ErrorDGT(Exception):
    pass


@dataclass(frozen=True)
class Aviso:
    id: str
    etiquetas: frozenset
    categoria: str
    via: str
    detalle_via: str
    comentario: str
    inicio: datetime.datetime | None
    lat: float
    lon: float


def en_caja(lat, lon, caja) -> bool:
    try:
        return caja["lat_min"] <= float(lat) <= caja["lat_max"] and caja["lon_min"] <= float(lon) <= caja["lon_max"]
    except (TypeError, ValueError):
        return False


def tipo_desde_texto(txt: str) -> str:
    t = txt.lower()
    if "accident" in t: return "Accidente"
    if re.search(r"cortes?\s+(de|del)\s+(agua|luz|gas|electricidad|suministro)", t): return "Suministro"
    if "corte" in t or "closure" in t or "cerrad" in t: return "Corte"
    if "obra" in t or "works" in t or "maintenance" in t or "mantenimiento" in t: return "Obras"
    if "retenci" in t or "congestion" in t or "atasco" in t: return "Retención"
    return "Otros"


def tipo_dgt(rec, xp, crudo: str = "") -> str:
    """Tipo de un registro DATEX II usando sus campos estructurados (igual que oi_zgz).
    'laneClosures' (un carril cerrado) NO es un corte: solo 'roadClosed' y 'carriagewayClosures'."""
    causa = [c.lower() for c in xp(rec, './/*[local-name()="cause"]/*[local-name()="causeType"]/text()')]
    gestion = [g.lower() for g in xp(rec, './/*[local-name()="roadOrCarriagewayOrLaneManagementType"]/text()')]
    xsi = (rec.get(XSI) or "").lower()
    if "accident" in causa or "accident" in xsi:
        return "Accidente"
    if {"roadclosed", "carriagewayclosures"} & set(gestion):
        return "Corte"
    if "roadmaintenance" in causa or "works" in xsi or "maintenance" in xsi:
        return "Obras"
    if "abnormaltraffic" in causa or xp(rec, './/*[local-name()="abnormalTrafficType"]/text()'):
        return "Retención"
    limpio = re.sub(r"\b\w*closures?\b", " ", crudo, flags=re.I)
    t = tipo_desde_texto(limpio)
    return "Otros" if t == "Corte" and gestion else t


def causa_dgt(rec, xp) -> str:
    det = xp(rec, './/*[local-name()="detailedCauseType"]//text()')
    gen = xp(rec, './/*[local-name()="cause"]/*[local-name()="causeType"]/text()')
    for c in det + gen:
        if c.lower() in CAUSAS:
            return CAUSAS[c.lower()]
    return ""


def _xp(rec, q):
    return [t.strip() for t in rec.xpath(q) if t.strip()]


def parse_fecha(s):
    if not s:
        return None
    try:
        d = datetime.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=MADRID) if d.tzinfo is None else d.astimezone(MADRID)


def categoria_principal(etiquetas) -> str:
    for p in PRIORIDAD:
        if p in etiquetas:
            return p
    return sorted(etiquetas)[0]


def parsear(contenido: bytes, caja: dict, ahora: datetime.datetime) -> list[Aviso]:
    """Avisos del feed que caen dentro de la caja y no han caducado."""
    try:
        root = etree.fromstring(contenido, etree.XMLParser(recover=True, encoding="utf-8"))
    except etree.XMLSyntaxError:
        root = None
    if root is None:
        raise ErrorDGT("La respuesta de la DGT no es un XML válido")
    registros = root.xpath('//*[local-name()="situationRecord"]')
    if not registros:
        raise ErrorDGT("El XML de la DGT no contiene ningún situationRecord")
    out = []
    for rec in registros:
        rid = rec.get("id")
        lats = _xp(rec, './/*[local-name()="latitude"]/text()')
        lons = _xp(rec, './/*[local-name()="longitude"]/text()')
        if not rid or not lats or not lons or not en_caja(lats[0], lons[0], caja):
            continue
        fin = parse_fecha((_xp(rec, './/*[local-name()="overallEndTime"]/text()') or [None])[0])
        if fin and fin < ahora:
            continue
        crudo = (rec.get(XSI) or "") + " " + " ".join(_xp(rec, ".//text()"))
        tipo, causa = tipo_dgt(rec, _xp, crudo), causa_dgt(rec, _xp)
        etiquetas = {t for t in (tipo, causa) if t and t != "Otros"} or {"Otros"}
        pks = sorted(set(_xp(rec, './/*[local-name()="kilometerPoint"]/text()')))
        dirs = _xp(rec, './/*[local-name()="tpegDirectionRoad"]/text()') + _xp(rec, './/*[local-name()="tpegDirection"]/text()')
        sent = [SENTIDOS[v.upper()] for v in dirs if v.upper() in SENTIDOS]
        orient = [ORIENTACIONES[v.lower()] for v in dirs if v.lower() in ORIENTACIONES]
        extra = []
        if pks: extra.append("pk " + (pks[0] if len(pks) == 1 else f"{pks[0]}–{pks[-1]}"))
        if sent: extra.append(sent[0])
        if orient: extra.append("orientación " + orient[0])
        via = (_xp(rec, './/*[local-name()="roadName"]/text()') or _xp(rec, './/*[local-name()="roadNumber"]/text()') or ["Carretera"])[0]
        coment = " ".join(_xp(rec, './/*[local-name()="generalPublicComment"]//*[local-name()="value"]/text()'))[:300]
        out.append(Aviso(
            id=f"dgt-{rid}", etiquetas=frozenset(etiquetas), categoria=categoria_principal(etiquetas),
            via=via, detalle_via=" · ".join(extra), comentario=coment,
            inicio=parse_fecha((_xp(rec, './/*[local-name()="overallStartTime"]/text()') or [None])[0]),
            lat=float(lats[0]), lon=float(lons[0]),
        ))
    return out


def descargar(intentos: int = 3, espera: int = 3) -> bytes:
    ultimo = None
    for i in range(1, intentos + 1):
        try:
            r = requests.get(URL_DGT, headers=UA, timeout=45)
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            ultimo = e
            print(f"DGT: intento {i}/{intentos} fallido: {type(e).__name__}")
            if i < intentos:
                time.sleep(espera * i)
    raise ErrorDGT(f"No se pudo descargar el feed de la DGT ({type(ultimo).__name__})")
