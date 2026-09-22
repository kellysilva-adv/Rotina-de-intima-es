#!/usr/bin/env python3
"""Varredura diaria de acervo em 26 tribunais - Kelly Silva Advocacia.

Rotina completa:
  1. autentica com o certificado digital A1 (.pfx) via mTLS
  2. varre a aba ACERVO de cada tribunal (MNI, com fallback de raspagem)
  3. filtra movimentacoes da PARTE CONTRARIA, do TRIBUNAL/JUIZO e do MP
  4. grava as movimentacoes brutas em raw_movimentacoes.json
  5. calcula os prazos em dias uteis (CPC, arts. 219, 220 e 224)
  6. gera prazos_urgentes_diarios.md, do mais urgente para o menos urgente

Uso rapido:
  python3 varredura_tribunais.py --simular          # ve o relatorio sem rede
  python3 varredura_tribunais.py --validar-certificado
  python3 varredura_tribunais.py --testar-conectividade
  python3 varredura_tribunais.py                    # varredura completa
  python3 varredura_tribunais.py --processar        # so reprocessa o raw
  python3 varredura_tribunais.py --instalar-cron    # agenda 5h, seg a sex
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from core import cron as agendador
from core.adaptadores import (
    ADAPTADORES_HTML,
    AdaptadorDataJud,
    AdaptadorMNI,
    ResultadoVarredura,
)
from core.certificado import ErroCertificado, carregar_dotenv, obter_credencial, validar_certificado
from core.classificador import Classificador, ordenar_por_urgencia
from core.modelo import Movimentacao, Processo, normalizar_cnj
from core.prazos import RAMO_ESTADUAL, RAMO_FEDERAL, CalendarioForense, carregar_feriados_extras
from core.relatorio import gerar_markdown, salvar
from core.sessao import SessaoTribunal

# ------------------------------------------------------------------ caminhos
CONFIG_TRIBUNAIS = RAIZ / "config" / "tribunais.json"
CONFIG_REGRAS = RAIZ / "config" / "regras_prazos.json"
CONFIG_FERIADOS = RAIZ / "config" / "feriados.json"
CONFIG_SELETORES = RAIZ / "config" / "seletores_acervo.json"

ENTRADA_PROCESSOS = RAIZ / "relatorio_prazos.json"
SAIDA_RAW = RAIZ / "raw_movimentacoes.json"
SAIDA_MD = RAIZ / "prazos_urgentes_diarios.md"
SAIDA_JSON = RAIZ / "dados" / "prazos_urgentes_diarios.json"
HISTORICO = RAIZ / "dados" / "historico"
DIR_HTML = RAIZ / "dados" / "html"
DIR_LOGS = RAIZ / "logs"

log = logging.getLogger("varredura")


def configurar_log(silencioso: bool) -> None:
    DIR_LOGS.mkdir(exist_ok=True)
    formato = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
    manipuladores: list[logging.Handler] = [
        logging.FileHandler(DIR_LOGS / "varredura.log", encoding="utf-8")
    ]
    if not silencioso:
        manipuladores.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format=formato, handlers=manipuladores, force=True)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ------------------------------------------------------------------ carregar

def carregar_tribunais(apenas: list[str] | None = None) -> list[dict[str, Any]]:
    dados = json.loads(CONFIG_TRIBUNAIS.read_text(encoding="utf-8"))
    tribunais = [t for t in dados["tribunais"] if t.get("ativo", True)]
    if apenas:
        alvo = {a.lower() for a in apenas}
        tribunais = [t for t in tribunais if t["id"].lower() in alvo]
    return tribunais


def carregar_processos() -> list[Processo]:
    """Le relatorio_prazos.json - a lista de processos que o escritorio acompanha."""
    if not ENTRADA_PROCESSOS.exists():
        log.warning(
            "%s nao encontrado. Copie relatorio_prazos.exemplo.json e preencha "
            "com os seus processos.", ENTRADA_PROCESSOS.name,
        )
        return []
    try:
        dados = json.loads(ENTRADA_PROCESSOS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error("%s tem JSON invalido (linha %d): %s", ENTRADA_PROCESSOS.name, exc.lineno, exc.msg)
        return []

    bruto = dados.get("processos", dados) if isinstance(dados, dict) else dados
    processos: list[Processo] = []
    for item in bruto:
        if not isinstance(item, dict):
            continue
        proc = Processo.de_dict(item)
        if len(proc.numero) != 20:
            log.warning("Processo ignorado - numero CNJ invalido: %r", item.get("numero"))
            continue
        if not proc.tribunal_id:
            log.warning("Processo %s ignorado - sem 'tribunal_id'.", proc.numero_formatado)
            continue
        processos.append(proc)
    return processos


def ramo_do_tribunal(tribunal: dict[str, Any]) -> str:
    """Justica Federal tem feriados proprios (Lei 5.010/66) - precisa distinguir."""
    identificador = tribunal["id"].lower()
    if identificador.startswith(("trf", "jf")):
        return RAMO_FEDERAL
    return RAMO_ESTADUAL


def calendario_do_tribunal(tribunal: dict[str, Any]) -> CalendarioForense:
    return CalendarioForense(
        ramo=ramo_do_tribunal(tribunal),
        feriados_extras=carregar_feriados_extras(CONFIG_FERIADOS, tribunal["id"]),
    )


# ------------------------------------------------------------------ varredura

def varrer_tribunal(
    tribunal: dict[str, Any],
    processos: list[Processo],
    sessao: SessaoTribunal,
    credenciais_mni: tuple[str, str],
    dias: int,
    chave_datajud: str = "",
    fonte_forcada: str = "",
) -> ResultadoVarredura:
    """Tenta as tres vias, da mais rica para a mais disponivel.

    1. MNI    - traz o inteiro teor dos movimentos, mas exige credencial que
                nem todo tribunal libera para advogado.
    2. DataJud- nao exige login nenhum e funciona nos 26 tribunais, mas so traz
                metadados: diz QUE houve a movimentacao, nao o que ela diz.
    3. Raspagem da area logada - ultimo recurso, e so onde o perfil do sistema
                ja estiver mapeado.
    """
    tentativas: list[str] = []

    def via_mni() -> ResultadoVarredura:
        id_consultante, senha_consultante = credenciais_mni
        return AdaptadorMNI(tribunal, sessao, id_consultante, senha_consultante).varrer(
            processos, desde_dias=dias
        )

    def via_datajud() -> ResultadoVarredura:
        return AdaptadorDataJud(tribunal, sessao, chave_datajud).varrer(
            processos, desde_dias=dias
        )

    def via_html() -> ResultadoVarredura:
        classe = ADAPTADORES_HTML.get(tribunal["sistema"])
        if classe is None:
            vazio = ResultadoVarredura(
                tribunal_id=tribunal["id"], tribunal_nome=tribunal["nome"],
                sistema=tribunal["sistema"], fonte="html",
                mensagem=f"Sistema '{tribunal['sistema']}' sem adaptador de raspagem.",
            )
            return vazio
        return classe(tribunal, sessao, caminho_perfis=CONFIG_SELETORES).varrer(
            processos, desde_dias=dias
        )

    vias = {"mni": via_mni, "datajud": via_datajud, "html": via_html}

    if fonte_forcada:
        return vias[fonte_forcada]()

    ultimo: ResultadoVarredura | None = None
    for nome, via in vias.items():
        resultado = via()
        ultimo = resultado
        if resultado.sucesso and resultado.movimentacoes:
            if tentativas:
                resultado.mensagem += f" (antes: {'; '.join(tentativas)})"
            return resultado
        tentativas.append(f"{nome}: {resultado.mensagem}")
        log.info("[%s] %s sem retorno util - %s", tribunal["id"], nome, resultado.mensagem)

    assert ultimo is not None
    ultimo.mensagem = "; ".join(tentativas)
    return ultimo


def executar_varredura(args: argparse.Namespace) -> tuple[list[Movimentacao], list[dict[str, Any]]]:
    tribunais = carregar_tribunais(args.tribunal)
    if not tribunais:
        log.error("Nenhum tribunal ativo corresponde ao filtro informado.")
        return [], []

    todos_processos = carregar_processos()
    log.info("%d processos acompanhados | %d tribunais na varredura",
             len(todos_processos), len(tribunais))

    ambiente = dict(carregar_dotenv(RAIZ / ".env"))
    import os
    ambiente.update({k: v for k, v in os.environ.items() if v})
    credenciais_mni = (
        ambiente.get("MNI_ID_CONSULTANTE", ""),
        ambiente.get("MNI_SENHA_CONSULTANTE", ""),
    )
    if not credenciais_mni[0]:
        log.warning(
            "MNI_ID_CONSULTANTE nao configurado no .env - a consulta oficial por "
            "webservice sera pulada em todos os tribunais."
        )

    chave_datajud = ambiente.get("DATAJUD_API_KEY", "")

    # Sem certificado nao ha MNI nem raspagem, mas o DataJud continua de pe -
    # ele nao usa credencial nenhuma. Entao falta de certificado degrada a
    # varredura, nao a impede.
    credencial = None
    try:
        credencial = obter_credencial(RAIZ, args.certificado, permitir_prompt=not args.silencioso)
    except ErroCertificado as exc:
        if args.fonte == "datajud":
            log.info("Sem certificado (%s) - seguindo so pelo DataJud, que dispensa login.", exc)
        else:
            raise

    movimentacoes: list[Movimentacao] = []
    diagnostico: list[dict[str, Any]] = []

    with SessaoTribunal(credencial, timeout=args.timeout) as sessao:
        for i, tribunal in enumerate(tribunais, 1):
            do_tribunal = [p for p in todos_processos if p.tribunal_id == tribunal["id"]]
            log.info("[%2d/%d] %s - %d processos", i, len(tribunais), tribunal["id"], len(do_tribunal))
            try:
                resultado = varrer_tribunal(
                    tribunal, do_tribunal, sessao, credenciais_mni, args.dias,
                    chave_datajud=chave_datajud, fonte_forcada=args.fonte,
                )
            except Exception as exc:
                log.exception("[%s] erro nao tratado na varredura", tribunal["id"])
                resultado = ResultadoVarredura(
                    tribunal_id=tribunal["id"], tribunal_nome=tribunal["nome"],
                    sistema=tribunal["sistema"], fonte="erro",
                    mensagem=f"{type(exc).__name__}: {str(exc)[:200]}",
                )
            movimentacoes.extend(resultado.movimentacoes)
            diagnostico.append(resultado.para_dict())
            log.info("        -> %s", resultado.mensagem)

    return movimentacoes, diagnostico


def gravar_raw(movimentacoes: list[Movimentacao], diagnostico: list[dict[str, Any]]) -> None:
    SAIDA_RAW.write_text(
        json.dumps(
            {
                "gerado_em": datetime.now().isoformat(timespec="seconds"),
                "total_movimentacoes": len(movimentacoes),
                "diagnostico": diagnostico,
                "movimentacoes": [m.para_dict() for m in movimentacoes],
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    log.info("Movimentacoes brutas gravadas em %s", SAIDA_RAW.name)


# ---------------------------------------------------------------- processar

def processar(hoje: date | None = None) -> int:
    """Le raw_movimentacoes.json, calcula prazos e gera o relatorio final."""
    if not SAIDA_RAW.exists():
        log.error("%s nao encontrado. Rode a varredura antes.", SAIDA_RAW.name)
        return 1

    dados = json.loads(SAIDA_RAW.read_text(encoding="utf-8"))
    movimentacoes = [Movimentacao.de_dict(m) for m in dados.get("movimentacoes", [])]
    diagnostico = dados.get("diagnostico", [])

    classificador = Classificador(CONFIG_REGRAS)
    tribunais = {t["id"]: t for t in carregar_tribunais()}
    calendarios: dict[str, CalendarioForense] = {}
    hoje = hoje or date.today()

    prazos = []
    ignoradas = 0
    for mov in movimentacoes:
        tribunal = tribunais.get(mov.tribunal_id, {"id": mov.tribunal_id})
        if mov.tribunal_id not in calendarios:
            calendarios[mov.tribunal_id] = calendario_do_tribunal(tribunal)
        prazo = classificador.avaliar(mov, calendarios[mov.tribunal_id], hoje=hoje)
        if prazo is None:
            ignoradas += 1
            continue
        prazos.append(prazo)

    prazos = ordenar_por_urgencia(prazos)
    log.info("%d movimentacoes -> %d prazos (%d sem tarefa para o escritorio)",
             len(movimentacoes), len(prazos), ignoradas)

    markdown = gerar_markdown(prazos, diagnostico)
    salvar(SAIDA_MD, markdown, historico=HISTORICO)

    SAIDA_JSON.parent.mkdir(parents=True, exist_ok=True)
    SAIDA_JSON.write_text(
        json.dumps(
            {
                "gerado_em": datetime.now().isoformat(timespec="seconds"),
                "data_referencia": hoje.isoformat(),
                "total": len(prazos),
                "prazos": [p.para_dict() for p in prazos],
                "diagnostico": diagnostico,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    log.info("Relatorio gravado em %s", SAIDA_MD.name)
    return 0


# ------------------------------------------------------------------ comandos

def cmd_validar_certificado(args: argparse.Namespace) -> int:
    credencial = obter_credencial(RAIZ, args.certificado, permitir_prompt=not args.silencioso)
    info = validar_certificado(credencial)
    print("\nCertificado digital A1")
    print("-" * 52)
    for rotulo, chave in (
        ("Titular", "titular"), ("Emissor", "emissor"),
        ("Valido de", "valido_de"), ("Valido ate", "valido_ate"),
        ("Dias para vencer", "dias_para_vencer"), ("Vencido", "vencido"),
    ):
        print(f"{rotulo:<18}: {info[chave]}")
    print()
    if info["vencido"] == "sim":
        print("ATENCAO: certificado VENCIDO - a varredura vai falhar em todos os tribunais.")
        return 1
    if int(info["dias_para_vencer"]) < 30:
        print(f"AVISO: vence em {info['dias_para_vencer']} dias. Providencie a renovacao.")
    return 0


def cmd_testar_conectividade(args: argparse.Namespace) -> int:
    """Confere, um a um, se o portal e o endpoint MNI respondem."""
    tribunais = carregar_tribunais(args.tribunal)
    credencial = None
    try:
        credencial = obter_credencial(RAIZ, args.certificado, permitir_prompt=not args.silencioso)
    except ErroCertificado as exc:
        print(f"Sem certificado ({exc}). Testando apenas o alcance publico dos portais.\n")

    import os
    ambiente = dict(carregar_dotenv(RAIZ / ".env"))
    ambiente.update({k: v for k, v in os.environ.items() if v})
    chave_datajud = ambiente.get("DATAJUD_API_KEY", "")

    largura = max(len(t["id"]) for t in tribunais)
    ok_portal = ok_mni = ok_datajud = 0

    print(f"\n{'TRIBUNAL'.ljust(largura)}  {'DATAJUD (sem login)':<36}  "
          f"{'MNI (login/senha)':<30}  PORTAL")
    print("-" * (largura + 92))

    with SessaoTribunal(credencial, timeout=args.timeout) as sessao:
        for tribunal in tribunais:
            dj_ok, diag_dj = AdaptadorDataJud(tribunal, sessao, chave_datajud).testar()
            ok_datajud += dj_ok
            mni_ok, diag_mni = AdaptadorMNI(tribunal, sessao).testar_endpoint()
            ok_mni += mni_ok
            alcancavel, diag_portal = sessao.testar(tribunal["url_base"])
            ok_portal += alcancavel
            print(
                f"{tribunal['id'].ljust(largura)}  "
                f"{'OK  ' if dj_ok else 'FALHA'} {diag_dj[:30]:<30}  "
                f"{'OK  ' if mni_ok else 'FALHA'} {diag_mni[:24]:<24}  "
                f"{'OK' if alcancavel else 'FALHA'}"
            )

    total = len(tribunais)
    print("-" * (largura + 92))
    print(f"DataJud: {ok_datajud}/{total}  |  MNI: {ok_mni}/{total}  |  Portais: {ok_portal}/{total}")
    print(
        "\nCOMO LER ESTE RESULTADO"
        "\n  DataJud OK  -> esse tribunal ja pode ser varrido HOJE, sem certificado e"
        "\n                 sem senha. E a via que resolve o problema de login."
        "\n  MNI FALHA   -> esperado: os endpoints do cadastro foram montados pelo padrao"
        "\n                 de cada sistema e nao sao oficiais. Peca o WSDL ao tribunal e"
        "\n                 corrija 'endpoint_mni' em config/tribunais.json."
        "\n  Portal OK   -> o site responde, o que nao significa que o login automatico"
        "\n                 funcione: varios exigem assinatura por desafio (PjeOffice)."
    )
    return 0


def cmd_capturar_html(args: argparse.Namespace) -> int:
    tribunais = carregar_tribunais([args.capturar_html])
    if not tribunais:
        print(f"Tribunal '{args.capturar_html}' nao encontrado em config/tribunais.json.")
        return 1
    tribunal = tribunais[0]
    classe = ADAPTADORES_HTML.get(tribunal["sistema"])
    if classe is None:
        print(f"Sistema '{tribunal['sistema']}' sem adaptador de raspagem.")
        return 1

    credencial = obter_credencial(RAIZ, args.certificado, permitir_prompt=not args.silencioso)
    with SessaoTribunal(credencial, timeout=args.timeout) as sessao:
        adaptador = classe(tribunal, sessao, caminho_perfis=CONFIG_SELETORES)
        relatorio = adaptador.capturar_html(DIR_HTML)

    print(f"\nCaptura de {tribunal['nome']}\n" + "-" * 60)
    for arquivo in relatorio["arquivos"]:
        if "erro" in arquivo:
            print(f"  ERRO  {arquivo['url']} -> {arquivo['erro']}")
        else:
            print(f"  HTTP {arquivo['status']}  {arquivo['url']}\n         -> {arquivo['arquivo']}")
    if relatorio["tabelas"]:
        print("\nTabelas candidatas ao acervo:")
        for t in relatorio["tabelas"]:
            print(f"  id={t['id'] or '-':<28} class={t['class'] or '-':<28} linhas={t['linhas']}")
    print(
        f"\nAbra os arquivos em {DIR_HTML}/, ache a tabela do acervo e preencha o perfil "
        f"do sistema\n'{tribunal['sistema']}' em config/seletores_acervo.json (lembre de por "
        "'mapeado': true)."
    )
    return 0


def cmd_simular(args: argparse.Namespace) -> int:
    """Roda o pipeline inteiro com dados de exemplo, sem tocar na rede.

    Serve para conferir o formato do relatorio e ajustar as regras de prazo
    antes de ter o certificado e as credenciais MNI em maos.
    """
    exemplo = RAIZ / "dados" / "raw_movimentacoes.exemplo.json"
    if not exemplo.exists():
        log.error("Arquivo de exemplo ausente: %s", exemplo)
        return 1

    dados = json.loads(exemplo.read_text(encoding="utf-8"))
    dados = _resolver_datas_relativas(dados)
    SAIDA_RAW.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Modo simulacao: %d movimentacoes ficticias carregadas de %s",
             len(dados.get("movimentacoes", [])), exemplo.name)
    return processar()


def _resolver_datas_relativas(dados: dict[str, Any]) -> dict[str, Any]:
    """Converte '@-7' em data real e '@agora' no horario atual.

    O exemplo guarda deslocamentos em vez de datas fixas para a simulacao
    continuar mostrando urgencias plausiveis em qualquer dia que rodar.
    """
    from datetime import timedelta

    hoje = date.today()

    def resolver(valor: Any) -> Any:
        if not isinstance(valor, str) or not valor.startswith("@"):
            return valor
        if valor == "@agora":
            return datetime.now().isoformat(timespec="seconds")
        try:
            return (hoje + timedelta(days=int(valor[1:]))).isoformat()
        except ValueError:
            return valor

    def percorrer(no: Any) -> Any:
        if isinstance(no, dict):
            return {k: percorrer(v) for k, v in no.items()}
        if isinstance(no, list):
            return [percorrer(v) for v in no]
        return resolver(no)

    return percorrer(dados)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="varredura_tribunais.py",
        description="Varredura diaria de acervo em 26 tribunais - Kelly Silva Advocacia.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--certificado", help="caminho do .pfx (sobrepoe CAMINHO_CERTIFICADO do .env)")
    p.add_argument("--tribunal", action="append", help="limita a varredura a este id (repetivel)")
    p.add_argument("--dias", type=int, default=15, help="janela de movimentacoes, em dias (padrao: 15)")
    p.add_argument("--timeout", type=int, default=45, help="timeout por requisicao, em segundos")
    p.add_argument("--silencioso", action="store_true", help="modo cron: sem prompt e sem saida no terminal")
    p.add_argument("--fonte", choices=("mni", "datajud", "html"), default="",
                   help="forca uma unica via de captura (padrao: tenta as tres em ordem)")

    g = p.add_mutually_exclusive_group()
    g.add_argument("--processar", action="store_true", help="so reprocessa raw_movimentacoes.json")
    g.add_argument("--simular", action="store_true", help="roda com dados de exemplo, sem rede")
    g.add_argument("--validar-certificado", action="store_true", help="confere titular e validade do .pfx")
    g.add_argument("--testar-conectividade", action="store_true", help="testa portais e endpoints MNI")
    g.add_argument("--capturar-html", metavar="ID", help="salva o HTML logado para mapear seletores")
    g.add_argument("--instalar-cron", action="store_true", help="agenda 05:00, de segunda a sexta")
    g.add_argument("--remover-cron", action="store_true", help="remove o agendamento")
    g.add_argument("--status-cron", action="store_true", help="mostra o agendamento instalado")

    args = p.parse_args(argv)
    configurar_log(args.silencioso)

    try:
        if args.instalar_cron:
            ok, msg = agendador.instalar(RAIZ)
            print(msg)
            return 0 if ok else 1
        if args.remover_cron:
            ok, msg = agendador.remover(RAIZ)
            print(msg)
            return 0 if ok else 1
        if args.status_cron:
            print(agendador.status(RAIZ))
            return 0
        if args.simular:
            return cmd_simular(args)
        if args.processar:
            return processar()
        if args.validar_certificado:
            return cmd_validar_certificado(args)
        if args.testar_conectividade:
            return cmd_testar_conectividade(args)
        if args.capturar_html:
            return cmd_capturar_html(args)

        # Varredura completa.
        inicio = datetime.now()
        log.info("=== Varredura iniciada em %s ===", inicio.strftime("%d/%m/%Y %H:%M:%S"))
        movimentacoes, diagnostico = executar_varredura(args)
        gravar_raw(movimentacoes, diagnostico)
        codigo = processar()
        duracao = (datetime.now() - inicio).total_seconds()
        log.info("=== Varredura concluida em %.1fs ===", duracao)
        return codigo

    except ErroCertificado as exc:
        log.error("Certificado: %s", exc)
        return 2
    except KeyboardInterrupt:
        log.warning("Interrompido pela usuaria.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
