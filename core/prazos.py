"""Calendario forense e contagem de prazos processuais em dias uteis.

Base legal implementada:
  - CPC, art. 219  -> prazos processuais contam-se em DIAS UTEIS.
  - CPC, art. 224  -> exclui-se o dia do comeco e inclui-se o do vencimento;
                      se o comeco ou o vencimento cair em dia sem expediente,
                      prorroga-se para o dia util seguinte.
  - CPC, art. 224, par. 2o e 3o -> publicacao = 1o dia util seguinte a
                      disponibilizacao no DJe; a contagem comeca no 1o dia util
                      seguinte ao da publicacao.
  - CPC, art. 220  -> suspensao do curso dos prazos de 20/12 a 20/01, inclusive.
  - Lei 11.419/2006, art. 5o -> intimacao eletronica: considera-se realizada no
                      dia da consulta; nao consultada em 10 dias corridos da
                      disponibilizacao, reputa-se realizada ao fim desse prazo.
  - Lei 5.010/1966, art. 62 -> feriados proprios da Justica Federal.

AVISO IMPORTANTE (e por isso o relatorio sai com coluna de confianca):
feriados LOCAIS de comarca/secao e suspensoes por portaria do tribunal NAO
entram automaticamente. Cadastre-os em config/feriados.json antes de confiar
em prazo apertado. O calculo e ferramenta de triagem, nao substitui a
conferencia da data no proprio sistema do tribunal.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

RAMO_FEDERAL = "federal"
RAMO_ESTADUAL = "estadual"


def domingo_de_pascoa(ano: int) -> date:
    """Algoritmo gregoriano anonimo (Meeus/Jones/Butcher)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def feriados_moveis(ano: int) -> dict[date, str]:
    """Feriados dependentes da Pascoa."""
    pascoa = domingo_de_pascoa(ano)
    return {
        pascoa - timedelta(days=48): "Segunda-feira de Carnaval",
        pascoa - timedelta(days=47): "Terca-feira de Carnaval",
        pascoa - timedelta(days=46): "Quarta-feira de Cinzas",
        pascoa - timedelta(days=3): "Quinta-feira Santa",
        pascoa - timedelta(days=2): "Sexta-feira da Paixao",
        pascoa + timedelta(days=60): "Corpus Christi",
    }


def feriados_nacionais_fixos(ano: int) -> dict[date, str]:
    return {
        date(ano, 1, 1): "Confraternizacao Universal",
        date(ano, 4, 21): "Tiradentes",
        date(ano, 5, 1): "Dia do Trabalho",
        date(ano, 9, 7): "Independencia",
        date(ano, 10, 12): "Nossa Senhora Aparecida",
        date(ano, 11, 2): "Finados",
        date(ano, 11, 15): "Proclamacao da Republica",
        date(ano, 11, 20): "Consciencia Negra",
        date(ano, 12, 25): "Natal",
    }


def feriados_forenses_federais(ano: int) -> dict[date, str]:
    """Lei 5.010/1966, art. 62 - feriados proprios da Justica Federal."""
    moveis = feriados_moveis(ano)
    pascoa = domingo_de_pascoa(ano)
    dias = {
        date(ano, 8, 11): "Dia do Advogado (feriado na JF)",
        date(ano, 11, 1): "Feriado forense - JF",
        date(ano, 12, 8): "Feriado forense - JF",
    }
    # Semana Santa: da quarta-feira ao domingo de Pascoa.
    for delta in range(4, 0, -1):
        dias[pascoa - timedelta(days=delta)] = "Semana Santa (JF)"
    for d, nome in moveis.items():
        if "Carnaval" in nome:
            dias[d] = nome + " (JF)"
    # Recesso da JF: 20/12 a 06/01.
    inicio = date(ano, 12, 20)
    for n in range((date(ano, 12, 31) - inicio).days + 1):
        dias[inicio + timedelta(days=n)] = "Recesso forense - JF"
    for n in range(6):
        dias[date(ano, 1, 1) + timedelta(days=n)] = "Recesso forense - JF"
    return dias


def em_suspensao_cpc220(d: date) -> bool:
    """CPC art. 220: prazos suspensos de 20/12 a 20/01, inclusive."""
    return (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 20)


class CalendarioForense:
    """Calendario por ramo (federal/estadual) com feriados extras cadastrados."""

    def __init__(
        self,
        ramo: str = RAMO_ESTADUAL,
        feriados_extras: Iterable[str] | None = None,
        aplicar_suspensao_cpc220: bool = True,
    ) -> None:
        self.ramo = ramo
        self.aplicar_suspensao_cpc220 = aplicar_suspensao_cpc220
        self._extras: set[date] = set()
        for iso in feriados_extras or []:
            try:
                self._extras.add(date.fromisoformat(iso))
            except ValueError:
                continue
        self._cache: dict[int, dict[date, str]] = {}

    def _tabela(self, ano: int) -> dict[date, str]:
        if ano not in self._cache:
            tabela = dict(feriados_nacionais_fixos(ano))
            moveis = feriados_moveis(ano)
            # Quarta-feira de Cinzas tem expediente a partir das 14h; como o
            # protocolo eletronico funciona ate as 24h, nao e tratada como feriado.
            moveis.pop(domingo_de_pascoa(ano) - timedelta(days=46), None)
            tabela.update(moveis)
            if self.ramo == RAMO_FEDERAL:
                tabela.update(feriados_forenses_federais(ano))
            self._cache[ano] = tabela
        return self._cache[ano]

    def motivo_nao_util(self, d: date) -> str | None:
        if d.weekday() >= 5:
            return "Fim de semana"
        if d in self._extras:
            return "Feriado local cadastrado"
        if self.aplicar_suspensao_cpc220 and em_suspensao_cpc220(d):
            return "Suspensao de prazos - CPC art. 220"
        return self._tabela(d.year).get(d)

    def e_dia_util(self, d: date) -> bool:
        return self.motivo_nao_util(d) is None

    def proximo_dia_util(self, d: date, incluir_hoje: bool = True) -> date:
        atual = d if incluir_hoje else d + timedelta(days=1)
        for _ in range(400):
            if self.e_dia_util(atual):
                return atual
            atual += timedelta(days=1)
        raise RuntimeError("Nenhum dia util encontrado em 400 dias - confira o calendario")

    def somar_dias_uteis(self, inicio: date, dias: int) -> date:
        """CPC art. 224: exclui o dia do comeco, inclui o do vencimento."""
        atual = inicio
        contados = 0
        for _ in range(dias * 8 + 500):
            atual += timedelta(days=1)
            if self.e_dia_util(atual):
                contados += 1
                if contados >= dias:
                    return atual
        raise RuntimeError("Falha ao somar dias uteis - confira o calendario")

    def vencimento_dias_uteis(self, termo_inicial: date, dias: int) -> date:
        """Vencimento contando o TERMO INICIAL como dia 1.

        O art. 224, par. 3o manda iniciar a contagem no primeiro dia util
        seguinte ao da publicacao - esse dia ja e o dia 1 do prazo, nao o dia
        zero. Por isso somam-se aqui (dias - 1) dias uteis ao termo inicial.
        """
        if dias <= 0:
            return self.proximo_dia_util(termo_inicial)
        base = self.proximo_dia_util(termo_inicial)
        if dias == 1:
            return base
        return self.somar_dias_uteis(base, dias - 1)

    def vencimento_dias_corridos(self, termo_inicial: date, dias: int) -> date:
        """Idem, para os poucos prazos contados em dias corridos."""
        if dias <= 0:
            return self.proximo_dia_util(termo_inicial)
        return self.proximo_dia_util(termo_inicial + timedelta(days=dias - 1))

    def somar_dias_corridos(self, inicio: date, dias: int) -> date:
        """Prazo em dias corridos com prorrogacao do vencimento (CPC 224, par. 1o)."""
        return self.proximo_dia_util(inicio + timedelta(days=dias))

    def dias_uteis_entre(self, inicio: date, fim: date) -> int:
        """Dias uteis de inicio (exclusive) ate fim (inclusive). Negativo se vencido."""
        if fim == inicio:
            return 0
        sinal = 1 if fim > inicio else -1
        a, b = (inicio, fim) if sinal > 0 else (fim, inicio)
        total = 0
        atual = a + timedelta(days=1)
        while atual <= b:
            if self.e_dia_util(atual):
                total += 1
            atual += timedelta(days=1)
        return total * sinal


def termo_inicial_dje(cal: CalendarioForense, disponibilizacao: date) -> tuple[date, date]:
    """CPC art. 224, par. 2o e 3o.

    Devolve (data_publicacao, termo_inicial_da_contagem).
    """
    publicacao = cal.proximo_dia_util(disponibilizacao, incluir_hoje=False)
    termo = cal.proximo_dia_util(publicacao, incluir_hoje=False)
    return publicacao, termo


def termo_inicial_intimacao_eletronica(
    cal: CalendarioForense,
    disponibilizacao: date,
    data_consulta: date | None = None,
) -> tuple[date, date]:
    """Lei 11.419/2006, art. 5o, par. 1o a 3o.

    Devolve (data_da_intimacao, termo_inicial_da_contagem).
    Sem consulta registrada, assume a intimacao automatica no 10o dia corrido.
    """
    if data_consulta is not None:
        intimacao = data_consulta
    else:
        intimacao = cal.proximo_dia_util(disponibilizacao + timedelta(days=10))
    termo = cal.proximo_dia_util(intimacao, incluir_hoje=False)
    return intimacao, termo


def carregar_feriados_extras(caminho: Path, tribunal_id: str) -> list[str]:
    """Le config/feriados.json e devolve os feriados do tribunal + os globais."""
    if not caminho.exists():
        return []
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    extras = list(dados.get("globais", []))
    extras.extend(dados.get("por_tribunal", {}).get(tribunal_id, []))
    return extras


def parse_data(valor: str | None) -> date | None:
    """Aceita os formatos que os sistemas de tribunal costumam devolver."""
    if not valor:
        return None
    texto = str(valor).strip()
    formatos = (
        "%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    )
    for fmt in formatos:
        try:
            return datetime.strptime(texto[: len(datetime.now().strftime(fmt))], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date()
    except ValueError:
        return None
