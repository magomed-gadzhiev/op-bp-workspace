---
name: pdm-debug-ssh
description: Use when an SSH-exec step in a sandbox run fails — replay returned exit 127 / "no matcher" / hung on host-key check; walks through capture/fixture diff, known_hosts and bastion JSONL to localize the cause. Применять, когда падает именно SSH-шаг. Triggers / триггеры — "the SSH step failed", "ssh exec returned 127 / no matcher", «упал SSH-шаг», «ssh вернул 127 / нет матчера». Anti-trigger: для общего разбора упавшего прогона (не SSH) — pdm-debug-failed-run.
---

# pdm-debug-ssh

## Цель
Расследовать неудачный SSH exec в sandbox-прогоне БП и довести до либо
исправленной фикстуры, либо записи в `decisions/`.

## Preconditions
- Sandbox-стенд поднят:
  `docker compose -f docker-compose.full.yml -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml ps`
- В руках: `bp_slug`, имя кейса/теста, который падает.

## Steps

1. **Получить точную команду и host из неудачного прогона.** Источники:
   - вывод `pdm test` (когда появится в Этапе 4)
   - JSONL replay-сервера: `docker logs pdm_ssh_replay --tail 100`

2. **Проверить host-key в known_hosts клиента.**
   ```bash
   docker exec pdm_ssh_replay ssh-keygen -lf /shared/host_keys/host_rsa_key.pub
   ```
   Алиас, под которым клиент ходит (`deploy.local`, `prod.local`, …),
   должен присутствовать в `known_hosts` с тем же отпечатком, что у
   replay-сервера. При разных fingerprint'ах — очистить known_hosts
   у клиента и пересобрать его из shared-volume.

3. **Найти матчер фикстуры.**
   ```bash
   ls .pdm/ssh-replay-fixtures/
   grep -A3 "command_matches" .pdm/ssh-replay-fixtures/ssh-*.yaml
   ```
   Сопоставить регулярку из `command_matches` с реальной командой из шага 1.
   Типичные ошибки: лишние/недостающие пробелы, незаэкранированные `.`/`/`,
   чувствительность к регистру, пропущенный named-group.

4. **Если фикстура отсутствует** — записать из имеющихся captures:
   ```bash
   ls .pdm/ssh-captures/<bp>/
   pdm fixtures record --bp <bp> --case <new-case> --protocol ssh --dry-run
   pdm fixtures record --bp <bp> --case <new-case> --protocol ssh
   pdm fixtures replay --bp <bp> --protocol ssh
   docker compose -f docker-compose.full.yml -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml restart pdm-egress-ssh-replay
   ```

5. **Если capture пустой** — проверить, что SSH-шаг БП действительно
   ходит через bastion (`docker logs pdm_ssh_bastion_<bp>`), а не напрямую
   в upstream. Симптом: bastion JSONL пустой, но ssh-target отвечает.
   Причина: в конфигурации SSH-клиента шага `host=` указывает на upstream,
   а не на bastion / алиас, который роутится на bastion.

6. **Перезапустить replay** после правки фикстур (он перечитывает только
   при старте):
   ```bash
   docker compose -f docker-compose.full.yml -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml restart pdm-egress-ssh-replay
   ```

## Red flags

- **«No matching host key type found.»** — у replay RSA, у клиента в
  config'е разрешены только `ssh-ed25519`. Добавить
  `HostKeyAlgorithms +ssh-rsa` в client config или сменить тип ключа в
  `ssh-host-keys-init/init.sh` (на ed25519) и пересоздать volume
  `ssh-host-keys`.
- **«Host key verification failed.»** — known_hosts содержит другой
  отпечаток. Очистить known_hosts у клиента и дать entrypoint'у
  пересобрать (см. шаг 2).
- **`exit 127` + «no fixture matched»** — матчер фикстуры не покрывает
  команду. См. шаг 3.
- **Hang на 10+ секунд** — bastion forward-таймаут (10s connect, 60s exec,
  см. `bastion.py:_forward_exec`). Проверить, что `BASTION_TARGET_HOST`
  доступен из bastion-контейнера; либо что используется replay (без
  forward).

## Postconditions

- Конкретная причина зафиксирована либо как добавленная/исправленная
  фикстура, либо как fix в коде BP-скрипта.
- Если открылась системная проблема (не покрывается фикстурой) — запись
  в `processes/<bp>/decisions/YYYY-MM-DD-ssh-<topic>.md` по каноническому
  формату `pdm:decision-format` (`status: asked`, `source: debug-ssh`).
