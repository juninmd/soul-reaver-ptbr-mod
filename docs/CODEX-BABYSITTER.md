# Babysitter do Codex

`tools/codex-babysitter.ps1` reanima uma sessão do Codex quando o limite de uso
(quota) é atingido, para o trabalho continuar sem supervisão. Padrão inspirado no
babysitter do agy (401 → relança; 429 → espera o reset).

## Comportamento

1. Enquanto existir uma sessão interativa do Codex (`codex --yolo`) em outra
   janela, o babysitter apenas espera — nunca interfere no trabalho do usuário.
2. Quando essa sessão termina, ele retoma a thread em modo headless:
   `codex exec --dangerously-bypass-approvals-and-sandbox --json resume <ThreadId> "<prompt>"`.
3. Se a saída indicar limite de uso, ele calcula a espera — horário de reset
   quando a mensagem traz `resets at HH:MM`/`try again at HH:MM`, senão um
   cooldown fixo — e tenta de novo.
4. Se a execução termina sem sinal de limite, o babysitter encerra.

Logs em `staging/codex-babysitter/` (`babysitter.log` + `round-*.log`).

## Uso

```powershell
pwsh -NoProfile -File tools/codex-babysitter.ps1 -ThreadId <uuid>
pwsh -NoProfile -File tools/codex-babysitter.ps1 -ThreadId <uuid> -DryRun   # só imprime o comando
```

Parâmetros: `-ProjectDir`, `-Prompt`, `-MaxRounds` (padrão 100),
`-PollSeconds` (60), `-LimitCooldownMinutes` (60), `-LogDir`.

A thread atual aparece em `~/.codex/session_index.jsonl` (campo `id`).

## Limites

- O babysitter morre junto com a sessão que o lançou; relance ao abrir uma nova.
- Se a TUI do Codex permanecer **aberta** mostrando o aviso de limite (em vez de
  encerrar), o babysitter continua esperando. Feche a TUI para ele retomar.
- O modo headless usa `--dangerously-bypass-approvals-and-sandbox`; só aponte para
  a thread e o diretório corretos.
- Nunca use Task Scheduler: inicia sem autenticação completa.
