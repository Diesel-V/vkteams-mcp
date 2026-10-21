# vkteams-mcp

MCP-сервер для [VK Teams](https://teams.vk.com), работающий **от имени личного аккаунта** (не бота) — для Claude Desktop и любого другого MCP-клиента.

Официальный Bot API VK Teams не умеет читать историю и не видит личные чаты. Этот сервер ходит в тот же клиентский API (`rapi`), что и веб-версия VK Teams, поэтому видит всё, что видишь ты.

> ⚠️ Неофициальный API. Может сломаться при обновлении клиента VK Teams. Используется токен твоей сессии — перед использованием в корпоративном контуре согласуй с ИБ.

## Возможности

| Инструмент | Что делает |
|---|---|
| `get_history` | История чата или лички, с пагинацией и тредами; имена авторов подставляются из ответа |
| `send_message` | Отправка сообщения в личку или групповой чат |
| `rapi_call` | Произвольный метод `rapi/*` — для всего, что ещё не обёрнуто |

Проверено на облачном VK Teams (`myteam.mail.ru` / VK WorkSpace), API `v150`.

## Установка

Нужен Python 3.10+.

```bash
git clone https://github.com/Diesel-V/vkteams-mcp.git ~/mcp/vkteams-mcp
cd ~/mcp/vkteams-mcp
./setup.sh 'ТВОЙ_AIMSID' 'login@company.ru'
```

Скрипт создаёт venv, ставит зависимости, добавляет сервер `vkteams` в `claude_desktop_config.json` (старый конфиг сохраняется в `.bak`) и перезапускает Claude Desktop. Только macOS; на других ОС пропиши конфиг вручную (ниже).

### Где взять aimsid

1. Открой веб-версию VK Teams, F12 → Network, фильтр `rapi`.
2. Открой любой чат.
3. В любом запросе `rapi/...` во вкладке Payload будет поле `aimsid` — это оно.

aimsid действует до перелогина. После выхода из веб-сессии его нужно обновить.

### Ручная настройка

```json
{
  "mcpServers": {
    "vkteams": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/vkteams_mcp.py"],
      "env": {
        "VKTEAMS_AIMSID": "...",
        "VKTEAMS_SN": "login@company.ru"
      }
    }
  }
}
```

| Переменная | Обязательна | По умолчанию |
|---|---|---|
| `VKTEAMS_AIMSID` | да | — |
| `VKTEAMS_SN` | да | — |
| `VKTEAMS_U_DOMAIN` | нет | `https://u.myteam.vmailru.net` |
| `VKTEAMS_API_VER` | нет | `v150` |

Для on-premise инсталляции подставь свой `VKTEAMS_U_DOMAIN` (виден в DevTools как хост rapi-запросов).

## Как устроен API

- `POST {U_DOMAIN}/api/{ver}/rapi/<method>`, тело `{"reqId": "<n>-<unixtime>", "aimsid": "...", "params": {...}}`.
- Успех — `status.code == 20000` (не HTTP-код).
- `getHistory` требует `patchVersion` (для первого запроса — `"init"`).
- Отправка — `rapi/message/send` с `{"target": ..., "parts": {"mainPart": {"text": {"plain": ...}}}}`.
- Bearer-токен из веб-клиента не нужен, хватает aimsid.

## Безопасность

aimsid даёт полный доступ к аккаунту. Не коммить его, не вставляй в чаты. Если засветился — выйди из веб-сессии и зайди заново, старый токен станет недействительным.

## Лицензия

MIT
