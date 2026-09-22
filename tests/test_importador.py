"""Testes do importador da planilha de controle do escritorio."""

import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core.importador import importar_tabela, tribunal_por_subsecao, tribunal_por_url
from core.modelo import digito_verificador_valido

TRIBUNAIS = json.loads(
    (RAIZ / "config" / "tribunais.json").read_text(encoding="utf-8")
)["tribunais"]

PLANILHA = """| CLIENTES ONLINE - PREVIDENCIARIO |  |  |  |  |
| :-: | :-: | :-: | :-: | :-: |
| NUMERO PROCESSO | NOME DO CLIENTE | FASE PROCESSUAL | LINK | INTIMACOES |
| 1018795-96.2024.4.01.3600 | ELISA EXEMPLO | Redistribuido | https://pje1g.trf1.jus.br/ | OK |
| 5996029-21.2024.8.09.0103 | LUANA EXEMPLO | Protocolado PROJUDI | https://projudi.tjgo.jus.br/ | OK |
| 1018795-96.2024.4.01.3600 | ELISA EXEMPLO | Contestacao apresentada - IMPUGNAR | | OK |
| [merged] TJSP ESAJ (Verificado) |  |  |  |  |
| 1019277-49.2024.8.26.0032 | JOSE EXEMPLO | Aguardando | | OK |
| 0002141-80.2025.8.16.0038 | ANDREIA EXEMPLO | Perito inerte | senha: Kelly@2412 | OK |
| 1234567-89.2024.4.01.9999 | NUMERO ERRADO | - | | |
"""


class TestImportador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = importar_tabela(PLANILHA, TRIBUNAIS)

    def test_le_os_processos_validos(self):
        numeros = {p["numero"] for p in self.r.processos}
        self.assertIn("1018795-96.2024.4.01.3600", numeros)
        self.assertIn("5996029-21.2024.8.09.0103", numeros)

    def test_ignora_cabecalho_e_separador(self):
        for p in self.r.processos:
            self.assertNotIn("NOME DO CLIENTE", p["cliente"])

    def test_deduz_tribunal_do_numero(self):
        por_numero = {p["numero"]: p for p in self.r.processos}
        self.assertEqual(por_numero["1018795-96.2024.4.01.3600"]["tribunal_id"], "trf1")
        self.assertEqual(por_numero["5996029-21.2024.8.09.0103"]["tribunal_id"], "tjgo")

    def test_unifica_repetido_ficando_com_a_linha_mais_rica(self):
        iguais = [p for p in self.r.processos if p["numero"] == "1018795-96.2024.4.01.3600"]
        self.assertEqual(len(iguais), 1)
        self.assertIn("IMPUGNAR", iguais[0]["observacao"])
        self.assertEqual(self.r.duplicados, 1)

    def test_recusa_numero_com_digito_verificador_errado(self):
        numeros = {p["numero"] for p in self.r.processos}
        self.assertNotIn("1234567-89.2024.4.01.9999", numeros)
        self.assertEqual(len(self.r.invalidos), 1)

    def test_senha_nao_entra_no_cadastro(self):
        despejo = json.dumps(self.r.processos, ensure_ascii=False)
        self.assertNotIn("Kelly@2412", despejo)
        self.assertEqual(len(self.r.senhas_descartadas), 1)

    def test_captura_cliente_e_fase(self):
        por_numero = {p["numero"]: p for p in self.r.processos}
        self.assertEqual(por_numero["5996029-21.2024.8.09.0103"]["cliente"], "LUANA EXEMPLO")
        self.assertIn("PROJUDI", por_numero["5996029-21.2024.8.09.0103"]["observacao"])


class TestDesempate(unittest.TestCase):
    def test_subsecao_separa_parana_de_santa_catarina(self):
        # TRF4: 70xx e o Parana, 72xx e Santa Catarina.
        self.assertEqual(
            tribunal_por_subsecao("5008942-66.2024.4.04.7009", ["jfsc", "jfpr"], TRIBUNAIS),
            ["jfpr"],
        )
        self.assertEqual(
            tribunal_por_subsecao("5007555-98.2024.4.04.7208", ["jfsc", "jfpr"], TRIBUNAIS),
            ["jfsc"],
        )

    def test_subsecao_separa_rio_de_janeiro_de_espirito_santo(self):
        self.assertEqual(
            tribunal_por_subsecao("5001234-56.2024.4.02.5101", ["jfrj", "jfes"], TRIBUNAIS),
            ["jfrj"],
        )
        self.assertEqual(
            tribunal_por_subsecao("5001234-56.2024.4.02.5001", ["jfrj", "jfes"], TRIBUNAIS),
            ["jfes"],
        )

    def test_subsecao_do_rio_grande_do_sul_nao_casa_com_nenhuma_cadastrada(self):
        # 71xx e o RS, que nao esta entre os 26 - tem de sobrar vazio, nao chutar.
        self.assertEqual(
            tribunal_por_subsecao("5001164-83.2026.4.04.7103", ["jfsc", "jfpr"], TRIBUNAIS), []
        )

    def test_url_da_linha_identifica_o_tribunal(self):
        self.assertIn("tjgo", tribunal_por_url("veja https://projudi.tjgo.jus.br/ ok", TRIBUNAIS))
        self.assertEqual(tribunal_por_url("sem link aqui", TRIBUNAIS), [])


class TestDigitoVerificador(unittest.TestCase):
    def test_aceita_numero_real(self):
        for n in ("1018795-96.2024.4.01.3600", "5996029-21.2024.8.09.0103",
                  "0002141-80.2025.8.16.0038"):
            self.assertTrue(digito_verificador_valido(n), n)

    def test_recusa_digito_trocado(self):
        self.assertFalse(digito_verificador_valido("1018795-97.2024.4.01.3600"))

    def test_recusa_numero_incompleto(self):
        self.assertFalse(digito_verificador_valido("1018795-96.2024"))
        self.assertFalse(digito_verificador_valido(""))

    def test_aceita_separador_trocado(self):
        # Erro de digitacao real da planilha: traco no lugar do ponto.
        self.assertTrue(digito_verificador_valido("1008798-31-2020.4.01.3600"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
