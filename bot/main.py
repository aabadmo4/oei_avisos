"""Punto de entrada: python -m bot [--dry-run] [--xml archivo.xml]"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

from . import dgt, estado as est, nucleo, telegram

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cargar_config(ruta: str) -> dict:
    cfg = json.loads(json.dumps(nucleo.CONFIG_POR_DEFECTO))
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Avisos de la DGT por Telegram")
    p.add_argument("--config", default=os.path.join(RAIZ, "config", "avisos.json"))
    p.add_argument("--estado", default=os.path.join(RAIZ, "data", "estado.json"))
    p.add_argument("--xml", help="usar este XML local en vez de descargar el de la DGT")
    p.add_argument("--dry-run", action="store_true", help="no envía a Telegram ni guarda el estado; imprime los mensajes")
    args = p.parse_args(argv)

    cfg = cargar_config(args.config)
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not args.dry_run and not (token and chat):
        print("Faltan TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID", file=sys.stderr)
        return 2

    if args.dry_run:
        def enviar(texto, botones=None):
            print("-" * 40, texto, *(f"[{t}] {u}" for t, u in (botones or [])), sep="\n")
    else:
        def enviar(texto, botones=None):
            telegram.enviar(token, chat, texto, botones)

    if args.xml:
        def obtener_xml():
            with open(args.xml, "rb") as f:
                return f.read()
    else:
        obtener_xml = dgt.descargar

    estado = est.cargar(args.estado)
    codigo = nucleo.ejecutar(cfg, obtener_xml, estado, enviar, datetime.datetime.now(dgt.MADRID))
    if not args.dry_run and est.guardar(args.estado, estado):
        print("Estado actualizado")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
