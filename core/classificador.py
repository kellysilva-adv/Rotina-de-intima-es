"""Classificacao juridica das movimentacoes: origem, tarefa e prazo.

Duas decisoes de projeto que importam para a confianca do resultado:

1) Um prazo escrito EXPRESSAMENTE na movimentacao ("no prazo de 10 dias")
   sempre vence o prazo padrao da regra. O despacho manda mais que a tabela.

2) Nada aqui dispensa a conferencia no sistema do tribunal. Por isso cada
   linha do relatorio sai com grau de confianca e com os alertas que o
   classificador levantou.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from core.modelo import (
    Movimentacao,
    PrazoCalculado,
    ORIGEM_DESCONHECIDA,
    ORIGEM_PROPRIA,
    ORIGENS_MONITORADAS,
)
from core.prazos import (
    CalendarioForense,
    parse_data,
    termo_inicial_dje,
    termo_inicial_intimacao_eletronica,
)

URGENCIA_CRITICA = "CRITICA"
URGENCIA_ALTA = "ALTA"
URGENCIA_MEDIA = "MEDIA"
URGENCIA_BAIXA = "BAIXA"

# "no prazo de 15 (quinze) dias uteis", "prazo: 10 dias", "em 05 dias"
_RE_PRAZO = re.compile(
    r"(?:prazo\s+(?:de\s+|comum\s+de\s+|sucessivo\s+de\s+)?|em\s+|no\s+prazo\s+)"
    r"(\d{1,3})\s*(?:\([a-z\s]{3,20}\)\s*)?dias?"
    r"(\s*(?:uteis|corridos))?",
    re.IGNORECASE,
)

# Movimentacoes assinadas pelo proprio escritorio nao geram tarefa para nos.
_PADROES_PROPRIA = (
    "peticao do autor", "peticao da parte autora", "juntada de peticao pelo autor",
    "manifestacao da parte autora", "replica apresentada", "peticao inicial",
    "procuracao", "substabelecimento",
)


def normalizar(texto: str) -> str:
    """Minusculas, sem acento, espacos colapsados."""
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


class Classificador:
    def __init__(self, caminho_regras: Path) -> None:
        dados = json.loads(Path(caminho_regras).read_text(encoding="utf-8"))
        self.regras: list[dict[str, Any]] = sorted(
            dados["regras"], key=lambda r: r.get("prioridade", 0), reverse=True
        )
        self.origens: dict[str, list[str]] = dados["origens"]
        u = dados.get("urgencia", {})
        self.lim_critica = u.get("critica_ate_dias_uteis", 1)
        self.lim_alta = u.get("alta_ate_dias_uteis", 3)
        self.lim_media = u.get("media_ate_dias_uteis", 7)

    # ------------------------------------------------------------------ origem

    def detectar_origem(self, mov: Movimentacao) -> str:
        texto = normalizar(f"{mov.texto} {mov.autor_declarado}")
        if not texto:
            return ORIGEM_DESCONHECIDA
        if any(p in texto for p in _PADROES_PROPRIA):
            return ORIGEM_PROPRIA
        # MP e parte contraria tem precedencia: sao os que trazem surpresa.
        for origem in ("Ministerio Publico", "Parte Contraria", "Tribunal / Juizo"):
            if any(p in texto for p in self.origens.get(origem, [])):
                return origem
        return ORIGEM_DESCONHECIDA

    # ------------------------------------------------------------------- prazo

    @staticmethod
    def prazo_explicito(texto: str) -> tuple[int, str] | None:
        """Extrai 'prazo de N dias [uteis|corridos]' do proprio ato."""
        m = _RE_PRAZO.search(normalizar(texto))
        if not m:
            return None
        dias = int(m.group(1))
        if not 1 <= dias <= 180:
            return None
        sufixo = (m.group(2) or "").strip()
        # CPC art. 219: prazo processual e em dias uteis, salvo dito ao contrario.
        return dias, ("corridos" if "corrido" in sufixo else "uteis")

    def casar_regra(self, mov: Movimentacao) -> dict[str, Any] | None:
        texto = normalizar(mov.texto)
        if not texto:
            return None
        for regra in self.regras:
            exigida = regra.get("origem_exigida")
            if exigida and mov.origem not in exigida:
                continue
            if any(normalizar(p) in texto for p in regra["padroes"]):
                return regra
        return None

    # --------------------------------------------------------------- avaliacao

    def avaliar(
        self,
        mov: Movimentacao,
        calendario: CalendarioForense,
        hoje: date | None = None,
    ) -> PrazoCalculado | None:
        """Devolve o prazo calculado, ou None se a movimentacao nao gera tarefa."""
        hoje = hoje or date.today()

        if not mov.origem or mov.origem == ORIGEM_DESCONHECIDA:
            mov.origem = self.detectar_origem(mov)
        if mov.origem not in ORIGENS_MONITORADAS:
            return None

        regra = self.casar_regra(mov)
        if regra is None:
            return None

        alertas: list[str] = []
        confianca = regra.get("confianca", "media")

        dias = regra["dias"]
        contagem = regra.get("contagem", "uteis")
        fundamento = regra["fundamento"]

        explicito = self.prazo_explicito(mov.texto)
        if explicito:
            dias_exp, contagem_exp = explicito
            if dias_exp != dias or contagem_exp != contagem:
                alertas.append(
                    f"Prazo de {dias_exp} dias {contagem_exp} lido no proprio ato "
                    f"(a regra padrao previa {dias} {contagem})"
                )
            dias, contagem = dias_exp, contagem_exp
            fundamento = "Prazo fixado no proprio ato"
            confianca = "alta"

        # Termo inicial ------------------------------------------------------
        disponibilizacao = parse_data(mov.data_disponibilizacao)
        data_mov = parse_data(mov.data_movimentacao)
        base = disponibilizacao or data_mov

        if base is None:
            alertas.append("Movimentacao sem data legivel - prazo NAO calculado")
            return PrazoCalculado(
                movimentacao=mov, tarefa=regra["tarefa"], fundamento=fundamento,
                dias_prazo=dias, contagem=contagem, termo_inicial=None,
                data_limite=None, dias_uteis_restantes=None,
                urgencia=URGENCIA_ALTA, confianca="baixa", alertas=alertas,
            )

        modo_termo = regra.get("termo", "eletronica")
        if modo_termo == "dje":
            _, termo = termo_inicial_dje(calendario, base)
        else:
            # Sem registro de leitura, a lei presume a intimacao no 10o dia
            # corrido (Lei 11.419/06, art. 5o, par. 3o). Assumir a leitura
            # HOJE seria mais conservador, mas produziria prazo maior que o
            # real caso a intimacao ja tenha se consumado - por isso o alerta.
            _, termo = termo_inicial_intimacao_eletronica(calendario, base)
            alertas.append(
                "Termo inicial presumido pela intimacao automatica (10 dias). "
                "Se a intimacao foi lida antes, o prazo vence ANTES desta data."
            )
            if disponibilizacao is None:
                alertas.append("Sem data de disponibilizacao - usada a data da movimentacao")

        if contagem == "corridos":
            limite = calendario.vencimento_dias_corridos(termo, dias)
        else:
            limite = calendario.vencimento_dias_uteis(termo, dias)

        restantes = calendario.dias_uteis_entre(hoje, limite)
        urgencia = self.classificar_urgencia(restantes)

        if confianca == "baixa":
            alertas.append("Prazo padrao supletivo - CONFERIR o prazo no proprio ato")

        return PrazoCalculado(
            movimentacao=mov, tarefa=regra["tarefa"], fundamento=fundamento,
            dias_prazo=dias, contagem=contagem, termo_inicial=termo,
            data_limite=limite, dias_uteis_restantes=restantes,
            urgencia=urgencia, confianca=confianca, alertas=alertas,
        )

    def classificar_urgencia(self, dias_uteis_restantes: int | None) -> str:
        if dias_uteis_restantes is None:
            return URGENCIA_ALTA
        if dias_uteis_restantes <= self.lim_critica:
            return URGENCIA_CRITICA
        if dias_uteis_restantes <= self.lim_alta:
            return URGENCIA_ALTA
        if dias_uteis_restantes <= self.lim_media:
            return URGENCIA_MEDIA
        return URGENCIA_BAIXA


ORDEM_URGENCIA = {
    URGENCIA_CRITICA: 0,
    URGENCIA_ALTA: 1,
    URGENCIA_MEDIA: 2,
    URGENCIA_BAIXA: 3,
}


def ordenar_por_urgencia(prazos: list[PrazoCalculado]) -> list[PrazoCalculado]:
    """Mais urgente primeiro: vencido/curto no topo, sem data logo abaixo."""
    def chave(p: PrazoCalculado):
        return (
            ORDEM_URGENCIA.get(p.urgencia, 9),
            p.dias_uteis_restantes if p.dias_uteis_restantes is not None else 999,
            p.data_limite or date.max,
            p.movimentacao.processo,
        )
    return sorted(prazos, key=chave)
