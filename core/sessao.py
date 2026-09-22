"""Sessao HTTP com autenticacao mTLS por certificado A1 (.pfx)."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.certificado import CredencialCertificado

log = logging.getLogger("varredura.sessao")

USER_AGENT = (
    "KellySilvaAdvocacia-RotinaIntimacoes/1.0 "
    "(monitoramento de acervo proprio; contato: kellysilva.advocacia2024@gmail.com)"
)

# Intervalo minimo entre requisicoes ao MESMO tribunal. Nao e firula: varredura
# sem pausa em portal de tribunal vira bloqueio de IP e, com certificado, vira
# bloqueio do certificado.
INTERVALO_MINIMO_SEG = 1.5


class SessaoTribunal:
    """requests.Session com o .pfx injetado e ritmo controlado.

    Usa requests_pkcs12 quando disponivel (le o .pfx direto, sem despejar a
    chave privada em disco). Se a lib nao estiver instalada, a sessao ainda
    funciona para endpoints publicos e avisa no log.
    """

    def __init__(
        self,
        credencial: CredencialCertificado | None = None,
        timeout: int = 45,
        verificar_tls: bool = True,
        tentativas: int = 3,
    ) -> None:
        self.credencial = credencial
        self.timeout = timeout
        self.verificar_tls = verificar_tls
        # No teste de conectividade, repetir um endpoint morto tres vezes com
        # espera crescente triplica a duracao sem mudar o resultado.
        self.tentativas = tentativas
        self._ultimo_acesso: dict[str, float] = {}
        self.mtls_ativo = False
        self.sessao = self._montar_sessao()

    def _montar_sessao(self) -> requests.Session:
        politica = Retry(
            total=self.tentativas,
            backoff_factor=2,          # 2s, 4s, 8s
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
        )

        if self.credencial is not None:
            try:
                from requests_pkcs12 import Pkcs12Adapter

                sessao = requests.Session()
                adaptador = Pkcs12Adapter(
                    pkcs12_data=self.credencial.bytes_pfx,
                    pkcs12_password=self.credencial.senha,
                    max_retries=politica,
                )
                sessao.mount("https://", adaptador)
                self.mtls_ativo = True
                log.info("Sessao mTLS ativa (certificado A1 carregado em memoria).")
            except ImportError:
                log.warning(
                    "requests_pkcs12 nao instalado - seguindo SEM mTLS. "
                    "Instale com: pip install requests-pkcs12"
                )
                sessao = requests.Session()
                sessao.mount("https://", HTTPAdapter(max_retries=politica))
            except Exception as exc:
                # Mensagem generica de proposito: nao deixar a senha vazar no log.
                log.error("Falha ao carregar o certificado na sessao: %s", type(exc).__name__)
                raise
        else:
            sessao = requests.Session()
            sessao.mount("https://", HTTPAdapter(max_retries=politica))

        sessao.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9",
        })
        return sessao

    def _respeitar_ritmo(self, url: str) -> None:
        host = requests.utils.urlparse(url).netloc
        agora = time.monotonic()
        anterior = self._ultimo_acesso.get(host)
        if anterior is not None:
            espera = INTERVALO_MINIMO_SEG - (agora - anterior)
            if espera > 0:
                time.sleep(espera)
        self._ultimo_acesso[host] = time.monotonic()

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        self._respeitar_ritmo(url)
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("verify", self.verificar_tls)
        return self.sessao.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        self._respeitar_ritmo(url)
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("verify", self.verificar_tls)
        return self.sessao.post(url, **kwargs)

    def testar(self, url: str) -> tuple[bool, str]:
        """Bate no endpoint e devolve (alcancavel, diagnostico)."""
        try:
            resp = self.get(url, allow_redirects=True)
            return True, f"HTTP {resp.status_code} ({len(resp.content)} bytes)"
        except requests.exceptions.ProxyError:
            return False, "Bloqueado pelo proxy da rede"
        except requests.exceptions.SSLError as exc:
            return False, f"Erro TLS: {str(exc)[:120]}"
        except requests.exceptions.ConnectTimeout:
            return False, "Timeout de conexao"
        except requests.exceptions.ReadTimeout:
            return False, "Timeout de leitura"
        except requests.exceptions.ConnectionError as exc:
            return False, f"Falha de conexao: {str(exc)[:120]}"
        except requests.exceptions.RequestException as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:120]}"

    def fechar(self) -> None:
        self.sessao.close()

    def __enter__(self) -> "SessaoTribunal":
        return self

    def __exit__(self, *_: Any) -> None:
        self.fechar()
