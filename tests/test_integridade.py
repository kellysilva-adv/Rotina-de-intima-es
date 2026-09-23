"""Garante que nenhum arquivo necessario ao projeto fique fora do git.

POR QUE ESTE TESTE EXISTE
=========================
O .gitignore precisa bloquear certificado digital e dado de cliente. Um dos
padroes era 'certificado*', que casa em QUALQUER nivel de pasta - e engoliu o
core/certificado.py, o modulo que le o .pfx.

O git ignora em silencio: 'git add' nao reclama, 'git status' nao mostra. Na
maquina de quem escreveu o codigo tudo funciona, porque o arquivo esta la no
disco. Quem baixa o projeto recebe uma copia incompleta e so descobre na hora
de rodar, com um ModuleNotFoundError no meio da tela.

Este teste compara o disco com o que o git versiona e falha antes disso.
"""

import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Tudo aqui dentro precisa chegar a quem baixa o projeto.
PASTAS_OBRIGATORIAS = ("core", "config", "tests", "docs")
ARQUIVOS_OBRIGATORIOS = (
    "varredura_tribunais.py",
    "testar.bat",
    "varrer.bat",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "relatorio_prazos.exemplo.json",
    "dados/raw_movimentacoes.exemplo.json",
    "prompt_consolidacao_claude.md",
)


def git_disponivel() -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=RAIZ, capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def versionados() -> set[str]:
    r = subprocess.run(
        ["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True
    )
    return set(r.stdout.splitlines())


@unittest.skipUnless(git_disponivel(), "fora de um repositorio git")
class TestIntegridadeDoRepositorio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.no_git = versionados()

    def test_todo_codigo_fonte_esta_versionado(self):
        faltando = []
        for pasta in PASTAS_OBRIGATORIAS:
            for arquivo in sorted((RAIZ / pasta).rglob("*")):
                if not arquivo.is_file():
                    continue
                if "__pycache__" in arquivo.parts or arquivo.suffix == ".pyc":
                    continue
                relativo = arquivo.relative_to(RAIZ).as_posix()
                if relativo not in self.no_git:
                    faltando.append(relativo)

        self.assertEqual(
            faltando, [],
            "Arquivo(s) no disco mas FORA do git - quem baixar o projeto nao "
            "vai receber:\n  " + "\n  ".join(faltando) +
            "\n\nDescubra a causa com: git check-ignore -v <arquivo>",
        )

    def test_arquivos_essenciais_estao_versionados(self):
        faltando = [a for a in ARQUIVOS_OBRIGATORIOS if a not in self.no_git]
        self.assertEqual(faltando, [], f"Arquivos essenciais fora do git: {faltando}")

    def test_nenhum_segredo_foi_versionado(self):
        """O outro lado do mesmo risco: certificado ou dado de cliente no git."""
        proibidos = (".pfx", ".p12", ".pem", ".key", ".jks")
        vazados = [
            a for a in self.no_git
            if a.endswith(proibidos)
            or a == ".env"
            or a in ("relatorio_prazos.json", "raw_movimentacoes.json")
        ]
        self.assertEqual(
            vazados, [],
            f"SEGREDO OU DADO DE CLIENTE VERSIONADO: {vazados}. "
            "Remova com 'git rm --cached <arquivo>' e confira o .gitignore.",
        )

    def test_todo_modulo_importado_existe_no_disco(self):
        """Pega 'from core.x import y' apontando para modulo inexistente."""
        import re

        ausentes = []
        for arquivo in sorted(RAIZ.rglob("*.py")):
            if "__pycache__" in arquivo.parts or ".git" in arquivo.parts:
                continue
            texto = arquivo.read_text(encoding="utf-8")
            for modulo in re.findall(r"^\s*from\s+(core[\w.]*)\s+import", texto, re.M):
                caminho = RAIZ / Path(*modulo.split("."))
                if not (caminho.with_suffix(".py").exists() or (caminho / "__init__.py").exists()):
                    ausentes.append(f"{arquivo.relative_to(RAIZ).as_posix()} importa {modulo}")

        self.assertEqual(ausentes, [], "Import apontando para modulo inexistente:\n  "
                                       + "\n  ".join(ausentes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
