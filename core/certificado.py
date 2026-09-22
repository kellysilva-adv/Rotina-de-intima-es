"""Carga do certificado digital A1 (.pfx) e da senha, sem nada hardcoded.

Ordem de busca da senha:
  1. variavel de ambiente SENHA_CERTIFICADO_OAB
  2. variavel de ambiente SENHA_CERTIFICADO (alias aceito)
  3. arquivo .env na raiz do projeto (nao versionado)
  4. getpass no terminal - digitacao mascarada, so em execucao interativa

A senha nunca e escrita em log, em arquivo de saida nem em mensagem de erro.
"""

from __future__ import annotations

import getpass
import os
import sys
from dataclasses import dataclass
from pathlib import Path

VAR_SENHA_PRINCIPAL = "SENHA_CERTIFICADO_OAB"
VAR_SENHA_ALIAS = "SENHA_CERTIFICADO"
VAR_CAMINHO = "CAMINHO_CERTIFICADO"


class ErroCertificado(RuntimeError):
    """Problema de configuracao do certificado - mensagem segura para log."""


def carregar_dotenv(caminho: Path) -> dict[str, str]:
    """Leitor minimo de .env (KEY=VALOR). Evita dependencia extra."""
    valores: dict[str, str] = {}
    if not caminho.exists():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[chave.strip()] = valor
    return valores


@dataclass
class CredencialCertificado:
    """Par (arquivo .pfx, senha) usado nas requisicoes mTLS."""

    caminho_pfx: Path
    senha: str

    def __repr__(self) -> str:  # protege a senha em traceback e debug
        return f"CredencialCertificado(caminho_pfx={self.caminho_pfx!s}, senha='***')"

    __str__ = __repr__

    @property
    def bytes_pfx(self) -> bytes:
        return self.caminho_pfx.read_bytes()


def obter_credencial(
    raiz_projeto: Path,
    caminho_pfx: str | None = None,
    permitir_prompt: bool = True,
) -> CredencialCertificado:
    """Resolve caminho do .pfx e senha. Levanta ErroCertificado se faltar algo."""
    ambiente = dict(carregar_dotenv(raiz_projeto / ".env"))
    ambiente.update({k: v for k, v in os.environ.items() if v})

    bruto = caminho_pfx or ambiente.get(VAR_CAMINHO, "")
    if not bruto:
        raise ErroCertificado(
            f"Caminho do certificado nao informado. Defina {VAR_CAMINHO} no .env "
            "ou use --certificado /caminho/certificado.pfx"
        )

    pfx = Path(os.path.expanduser(bruto)).resolve()
    if not pfx.exists():
        raise ErroCertificado(f"Certificado nao encontrado em: {pfx}")
    if not pfx.is_file():
        raise ErroCertificado(f"O caminho do certificado nao e um arquivo: {pfx}")

    senha = ambiente.get(VAR_SENHA_PRINCIPAL) or ambiente.get(VAR_SENHA_ALIAS) or ""
    if not senha:
        if not permitir_prompt or not sys.stdin.isatty():
            # Caso do cron: nao ha terminal para digitar.
            raise ErroCertificado(
                f"Senha do certificado ausente. Em execucao nao interativa (cron) "
                f"defina {VAR_SENHA_PRINCIPAL} no arquivo .env do projeto."
            )
        senha = getpass.getpass(f"Senha do certificado A1 ({pfx.name}): ")
        if not senha:
            raise ErroCertificado("Senha vazia - operacao cancelada.")

    return CredencialCertificado(caminho_pfx=pfx, senha=senha)


def validar_certificado(credencial: CredencialCertificado) -> dict[str, str]:
    """Abre o .pfx e devolve titular, emissor e validade.

    Serve para a Kelly conferir, ANTES da varredura, se a senha esta correta e
    se o certificado nao venceu - erro classico que derruba a rotina das 5h.
    """
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography import x509
    except ImportError as exc:  # pragma: no cover
        raise ErroCertificado(
            "Biblioteca 'cryptography' nao instalada. Rode: pip install -r requirements.txt"
        ) from exc

    try:
        _, cert, _ = pkcs12.load_key_and_certificates(
            credencial.bytes_pfx, credencial.senha.encode("utf-8")
        )
    except ValueError as exc:
        raise ErroCertificado(
            "Nao foi possivel abrir o certificado. Senha incorreta ou arquivo .pfx invalido."
        ) from exc

    if cert is None:
        raise ErroCertificado("O arquivo .pfx nao contem certificado.")

    def _campo(nome: x509.ObjectIdentifier, alvo) -> str:
        try:
            return alvo.get_attributes_for_oid(nome)[0].value
        except (IndexError, AttributeError):
            return ""

    from datetime import datetime, timezone

    try:
        expira = cert.not_valid_after_utc
        inicio = cert.not_valid_before_utc
        agora = datetime.now(timezone.utc)
    except AttributeError:  # cryptography < 42
        expira = cert.not_valid_after
        inicio = cert.not_valid_before
        agora = datetime.utcnow()

    return {
        "titular": _campo(x509.NameOID.COMMON_NAME, cert.subject),
        "emissor": _campo(x509.NameOID.COMMON_NAME, cert.issuer),
        "valido_de": inicio.strftime("%d/%m/%Y"),
        "valido_ate": expira.strftime("%d/%m/%Y"),
        "dias_para_vencer": str((expira - agora).days),
        "vencido": "sim" if expira < agora else "nao",
    }
