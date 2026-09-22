"""Importacao do acervo a partir da planilha de controle do escritorio.

A planilha da Kelly e organizada em blocos por tribunal, com as colunas
NUMERO PROCESSO | NOME DO CLIENTE | FASE PROCESSUAL | LINK | INTIMACOES.

Tres decisoes que importam aqui:

1) O numero e aceito pelo DIGITO VERIFICADOR, nao pelo formato. Assim um
   '1008798-31-2020.4.01.3600' (ponto trocado por traco) entra, e um numero
   truncado ou digitado errado fica de fora com aviso, em vez de virar uma
   consulta silenciosa a processo que nao existe.

2) Quando o codigo CNJ aponta para mais de um cadastro - o TJSP roda e-SAJ e
   eproc, o TRF2 atende RJ e ES -, a duvida e resolvida pela URL da propria
   linha e, se faltar, pelo titulo do bloco.

3) SENHA NAO E IMPORTADA. A planilha tem senha anotada em coluna de
   observacao; o importador detecta, descarta o texto e avisa. Senha de
   sistema de tribunal nao tem por que existir em arquivo de projeto.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from core.modelo import (
    Processo,
    digito_verificador_valido,
    formatar_cnj,
    inferir_tribunal,
    normalizar_cnj,
)

# Tolerante com o separador, rigoroso com o digito verificador depois.
RE_NUMERO = re.compile(r"\b\d{7}[-.\s]?\d{2}[-.\s]?\d{4}[-.\s]?\d[-.\s]?\d{2}[-.\s]?\d{4}\b")
RE_URL = re.compile(r"https?://[^\s|)\\]+")

# Qualquer coisa que cheire a credencial nao entra no projeto.
RE_SENHA = re.compile(
    r"(senha|password|pass|login|usuario|user|token|credencial)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


@dataclass
class ResultadoImportacao:
    processos: list[dict[str, Any]] = field(default_factory=list)
    ambiguos: list[tuple[str, list[str]]] = field(default_factory=list)
    fora_do_escopo: list[tuple[str, str]] = field(default_factory=list)
    invalidos: list[tuple[int, str]] = field(default_factory=list)
    secao_desconhecida: list[tuple[str, str, str]] = field(default_factory=list)
    duplicados: int = 0
    senhas_descartadas: list[int] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.processos)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento.upper()).strip()


def _limpar(celula: str) -> str:
    """Tira escapes de Markdown e espaco sobrando que a exportacao deixa."""
    texto = re.sub(r"\\(.)", r"\1", celula or "")
    return re.sub(r"\s+", " ", texto).strip()


def tribunal_por_subsecao(numero: str, candidatos: list[str], tribunais: list[dict]) -> list[str]:
    """Desempata dentro de uma regiao federal pelo codigo de subsecao.

    Uma regiao do TRF atende mais de um estado, e as ultimas quatro posicoes do
    numero CNJ dizem qual: no TRF4, 70xx e Parana, 71xx e Rio Grande do Sul e
    72xx e Santa Catarina. Isso resolve sozinho o que a URL da planilha nem
    sempre diz.
    """
    d = normalizar_cnj(numero)
    if len(d) != 20:
        return []
    prefixo = d[16:18]
    por_id = {t["id"]: t for t in tribunais}
    achados = [
        c for c in candidatos
        if prefixo in (por_id.get(c, {}).get("subsecoes") or [])
    ]
    return achados


def tribunal_por_url(texto: str, tribunais: list[dict]) -> list[str]:
    """Casa o host de uma URL da linha com o url_base de um tribunal."""
    hosts = {urlparse(u).netloc.lower() for u in RE_URL.findall(texto or "")}
    if not hosts:
        return []
    achados = []
    for t in tribunais:
        host_cadastrado = urlparse(t["url_base"]).netloc.lower()
        if host_cadastrado and host_cadastrado in hosts:
            achados.append(t["id"])
    return achados


def tribunal_por_titulo(titulo: str, tribunais: list[dict]) -> list[str]:
    """Casa um titulo de bloco ('TRF 1', 'TJSP ESAJ') com o cadastro."""
    alvo = _normalizar(titulo).replace(" ", "")
    if not alvo:
        return []
    achados = []
    for t in tribunais:
        sigla = _normalizar(t["id"]).replace("_", "").replace(" ", "")
        if sigla and sigla in alvo:
            achados.append(t["id"])
    if achados:
        return achados
    # Segunda chance: so a sigla do tribunal, sem o sufixo do sistema.
    for t in tribunais:
        base = _normalizar(t["id"].split("_")[0])
        if base and base in alvo:
            achados.append(t["id"])
    return achados


def _e_cabecalho(celulas: list[str]) -> bool:
    return any("NUMERO PROCESSO" in _normalizar(c) for c in celulas)


def _e_titulo_de_bloco(celulas: list[str]) -> str:
    """Devolve o titulo se a linha for um cabecalho de bloco de tribunal."""
    preenchidas = [c for c in celulas if c.strip()]
    if len(preenchidas) != 1:
        return ""
    texto = _limpar(preenchidas[0])
    if RE_NUMERO.search(texto):
        return ""
    normalizado = _normalizar(texto)
    if re.search(r"\b(TRF|TJ|JF)\s?\d?", normalizado):
        return texto
    return ""


def importar_tabela(texto: str, tribunais: list[dict]) -> ResultadoImportacao:
    """Le a planilha exportada em tabela e devolve os processos encontrados."""
    resultado = ResultadoImportacao()
    por_numero: dict[str, dict[str, Any]] = {}
    bloco_atual = ""

    for n_linha, linha in enumerate(texto.split("\n"), 1):
        if "|" not in linha:
            continue
        celulas = [_limpar(c) for c in linha.split("|")]
        celulas = celulas[1:-1] if len(celulas) > 2 else celulas

        if _e_cabecalho(celulas) or all(re.fullmatch(r":?-+:?", c or "-") for c in celulas):
            continue

        titulo = _e_titulo_de_bloco(celulas)
        if titulo:
            bloco_atual = titulo
            continue

        primeira = celulas[0] if celulas else ""
        achado = RE_NUMERO.search(primeira)
        if not achado:
            continue

        numero = normalizar_cnj(achado.group(0))
        if not digito_verificador_valido(numero):
            resultado.invalidos.append((n_linha, primeira[:40]))
            continue

        linha_toda = " ".join(celulas)
        if RE_SENHA.search(linha_toda):
            resultado.senhas_descartadas.append(n_linha)
            linha_toda = RE_SENHA.sub("[credencial removida]", linha_toda)
            celulas = [RE_SENHA.sub("[credencial removida]", c) for c in celulas]

        candidatos = inferir_tribunal(numero, tribunais)
        if not candidatos:
            resultado.fora_do_escopo.append((formatar_cnj(numero), f"{numero[13]}.{numero[14:16]}"))
            continue

        if len(candidatos) > 1:
            # Ordem das pistas: o proprio numero primeiro, porque nao depende
            # de como a planilha foi preenchida; depois a URL da linha e, por
            # ultimo, o titulo do bloco.
            for pista in (tribunal_por_subsecao(numero, candidatos, tribunais),
                          tribunal_por_url(linha_toda, tribunais),
                          tribunal_por_titulo(bloco_atual, tribunais)):
                restritos = [c for c in candidatos if c in pista]
                if len(restritos) == 1:
                    candidatos = restritos
                    break
            else:
                # Sobrou ambiguidade de verdade. Se a regiao federal atende um
                # estado que NAO esta entre os 26 cadastrados, isso precisa ser
                # dito - e o caso do RS no TRF4.
                por_id = {t["id"]: t for t in tribunais}
                tem_subsecao = any(por_id.get(c, {}).get("subsecoes") for c in candidatos)
                if tem_subsecao:
                    resultado.secao_desconhecida.append(
                        (formatar_cnj(numero), numero[16:20], candidatos[0])
                    )

        cliente = celulas[1] if len(celulas) > 1 else ""
        fase = celulas[2] if len(celulas) > 2 else ""

        registro = {
            "numero": formatar_cnj(numero),
            "tribunal_id": candidatos[0],
            "cliente": cliente,
            "orgao_julgador": "",
            "classe": "",
            "beneficio": "",
            "observacao": fase,
        }
        if len(candidatos) > 1:
            registro["tribunal_alternativo"] = candidatos[1:]
            resultado.ambiguos.append((formatar_cnj(numero), candidatos))

        if numero in por_numero:
            resultado.duplicados += 1
            # Fica a linha com mais informacao preenchida.
            anterior = por_numero[numero]
            if len(f"{cliente}{fase}") <= len(f"{anterior['cliente']}{anterior['observacao']}"):
                continue
        por_numero[numero] = registro

    resultado.processos = list(por_numero.values())
    return resultado
