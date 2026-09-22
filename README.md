# Rotina-de-intima-es
Atue como um Engenheiro de Software e Legaltech Developer sênior. Preciso que você configure uma automação completa de monitoramento processual no meu ambiente local de trabalho.
Atue como um Engenheiro de Software e Legaltech Developer sênior. Preciso que você configure uma automação completa de monitoramento processual no meu ambiente local de trabalho.

Siga estritamente as diretrizes abaixo para criar a solução:
ARQUITETURA DO SCRIPT DE VARREDURA:
   - Crie um script em Python chamado `varredura_tribunais.py`.
   - O script deve conter uma lista com as seguintes 26 URLs de tribunais fornecidas pelo usuário:
     * https://pje1g.trf1.jus.br/pje/
     * https://eproc.jfrj.jus.br/eproc/
     * https://eproc.jfes.jus.br/
     * https://pje1g.trf3.jus.br
     * https://eproc.jfsc.jus.br/eprocV2/
     * https://eproc.jfpr.jus.br
     * https://pje1g.trf5.jus.br/pje/
     * https://eproc1g.trf6.jus.br/
     * https://projudi.tjgo.jus.br/
     * https://pje.tjpa.jus.br/pje/
     * https://pje.tjmg.jus.br/pje
     * https://pje.tjma.jus.br/pje/
     * https://esaj.tjsp.jus.br/
     * https://eproc1g.tjsp.jus.br/eproc/
     * https://pje.tjmt.jus.br/pje/
     * https://projudi.tjpr.jus.br/projudi/
     * https://pje.tjes.jus.br/pje
     * https://esaj.tjms.jus.br/
     * https://tjrj.pje.jus.br/1g
     * https://eproc1g.tjrj.jus.br/
     * https://pje.tjba.jus.br/
     * https://pje.cloud.tjpe.jus.br/1g/
     * https://eproc1.tjto.jus.br/
     * https://projudi.tjam.jus.br/projudi/
     * https://pje1g.tjrn.jus.br/pje
     * https://pje.tjce.jus.br/pje1grau
   
LÓGICA DE CAPTURA (ABA ACERVO):
   - O script deve simular o acesso (ou interagir via MNI/API) para entrar na aba de ACERVO e varrer as Seções Judiciárias de cada Estado.
   - O foco da captura deve ser rastrear movimentações originadas por: Parte Contrária, Tribunal/Juízo e Ministério Público (MP).
   - Salve o retorno dessas movimentações brutas em um arquivo local chamado `raw_movimentacoes.json`.
AGENDAMENTO AUTOMÁTICO (CRON):
   - Escreva uma rotina (usando a biblioteca 'crontab' ou gerando o comando para o sistema operacional) para agendar a execução desse script TODO DIA ÚTIL, IMPRETERIVELMENTE ÀS 05:00 AM.
   - Configuração do Cron para dias úteis (segunda a sexta): `0 5 * * 1-5 python3 /caminho/do/seu/projeto/varredura_tribunais.py`
PROCESSAMENTO E CONSOLIDAÇÃO JURÍDICA:
   - Crie uma função de pós-processamento onde você (Claude) lerá o arquivo `raw_movimentacoes.json` gerado e aplicará inteligência jurídica para filtrar apenas os atos que geram prazos urgentes/relevantes (ex: intimações, despachos de especificação de provas, decisões liminares, prazos recursais).
   - Calcule os prazos limites com base nas regras do CPC (dias úteis).
SAÍDA LÍMPIDA E DIRETA:
   - Sobreviva ou atualize um arquivo final em Markdown chamado `prazos_urgentes_diarios.md`.
   - Exiba o resultado exclusivamente em formato de tabela limpa, ordenada pela maior urgência (prazos mais curtos primeiro):
| N° do Processo | Tribunal / Seção | Movimentação Relevante (Origem) | Tarefa Limpa a Executar | Prazo Limite | Urgência |
| :--- | :--- | :--- | :--- | :--- | :--- |

Gere o código necessário, configure o ambiente na minha pasta local e me diga quais dependências de Python precisaremos instalar.

Prepare o script 'varredura_tribunais.py' para autenticar nos sites utilizando um certificado digital A1 (.pfx) armazenado localmente.

Siga estas diretrizes de segurança:
1. Não armazene senhas hardcoded no código. Configure o script para ler a senha do certificado através de uma variável de ambiente chamada 'SENHA_CERTIFICADO_OAB' ou usando o módulo 'getpass' para digitação segura no terminal.
2. Utilize a biblioteca 'requests_pkcs12' para realizar as requisições HTTPS nos endpoints do eproc e PJe que aceitam autenticação por certificado mTLS.
3. Crie um arquivo '.env.example' indicando onde o usuário deve colocar o caminho do certificado local e a variável da senha, garantindo que o arquivo '.env' real seja incluído no '.gitignore' para nunca ser exposto.

Atue como especialista em automação jurídica e Legaltech. Vamos implementar o script 'varredura_tribunais.py' configurado para autenticação mTLS usando o meu certificado digital A1 (.pfx) local.

Instruções para o desenvolvimento do script:
CONFIGURAÇÃO DE SEGURANÇA LOCAL:
   - Use a biblioteca 'requests_pkcs12' para injetar o arquivo 'certificado.pfx' nas requisições HTTP destinadas aos 26 tribunais.
   - Para proteger a senha do certificado, use o módulo 'getpass' ou configure o script para ler de uma variável de ambiente local (ex: 'SENHA_CERTIFICADO'). Nunca deixe a senha exposta no código-fonte.
FLUXO DE VARREDURA (ABA ACERVO):
   - O script deve ler o arquivo local 'relatorio_prazos.json' para obter a lista de processos que eu acompanho.
   - Para cada tribunal da lista de 26 URLs, o script deve autenticar usando o certificado A1, acessar a área logada de "Acervo" / "Consulta Processual" e capturar as últimas movimentações.
   - Filtre especificamente as petições ou despachos vindos da Parte Contrária, do Tribunal/Juízo ou do Ministério Público (MP).
   - Salve as movimentações brutas encontradas em um arquivo temporário 'raw_movimentacoes.json'.
AGENDAMENTO (CRONJOB DIÁRIO):
   - Crie uma função secundária no script (ou um comando shell complementar) que adicione esta rotina no Cron do sistema operacional para rodar AUTOMATICAMENTE TODO DIA ÚTIL ÀS 05:00 AM:
     0 5 * * 1-5 python3 /caminho/do/seu/projeto/varredura_tribunais.py
ANÁLISE DE PRAZOS E RELATÓRIO LIMPO:
   - Após a varredura, processe o 'raw_movimentacoes.json'. Identifique termos que geram prazos (intimação, vista, réplica, prazo de X dias).
   - Calcule a data limite em dias úteis (conforme o CPC).
   - Gere e salve o arquivo final 'prazos_urgentes_diarios.md' com uma tabela limpa e direta contendo as colunas: | N° do Processo | Tribunal / Seção | Movimentação Relevante (Origem) | Tarefa Limpa a Executar | Prazo Limite | Urgência |.
Me forneça os comandos para instalar as dependências de Python necessárias (como requests-pkcs12) e o código estruturado.
