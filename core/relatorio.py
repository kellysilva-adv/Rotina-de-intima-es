"""Geracao do relatorio final em Markdown - saida limpa e direta."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.classificador import (
    URGENCIA_ALTA,
    URGENCIA_BAIXA,
    URGENCIA_CRITICA,
    URGENCIA_MEDIA,
    ordenar_por_urgencia,
)
from core.modelo import PrazoCalculado, formatar_cnj

MARCADOR = {
    URGENCIA_CRITICA: "CRITICA",
    URGENCIA_ALTA: "ALTA",
    URGENCIA_MEDIA: "MEDIA",
    URGENCIA_BAIXA: "BAIXA",
}

COLUNAS = (
    "N° do Processo",
    "Tribunal / Seção",
    "Movimentação Relevante (Origem)",
    "Tarefa Limpa a Executar",
    "Prazo Limite",
    "Urgência",
)


def _celula(texto: str, limite: int = 110) -> str:
    """Deixa o texto seguro para uma celula de tabela Markdown."""
    limpo = re.sub(r"\s+", " ", (texto or "").strip())
    limpo = limpo.replace("|", "/").replace("\\", "/")
    if len(limpo) > limite:
        limpo = limpo[: limite - 1].rstrip() + "…"
    return limpo or "—"


def _linha_prazo(p: PrazoCalculado) -> str:
    if p.data_limite is None:
        return "**A CONFERIR**"
    restantes = p.dias_uteis_restantes
    if restantes is None:
        return p.rotulo_prazo
    if restantes < 0:
        return f"**{p.rotulo_prazo} — VENCIDO há {abs(restantes)} d.ú.**"
    if restantes == 0:
        return f"**{p.rotulo_prazo} — VENCE HOJE**"
    if restantes == 1:
        return f"**{p.rotulo_prazo} — 1 dia útil**"
    return f"{p.rotulo_prazo} — {restantes} dias úteis"


def montar_tabela(prazos: list[PrazoCalculado]) -> str:
    linhas = [
        "| " + " | ".join(COLUNAS) + " |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for p in prazos:
        mov = p.movimentacao
        secao = mov.secao or mov.orgao_julgador
        tribunal = mov.tribunal_nome if not secao else f"{mov.tribunal_nome} — {secao}"
        # A origem entra DEPOIS do corte: e ela que responde "quem mexeu no
        # processo", e some justamente nas movimentacoes longas se for truncada junto.
        movimentacao = f"{_celula(mov.texto, 108)} _({mov.origem})_"
        tarefa = p.tarefa
        if mov.cliente:
            tarefa = f"{tarefa} — cliente: {mov.cliente}"
        linhas.append(
            "| "
            + " | ".join([
                f"`{_celula(formatar_cnj(mov.processo), 30)}`",
                _celula(tribunal, 70),
                movimentacao,
                _celula(tarefa, 120),
                _linha_prazo(p),
                MARCADOR.get(p.urgencia, p.urgencia),
            ])
            + " |"
        )
    return "\n".join(linhas)


def _resumo(prazos: list[PrazoCalculado]) -> str:
    contagem = {u: 0 for u in MARCADOR}
    for p in prazos:
        contagem[p.urgencia] = contagem.get(p.urgencia, 0) + 1
    vencidos = sum(
        1 for p in prazos if p.dias_uteis_restantes is not None and p.dias_uteis_restantes < 0
    )
    partes = [
        f"**{len(prazos)}** prazos identificados",
        f"**{contagem.get(URGENCIA_CRITICA, 0)}** críticos",
        f"**{contagem.get(URGENCIA_ALTA, 0)}** de alta urgência",
    ]
    if vencidos:
        partes.append(f"**{vencidos} JÁ VENCIDOS — conferir imediatamente**")
    return " · ".join(partes)


def gerar_markdown(
    prazos: list[PrazoCalculado],
    diagnostico: list[dict[str, Any]] | None = None,
    data_execucao: datetime | None = None,
) -> str:
    agora = data_execucao or datetime.now()
    ordenados = ordenar_por_urgencia(prazos)

    partes: list[str] = [
        "# Prazos urgentes — varredura diária",
        "",
        "**Kelly Silva Advocacia** · Direito Previdenciário · Minaçu/GO  ",
        f"Varredura de {agora.strftime('%d/%m/%Y às %H:%M')}",
        "",
    ]

    if not ordenados:
        partes += [
            "## Nenhum prazo urgente identificado nesta varredura",
            "",
            "Nenhuma movimentação da parte contrária, do juízo ou do Ministério Público "
            "gerou prazo no período varrido.",
            "",
        ]
    else:
        partes += [_resumo(ordenados), "", montar_tabela(ordenados), ""]

    # Alertas: o que o cálculo não garante. Alerta que se repete em vários
    # processos vira UMA linha com a contagem — repetir quarenta vezes vira
    # ruído, e ruído é a forma mais rápida de a advertência deixar de ser lida.
    agrupados: dict[str, list[str]] = {}
    for p in ordenados:
        for alerta in p.alertas:
            agrupados.setdefault(alerta, []).append(formatar_cnj(p.movimentacao.processo))
    if agrupados:
        partes += ["", "## Pontos a conferir antes de agendar", ""]
        for alerta, afetados in sorted(agrupados.items(), key=lambda kv: -len(kv[1])):
            unicos = sorted(set(afetados))
            if len(unicos) == 1:
                partes.append(f"- `{unicos[0]}` — {alerta}")
            elif len(unicos) <= 4:
                lista = ", ".join(f"`{n}`" for n in unicos)
                partes.append(f"- {alerta}  \n  Processos: {lista}")
            else:
                partes.append(f"- {alerta}  \n  Afeta **{len(unicos)} processos** desta varredura.")
        partes.append("")

    if diagnostico:
        ok = [d for d in diagnostico if d.get("sucesso")]
        falhos = [d for d in diagnostico if not d.get("sucesso")]
        partes += [
            "",
            "## Diagnóstico da varredura",
            "",
            f"Tribunais consultados com sucesso: **{len(ok)}/{len(diagnostico)}**",
            "",
        ]
        if falhos:
            partes += [
                "| Tribunal | Sistema | Fonte | Problema |",
                "| :--- | :--- | :--- | :--- |",
            ]
            for d in falhos:
                partes.append(
                    f"| {_celula(d.get('tribunal_nome',''), 50)} | {d.get('sistema','')} "
                    f"| {d.get('fonte','')} | {_celula(d.get('mensagem',''), 130)} |"
                )
            partes.append("")

    partes += [
        "",
        "---",
        "",
        "> Relatório gerado automaticamente a partir das movimentações capturadas nos "
        "sistemas dos tribunais. As datas são calculadas em dias úteis (CPC, arts. 219, "
        "220 e 224) e **não dispensam a conferência do prazo no próprio processo** — "
        "feriados locais de comarca e suspensões por portaria não entram no cálculo "
        "automático.",
        "",
    ]
    return "\n".join(partes)


def salvar(caminho: Path, conteudo: str, historico: Path | None = None) -> None:
    """Grava o relatorio do dia e, opcionalmente, arquiva a versao datada."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(conteudo, encoding="utf-8")
    if historico is not None:
        historico.mkdir(parents=True, exist_ok=True)
        datado = historico / f"prazos_{date.today().isoformat()}.md"
        datado.write_text(conteudo, encoding="utf-8")
