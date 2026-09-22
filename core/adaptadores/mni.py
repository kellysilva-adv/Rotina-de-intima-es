"""Adaptador MNI 2.2.2 - Modelo Nacional de Interoperabilidade (CNJ).

Este e o caminho OFICIAL e o unico realmente estavel para consultar acervo
programaticamente: o mesmo contrato SOAP vale para PJe, eproc, e-SAJ e Projudi.

Duas advertencias honestas:

1) O MNI exige credenciais proprias (idConsultante/senhaConsultante), que NAO
   sao o certificado digital - normalmente sao o login do advogado no sistema
   do tribunal. O certificado A1 entra no transporte (mTLS), autenticando a
   conexao; as credenciais entram no envelope, autorizando a consulta.

2) Nem todo tribunal libera o MNI para advogado. Onde nao liberar, a resposta
   vem com sucesso=false e a mensagem do proprio tribunal - o relatorio de
   diagnostico mostra exatamente isso, tribunal por tribunal.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Iterator

from core.adaptadores.base import AdaptadorBase, ResultadoVarredura
from core.modelo import Movimentacao, Processo, normalizar_cnj

log = logging.getLogger("varredura.mni")

NS_SERVICO = "http://www.cnj.jus.br/servico-intercomunicacao-2.2.2/"
NS_TIPOS = "http://www.cnj.jus.br/intercomunicacao-2.2.2"

ENVELOPE_CONSULTAR_PROCESSO = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:ser="{ns_servico}">
  <soapenv:Header/>
  <soapenv:Body>
    <ser:consultarProcesso>
      <idConsultante>{id_consultante}</idConsultante>
      <senhaConsultante>{senha_consultante}</senhaConsultante>
      <numeroProcesso>{numero_processo}</numeroProcesso>
      <dataReferencia>{data_referencia}</dataReferencia>
      <movimentos>true</movimentos>
      <incluirCabecalho>true</incluirCabecalho>
      <incluirDocumentos>false</incluirDocumentos>
    </ser:consultarProcesso>
  </soapenv:Body>
</soapenv:Envelope>
"""


def _sem_ns(tag: str) -> str:
    """'{ns}movimento' -> 'movimento'."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _achar_todos(raiz: ET.Element, nome: str) -> Iterator[ET.Element]:
    """Busca por nome local, ignorando namespace (implementacoes divergem)."""
    for el in raiz.iter():
        if _sem_ns(el.tag) == nome:
            yield el


def _achar(raiz: ET.Element, nome: str) -> ET.Element | None:
    return next(_achar_todos(raiz, nome), None)


def _texto(raiz: ET.Element | None, nome: str) -> str:
    if raiz is None:
        return ""
    el = _achar(raiz, nome)
    return (el.text or "").strip() if el is not None else ""


class AdaptadorMNI(AdaptadorBase):
    fonte = "mni"

    def __init__(self, tribunal, sessao, id_consultante: str = "", senha_consultante: str = ""):
        super().__init__(tribunal, sessao)
        self.id_consultante = id_consultante
        self.senha_consultante = senha_consultante
        self.endpoint = tribunal.get("endpoint_mni", "")

    # ------------------------------------------------------------------ SOAP

    def _chamar(self, corpo: str, acao: str) -> ET.Element:
        cabecalhos = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{acao}"',
        }
        resp = self.sessao.post(self.endpoint, data=corpo.encode("utf-8"), headers=cabecalhos)
        if resp.status_code >= 400:
            trecho = re.sub(r"\s+", " ", resp.text[:300])
            raise RuntimeError(f"HTTP {resp.status_code} do endpoint MNI: {trecho}")
        try:
            return ET.fromstring(resp.content)
        except ET.ParseError as exc:
            trecho = re.sub(r"\s+", " ", resp.text[:300])
            raise RuntimeError(f"Resposta nao e XML valido: {trecho}") from exc

    def consultar_processo(self, numero: str, desde: datetime) -> tuple[bool, str, ET.Element | None]:
        corpo = ENVELOPE_CONSULTAR_PROCESSO.format(
            ns_servico=NS_SERVICO,
            id_consultante=self.id_consultante,
            senha_consultante=self.senha_consultante,
            numero_processo=normalizar_cnj(numero),
            data_referencia=desde.strftime("%Y%m%d%H%M%S"),
        )
        raiz = self._chamar(corpo, "consultarProcesso")

        falha = _achar(raiz, "Fault")
        if falha is not None:
            return False, _texto(falha, "faultstring") or "SOAP Fault", None

        resposta = _achar(raiz, "consultarProcessoResposta") or raiz
        sucesso = _texto(resposta, "sucesso").lower() == "true"
        mensagem = _texto(resposta, "mensagem")
        return sucesso, mensagem, resposta

    # -------------------------------------------------------------- extracao

    def _extrair(self, resposta: ET.Element, processo: Processo) -> list[Movimentacao]:
        dados = _achar(resposta, "dadosBasicos")
        orgao = ""
        classe = ""
        if dados is not None:
            oj = _achar(dados, "orgaoJulgador")
            if oj is not None:
                orgao = oj.attrib.get("nomeOrgao", "") or (oj.text or "").strip()
            classe = dados.attrib.get("classeProcessual", "")

        movs: list[Movimentacao] = []
        for el in _achar_todos(resposta, "movimento"):
            data_hora = el.attrib.get("dataHora", "")
            codigo = el.attrib.get("nivelSigilo", "")  # sobrescrito abaixo se houver

            descricao = ""
            nacional = _achar(el, "movimentoNacional")
            if nacional is not None:
                codigo = nacional.attrib.get("codigoNacional", "") or codigo
                descricao = (nacional.text or "").strip()
            local = _achar(el, "movimentoLocal")
            if local is not None and not descricao:
                codigo = local.attrib.get("codigoMovimento", "") or codigo
                descricao = (local.text or "").strip()

            complementos = [
                (c.text or "").strip()
                for c in _achar_todos(el, "complemento")
                if (c.text or "").strip()
            ]
            # Alguns tribunais mandam so o complemento, sem descricao nomeada.
            if not descricao and complementos:
                descricao = complementos[0]

            identificador = _achar(el, "identificadorMovimento")
            autor = ""
            if identificador is not None:
                autor = identificador.attrib.get("nomePessoa", "")

            mov = Movimentacao(
                processo=normalizar_cnj(processo.numero),
                tribunal_id=self.id,
                tribunal_nome=self.nome,
                sistema=self.sistema,
                orgao_julgador=orgao or processo.orgao_julgador,
                secao=processo.orgao_julgador or orgao,
                data_movimentacao=data_hora,
                codigo_movimento=str(codigo),
                descricao=descricao or classe,
                complemento=" | ".join(complementos),
                autor_declarado=autor,
                cliente=processo.cliente,
                fonte=self.fonte,
                url_consulta=self.endpoint,
            )
            if self.filtrar_secao(mov):
                movs.append(mov)
        return movs

    # ---------------------------------------------------------------- varrer

    def varrer(self, processos: list[Processo], desde_dias: int = 15) -> ResultadoVarredura:
        resultado = self.novo_resultado()

        if not self.endpoint:
            resultado.mensagem = "Endpoint MNI nao cadastrado para este tribunal."
            return resultado
        if not (self.id_consultante and self.senha_consultante):
            resultado.mensagem = (
                "Credenciais MNI ausentes (MNI_ID_CONSULTANTE / MNI_SENHA_CONSULTANTE no .env)."
            )
            return resultado
        if not processos:
            resultado.sucesso = True
            resultado.mensagem = "Nenhum processo cadastrado para este tribunal."
            return resultado

        desde = datetime.now() - timedelta(days=desde_dias)
        houve_resposta = False

        for proc in processos:
            resultado.processos_consultados += 1
            try:
                ok, mensagem, resposta = self.consultar_processo(proc.numero, desde)
                houve_resposta = True
                if not ok or resposta is None:
                    resultado.registrar_erro(proc.numero_formatado, mensagem or "consulta sem sucesso")
                    continue
                resultado.movimentacoes.extend(self._extrair(resposta, proc))
            except Exception as exc:
                resultado.registrar_erro(proc.numero_formatado, exc)

        resultado.sucesso = houve_resposta and resultado.processos_com_erro < len(processos)
        if resultado.sucesso:
            resultado.mensagem = (
                f"{len(resultado.movimentacoes)} movimentacoes em "
                f"{resultado.processos_consultados} processos"
            )
        else:
            resultado.mensagem = (
                resultado.erros[0] if resultado.erros else "Nenhuma resposta util do endpoint MNI"
            )
        return resultado

    # ------------------------------------------------------------ utilitario

    def testar_endpoint(self) -> tuple[bool, str]:
        """Confere se o WSDL responde - use antes de confiar no cadastro."""
        if not self.endpoint:
            return False, "endpoint nao cadastrado"
        url = self.endpoint + ("&wsdl" if "?" in self.endpoint else "?wsdl")
        ok, diagnostico = self.sessao.testar(url)
        if not ok:
            return False, diagnostico
        try:
            resp = self.sessao.get(url)
            corpo = resp.text[:4000].lower()
            if "wsdl" in corpo and ("intercomunicacao" in corpo or "consultarprocesso" in corpo):
                return True, f"WSDL MNI respondeu ({diagnostico})"
            if resp.status_code == 200:
                return False, f"Respondeu, mas nao parece WSDL do MNI ({diagnostico})"
            return False, diagnostico
        except Exception as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:120]}"
