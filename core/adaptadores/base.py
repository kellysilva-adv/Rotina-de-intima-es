"""Contrato comum dos adaptadores de captura."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.modelo import Movimentacao, Processo
from core.sessao import SessaoTribunal

log = logging.getLogger("varredura.adaptador")


@dataclass
class ResultadoVarredura:
    """O que aconteceu em um tribunal - vira o diagnostico do run."""

    tribunal_id: str
    tribunal_nome: str
    sistema: str
    fonte: str
    movimentacoes: list[Movimentacao] = field(default_factory=list)
    processos_consultados: int = 0
    processos_com_erro: int = 0
    sucesso: bool = False
    mensagem: str = ""
    erros: list[str] = field(default_factory=list)

    def registrar_erro(self, processo: str, exc: Exception | str) -> None:
        self.processos_com_erro += 1
        detalhe = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
        self.erros.append(f"{processo}: {detalhe}"[:300])

    def para_dict(self) -> dict[str, Any]:
        return {
            "tribunal_id": self.tribunal_id,
            "tribunal_nome": self.tribunal_nome,
            "sistema": self.sistema,
            "fonte": self.fonte,
            "sucesso": self.sucesso,
            "mensagem": self.mensagem,
            "processos_consultados": self.processos_consultados,
            "processos_com_erro": self.processos_com_erro,
            "movimentacoes_capturadas": len(self.movimentacoes),
            "erros": self.erros[:20],
        }


class AdaptadorBase:
    """Interface que todo adaptador implementa."""

    fonte = "base"

    def __init__(self, tribunal: dict[str, Any], sessao: SessaoTribunal) -> None:
        self.tribunal = tribunal
        self.sessao = sessao

    @property
    def id(self) -> str:
        return self.tribunal["id"]

    @property
    def nome(self) -> str:
        return self.tribunal["nome"]

    @property
    def sistema(self) -> str:
        return self.tribunal["sistema"]

    def novo_resultado(self) -> ResultadoVarredura:
        return ResultadoVarredura(
            tribunal_id=self.id,
            tribunal_nome=self.nome,
            sistema=self.sistema,
            fonte=self.fonte,
        )

    def varrer(self, processos: list[Processo], desde_dias: int = 15) -> ResultadoVarredura:
        raise NotImplementedError

    def filtrar_secao(self, mov: Movimentacao) -> bool:
        """Aplica o filtro de secoes/comarcas do cadastro. Vazio = aceita tudo."""
        secoes = [s.lower() for s in self.tribunal.get("secoes", []) if s]
        if not secoes:
            return True
        alvo = f"{mov.orgao_julgador} {mov.secao}".lower()
        return any(s in alvo for s in secoes)
