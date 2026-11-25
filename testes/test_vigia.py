import unittest

import vigia

S = {"id": "amelie", "nome": "AMELIE", "ping": "https://exemplo.invalid/ping"}
T0 = 1_800_000_000.0


class Decidir(unittest.TestCase):
    def test_uma_falha_nao_avisa(self):
        novo, avisos = vigia.decidir(S, {}, False, "sem resposta", None, T0)
        self.assertEqual(avisos, [])
        self.assertEqual((novo["falhas"], novo["fora_desde"], novo["avisado_em"]), (1, T0, None))

    def test_segunda_falha_avisa_uma_vez(self):
        a1, _ = vigia.decidir(S, {}, False, "sem resposta", None, T0)
        a2, avisos = vigia.decidir(S, a1, False, "HTTP 500", None, T0 + 300)
        self.assertEqual([(a["tipo"], a["texto"]) for a in avisos], [("fora", "Fora do ar (HTTP 500).")])
        a3, avisos = vigia.decidir(S, a2, False, "HTTP 500", None, T0 + 600)
        self.assertEqual(avisos, [])
        self.assertEqual(a3["fora_desde"], T0)

    def test_lembra_depois_de_seis_horas(self):
        ant = {"falhas": 5, "fora_desde": T0, "avisado_em": T0 + 300}
        _, avisos = vigia.decidir(S, ant, False, "sem conexão", None, T0 + 300 + 6 * 3600)
        self.assertEqual(avisos[0]["texto"], "Continua fora do ar há 6 h 5 min.")

    def test_voltou_so_se_tinha_avisado(self):
        _, avisos = vigia.decidir(S, {"falhas": 1, "fora_desde": T0, "avisado_em": None}, True, "ok", None, T0 + 300)
        self.assertEqual(avisos, [])
        novo, avisos = vigia.decidir(S, {"falhas": 4, "fora_desde": T0, "avisado_em": T0 + 300}, True, "ok", None, T0 + 1500)
        self.assertEqual(avisos[0]["texto"], "Voltou ao ar. Ficou fora por cerca de 25 min.")
        self.assertEqual((novo["falhas"], novo["fora_desde"], novo["avisado_em"]), (0, None, None))

    def test_certificado_avisa_em_cada_marco_uma_vez(self):
        e, avisos = vigia.decidir(S, {}, True, "ok", 30, T0)
        self.assertEqual((avisos, e["cert_avisado"]), ([], None))
        e, avisos = vigia.decidir(S, e, True, "ok", 7, T0)
        self.assertEqual(avisos[0]["texto"], "O certificado do site vence em 7 dias.")
        e, avisos = vigia.decidir(S, e, True, "ok", 5, T0)
        self.assertEqual(avisos, [])
        e, avisos = vigia.decidir(S, e, True, "ok", 3, T0)
        self.assertEqual(avisos[0]["texto"], "O certificado do site vence em 3 dias.")
        e, avisos = vigia.decidir(S, e, True, "ok", 1, T0)
        self.assertEqual(avisos[0]["texto"], "O certificado do site vence amanhã.")
        e, avisos = vigia.decidir(S, e, True, "ok", 0, T0)
        self.assertEqual(avisos, [])
        e, _ = vigia.decidir(S, e, True, "ok", 89, T0)
        self.assertIsNone(e["cert_avisado"])

    def test_sem_leitura_do_certificado_mantem_o_marco(self):
        e, _ = vigia.decidir(S, {"cert_avisado": 3}, True, "ok", None, T0)
        self.assertEqual(e["cert_avisado"], 3)

    def test_duracao(self):
        self.assertEqual([vigia.duracao(5), vigia.duracao(60), vigia.duracao(135)], ["5 min", "1 h", "2 h 15 min"])

    def test_tokens_so_no_formato(self):
        import os
        os.environ["VIGIA_PUSH_TOKENS"] = "ExponentPushToken[abc], lixo ,\nExpoPushToken[def]"
        self.assertEqual(vigia.tokens_do_ambiente(), ["ExponentPushToken[abc]", "ExpoPushToken[def]"])


class Saude(unittest.TestCase):
    V = {"id": "servidor", "nome": "Servidor da FERGO", "ping": "https://exemplo.invalid/s.json", "tipo": "saude"}

    def test_boletim_bom(self):
        self.assertEqual(vigia.ler_saude(b'{"ok": true, "gerado": %d, "problemas": []}' % T0, T0 + 600), (True, "ok"))

    def test_boletim_com_problema_diz_qual(self):
        corpo = b'{"ok": false, "gerado": %d, "problemas": ["backup externo", "disco"]}' % T0
        self.assertEqual(vigia.ler_saude(corpo, T0 + 600), (False, "backup externo, disco"))

    def test_boletim_velho_e_problema_mesmo_dizendo_ok(self):
        ok, motivo = vigia.ler_saude(b'{"ok": true, "gerado": %d}' % T0, T0 + 4 * 3600)
        self.assertEqual((ok, motivo), (False, "servidor sem se conferir há 4 h"))

    def test_boletim_quebrado(self):
        self.assertEqual(vigia.ler_saude(b"<html>", T0), (False, "boletim fora do combinado"))
        self.assertEqual(vigia.ler_saude(b'{"ok": true}', T0), (False, "boletim fora do combinado"))

    def test_textos_do_servidor(self):
        a1, _ = vigia.decidir(self.V, {}, False, "backup externo", None, T0)
        a2, avisos = vigia.decidir(self.V, a1, False, "backup externo", None, T0 + 300)
        self.assertEqual(avisos[0]["texto"], "Precisa de atenção: backup externo.")
        _, avisos = vigia.decidir(self.V, a2, True, "ok", None, T0 + 3900)
        self.assertEqual(avisos[0]["texto"], "Voltou ao normal depois de 1 h 5 min.")


if __name__ == "__main__":
    unittest.main()
