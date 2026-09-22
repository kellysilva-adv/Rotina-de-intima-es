"""Estruturas de dados compartilhadas pela varredura."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any


# Origem da movimentacao: e isso que a Kelly quer filtrar.
ORIGEM_PARTE_CONTRARIA = "Parte Contraria"
ORIGEM_TRIBUNAL = "Tribunal / Juizo"
ORIGEM_MP = "Ministerio Publico"
ORIGEM_PROPRIA = "Escritorio (nossa peticao)"
ORIGEM_DESCONHECIDA = "Nao identificada"

ORIGENS_MONITORADAS = (ORIGEM_PARTE_CONTRARIA, ORIGEM_TRIBUNAL, ORIGEM_MP)


def normalizar_cnj(numero: str) -> str:
    """Devolve o numero CNJ apenas com digitos (20 posicoes)."""
    return re.sub(r"\D", "", numero or "")


def formatar_cnj(numero: str) -> str:
    """Formata NNNNNNN-DD.AAAA.J.TR.OOOO a partir de qualquer grafia."""
    d = normalizar_cnj(numero)
    if len(d) != 20:
        return numero or ""
    return f"{d[0:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:20]}"


@dataclass
class Processo:
    """Processo acompanhado pelo escritorio (vem do relatorio_prazos.json)."""

    numero: str
    tribunal_id: str
    cliente: str = ""
    orgao_julgador: str = ""
    classe: str = ""
    beneficio: str = ""
    observacao: str = ""

    @property
    def numero_formatado(self) -> str:
        return formatar_cnj(self.numero)

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> "Processo":
        return cls(
            numero=normalizar_cnj(dados.get("numero") or dados.get("processo") or ""),
            tribunal_id=(dados.get("tribunal_id") or dados.get("tribunal") or "").strip(),
            cliente=dados.get("cliente", ""),
            orgao_julgador=dados.get("orgao_julgador", "") or dados.get("secao", ""),
            classe=dados.get("classe", ""),
            beneficio=dados.get("beneficio", ""),
            observacao=dados.get("observacao", ""),
        )


@dataclass
class Movimentacao:
    """Uma movimentacao bruta capturada em um tribunal."""

    processo: str
    tribunal_id: str
    tribunal_nome: str
    sistema: str
    orgao_julgador: str = ""
    secao: str = ""
    data_movimentacao: str = ""          # ISO 8601
    data_disponibilizacao: str = ""      # ISO 8601 (DJe), quando informada
    codigo_movimento: str = ""           # codigo TPU/CNJ, quando informado
    descricao: str = ""
    complemento: str = ""
    origem: str = ORIGEM_DESCONHECIDA
    autor_declarado: str = ""            # quem o sistema aponta como signatario
    cliente: str = ""
    fonte: str = ""                      # mni | html | manual
    url_consulta: str = ""
    capturado_em: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def texto(self) -> str:
        return f"{self.descricao} {self.complemento}".strip()

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> "Movimentacao":
        validos = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in dados.items() if k in validos})


@dataclass
class PrazoCalculado:
    """Resultado da analise juridica de uma movimentacao."""

    movimentacao: Movimentacao
    tarefa: str
    fundamento: str                       # artigo/base legal do prazo
    dias_prazo: int
    contagem: str                         # "uteis" | "corridos"
    termo_inicial: date | None
    data_limite: date | None
    dias_uteis_restantes: int | None
    urgencia: str                         # CRITICA | ALTA | MEDIA | BAIXA
    confianca: str                        # alta | media | baixa
    alertas: list[str] = field(default_factory=list)

    @property
    def rotulo_prazo(self) -> str:
        if self.data_limite is None:
            return "A CONFERIR"
        return self.data_limite.strftime("%d/%m/%Y")

    def para_dict(self) -> dict[str, Any]:
        return {
            "processo": formatar_cnj(self.movimentacao.processo),
            "processo_digitos": self.movimentacao.processo,
            "tribunal": self.movimentacao.tribunal_nome,
            "secao": self.movimentacao.secao or self.movimentacao.orgao_julgador,
            "cliente": self.movimentacao.cliente,
            "origem": self.movimentacao.origem,
            "movimentacao": self.movimentacao.texto,
            "data_movimentacao": self.movimentacao.data_movimentacao,
            "tarefa": self.tarefa,
            "fundamento": self.fundamento,
            "dias_prazo": self.dias_prazo,
            "contagem": self.contagem,
            "termo_inicial": self.termo_inicial.isoformat() if self.termo_inicial else None,
            "data_limite": self.data_limite.isoformat() if self.data_limite else None,
            "dias_uteis_restantes": self.dias_uteis_restantes,
            "urgencia": self.urgencia,
            "confianca": self.confianca,
            "alertas": self.alertas,
        }


# ---------------------------------------------------------------------------
# Descoberta do tribunal a partir do proprio numero do processo
# ---------------------------------------------------------------------------
#
# O numero CNJ e NNNNNNN-DD.AAAA.J.TR.OOOO, e as posicoes J e TR ja dizem de
# que tribunal o processo e. Isso poupa a advogada de preencher o tribunal
# processo a processo - trabalho manual que so serve para gerar erro de
# digitacao num cadastro de centenas de linhas.

def segmento_e_tribunal(numero: str) -> tuple[str, str]:
    """Devolve ('J', 'TR') do numero CNJ. ('', '') se o numero for invalido."""
    d = normalizar_cnj(numero)
    if len(d) != 20:
        return "", ""
    return d[13], d[14:16]


def codigo_cnj(numero: str) -> str:
    """Devolve 'J.TR' - ex.: '4.01' para o TRF1, '8.09' para o TJGO."""
    j, tr = segmento_e_tribunal(numero)
    return f"{j}.{tr}" if j else ""


def inferir_tribunal(numero: str, tribunais: list[dict]) -> list[str]:
    """Lista os ids de tribunal compativeis com o numero informado.

    Devolve mais de um quando o mesmo tribunal roda dois sistemas (o TJSP tem
    e-SAJ e eproc; o TJRJ tem PJe e eproc) ou quando a regiao federal atende
    mais de uma secao judiciaria (TRF2 = RJ e ES; TRF4 = SC e PR).
    """
    codigo = codigo_cnj(numero)
    if not codigo:
        return []
    return [t["id"] for t in tribunais if t.get("codigo_cnj") == codigo]
