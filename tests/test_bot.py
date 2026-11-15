import datetime
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import requests
from bot import dgt, estado as est, mensajes, nucleo, telegram
from bot.telegram import ErrorTelegram

XML = open(os.path.join(os.path.dirname(__file__), "fixtures", "dgt_ejemplo.xml"), "rb").read()
CAJA = nucleo.CONFIG_POR_DEFECTO["caja"]
AHORA = datetime.datetime(2026, 11, 14, 14, 0, tzinfo=dgt.MADRID)


def cfg(**kw):
    c = json.loads(json.dumps(nucleo.CONFIG_POR_DEFECTO))
    c.update(kw)
    return c


class Sender:
    def __init__(self, falla=False):
        self.enviados, self.falla = [], falla

    def __call__(self, texto, botones=None):
        if self.falla:
            raise ErrorTelegram("fallo simulado")
        self.enviados.append((texto, botones))


def xml_con(*ids_a_quitar):
    """El XML de ejemplo sin los registros indicados."""
    s = XML.decode()
    for i in ids_a_quitar:
        a = s.index(f'id="{i}"')
        ini = s.rindex("<sit:situationRecord", 0, a)
        fin = s.index("</sit:situationRecord>", a) + len("</sit:situationRecord>")
        s = s[:ini] + s[fin:]
    return s.encode()


class TestParseo(unittest.TestCase):
    def test_filtra_caja_y_caducados(self):
        ids = {a.id for a in dgt.parsear(XML, CAJA, AHORA)}
        self.assertEqual(ids, {"dgt-9001", "dgt-9002", "dgt-9003", "dgt-9004"})

    def test_categorias(self):
        por_id = {a.id: a for a in dgt.parsear(XML, CAJA, AHORA)}
        self.assertEqual(por_id["dgt-9001"].categoria, "Accidente")
        self.assertEqual(por_id["dgt-9002"].categoria, "Vehículo detenido")
        self.assertEqual(por_id["dgt-9003"].categoria, "Retención")
        self.assertIn("Tráfico lento", por_id["dgt-9003"].etiquetas)
        self.assertEqual(por_id["dgt-9004"].categoria, "Obras")

    def test_detalle_via(self):
        a = {a.id: a for a in dgt.parsear(XML, CAJA, AHORA)}
        self.assertEqual(a["dgt-9001"].via, "A-2")
        self.assertEqual(a["dgt-9001"].detalle_via, "pk 312.4 · sentido creciente · orientación este")
        self.assertEqual(a["dgt-9003"].detalle_via, "pk 23.0–24.0")

    def test_xml_invalido_o_vacio_es_error_dgt(self):
        for malo in (b"", b"<html>no es xml", b"<a><b/></a>"):
            with self.assertRaises(dgt.ErrorDGT):
                dgt.parsear(malo, CAJA, AHORA)

    def test_lane_closures_no_es_corte(self):
        a = {a.id: a for a in dgt.parsear(XML, CAJA, AHORA)}
        self.assertNotIn("Corte", a["dgt-9004"].etiquetas)


class TestMensajes(unittest.TestCase):
    def test_escapa_html_y_botones(self):
        a = {a.id: a for a in dgt.parsear(XML, CAJA, AHORA)}["dgt-9001"]
        texto, botones = mensajes.formatear(a, AHORA)
        self.assertIn("&lt;varios&gt; vehículos &amp; heridos", texto)
        self.assertNotIn("<varios>", texto)
        self.assertIn("🕒 Desde las 13:25", texto)
        self.assertTrue(texto.startswith("💥 <b>Accidente</b> · A-2"))
        self.assertEqual(botones[1][1], "https://obraseincidenciaszaragoza.es/#dgt-9001")
        self.assertIn("maps?q=41.6402,-0.8901", botones[0][1])

    def test_no_repite_comentario_igual_a_la_causa(self):
        a = dgt.Aviso("dgt-1", frozenset({"Vehículo detenido"}), "Vehículo detenido", "A-23", "", "Vehículo detenido", None, 41.6, -0.9)
        self.assertNotIn("<i>", mensajes.formatear(a, AHORA)[0])


class TestLogica(unittest.TestCase):
    def test_primera_ejecucion_no_inunda(self):
        e, s = est.vacio(), Sender()
        self.assertEqual(nucleo.ejecutar(cfg(), lambda: XML, e, s, AHORA), 0)
        self.assertEqual(len(s.enviados), 1)
        self.assertIn("activo", s.enviados[0][0])
        self.assertTrue(e["inicializado"])
        self.assertEqual(set(e["avisados"]), {"dgt-9001", "dgt-9002", "dgt-9003"})

    def test_solo_avisa_de_lo_nuevo(self):
        e = est.vacio()
        nucleo.ejecutar(cfg(), lambda: xml_con(9001), e, Sender(), AHORA)
        s = Sender()
        nucleo.ejecutar(cfg(), lambda: XML, e, s, AHORA + datetime.timedelta(minutes=5))
        self.assertEqual(len(s.enviados), 1)
        self.assertIn("Accidente", s.enviados[0][0])
        s2 = Sender()
        nucleo.ejecutar(cfg(), lambda: XML, e, s2, AHORA + datetime.timedelta(minutes=10))
        self.assertEqual(s2.enviados, [])

    def test_no_avisa_de_obras_ni_de_lo_que_no_se_pide(self):
        e = est.vacio()
        nucleo.ejecutar(cfg(avisar=["Accidente"]), lambda: xml_con(9001), e, Sender(), AHORA)
        s = Sender()
        nucleo.ejecutar(cfg(avisar=["Accidente"]), lambda: XML, e, s, AHORA)
        self.assertEqual(len(s.enviados), 1)

    def test_reaparicion_dentro_de_la_ventana_no_repite(self):
        e = est.vacio()
        nucleo.ejecutar(cfg(), lambda: XML, e, Sender(), AHORA)
        nucleo.ejecutar(cfg(), lambda: xml_con(9003), e, Sender(), AHORA + datetime.timedelta(minutes=5))
        self.assertIsNotNone(e["avisados"]["dgt-9003"]["fuera"])
        s = Sender()
        nucleo.ejecutar(cfg(), lambda: XML, e, s, AHORA + datetime.timedelta(hours=2))
        self.assertEqual(s.enviados, [])
        self.assertIsNone(e["avisados"]["dgt-9003"]["fuera"])

    def test_se_olvida_pasada_la_ventana_y_vuelve_a_avisar(self):
        e = est.vacio()
        nucleo.ejecutar(cfg(), lambda: XML, e, Sender(), AHORA)
        t = AHORA
        for _ in range(2):  # primera pasada marca "fuera"; la segunda, 7 h después, lo olvida
            nucleo.ejecutar(cfg(), lambda: xml_con(9003), e, Sender(), t)
            t += datetime.timedelta(hours=7)
        self.assertNotIn("dgt-9003", e["avisados"])
        s = Sender()
        nucleo.ejecutar(cfg(), lambda: XML, e, s, t)
        self.assertEqual(len(s.enviados), 1)

    def test_tope_de_mensajes_y_resumen(self):
        e = est.vacio()
        nucleo.ejecutar(cfg(), lambda: xml_con(9001, 9002, 9003), e, Sender(), AHORA)
        s = Sender()
        nucleo.ejecutar(cfg(max_mensajes_por_ejecucion=1), lambda: XML, e, s, AHORA)
        self.assertEqual(len(s.enviados), 2)
        self.assertIn("Accidente", s.enviados[0][0])  # el más grave va primero
        self.assertIn("2 avisos más", s.enviados[1][0])
        self.assertEqual(set(e["avisados"]), {"dgt-9001", "dgt-9002", "dgt-9003"})

    def test_si_telegram_falla_se_reintenta_en_la_siguiente(self):
        e = est.vacio()
        nucleo.ejecutar(cfg(), lambda: xml_con(9001), e, Sender(), AHORA)
        self.assertEqual(nucleo.ejecutar(cfg(), lambda: XML, e, Sender(falla=True), AHORA), 1)
        self.assertNotIn("dgt-9001", e["avisados"])  # sin registrar: se reintenta
        s = Sender()
        self.assertEqual(nucleo.ejecutar(cfg(), lambda: XML, e, s, AHORA), 0)
        self.assertEqual(len(s.enviados), 1)
        self.assertIn("dgt-9001", e["avisados"])

    def test_fallo_inicial_de_telegram_no_inicializa(self):
        e = est.vacio()
        self.assertEqual(nucleo.ejecutar(cfg(), lambda: XML, e, Sender(falla=True), AHORA), 1)
        self.assertFalse(e["inicializado"])

    def test_caida_de_la_dgt_alerta_una_vez_y_avisa_al_recuperarse(self):
        e = est.vacio()
        nucleo.ejecutar(cfg(), lambda: XML, e, Sender(), AHORA)

        def caida():
            raise dgt.ErrorDGT("caída simulada")

        s = Sender()
        for _ in range(8):
            self.assertEqual(nucleo.ejecutar(cfg(fallos_dgt_para_alertar=3), caida, e, s, AHORA), 0)
        self.assertEqual(len(s.enviados), 1)
        self.assertIn("La DGT no responde", s.enviados[0][0])
        nucleo.ejecutar(cfg(), lambda: XML, e, s, AHORA)
        self.assertIn("vuelve a responder", s.enviados[1][0])
        self.assertEqual((e["fallos_dgt"], e["alerta_dgt_enviada"]), (0, False))

    def test_caida_breve_no_alerta(self):
        e = est.vacio()
        nucleo.ejecutar(cfg(), lambda: XML, e, Sender(), AHORA)
        s = Sender()
        nucleo.ejecutar(cfg(), lambda: (_ for _ in ()).throw(dgt.ErrorDGT("x")), e, s, AHORA)
        nucleo.ejecutar(cfg(), lambda: XML, e, s, AHORA)
        self.assertEqual(s.enviados, [])


class TestTelegram(unittest.TestCase):
    def test_el_token_no_se_filtra_en_los_errores(self):
        boom = requests.ConnectionError("HTTPSConnectionPool: /botSECRETO123/sendMessage")
        with mock.patch("bot.telegram.requests.post", side_effect=boom), mock.patch("bot.telegram.time.sleep"):
            with self.assertRaises(ErrorTelegram) as cm:
                telegram.enviar("SECRETO123", "1", "hola")
        self.assertNotIn("SECRETO123", str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)

    def test_error_de_api_incluye_descripcion(self):
        r = mock.Mock(status_code=400, ok=False)
        r.json.return_value = {"description": "Bad Request: chat not found"}
        with mock.patch("bot.telegram.requests.post", return_value=r):
            with self.assertRaisesRegex(ErrorTelegram, "chat not found"):
                telegram.enviar("t", "1", "hola")

    def test_envia_html_y_botones(self):
        r = mock.Mock(status_code=200, ok=True)
        with mock.patch("bot.telegram.requests.post", return_value=r) as post:
            telegram.enviar("t", "42", "hola", [("Mapa", "https://x")])
        datos = post.call_args.kwargs["data"]
        self.assertEqual((datos["chat_id"], datos["parse_mode"]), ("42", "HTML"))
        self.assertIn("https://x", datos["reply_markup"])


class TestEstado(unittest.TestCase):
    def test_guardar_solo_si_cambia(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "data", "estado.json")
            e = est.cargar(ruta)
            self.assertTrue(est.guardar(ruta, e))
            self.assertFalse(est.guardar(ruta, est.cargar(ruta)))


if __name__ == "__main__":
    unittest.main()
