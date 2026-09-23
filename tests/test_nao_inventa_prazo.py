"""Nenhuma data pode ser calculada sem o teor do ato.

POR QUE ESTE ARQUIVO EXISTE
===========================
A rotina apresentou a uma advogada um prazo que nao existia. O processo
1004634-47.2025.4.01.3503 tinha a movimentacao "Ato ordinatorio", e todos os
expedientes dele ja estavam fechados no PJe - o ultimo prazo real vencera dois
meses antes. Mesmo assim o relatorio anunciou "01/10/2026 - 6 dias uteis".

A causa: o DataJud devolve apenas o NOME do movimento. "Ato ordinatorio" nao
diz o que foi determinado nem a quem - pode ser "abra-se vista ao INSS", que
nao gera prazo algum para o escritorio. Havia uma regra generica que casava
esse nome e aplicava 5 dias por analogia ao art. 218, par. 3o do CPC.

Prazo inventado em relatorio de advogado e pior que relatorio nenhum: enche a
pauta de ruido, e quando o ruido vira rotina o prazo verdadeiro passa batido
no meio dele.
"""

import sys
import unittest
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core.classificador import Classificador, URGENCIA_VERIFICAR, separar
from core.modelo import Movimentacao
from core.prazos import CalendarioForense, RAMO_FEDERAL

# Nomes de movimento que o DataJud devolve sem nenhum teor.
SO_O_NOME = [
    "Ato ordinatorio",
    "Ato ordinatorio praticado",
    "Despacho",
    "Decisao",
    "Intimacao",
    "Expedicao de documento",
    "Juntada de peticao",
]


class TestNaoInventaPrazo(unittest.TestCase):
    def setUp(self):
        self.c = Classificador(RAIZ / "config" / "regras_prazos.json")
        self.cal = CalendarioForense(RAMO_FEDERAL)
        self.hoje = date(2026, 9, 23)

    def _mov(self, descricao, complemento=""):
        return Movimentacao(
            processo="10046344720254013503", tribunal_id="trf1",
            tribunal_nome="TRF1 - Justica Federal 1a Regiao", sistema="pje",
            fonte="datajud", descricao=descricao, complemento=complemento,
            data_movimentacao="2026-09-14", cliente="Cliente Exemplo",
        )

    def test_movimento_sem_teor_nao_ganha_data(self):
        for nome in SO_O_NOME:
            prazo = self.c.avaliar(self._mov(nome), self.cal, hoje=self.hoje)
            if prazo is None:
                continue
            self.assertIsNone(prazo.data_limite, f"{nome} recebeu data inventada")
            self.assertEqual(prazo.urgencia, URGENCIA_VERIFICAR, nome)
            self.assertEqual(prazo.dias_prazo, 0, nome)

    def test_o_caso_real_que_motivou_a_correcao(self):
        """1004634-47.2025.4.01.3503: 'Ato ordinatorio', sem prazo aberto."""
        prazo = self.c.avaliar(self._mov("Ato ordinatorio"), self.cal, hoje=self.hoje)
        self.assertIsNotNone(prazo, "a movimentacao deve aparecer, mas sem data")
        self.assertIsNone(prazo.data_limite)
        self.assertIn("ABRIR O PROCESSO", prazo.tarefa)
        self.assertTrue(
            any("nome" in a.lower() and "teor" in a.lower() for a in prazo.alertas),
            f"o alerta precisa explicar por que nao ha data: {prazo.alertas}",
        )

    def test_movimento_com_teor_continua_gerando_data(self):
        """A correcao nao pode cegar a rotina onde ha informacao de verdade."""
        prazo = self.c.avaliar(
            self._mov("Intimacao", "Manifeste-se a parte autora no prazo de 15 dias"),
            self.cal, hoje=self.hoje,
        )
        self.assertIsNotNone(prazo.data_limite)
        self.assertEqual(prazo.dias_prazo, 15)
        self.assertNotEqual(prazo.urgencia, URGENCIA_VERIFICAR)

    def test_prazo_escrito_por_extenso_conta_como_teor(self):
        prazo = self.c.avaliar(
            self._mov("Despacho - manifeste-se no prazo de 5 dias"), self.cal, hoje=self.hoje
        )
        self.assertIsNotNone(prazo.data_limite)
        self.assertEqual(prazo.dias_prazo, 5)

    def test_contestacao_com_teor_gera_replica(self):
        prazo = self.c.avaliar(
            self._mov("Juntada de peticao", "Contestacao apresentada pelo INSS - PGF"),
            self.cal, hoje=self.hoje,
        )
        self.assertIsNotNone(prazo.data_limite)
        self.assertIn("REPLICA", prazo.tarefa)


class TestSeparacaoNoRelatorio(unittest.TestCase):
    """As duas listas nao podem sair na mesma tabela."""

    def setUp(self):
        self.c = Classificador(RAIZ / "config" / "regras_prazos.json")
        self.cal = CalendarioForense(RAMO_FEDERAL)

    def _avaliar(self, descricao, complemento=""):
        m = Movimentacao(
            processo="10046344720254013503", tribunal_id="trf1", tribunal_nome="TRF1",
            sistema="pje", fonte="datajud", descricao=descricao, complemento=complemento,
            data_movimentacao="2026-09-14",
        )
        return self.c.avaliar(m, self.cal, hoje=date(2026, 9, 23))

    def test_separa_com_data_de_a_verificar(self):
        prazos = [
            self._avaliar("Ato ordinatorio"),
            self._avaliar("Despacho"),
            self._avaliar("Intimacao", "manifeste-se no prazo de 10 dias"),
        ]
        com_data, a_verificar = separar([p for p in prazos if p])
        self.assertEqual(len(com_data), 1)
        self.assertEqual(len(a_verificar), 2)
        self.assertTrue(all(p.data_limite is not None for p in com_data))
        self.assertTrue(all(p.data_limite is None for p in a_verificar))

    def test_relatorio_nao_conta_verificar_como_prazo(self):
        from core.relatorio import gerar_markdown, gerar_html

        prazos = [p for p in (self._avaliar("Ato ordinatorio"),
                              self._avaliar("Despacho")) if p]
        md = gerar_markdown(prazos)
        self.assertIn("0** prazos com data calculada", md)
        self.assertIn("2** movimentações a verificar", md)
        self.assertIn("Movimentações a verificar", md)

        html = gerar_html(prazos)
        self.assertIn("A VERIFICAR", html.upper())
        self.assertIn("Nenhum prazo com data calculada", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
