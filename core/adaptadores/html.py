"""Adaptadores de raspagem da area logada (aba ACERVO) por sistema.

LEIA ISTO ANTES DE CONFIAR NA RASPAGEM
======================================
O MNI (core/adaptadores/mni.py) tem contrato publico e estavel. A area logada
NAO tem: cada tribunal muda fluxo de login, nome de parametro e estrutura da
tabela do acervo, e varios usam JSF/PrimeFaces com ViewState, que nao se
reproduz por requisicao simples.

Por isso este modulo NAO chuta seletor. Ele e um raspador COMPLETO e generico,
dirigido por config/seletores_acervo.json. Enquanto o perfil de um sistema
estiver sem mapeamento, o adaptador diz isso com todas as letras no relatorio
de diagnostico em vez de devolver lista vazia fingindo que varreu.

Para mapear um tribunal:
    python3 varredura_tribunais.py --capturar-html trf1
Isso autentica com o certificado, salva o HTML da area logada em dados/html/
e imprime as tabelas candidatas. Com esse HTML em maos, preencha o perfil do
sistema no JSON - o adaptador passa a funcionar sem mudar uma linha de codigo.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from core.adaptadores.base import AdaptadorBase, ResultadoVarredura
from core.modelo import Movimentacao, Processo, normalizar_cnj

log = logging.getLogger("varredura.html")

_RE_CNJ = re.compile(r"\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}")


def _carregar_perfis(caminho: Path) -> dict[str, Any]:
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8")).get("perfis", {})
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Nao foi possivel ler os perfis de raspagem: %s", exc)
        return {}


class AdaptadorHTML(AdaptadorBase):
    """Raspador generico da aba Acervo, dirigido por perfil declarativo."""

    fonte = "html"
    sistema_perfil = ""            # sobrescrito nas subclasses
    caminho_perfis = Path("config/seletores_acervo.json")

    def __init__(self, tribunal, sessao, caminho_perfis: Path | None = None):
        super().__init__(tribunal, sessao)
        if caminho_perfis:
            self.caminho_perfis = Path(caminho_perfis)
        perfis = _carregar_perfis(self.caminho_perfis)
        # Perfil por tribunal tem precedencia sobre o perfil do sistema.
        self.perfil: dict[str, Any] = perfis.get(self.id) or perfis.get(self.sistema_perfil) or {}

    # ------------------------------------------------------------- ajudantes

    @property
    def mapeado(self) -> bool:
        return bool(self.perfil.get("mapeado")) and bool(self.perfil.get("acervo", {}).get("linha"))

    def url(self, caminho: str) -> str:
        base = self.tribunal["url_base"]
        if not base.endswith("/"):
            base += "/"
        return urljoin(base, caminho.lstrip("/"))

    def _sopa(self, html: str):
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "BeautifulSoup nao instalado. Rode: pip install -r requirements.txt"
            ) from exc
        return BeautifulSoup(html, "html.parser")

    # ------------------------------------------------------------ autenticar

    def autenticar(self) -> tuple[bool, str]:
        """Abre a area logada usando o certificado A1 ja montado na sessao.

        Nos sistemas que aceitam mTLS, o proprio handshake autentica e o
        endpoint de login por certificado ja devolve a sessao aberta.
        """
        if not self.sessao.mtls_ativo:
            return False, "Sessao sem mTLS - certificado A1 nao carregado."

        caminho_login = self.perfil.get("login", {}).get("caminho")
        if not caminho_login:
            return False, "Perfil sem caminho de login por certificado."

        try:
            resp = self.sessao.get(self.url(caminho_login), allow_redirects=True)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:150]}"

        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code} no login por certificado."

        marcador = self.perfil.get("login", {}).get("marcador_sucesso")
        if marcador and marcador.lower() not in resp.text.lower():
            return False, "Login por certificado nao confirmado (marcador ausente na resposta)."
        return True, "Autenticado por certificado digital."

    # ---------------------------------------------------------------- acervo

    def _linhas_acervo(self, html: str) -> list[dict[str, str]]:
        """Extrai as linhas do acervo conforme os seletores CSS do perfil."""
        cfg = self.perfil.get("acervo", {})
        sopa = self._sopa(html)
        linhas: list[dict[str, str]] = []
        for elemento in sopa.select(cfg["linha"]):
            registro: dict[str, str] = {}
            for campo, seletor in cfg.get("campos", {}).items():
                alvo = elemento.select_one(seletor) if seletor else None
                registro[campo] = alvo.get_text(" ", strip=True) if alvo else ""
            if not registro.get("processo"):
                # Ultimo recurso: acha o CNJ em qualquer lugar da linha.
                achado = _RE_CNJ.search(elemento.get_text(" ", strip=True))
                if achado:
                    registro["processo"] = achado.group(0)
            if registro.get("processo"):
                linhas.append(registro)
        return linhas

    def varrer(self, processos: list[Processo], desde_dias: int = 15) -> ResultadoVarredura:
        resultado = self.novo_resultado()

        if not self.mapeado:
            resultado.mensagem = (
                f"Perfil de raspagem do sistema '{self.sistema_perfil}' ainda NAO mapeado. "
                f"Rode: python3 varredura_tribunais.py --capturar-html {self.id}"
            )
            return resultado

        ok, mensagem = self.autenticar()
        if not ok:
            resultado.mensagem = f"Falha de autenticacao: {mensagem}"
            return resultado

        caminho_acervo = self.perfil.get("acervo", {}).get("caminho", "")
        try:
            resp = self.sessao.get(self.url(caminho_acervo), allow_redirects=True)
            linhas = self._linhas_acervo(resp.text)
        except Exception as exc:
            resultado.mensagem = f"Falha ao ler o acervo: {type(exc).__name__}: {exc}"
            return resultado

        acompanhados = {normalizar_cnj(p.numero): p for p in processos}
        so_acompanhados = bool(acompanhados) and self.perfil.get("apenas_acompanhados", True)

        for linha in linhas:
            numero = normalizar_cnj(linha.get("processo", ""))
            if so_acompanhados and numero not in acompanhados:
                continue
            proc = acompanhados.get(numero)
            mov = Movimentacao(
                processo=numero,
                tribunal_id=self.id,
                tribunal_nome=self.nome,
                sistema=self.sistema,
                orgao_julgador=linha.get("orgao", ""),
                secao=linha.get("secao", "") or linha.get("orgao", ""),
                data_movimentacao=linha.get("data", ""),
                descricao=linha.get("movimentacao", "") or linha.get("descricao", ""),
                complemento=linha.get("complemento", ""),
                autor_declarado=linha.get("autor", ""),
                cliente=proc.cliente if proc else "",
                fonte=self.fonte,
                url_consulta=self.url(caminho_acervo),
            )
            if self.filtrar_secao(mov):
                resultado.movimentacoes.append(mov)

        resultado.processos_consultados = len(linhas)
        resultado.sucesso = True
        resultado.mensagem = (
            f"{len(resultado.movimentacoes)} movimentacoes em {len(linhas)} linhas de acervo"
        )
        return resultado

    # ----------------------------------------------------------------- debug

    def capturar_html(self, destino: Path) -> dict[str, Any]:
        """Salva o HTML da area logada para mapear os seletores."""
        destino.mkdir(parents=True, exist_ok=True)
        relatorio: dict[str, Any] = {"tribunal": self.id, "arquivos": [], "tabelas": []}

        candidatos = self.perfil.get("caminhos_debug") or [
            self.perfil.get("login", {}).get("caminho", ""),
            self.perfil.get("acervo", {}).get("caminho", ""),
            "",
        ]
        for i, caminho in enumerate([c for c in candidatos if c is not None]):
            url = self.url(caminho or "")
            try:
                resp = self.sessao.get(url, allow_redirects=True)
            except Exception as exc:
                relatorio["arquivos"].append({"url": url, "erro": f"{type(exc).__name__}: {exc}"})
                continue

            arquivo = destino / f"{self.id}_{i}.html"
            arquivo.write_text(resp.text, encoding="utf-8", errors="replace")
            relatorio["arquivos"].append({
                "url": resp.url, "status": resp.status_code, "arquivo": str(arquivo)
            })

            try:
                sopa = self._sopa(resp.text)
                for tabela in sopa.find_all("table")[:10]:
                    relatorio["tabelas"].append({
                        "url": resp.url,
                        "id": tabela.get("id", ""),
                        "class": " ".join(tabela.get("class", [])),
                        "linhas": len(tabela.find_all("tr")),
                    })
            except RuntimeError:
                pass
        return relatorio


class AdaptadorPJe(AdaptadorHTML):
    sistema_perfil = "pje"


class AdaptadorEproc(AdaptadorHTML):
    sistema_perfil = "eproc"


class AdaptadorEsaj(AdaptadorHTML):
    sistema_perfil = "esaj"


class AdaptadorProjudi(AdaptadorHTML):
    sistema_perfil = "projudi"
