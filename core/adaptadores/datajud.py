"""Adaptador da API Publica do DataJud (CNJ).

POR QUE ESTE ADAPTADOR EXISTE
=============================
Ele resolve o problema do login: a API Publica do DataJud **nao pede
certificado digital nem usuario e senha**. Autentica com uma chave PUBLICA
que o proprio CNJ divulga, igual para todo mundo. Roda em qualquer maquina,
inclusive dentro de um cron, sem nenhum segredo do escritorio envolvido.

O QUE ELA ENTREGA - E O QUE NAO ENTREGA
=======================================
Entrega: numero do processo, classe, assuntos, orgao julgador e a LISTA DE
MOVIMENTOS com codigo da Tabela Processual Unificada (TPU), nome e data/hora.
Isso basta para DETECTAR que houve movimentacao e de que tipo ela e.

Nao entrega: o TEXTO do despacho, da decisao ou da peticao. O DataJud guarda
metadados, nao o inteiro teor. Entao ele diz "houve uma Juntada de Peticao em
18/09", mas nao diz o que o juiz escreveu.

Tambem nao cobre processo em SEGREDO DE JUSTICA, e a alimentacao pelos
tribunais tem atraso (em regra diario, as vezes maior).

CONCLUSAO PRATICA: o DataJud e a camada de DETECCAO, que funciona nos 26
tribunais sem login. Para LER o ato, ainda e preciso abrir o processo no
sistema do tribunal - com o certificado, na maquina da advogada.

Referencia: https://datajud-wiki.cnj.jus.br/api-publica/
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from core.adaptadores.base import AdaptadorBase, ResultadoVarredura
from core.modelo import Movimentacao, Processo, normalizar_cnj

log = logging.getLogger("varredura.datajud")

URL_BASE = "https://api-publica.datajud.cnj.jus.br"

# Chave PUBLICA divulgada pelo CNJ - nao e segredo, e a mesma para todos.
# O CNJ pode troca-la a qualquer momento; a vigente fica sempre em
# https://datajud-wiki.cnj.jus.br/api-publica/acesso/
# Pode ser sobrescrita pela variavel DATAJUD_API_KEY no .env.
CHAVE_PUBLICA_PADRAO = (
    "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
)

# Tamanho do lote de processos por requisicao. A API aceita busca por varios
# numeros de uma vez, o que evita 300 requisicoes para 300 processos.
TAMANHO_LOTE = 50


def _campo(no: Any, *caminho: str, padrao: str = "") -> str:
    """Navega um dicionario aninhado sem estourar se faltar chave."""
    atual = no
    for chave in caminho:
        if not isinstance(atual, dict):
            return padrao
        atual = atual.get(chave)
    if atual is None:
        return padrao
    return str(atual)


class AdaptadorDataJud(AdaptadorBase):
    fonte = "datajud"

    def __init__(self, tribunal, sessao, chave_api: str = ""):
        super().__init__(tribunal, sessao)
        self.alias = tribunal.get("alias_datajud", "")
        self.chave = chave_api or CHAVE_PUBLICA_PADRAO

    @property
    def endpoint(self) -> str:
        return f"{URL_BASE}/{self.alias}/_search"

    def _cabecalhos(self) -> dict[str, str]:
        return {
            "Authorization": f"APIKey {self.chave}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------- consulta

    def _consultar_lote(self, numeros: list[str], tamanho: int = 200) -> list[dict[str, Any]]:
        """Busca varios processos numa requisicao so (Elasticsearch terms)."""
        consulta = {
            "size": tamanho,
            "query": {"terms": {"numeroProcesso": numeros}},
            "sort": [{"dataHoraUltimaAtualizacao": {"order": "desc"}}],
        }
        resposta = self.sessao.post(
            self.endpoint, data=json.dumps(consulta).encode("utf-8"),
            headers=self._cabecalhos(),
        )
        if resposta.status_code == 401:
            raise RuntimeError(
                "Chave do DataJud recusada (HTTP 401). O CNJ pode ter trocado a chave "
                "publica - pegue a vigente em https://datajud-wiki.cnj.jus.br/api-publica/acesso/ "
                "e ponha em DATAJUD_API_KEY no .env."
            )
        if resposta.status_code >= 400:
            raise RuntimeError(f"HTTP {resposta.status_code}: {resposta.text[:250]}")

        dados = resposta.json()
        return [h.get("_source", {}) for h in dados.get("hits", {}).get("hits", [])]

    # -------------------------------------------------------------- extracao

    def _extrair(
        self, documento: dict[str, Any], processo: Processo | None, desde: datetime
    ) -> list[Movimentacao]:
        numero = normalizar_cnj(documento.get("numeroProcesso", ""))
        orgao = _campo(documento, "orgaoJulgador", "nome")
        classe = _campo(documento, "classe", "nome")

        movs: list[Movimentacao] = []
        for m in documento.get("movimentos", []) or []:
            if not isinstance(m, dict):
                continue
            data_hora = str(m.get("dataHora", ""))

            # Janela: o DataJud devolve o historico inteiro do processo, e nos
            # so queremos o que e novo desde a ultima varredura.
            quando = self._parse_iso(data_hora)
            if quando is not None and quando < desde:
                continue

            complementos = []
            for c in m.get("complementosTabelados", []) or []:
                if isinstance(c, dict):
                    texto = c.get("descricao") or c.get("nome") or ""
                    valor = c.get("valor")
                    complementos.append(f"{texto}: {valor}" if valor not in (None, "") else str(texto))

            mov = Movimentacao(
                processo=numero,
                tribunal_id=self.id,
                tribunal_nome=self.nome,
                sistema=self.sistema,
                orgao_julgador=_campo(m, "orgaoJulgador", "nome") or orgao,
                secao=(processo.orgao_julgador if processo else "") or orgao,
                data_movimentacao=data_hora,
                codigo_movimento=str(m.get("codigo", "")),
                descricao=str(m.get("nome", "")) or classe,
                complemento=" | ".join(c for c in complementos if c),
                cliente=processo.cliente if processo else "",
                fonte=self.fonte,
                url_consulta=self.endpoint,
            )
            if self.filtrar_secao(mov):
                movs.append(mov)
        return movs

    @staticmethod
    def _parse_iso(valor: str) -> datetime | None:
        if not valor:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(valor, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(valor.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    # ---------------------------------------------------------------- varrer

    def varrer(self, processos: list[Processo], desde_dias: int = 15) -> ResultadoVarredura:
        resultado = self.novo_resultado()

        if not self.alias:
            resultado.mensagem = "Tribunal sem 'alias_datajud' no cadastro."
            return resultado
        if not processos:
            resultado.sucesso = True
            resultado.mensagem = "Nenhum processo cadastrado para este tribunal."
            return resultado

        desde = datetime.now() - timedelta(days=desde_dias)
        por_numero = {normalizar_cnj(p.numero): p for p in processos}
        numeros = list(por_numero)
        encontrados: set[str] = set()

        for i in range(0, len(numeros), TAMANHO_LOTE):
            lote = numeros[i : i + TAMANHO_LOTE]
            resultado.processos_consultados += len(lote)
            try:
                for documento in self._consultar_lote(lote):
                    numero = normalizar_cnj(documento.get("numeroProcesso", ""))
                    encontrados.add(numero)
                    resultado.movimentacoes.extend(
                        self._extrair(documento, por_numero.get(numero), desde)
                    )
            except Exception as exc:
                resultado.registrar_erro(f"lote {i // TAMANHO_LOTE + 1}", exc)

        nao_achados = set(numeros) - encontrados
        if nao_achados:
            # Causa mais comum: segredo de justica, ou atraso na alimentacao.
            resultado.erros.append(
                f"{len(nao_achados)} processo(s) sem retorno no DataJud "
                f"(segredo de justica ou base ainda nao atualizada): "
                + ", ".join(sorted(nao_achados)[:5])
            )

        resultado.sucesso = bool(encontrados) or not resultado.erros
        resultado.mensagem = (
            f"{len(resultado.movimentacoes)} movimentacoes em {len(encontrados)}/"
            f"{len(numeros)} processos (janela de {desde_dias} dias)"
        )
        return resultado

    # ------------------------------------------------------------ utilitario

    def testar(self) -> tuple[bool, str]:
        """Confere se o indice do tribunal responde com a chave configurada."""
        if not self.alias:
            return False, "sem alias_datajud"
        try:
            consulta = {"size": 0, "query": {"match_all": {}}}
            resposta = self.sessao.post(
                self.endpoint, data=json.dumps(consulta).encode("utf-8"),
                headers=self._cabecalhos(),
            )
            if resposta.status_code == 401:
                return False, "HTTP 401 - chave publica invalida ou trocada pelo CNJ"
            if resposta.status_code == 404:
                return False, f"HTTP 404 - alias '{self.alias}' nao existe"
            if resposta.status_code >= 400:
                return False, f"HTTP {resposta.status_code}"
            total = resposta.json().get("hits", {}).get("total", {})
            quantidade = total.get("value") if isinstance(total, dict) else total
            return True, f"OK - indice com {quantidade:,} processos".replace(",", ".")
        except Exception as exc:
            nome = type(exc).__name__
            if "Proxy" in nome:
                return False, "Bloqueado pelo proxy da rede"
            if "Connection" in nome or "Timeout" in nome:
                return False, "Sem conexao com api-publica.datajud.cnj.jus.br"
            return False, f"{nome}: {str(exc)[:100]}"
