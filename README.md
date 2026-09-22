# Rotina de Intimações

Varredura automática do acervo em **26 tribunais**, todo dia útil às 5h, com
relatório de prazos urgentes calculados em dias úteis.

**Kelly Silva Advocacia** — Direito Previdenciário — Minaçu/GO

---

## O que a rotina faz

1. Busca as movimentações por três vias: **DataJud** (API pública do CNJ, sem
   login), **MNI** (webservice oficial) e raspagem da área logada com o
   **certificado A1** por mTLS.
2. Varre a aba **Acervo** de cada tribunal buscando movimentações novas.
3. Filtra só o que interessa: **parte contrária**, **juízo/tribunal** e **Ministério Público**.
4. Grava o bruto em `raw_movimentacoes.json`.
5. Calcula os prazos em **dias úteis** (CPC, arts. 219, 220 e 224).
6. Gera `prazos_urgentes_diarios.md` — tabela ordenada do mais urgente ao menos.

---

## Instalação

```bash
# 1. dependências
pip install -r requirements.txt

# 2. configuração (o .env NUNCA vai para o git)
cp .env.example .env
chmod 600 .env
# abra o .env e preencha o caminho do .pfx e a senha

# 3. seus processos
cp relatorio_prazos.exemplo.json relatorio_prazos.json
# abra e substitua pelos processos reais

# 4. confira que o certificado abre e não está vencido
python3 varredura_tribunais.py --validar-certificado

# 5. descubra quais tribunais respondem
python3 varredura_tribunais.py --testar-conectividade

# 6. agende às 5h, de segunda a sexta
python3 varredura_tribunais.py --instalar-cron
```

### Dependências

| Pacote | Para quê |
| :--- | :--- |
| `requests` | requisições HTTP |
| `requests-pkcs12` | injeta o `.pfx` na sessão TLS sem gravar a chave privada em disco |
| `cryptography` | abre o `.pfx` para conferir titular e validade |
| `beautifulsoup4` + `lxml` | leitura do HTML da área logada, onde o MNI não estiver liberado |

Tudo em uma linha:

```bash
pip install requests requests-pkcs12 cryptography beautifulsoup4 lxml
```

---

## Comandos

| Comando | O que faz |
| :--- | :--- |
| `python3 varredura_tribunais.py` | varredura completa e relatório |
| `--simular` | roda com dados fictícios, sem rede — para ver o formato da saída |
| `--processar` | só recalcula os prazos a partir do `raw_movimentacoes.json` |
| `--validar-certificado` | mostra titular, emissor e data de validade do `.pfx` |
| `--testar-conectividade` | testa as 3 vias nos 26 tribunais e salva `dados/conectividade.json` |
| `--capturar-html <id>` | salva o HTML da área logada para mapear os seletores |
| `--fonte datajud` | força uma via só: `datajud` (sem login), `mni` ou `html` |
| `--tribunal trf1` | limita a varredura a um tribunal (repetível) |
| `--dias 30` | amplia a janela de movimentações buscadas |
| `--instalar-cron` / `--remover-cron` / `--status-cron` | gerencia o agendamento |

Comece por `--simular`: ele mostra o relatório final sem exigir certificado,
credencial nem rede.

---

## Agendamento

```
0 5 * * 1-5   segunda a sexta, às 05:00
```

Instale com `--instalar-cron`. Para Windows e macOS, veja
[`docs/AGENDAMENTO.md`](docs/AGENDAMENTO.md).

Uma observação: o cron entende `1-5` como segunda a sexta, não como *dia útil
forense*. Em feriado nacional ele dispara assim mesmo. É de propósito — a
varredura roda, captura o que apareceu, e o cálculo de prazos já desconta o
feriado. Deixar de rodar seria pior que rodar a mais.

---

## Como a captura funciona — e a questão do login

A rotina tenta três vias, da mais rica para a mais disponível. Você pode forçar
uma delas com `--fonte datajud`, `--fonte mni` ou `--fonte html`.

### 1. DataJud — a via que dispensa login

A [API Pública do DataJud](https://datajud-wiki.cnj.jus.br/api-publica/) é a base
nacional do CNJ. **Não pede certificado digital nem usuário e senha** — autentica
com uma chave pública que o próprio CNJ divulga, igual para todo mundo. Cobre os
26 tribunais e já está cadastrada (`alias_datajud` em `config/tribunais.json`).

É por aqui que a varredura começa a funcionar hoje, sem configurar nada:

```bash
python3 varredura_tribunais.py --fonte datajud
```

**O que ela entrega:** número do processo, classe, órgão julgador e a lista de
movimentos com código da Tabela Processual Unificada, nome e data. Basta para
detectar *que* houve movimentação e *de que tipo* ela é.

**O que ela não entrega:** o texto do despacho. O DataJud guarda metadados, não
o inteiro teor. Ele diz "Juntada de Petição em 18/09", não diz o que o juiz
escreveu. Também não cobre processo em segredo de justiça, e a alimentação pelos
tribunais tem atraso (em regra diário).

Na prática: o DataJud detecta o prazo, você abre o processo para ler o ato.

### 2. MNI 2.2.2 — o webservice oficial do CNJ

Contrato SOAP público, o mesmo para PJe, eproc, e-SAJ e Projudi. Traz o inteiro
teor dos movimentos — é a via mais rica. Duas coisas precisam ser verdadeiras:

- o **endpoint** em `config/tribunais.json` precisa estar certo. Os 26 que deixei
  cadastrados foram montados pelo padrão de cada sistema e **não foram validados**
  (`"mni_verificado": false`). O `--testar-conectividade` diz quais respondem.
- o tribunal precisa **liberar o MNI para advogado**, com usuário e senha
  (`MNI_ID_CONSULTANTE` / `MNI_SENHA_CONSULTANTE`). Nem todo tribunal libera.

### 3. Raspagem da área logada — último recurso

**Os perfis ainda não estão mapeados**, e isso é deliberado. Cada tribunal tem
fluxo de login e tabela próprios. Chutar seletor devolveria lista vazia — e você
acharia que não há prazo quando há. Em vez disso, o adaptador **avisa no
relatório** que aquele tribunal não foi varrido, e por quê.

Para mapear: `python3 varredura_tribunais.py --capturar-html tjgo` salva o HTML
logado em `dados/html/`; preencha o perfil em `config/seletores_acervo.json` e
mude `"mapeado"` para `true`.

### Sobre o certificado A1 e o login automático

O certificado **nunca sai da sua máquina**. O script lê o `.pfx` em memória na
hora da requisição — não copia, não envia, não guarda. Por isso a varredura roda
no seu computador, não em um servidor remoto.

Vale saber que mTLS puro (que é o que o `requests_pkcs12` faz) **não resolve o
login de todos os sistemas**. Vários PJe e Projudi usam assinatura por
desafio — o servidor manda um dado aleatório, o cliente assina com a chave
privada e devolve. É para isso que existe o PjeOffice. Onde o tribunal exigir
esse fluxo, o login por requisição simples não passa, e a via prática passa a
ser DataJud ou MNI.

## Cálculo de prazos

Implementado em `core/prazos.py`, com 32 testes em `tests/test_prazos.py`:

- **CPC, art. 219** — prazos processuais em dias úteis
- **CPC, art. 224** — exclui o dia do começo, inclui o do vencimento; prorroga
  quando cai em dia sem expediente
- **CPC, art. 224, §§ 2º e 3º** — publicação = 1º dia útil após a
  disponibilização; contagem inicia no 1º dia útil seguinte à publicação
- **CPC, art. 220** — suspensão de 20/12 a 20/01
- **Lei 11.419/2006, art. 5º** — intimação eletrônica; sem registro de leitura,
  presume-se realizada no 10º dia corrido
- **Lei 5.010/1966, art. 62** — feriados próprios da Justiça Federal
- Feriados móveis calculados a partir da Páscoa (Carnaval, Sexta-feira da
  Paixão, Corpus Christi)

**O que o cálculo não sabe:** feriado municipal de comarca, feriado estadual e
suspensão por portaria do tribunal. Cadastre em `config/feriados.json`. E o
relatório sempre fecha lembrando: **confira a data no próprio processo antes
de mandar para a agenda.**

Rodar os testes:

```bash
python3 -m unittest discover -s tests -v
```

---

## Consolidação pelo Claude

O script faz o cálculo mecânico. A leitura jurídica — entender o que o juízo
determinou, separar tarefa de andamento, priorizar por consequência e não só
por data — está no prompt em
[`prompt_consolidacao_claude.md`](prompt_consolidacao_claude.md).

---

## Estrutura

```
varredura_tribunais.py          script principal (CLI)
core/
  modelo.py                     Processo, Movimentacao, PrazoCalculado
  prazos.py                     calendário forense e contagem em dias úteis
  classificador.py              origem da movimentação, tarefa e prazo
  relatorio.py                  geração do Markdown
  certificado.py                carga do .pfx e da senha
  sessao.py                     sessão HTTP com mTLS
  cron.py                       agendamento
  adaptadores/
    datajud.py                  API pública do DataJud (CNJ), sem login
    mni.py                      cliente SOAP do MNI 2.2.2 (CNJ)
    html.py                     raspagem da área logada, dirigida por config
config/
  tribunais.json                os 26 tribunais
  regras_prazos.json            regras de prazo e detecção de origem
  feriados.json                 feriados locais (você cadastra)
  seletores_acervo.json         perfis de raspagem por sistema
tests/test_prazos.py            testes do cálculo
```

### Arquivos de dados

| Arquivo | Papel |
| :--- | :--- |
| `relatorio_prazos.json` | **entrada** — processos acompanhados |
| `raw_movimentacoes.json` | **intermediário** — movimentações brutas capturadas |
| `prazos_urgentes_diarios.md` | **saída** — a tabela de prazos |
| `dados/prazos_urgentes_diarios.json` | mesma saída em JSON, para o Claude |
| `dados/historico/` | cópia datada de cada relatório |

---

## Segurança e sigilo

- Senha lida de variável de ambiente ou digitada com `getpass` — **nunca** no código.
- `CredencialCertificado` mascara a senha em `repr`, `str` e traceback, para não
  vazar em log.
- `.gitignore` bloqueia `.env`, `*.pfx`, `*.p12`, `*.pem`, `*.key` e todos os
  arquivos com dado de cliente (`relatorio_prazos.json`, `raw_movimentacoes.json`,
  `prazos_urgentes_diarios.md`, `dados/historico/`, `logs/`).
- A sessão respeita intervalo mínimo entre requisições ao mesmo tribunal.
  Varredura sem pausa em portal de tribunal vira bloqueio de IP — e, com
  certificado, bloqueio do certificado.

Só versione os arquivos `.exemplo.json`. Os reais têm dado de cliente e estão
cobertos pelo sigilo profissional (EOAB, art. 34, VII).

**Se a senha do certificado ficar no `.env` para o cron rodar sozinho**, o
arquivo dá acesso ao seu certificado digital. Mantenha `chmod 600` e não
sincronize a pasta do projeto com nuvem pública.
