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
    URGENCIA_VERIFICAR,
    ordenar_por_urgencia,
    separar,
)
from core.modelo import PrazoCalculado, formatar_cnj

MARCADOR = {
    URGENCIA_CRITICA: "CRITICA",
    URGENCIA_ALTA: "ALTA",
    URGENCIA_MEDIA: "MEDIA",
    URGENCIA_BAIXA: "BAIXA",
    URGENCIA_VERIFICAR: "VERIFICAR",
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


def _resumo(com_data: list[PrazoCalculado], a_verificar: list[PrazoCalculado]) -> str:
    """Conta as duas coisas separadamente - juntar seria enganoso."""
    contagem = {u: 0 for u in MARCADOR}
    for p in com_data:
        contagem[p.urgencia] = contagem.get(p.urgencia, 0) + 1
    vencidos = sum(
        1 for p in com_data if p.dias_uteis_restantes is not None and p.dias_uteis_restantes < 0
    )
    partes = [
        f"**{len(com_data)}** prazos com data calculada",
        f"**{contagem.get(URGENCIA_CRITICA, 0)}** críticos",
        f"**{contagem.get(URGENCIA_ALTA, 0)}** de alta urgência",
        f"**{len(a_verificar)}** movimentações a verificar",
    ]
    if vencidos:
        partes.insert(1, f"**{vencidos} JÁ VENCIDOS**")
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

    com_data, a_verificar = separar(ordenados)

    partes += [_resumo(com_data, a_verificar), ""]

    if com_data:
        partes += [
            "## Prazos com data calculada",
            "",
            montar_tabela(com_data),
            "",
        ]
    else:
        partes += [
            "## Nenhum prazo com data calculada",
            "",
            "Nenhuma movimentação trouxe o teor do ato, então nenhuma data foi "
            "calculada. Isso **não** significa que não há prazo — significa que a "
            "fonte consultada não permite afirmar. Veja o bloco abaixo.",
            "",
        ]

    if a_verificar:
        partes += [
            "## Movimentações a verificar — sem prazo calculado",
            "",
            "Estes processos tiveram movimentação da parte contrária, do juízo ou do "
            "Ministério Público, mas a fonte informou apenas o **nome** do ato, não o "
            "seu teor. **Nenhuma data foi calculada aqui.** Abra cada processo e "
            "confira se há prazo.",
            "",
            montar_tabela(a_verificar),
            "",
        ]

    # Alertas: o que o cálculo não garante. Alerta que se repete em vários
    # processos vira UMA linha com a contagem — repetir quarenta vezes vira
    # ruído, e ruído é a forma mais rápida de a advertência deixar de ser lida.
    agrupados: dict[str, list[str]] = {}
    for p in com_data:
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


# ---------------------------------------------------------------------------
# Versao HTML - a que a Kelly realmente abre de manha
# ---------------------------------------------------------------------------
#
# O Markdown serve para o Claude reprocessar e para versionar. Para LER a
# pauta do dia, um .md no Bloco de Notas e um tijolo de pipes. O HTML abre no
# navegador com dois cliques, imprime direito e destaca o que esta vencendo.

CSS_RELATORIO = """
:root {
  --tinta: #1a1a1a; --fundo: #ffffff; --borda: #d8d8d8; --suave: #f7f7f8;
  --critica: #b3261e; --critica-fundo: #fdecea;
  --alta: #b35309; --alta-fundo: #fdf3e7;
  --media: #8a6d00; --media-fundo: #fdfaeb;
  --baixa: #46617a; --baixa-fundo: #f1f5f9;
}
* { box-sizing: border-box; }
body {
  font-family: "Segoe UI", Calibri, system-ui, sans-serif;
  color: var(--tinta); background: var(--fundo);
  margin: 0; padding: 24px 16px; line-height: 1.5;
}
.folha { max-width: 1180px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.1rem; margin: 32px 0 10px; padding-bottom: 6px;
     border-bottom: 1px solid var(--borda); }
.escritorio { color: #555; margin: 0 0 2px; }
.carimbo { color: #777; font-size: .9rem; margin: 0 0 20px; }
.resumo { display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 20px; }
.ficha { border: 1px solid var(--borda); border-radius: 8px;
         padding: 10px 14px; min-width: 116px; background: var(--suave); }
.ficha .numero { font-size: 1.5rem; font-weight: 700; display: block; line-height: 1.2; }
.ficha .rotulo { font-size: .78rem; color: #555; text-transform: uppercase;
                 letter-spacing: .04em; }
.ficha.critica .numero { color: var(--critica); }
.ficha.alta .numero { color: var(--alta); }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th { text-align: left; background: var(--suave); border-bottom: 2px solid var(--borda);
     padding: 9px 10px; font-size: .78rem; text-transform: uppercase;
     letter-spacing: .04em; color: #444; }
td { padding: 10px; border-bottom: 1px solid #eee; vertical-align: top; }
tr:hover td { background: #fafafa; }
.processo { font-family: Consolas, "Courier New", monospace; font-size: .85rem;
            white-space: nowrap; }
.cliente { display: block; color: #666; font-size: .82rem; margin-top: 3px; }
.tarefa { font-weight: 600; }
.prazo { white-space: nowrap; font-weight: 600; }
.selo { display: inline-block; padding: 2px 9px; border-radius: 999px;
        font-size: .74rem; font-weight: 700; letter-spacing: .03em; }
.selo.CRITICA { color: var(--critica); background: var(--critica-fundo); }
.selo.ALTA    { color: var(--alta);    background: var(--alta-fundo); }
.selo.MEDIA   { color: var(--media);   background: var(--media-fundo); }
.selo.BAIXA   { color: var(--baixa);   background: var(--baixa-fundo); }
.selo.VERIFICAR { color: #5b4a7a; background: #f2eef8; }
tr.CRITICA td { background: var(--critica-fundo); }
tr.CRITICA:hover td { background: #fbe2de; }
.origem { color: #666; font-size: .82rem; font-style: italic; }
.aviso { border-left: 3px solid #c9a227; background: #fdfaeb;
         padding: 12px 16px; margin: 14px 0; border-radius: 0 6px 6px 0; }
.aviso ul { margin: 6px 0 0; padding-left: 20px; }
.rodape { margin-top: 36px; padding-top: 14px; border-top: 1px solid var(--borda);
          color: #666; font-size: .85rem; }
.nota { border-left: 3px solid #5b4a7a; background: #f6f3fb; padding: 12px 16px;
        margin: 0 0 14px; border-radius: 0 6px 6px 0; font-size: .9rem; }
.vazio { padding: 40px; text-align: center; color: #555; background: var(--suave);
         border-radius: 8px; }
@media print {
  body { padding: 0; font-size: 10pt; }
  tr.CRITICA td { background: #fdecea !important; -webkit-print-color-adjust: exact; }
  h2 { page-break-after: avoid; }
  tr { page-break-inside: avoid; }
}
"""


def _escapar(texto: str) -> str:
    return (
        (texto or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def gerar_html(
    prazos: list[PrazoCalculado],
    diagnostico: list[dict[str, Any]] | None = None,
    data_execucao: datetime | None = None,
) -> str:
    agora = data_execucao or datetime.now()
    ordenados = ordenar_por_urgencia(prazos)

    com_data, a_verificar = separar(ordenados)
    contagem = {u: 0 for u in MARCADOR}
    for p in com_data:
        contagem[p.urgencia] = contagem.get(p.urgencia, 0) + 1
    vencidos = sum(
        1 for p in com_data
        if p.dias_uteis_restantes is not None and p.dias_uteis_restantes < 0
    )

    partes = [
        "<!DOCTYPE html>", '<html lang="pt-BR">', "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Prazos urgentes - {agora.strftime('%d/%m/%Y')}</title>",
        f"<style>{CSS_RELATORIO}</style>", "</head>", "<body>", '<div class="folha">',
        "<h1>Prazos urgentes</h1>",
        '<p class="escritorio"><strong>Kelly Silva Advocacia</strong> '
        "&middot; Direito Previdenciario &middot; Minacu/GO</p>",
        f'<p class="carimbo">Varredura de {agora.strftime("%d/%m/%Y as %H:%M")}</p>',
    ]

    fichas = [
        ("Prazos com data", len(com_data), ""),
        ("Criticos", contagem.get(URGENCIA_CRITICA, 0), "critica"),
        ("Alta urgencia", contagem.get(URGENCIA_ALTA, 0), "alta"),
        ("A verificar", len(a_verificar), ""),
    ]
    if vencidos:
        fichas.insert(1, ("Ja vencidos", vencidos, "critica"))
    partes.append('<div class="resumo">')
    for rotulo, valor, classe in fichas:
        partes.append(
            f'<div class="ficha {classe}"><span class="numero">{valor}</span>'
            f'<span class="rotulo">{rotulo}</span></div>'
        )
    partes.append("</div>")

    def _tabela(linhas):
        saida = [
            "<table><thead><tr>",
            "<th>N&ordm; do Processo</th><th>Tribunal / Se&ccedil;&atilde;o</th>",
            "<th>Movimenta&ccedil;&atilde;o (Origem)</th><th>Tarefa a Executar</th>",
            "<th>Prazo Limite</th><th>Urg&ecirc;ncia</th>",
            "</tr></thead><tbody>",
        ]
        for p in linhas:
            mov = p.movimentacao
            secao = mov.secao or mov.orgao_julgador
            cliente = (
                f'<span class="cliente">{_escapar(mov.cliente)}</span>' if mov.cliente else ""
            )
            prazo = _linha_prazo(p).replace("**", "")
            saida.append(
                f'<tr class="{p.urgencia}">'
                f'<td class="processo">{_escapar(formatar_cnj(mov.processo))}{cliente}</td>'
                f"<td>{_escapar(mov.tribunal_nome)}<br><small>{_escapar(secao)}</small></td>"
                f'<td>{_escapar(mov.texto[:220])}<br>'
                f'<span class="origem">{_escapar(mov.origem)}</span></td>'
                f'<td class="tarefa">{_escapar(p.tarefa)}</td>'
                f'<td class="prazo">{_escapar(prazo)}</td>'
                f'<td><span class="selo {p.urgencia}">{p.urgencia}</span></td>'
                "</tr>"
            )
        saida.append("</tbody></table>")
        return saida

    if com_data:
        partes.append("<h2>Prazos com data calculada</h2>")
        partes += _tabela(com_data)
    else:
        partes += [
            "<h2>Nenhum prazo com data calculada</h2>",
            '<div class="vazio">Nenhuma movimentacao trouxe o teor do ato, entao '
            "nenhuma data foi calculada.<br>Isso <strong>nao</strong> significa que nao "
            "ha prazo &mdash; significa que a fonte consultada nao permite afirmar.</div>",
        ]

    if a_verificar:
        partes += [
            "<h2>Movimenta&ccedil;&otilde;es a verificar &mdash; sem prazo calculado</h2>",
            '<div class="nota">Estes processos tiveram movimenta&ccedil;&atilde;o da parte '
            "contr&aacute;ria, do ju&iacute;zo ou do Minist&eacute;rio P&uacute;blico, mas a "
            "fonte informou apenas o <strong>nome</strong> do ato, n&atilde;o o seu teor. "
            "<strong>Nenhuma data foi calculada aqui.</strong> Abra cada processo e confira "
            "se h&aacute; prazo.</div>",
        ]
        partes += _tabela(a_verificar)

    agrupados: dict[str, list[str]] = {}
    for p in com_data:
        for alerta in p.alertas:
            agrupados.setdefault(alerta, []).append(formatar_cnj(p.movimentacao.processo))
    if agrupados:
        partes += ["<h2>Pontos a conferir antes de agendar</h2>", '<div class="aviso"><ul>']
        for alerta, afetados in sorted(agrupados.items(), key=lambda kv: -len(kv[1])):
            unicos = sorted(set(afetados))
            sufixo = (
                f" &mdash; <strong>{len(unicos)} processos</strong>"
                if len(unicos) > 4 else
                " &mdash; " + ", ".join(f"<code>{n}</code>" for n in unicos)
            )
            partes.append(f"<li>{_escapar(alerta)}{sufixo}</li>")
        partes.append("</ul></div>")

    if diagnostico:
        falhos = [d for d in diagnostico if not d.get("sucesso")]
        ok = len(diagnostico) - len(falhos)
        partes += [
            "<h2>Diagnostico da varredura</h2>",
            f"<p>Tribunais consultados com sucesso: <strong>{ok}/{len(diagnostico)}</strong></p>",
        ]
        if falhos:
            partes.append("<table><thead><tr><th>Tribunal</th><th>Via</th>"
                          "<th>Problema</th></tr></thead><tbody>")
            for d in falhos:
                partes.append(
                    f"<tr><td>{_escapar(d.get('tribunal_nome', ''))}</td>"
                    f"<td>{_escapar(d.get('fonte', ''))}</td>"
                    f"<td>{_escapar(str(d.get('mensagem', ''))[:200])}</td></tr>"
                )
            partes.append("</tbody></table>")

    partes += [
        '<p class="rodape">Relatorio gerado automaticamente das movimentacoes '
        "capturadas nos sistemas dos tribunais. As datas sao calculadas em dias "
        "uteis (CPC, arts. 219, 220 e 224) e <strong>nao dispensam a conferencia "
        "do prazo no proprio processo</strong> &mdash; feriados locais de comarca "
        "e suspensoes por portaria nao entram no calculo automatico.</p>",
        "</div>", "</body>", "</html>",
    ]
    return "\n".join(partes)
