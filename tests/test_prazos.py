"""Testes do calculo de prazos e da classificacao juridica.

Rodar:  python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core.classificador import Classificador, URGENCIA_CRITICA, URGENCIA_BAIXA
from core.modelo import Movimentacao, formatar_cnj, normalizar_cnj
from core.prazos import (
    RAMO_ESTADUAL,
    RAMO_FEDERAL,
    CalendarioForense,
    domingo_de_pascoa,
    em_suspensao_cpc220,
    parse_data,
    termo_inicial_dje,
    termo_inicial_intimacao_eletronica,
)


class TestCalendario(unittest.TestCase):
    def setUp(self):
        self.estadual = CalendarioForense(RAMO_ESTADUAL)
        self.federal = CalendarioForense(RAMO_FEDERAL)

    def test_pascoa(self):
        # Datas conferiveis em qualquer calendario.
        self.assertEqual(domingo_de_pascoa(2024), date(2024, 3, 31))
        self.assertEqual(domingo_de_pascoa(2025), date(2025, 4, 20))
        self.assertEqual(domingo_de_pascoa(2026), date(2026, 4, 5))

    def test_feriados_nacionais_nao_sao_uteis(self):
        for d in (date(2025, 9, 7), date(2025, 5, 1), date(2025, 12, 25)):
            self.assertFalse(self.estadual.e_dia_util(d), d)

    def test_fim_de_semana(self):
        self.assertFalse(self.estadual.e_dia_util(date(2025, 9, 20)))  # sabado
        self.assertFalse(self.estadual.e_dia_util(date(2025, 9, 21)))  # domingo
        self.assertTrue(self.estadual.e_dia_util(date(2025, 9, 22)))   # segunda

    def test_carnaval_nao_e_util(self):
        # Carnaval 2025: 03 e 04/03 (Pascoa em 20/04).
        self.assertFalse(self.estadual.e_dia_util(date(2025, 3, 3)))
        self.assertFalse(self.estadual.e_dia_util(date(2025, 3, 4)))

    def test_quarta_de_cinzas_e_util(self):
        # Expediente reduzido, mas protocolo eletronico funciona - conta como util.
        self.assertTrue(self.estadual.e_dia_util(date(2025, 3, 5)))

    def test_suspensao_cpc220(self):
        self.assertTrue(em_suspensao_cpc220(date(2025, 12, 20)))
        self.assertTrue(em_suspensao_cpc220(date(2026, 1, 20)))
        self.assertFalse(em_suspensao_cpc220(date(2025, 12, 19)))
        self.assertFalse(em_suspensao_cpc220(date(2026, 1, 21)))
        self.assertFalse(self.estadual.e_dia_util(date(2025, 12, 29)))

    def test_feriado_forense_federal(self):
        # 08/12 e feriado na JF (Lei 5.010/66), mas nao na Justica Estadual.
        self.assertFalse(self.federal.e_dia_util(date(2026, 12, 8)))
        self.assertTrue(self.estadual.e_dia_util(date(2026, 12, 8)))

    def test_feriado_local_cadastrado(self):
        com_local = CalendarioForense(RAMO_ESTADUAL, feriados_extras=["2025-10-24"])
        self.assertTrue(self.estadual.e_dia_util(date(2025, 10, 24)))
        self.assertFalse(com_local.e_dia_util(date(2025, 10, 24)))


class TestContagem(unittest.TestCase):
    """CPC art. 224: exclui o dia do comeco, inclui o do vencimento."""

    def setUp(self):
        self.cal = CalendarioForense(RAMO_ESTADUAL)

    def test_publicacao_e_termo_inicial(self):
        # Disponibilizado na sexta 19/09/2025.
        publicacao, termo = termo_inicial_dje(self.cal, date(2025, 9, 19))
        self.assertEqual(publicacao, date(2025, 9, 22))  # 1o dia util seguinte
        self.assertEqual(termo, date(2025, 9, 23))       # dia 1 da contagem

    def test_prazo_15_dias_uteis(self):
        # Dia 1 = 23/09/2025 (terca). Dia 15 = 13/10/2025 (segunda).
        self.assertEqual(
            self.cal.vencimento_dias_uteis(date(2025, 9, 23), 15), date(2025, 10, 13)
        )

    def test_prazo_5_dias_uteis(self):
        # 23, 24, 25, 26 e 29/09 (27 e 28 sao fim de semana).
        self.assertEqual(
            self.cal.vencimento_dias_uteis(date(2025, 9, 23), 5), date(2025, 9, 29)
        )

    def test_prazo_1_dia_util_vence_no_proprio_termo(self):
        self.assertEqual(
            self.cal.vencimento_dias_uteis(date(2025, 9, 23), 1), date(2025, 9, 23)
        )

    def test_termo_inicial_caindo_em_feriado_e_prorrogado(self):
        # 07/09/2025 e domingo; 08/09 (segunda) e o primeiro dia util.
        self.assertEqual(
            self.cal.vencimento_dias_uteis(date(2025, 9, 7), 1), date(2025, 9, 8)
        )

    def test_suspensao_de_fim_de_ano_empurra_o_vencimento(self):
        # Dia 1 em 18/12/2025; a contagem para de 20/12 a 20/01 e volta em 21/01.
        limite = self.cal.vencimento_dias_uteis(date(2025, 12, 18), 5)
        self.assertGreater(limite, date(2026, 1, 20))

    def test_dias_corridos_prorrogam_vencimento_em_dia_nao_util(self):
        # 10 dias corridos a partir de sexta 19/09/2025 cairia em domingo 28/09.
        limite = self.cal.vencimento_dias_corridos(date(2025, 9, 19), 10)
        self.assertTrue(self.cal.e_dia_util(limite))
        self.assertEqual(limite, date(2025, 9, 29))

    def test_dias_uteis_entre_negativo_quando_vencido(self):
        self.assertLess(self.cal.dias_uteis_entre(date(2025, 10, 1), date(2025, 9, 25)), 0)
        self.assertEqual(self.cal.dias_uteis_entre(date(2025, 9, 22), date(2025, 9, 22)), 0)

    def test_intimacao_eletronica_presume_decimo_dia(self):
        intimacao, termo = termo_inicial_intimacao_eletronica(self.cal, date(2025, 9, 1))
        self.assertEqual(intimacao, date(2025, 9, 11))
        self.assertEqual(termo, date(2025, 9, 12))

    def test_intimacao_eletronica_com_consulta_registrada(self):
        intimacao, termo = termo_inicial_intimacao_eletronica(
            self.cal, date(2025, 9, 1), data_consulta=date(2025, 9, 3)
        )
        self.assertEqual(intimacao, date(2025, 9, 3))
        self.assertEqual(termo, date(2025, 9, 4))


class TestClassificador(unittest.TestCase):
    def setUp(self):
        self.c = Classificador(RAIZ / "config" / "regras_prazos.json")
        self.cal = CalendarioForense(RAMO_FEDERAL)
        self.hoje = date(2025, 10, 10)

    def _mov(self, texto, data="2025-09-15"):
        return Movimentacao(
            processo="50012345620244013600", tribunal_id="trf1",
            tribunal_nome="TRF1", sistema="pje",
            descricao=texto, data_movimentacao=data,
        )

    def test_origem_parte_contraria(self):
        self.assertEqual(
            self.c.detectar_origem(self._mov("Contestacao apresentada pelo INSS")),
            "Parte Contraria",
        )

    def test_origem_ministerio_publico(self):
        self.assertEqual(
            self.c.detectar_origem(self._mov("Parecer do Ministerio Publico Federal")),
            "Ministerio Publico",
        )

    def test_origem_tribunal(self):
        self.assertEqual(
            self.c.detectar_origem(self._mov("Despacho de mero expediente")),
            "Tribunal / Juizo",
        )

    def test_peticao_propria_nao_gera_tarefa(self):
        mov = self._mov("Juntada de peticao pelo autor - replica apresentada")
        self.assertIsNone(self.c.avaliar(mov, self.cal, hoje=self.hoje))

    def test_prazo_explicito_vence_a_regra_padrao(self):
        mov = self._mov("Intimacao sobre o laudo pericial, no prazo de 10 (dez) dias")
        prazo = self.c.avaliar(mov, self.cal, hoje=self.hoje)
        self.assertEqual(prazo.dias_prazo, 10)
        self.assertEqual(prazo.fundamento, "Prazo fixado no proprio ato")

    def test_prazo_explicito_em_dias_corridos(self):
        mov = self._mov("Manifeste-se no prazo de 30 dias corridos")
        prazo = self.c.avaliar(mov, self.cal, hoje=self.hoje)
        self.assertEqual((prazo.dias_prazo, prazo.contagem), (30, "corridos"))

    def test_numero_absurdo_nao_vira_prazo(self):
        self.assertIsNone(self.c.prazo_explicito("prazo de 9999 dias"))

    def test_laudo_social_nao_vira_laudo_medico(self):
        mov = self._mov("Juntada de laudo social - estudo social BPC/LOAS")
        prazo = self.c.avaliar(mov, self.cal, hoje=self.hoje)
        self.assertIn("SOCIAL", prazo.tarefa)

    def test_movimentacao_sem_data_nao_inventa_prazo(self):
        mov = self._mov("Contestacao do INSS", data="")
        prazo = self.c.avaliar(mov, self.cal, hoje=self.hoje)
        self.assertIsNone(prazo.data_limite)
        self.assertEqual(prazo.confianca, "baixa")

    def test_urgencia_por_dias_restantes(self):
        self.assertEqual(self.c.classificar_urgencia(0), URGENCIA_CRITICA)
        self.assertEqual(self.c.classificar_urgencia(-3), URGENCIA_CRITICA)
        self.assertEqual(self.c.classificar_urgencia(30), URGENCIA_BAIXA)


class TestModelo(unittest.TestCase):
    def test_formatar_cnj(self):
        self.assertEqual(
            formatar_cnj("50012345620244013600"), "5001234-56.2024.4.01.3600"
        )

    def test_normalizar_cnj(self):
        self.assertEqual(
            normalizar_cnj("5001234-56.2024.4.01.3600"), "50012345620244013600"
        )

    def test_cnj_invalido_devolve_original(self):
        self.assertEqual(formatar_cnj("123"), "123")

    def test_parse_data_formatos_de_tribunal(self):
        self.assertEqual(parse_data("20250918143000"), date(2025, 9, 18))
        self.assertEqual(parse_data("18/09/2025"), date(2025, 9, 18))
        self.assertEqual(parse_data("2025-09-18T14:30:00"), date(2025, 9, 18))
        self.assertIsNone(parse_data(""))
        self.assertIsNone(parse_data("nao e data"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
