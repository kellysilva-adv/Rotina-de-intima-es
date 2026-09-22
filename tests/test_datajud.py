"""Testes do adaptador do DataJud, com resposta simulada da API.

Nao ha rede aqui: a sessao e substituida por um dublê que devolve um payload
no formato que a API Publica do DataJud retorna (Elasticsearch).
"""

import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core.adaptadores.datajud import AdaptadorDataJud, CHAVE_PUBLICA_PADRAO
from core.modelo import Processo

TRIBUNAL = {
    "id": "trf1",
    "nome": "TRF1 - Justica Federal 1a Regiao",
    "sistema": "pje",
    "url_base": "https://pje1g.trf1.jus.br/pje/",
    "alias_datajud": "api_publica_trf1",
    "secoes": [],
}


def _agora_menos(dias: int) -> str:
    return (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class RespostaFalsa:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class SessaoFalsa:
    """Registra o que foi enviado e devolve o payload combinado."""

    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.chamadas = []
        self.mtls_ativo = False

    def post(self, url, data=None, headers=None, **kwargs):
        self.chamadas.append({"url": url, "corpo": json.loads(data), "headers": headers})
        return RespostaFalsa(self.payload, self.status)


def _payload(movimentos):
    return {
        "hits": {
            "total": {"value": 1},
            "hits": [{
                "_source": {
                    "numeroProcesso": "50012345620244013600",
                    "classe": {"codigo": 1116, "nome": "Procedimento Comum Civel"},
                    "orgaoJulgador": {"nome": "1a Vara Federal de Minacu/GO"},
                    "tribunal": "TRF1",
                    "grau": "G1",
                    "movimentos": movimentos,
                }
            }],
        }
    }


class TestDataJud(unittest.TestCase):
    def setUp(self):
        self.processo = Processo(
            numero="50012345620244013600", tribunal_id="trf1",
            cliente="Maria das Dores Exemplo",
            orgao_julgador="Subsecao de Uruacu/GO",
        )

    def test_endpoint_montado_com_alias(self):
        adaptador = AdaptadorDataJud(TRIBUNAL, SessaoFalsa(_payload([])))
        self.assertEqual(
            adaptador.endpoint,
            "https://api-publica.datajud.cnj.jus.br/api_publica_trf1/_search",
        )

    def test_header_de_autorizacao(self):
        sessao = SessaoFalsa(_payload([]))
        AdaptadorDataJud(TRIBUNAL, sessao).varrer([self.processo])
        cabecalho = sessao.chamadas[0]["headers"]["Authorization"]
        self.assertTrue(cabecalho.startswith("APIKey "))
        self.assertIn(CHAVE_PUBLICA_PADRAO, cabecalho)

    def test_chave_do_env_sobrepoe_a_padrao(self):
        sessao = SessaoFalsa(_payload([]))
        AdaptadorDataJud(TRIBUNAL, sessao, chave_api="MINHA_CHAVE").varrer([self.processo])
        self.assertEqual(sessao.chamadas[0]["headers"]["Authorization"], "APIKey MINHA_CHAVE")

    def test_consulta_em_lote_nao_faz_uma_requisicao_por_processo(self):
        sessao = SessaoFalsa(_payload([]))
        processos = [
            Processo(numero=f"500123456202440136{i:02d}", tribunal_id="trf1")
            for i in range(30)
        ]
        AdaptadorDataJud(TRIBUNAL, sessao).varrer(processos)
        self.assertEqual(len(sessao.chamadas), 1)
        self.assertEqual(len(sessao.chamadas[0]["corpo"]["query"]["terms"]["numeroProcesso"]), 30)

    def test_extrai_movimento_recente(self):
        sessao = SessaoFalsa(_payload([
            {"codigo": 85, "nome": "Juntada de Peticao", "dataHora": _agora_menos(3),
             "complementosTabelados": [
                 {"nome": "tipo_peticao", "descricao": "Tipo de peticao", "valor": "Contestacao"}
             ]},
        ]))
        resultado = AdaptadorDataJud(TRIBUNAL, sessao).varrer([self.processo], desde_dias=15)
        self.assertTrue(resultado.sucesso)
        self.assertEqual(len(resultado.movimentacoes), 1)
        mov = resultado.movimentacoes[0]
        self.assertEqual(mov.descricao, "Juntada de Peticao")
        self.assertEqual(mov.codigo_movimento, "85")
        self.assertEqual(mov.cliente, "Maria das Dores Exemplo")
        self.assertEqual(mov.fonte, "datajud")
        self.assertIn("Contestacao", mov.complemento)

    def test_descarta_movimento_fora_da_janela(self):
        # O DataJud devolve o historico inteiro; so o recente interessa.
        sessao = SessaoFalsa(_payload([
            {"codigo": 26, "nome": "Distribuicao", "dataHora": _agora_menos(400)},
            {"codigo": 85, "nome": "Juntada de Peticao", "dataHora": _agora_menos(2)},
        ]))
        resultado = AdaptadorDataJud(TRIBUNAL, sessao).varrer([self.processo], desde_dias=15)
        self.assertEqual(len(resultado.movimentacoes), 1)
        self.assertEqual(resultado.movimentacoes[0].descricao, "Juntada de Peticao")

    def test_processo_ausente_vira_alerta_e_nao_erro_silencioso(self):
        sessao = SessaoFalsa({"hits": {"total": {"value": 0}, "hits": []}})
        resultado = AdaptadorDataJud(TRIBUNAL, sessao).varrer([self.processo])
        self.assertTrue(any("segredo de justica" in e for e in resultado.erros))

    def test_chave_recusada_e_reportada_com_instrucao(self):
        sessao = SessaoFalsa({"error": "unauthorized"}, status=401)
        resultado = AdaptadorDataJud(TRIBUNAL, sessao).varrer([self.processo])
        self.assertFalse(resultado.sucesso)
        self.assertTrue(any("DATAJUD_API_KEY" in e for e in resultado.erros))

    def test_tribunal_sem_alias_nao_tenta_consultar(self):
        sem_alias = dict(TRIBUNAL, alias_datajud="")
        resultado = AdaptadorDataJud(sem_alias, SessaoFalsa(_payload([]))).varrer([self.processo])
        self.assertFalse(resultado.sucesso)
        self.assertIn("alias_datajud", resultado.mensagem)

    def test_movimento_do_datajud_alimenta_o_classificador(self):
        """O nome TPU do movimento precisa casar com as regras de prazo."""
        from core.classificador import Classificador
        from core.prazos import CalendarioForense, RAMO_FEDERAL

        sessao = SessaoFalsa(_payload([
            {"codigo": 85, "nome": "Juntada de Peticao", "dataHora": _agora_menos(12),
             "complementosTabelados": [
                 {"nome": "tipo", "descricao": "Tipo", "valor": "Contestacao do INSS"}
             ]},
        ]))
        resultado = AdaptadorDataJud(TRIBUNAL, sessao).varrer([self.processo], desde_dias=15)
        classificador = Classificador(RAIZ / "config" / "regras_prazos.json")
        prazo = classificador.avaliar(
            resultado.movimentacoes[0], CalendarioForense(RAMO_FEDERAL)
        )
        self.assertIsNotNone(prazo)
        self.assertIn("REPLICA", prazo.tarefa)


if __name__ == "__main__":
    unittest.main(verbosity=2)
