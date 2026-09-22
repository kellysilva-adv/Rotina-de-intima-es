# Agendamento em outros sistemas

No Linux e no macOS, o próprio script instala a rotina:

```bash
python3 varredura_tribunais.py --instalar-cron
python3 varredura_tribunais.py --status-cron
python3 varredura_tribunais.py --remover-cron
```

A linha instalada é:

```
0 5 * * 1-5 cd /caminho/do/projeto && /usr/bin/python3 /caminho/do/projeto/varredura_tribunais.py --silencioso >> /caminho/do/projeto/logs/varredura.log 2>&1
```

O `--silencioso` é necessário: sem terminal, o script não pode pedir a senha
do certificado. Em execução por cron, a senha precisa estar no `.env`.

---

## Windows — Agendador de Tarefas

**Pelo PowerShell** (execute como administrador, ajustando os caminhos):

```powershell
$projeto = "C:\Users\Kelly\Rotina-de-intima-es"
$python  = "C:\Python311\python.exe"

$acao    = New-ScheduledTaskAction -Execute $python `
           -Argument "$projeto\varredura_tribunais.py --silencioso" `
           -WorkingDirectory $projeto

$gatilho = New-ScheduledTaskTrigger -Weekly `
           -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
           -At 5:00AM

$config  = New-ScheduledTaskSettingsSet -StartWhenAvailable `
           -DontStopOnIdleEnd -WakeToRun

Register-ScheduledTask -TaskName "Varredura Tribunais - Kelly Silva Advocacia" `
  -Action $acao -Trigger $gatilho -Settings $config `
  -Description "Varredura diaria do acervo em 26 tribunais, as 5h"
```

`-StartWhenAvailable` faz a tarefa rodar assim que o computador ligar, caso
estivesse desligado às 5h. `-WakeToRun` tenta acordar a máquina suspensa.

**Pela interface:** Agendador de Tarefas → Criar Tarefa → Disparadores →
Semanalmente, 05:00, segunda a sexta → Ações → Iniciar programa:

- Programa: `C:\Python311\python.exe`
- Argumentos: `varredura_tribunais.py --silencioso`
- Iniciar em: `C:\Users\Kelly\Rotina-de-intima-es`

Confira depois:

```powershell
Get-ScheduledTask -TaskName "Varredura Tribunais*" | Get-ScheduledTaskInfo
```

---

## macOS — launchd

O cron funciona no macOS, mas o launchd é mais confiável e roda mesmo que a
máquina tenha ficado suspensa. Crie
`~/Library/LaunchAgents/br.adv.kellysilva.varredura.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>br.adv.kellysilva.varredura</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/kelly/Rotina-de-intima-es/varredura_tribunais.py</string>
    <string>--silencioso</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/kelly/Rotina-de-intima-es</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>5</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>5</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>5</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>5</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>5</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key>
  <string>/Users/kelly/Rotina-de-intima-es/logs/varredura.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/kelly/Rotina-de-intima-es/logs/varredura.log</string>
</dict>
</plist>
```

Carregue:

```bash
launchctl load ~/Library/LaunchAgents/br.adv.kellysilva.varredura.plist
launchctl list | grep kellysilva
```

---

## Se o computador ficar desligado às 5h

O cron do Linux e do macOS **não** executa tarefas perdidas. Se a máquina do
escritório desliga à noite, use `anacron` no Linux, o `-StartWhenAvailable` no
Windows ou o launchd no macOS — todos recuperam a execução perdida.

Alternativa mais simples: deixe a varredura rodar na primeira vez que você
abrir o computador, chamando o script pelo autostart do sistema. Perder a
varredura de um dia significa perder um dia de prazo.

---

## Conferir se rodou

```bash
tail -40 logs/varredura.log
ls -la dados/historico/
```

Cada execução grava uma cópia datada do relatório em `dados/historico/`. Se a
data de hoje não estiver lá, a rotina não rodou.
