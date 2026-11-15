"""Estado persistente (data/estado.json): qué avisos ya se han enviado.

Solo cambia cuando hay novedades (aviso nuevo, aviso desaparecido, fallos de la DGT),
para que el commit de estado del workflow no se haga en cada ejecución.
"""
from __future__ import annotations

import json
import os


def vacio() -> dict:
    return {"version": 1, "inicializado": False, "avisados": {}, "fallos_dgt": 0, "alerta_dgt_enviada": False}


def cargar(ruta: str) -> dict:
    try:
        with open(ruta, encoding="utf-8") as f:
            est = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return vacio()
    return {**vacio(), **est}


def serializar(estado: dict) -> str:
    return json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def guardar(ruta: str, estado: dict) -> bool:
    """Escribe solo si cambia. Devuelve True si escribió."""
    nuevo = serializar(estado)
    try:
        with open(ruta, encoding="utf-8") as f:
            if f.read() == nuevo:
                return False
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(nuevo)
    os.replace(tmp, ruta)
    return True
