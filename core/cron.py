"""Instalacao e remocao do agendamento no cron do sistema.

Agendamento pedido: todo dia util, as 05:00.
  0 5 * * 1-5

Observacao honesta sobre "dia util": o cron entende 1-5 como segunda a sexta,
nao como dia util forense - ele vai disparar tambem em feriado nacional e
durante a suspensao do art. 220 do CPC. Isso e proposital e e o comportamento
mais seguro: a varredura roda, captura o que apareceu e o calculo de prazos
ja considera o feriado. Deixar de rodar seria pior que rodar a mais.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

MARCADOR = "# [rotina-intimacoes] Kelly Silva Advocacia - varredura de acervo"
AGENDAMENTO = "0 5 * * 1-5"


def montar_linha(raiz: Path, python: str | None = None) -> str:
    """Monta a linha do crontab com caminhos absolutos."""
    interpretador = python or sys.executable or "python3"
    script = raiz / "varredura_tribunais.py"
    log = raiz / "logs" / "varredura.log"
    return (
        f"{AGENDAMENTO} cd {raiz} && {interpretador} {script} --silencioso "
        f">> {log} 2>&1"
    )


def _crontab_disponivel() -> bool:
    return shutil.which("crontab") is not None


def ler_crontab() -> str:
    resultado = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True, check=False
    )
    # Sem crontab ainda: o comando sai com codigo != 0 e stderr informativo.
    return resultado.stdout if resultado.returncode == 0 else ""


def escrever_crontab(conteudo: str) -> None:
    if not conteudo.endswith("\n"):
        conteudo += "\n"
    processo = subprocess.run(
        ["crontab", "-"], input=conteudo, text=True, capture_output=True, check=False
    )
    if processo.returncode != 0:
        raise RuntimeError(f"Falha ao gravar o crontab: {processo.stderr.strip()}")


def _sem_nossa_entrada(linhas: list[str]) -> list[str]:
    """Remove o marcador e a linha de agendamento que vem logo depois."""
    saida: list[str] = []
    pular_proxima = False
    for linha in linhas:
        if linha.strip() == MARCADOR:
            pular_proxima = True
            continue
        if pular_proxima:
            pular_proxima = False
            if "varredura_tribunais.py" in linha:
                continue
        if "varredura_tribunais.py" in linha:
            continue
        saida.append(linha)
    return saida


def instalar(raiz: Path, python: str | None = None) -> tuple[bool, str]:
    """Instala (ou atualiza) a entrada no crontab do usuario."""
    linha = montar_linha(raiz, python)

    if not _crontab_disponivel():
        return False, (
            "Comando 'crontab' nao encontrado neste sistema.\n"
            "No Windows, use o Agendador de Tarefas - veja docs/AGENDAMENTO.md.\n"
            f"Linha equivalente:\n  {linha}"
        )

    (raiz / "logs").mkdir(exist_ok=True)
    atual = ler_crontab()
    linhas = _sem_nossa_entrada(atual.splitlines())
    ja_existia = "varredura_tribunais.py" in atual

    while linhas and not linhas[-1].strip():
        linhas.pop()
    linhas += [MARCADOR, linha]

    try:
        escrever_crontab("\n".join(linhas))
    except RuntimeError as exc:
        return False, f"{exc}\nLinha a inserir manualmente com 'crontab -e':\n  {linha}"

    verbo = "atualizada" if ja_existia else "instalada"
    return True, f"Rotina {verbo} no cron:\n  {linha}"


def remover(raiz: Path) -> tuple[bool, str]:
    if not _crontab_disponivel():
        return False, "Comando 'crontab' nao encontrado neste sistema."
    atual = ler_crontab()
    if "varredura_tribunais.py" not in atual:
        return True, "Nenhuma entrada desta rotina estava instalada no cron."
    try:
        escrever_crontab("\n".join(_sem_nossa_entrada(atual.splitlines())))
    except RuntimeError as exc:
        return False, str(exc)
    return True, "Entrada removida do cron."


def status(raiz: Path) -> str:
    if not _crontab_disponivel():
        return "Comando 'crontab' indisponivel neste sistema."
    atual = ler_crontab()
    nossas = [l for l in atual.splitlines() if "varredura_tribunais.py" in l]
    if not nossas:
        return (
            "Rotina NAO instalada no cron.\n"
            "Instale com: python3 varredura_tribunais.py --instalar-cron"
        )
    return "Rotina instalada no cron:\n" + "\n".join(f"  {l}" for l in nossas)
