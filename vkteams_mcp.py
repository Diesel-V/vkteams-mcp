#!/usr/bin/env python3
"""MCP-сервер VK Teams под личным аккаунтом (неофициальный клиентский API веб-клиента).

Зависимости:  pip install "mcp[cli]" httpx

Переменные окружения:
  VKTEAMS_AIMSID    (обязательно) aimsid из тела любого rapi-запроса в DevTools
  VKTEAMS_SN        (обязательно) твой логин, напр. i.ivanov@company.ru
  VKTEAMS_U_DOMAIN  хост API, по умолчанию https://u.myteam.vmailru.net
  VKTEAMS_API_VER   версия API, по умолчанию v150
  VKTEAMS_BEARER    не нужен: rapi авторизуется одним aimsid (проверено).

Статус методов:
  get_history   — проверен вживую (rapi/getHistory, patchVersion обязателен)
  rapi_call     — общий вызов любого rapi-метода тем же способом
  send_message  — rapi/message/send, формат тела снят с реального трафика
"""
import itertools
import os
import time
from datetime import datetime, timezone

import httpx

try:
    from mcp.server.mcpserver.exceptions import ToolError  # mcp 2.x
except ImportError:
    try:
        from mcp.server.fastmcp.exceptions import ToolError  # mcp 1.x
    except ImportError:
        ToolError = RuntimeError
try:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp 2.x
except ImportError:
    from mcp.server.fastmcp import FastMCP  # mcp 1.x

AIMSID = os.environ.get("VKTEAMS_AIMSID", "")
SN = os.environ.get("VKTEAMS_SN", "")
U_DOMAIN = os.environ.get("VKTEAMS_U_DOMAIN", "https://u.myteam.vmailru.net").rstrip("/")
API_VER = os.environ.get("VKTEAMS_API_VER", "v150")
BEARER = os.environ.get("VKTEAMS_BEARER", "")

RAPI_BASE = f"{U_DOMAIN}/api/{API_VER}/rapi/"
# URL fetchEvents сессии: из DevTools, всё до "?" (напр. .../api/v150/bos/<server>/aim/fetchEvents)
FETCH_URL = os.environ.get("VKTEAMS_FETCH_URL", "")

_req_counter = itertools.count(1)
mcp = FastMCP("vkteams")


def _headers() -> dict:
    h = {
        "content-type": "application/json",
        "origin": "https://myteam.mail.ru",
        "referer": "https://myteam.mail.ru/",
        "x-req-sender-sn": SN,
    }
    if BEARER:
        h["authorization"] = f"Bearer {BEARER}"
    return h


def _check_env() -> None:
    if not AIMSID or not SN:
        raise ToolError("Не заданы VKTEAMS_AIMSID и/или VKTEAMS_SN")


async def _rapi(method: str, params: dict) -> dict:
    _check_env()
    body = {
        "reqId": f"{next(_req_counter)}-{int(time.time())}",
        "aimsid": AIMSID,
        "params": params,
    }
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(RAPI_BASE + method, json=body, headers=_headers())
    if r.status_code != 200:
        raise ToolError(f"rapi/{method}: HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    code = (data.get("status") or {}).get("code")
    if code != 20000:
        raise ToolError(f"rapi/{method}: status {code}: {data.get('status')}")
    return data.get("results") or {}


def _fmt_messages(res: dict) -> list[dict]:
    names = {p.get("sn"): p.get("friendly") or p.get("nick") for p in res.get("persons", [])}
    out = []
    for m in res.get("messages", []):
        chat = m.get("chat") or {}
        sender = chat.get("sender") or m.get("sender") or ("me" if m.get("outgoing") else None)
        text = "\n".join(p.get("text", "") for p in m.get("parts", []) if p.get("text"))
        if not text:
            text = m.get("text", "")
        out.append({
            "msgId": m.get("msgId"),
            "time": datetime.fromtimestamp(m.get("time", 0), tz=timezone.utc).isoformat(),
            "sender": names.get(sender, sender),
            "text": text,
            "thread": (m.get("thread") or {}).get("threadId"),
        })
    return out


@mcp.tool()
async def get_history(chat_sn: str, from_msg_id: str = "-1", count: int = -20,
                      patch_version: str = "init") -> dict:
    """История чата. chat_sn: '…@chat.agent' для группы или логин собеседника для лички.
    from_msg_id='-1' и отрицательный count — последние N сообщений.
    Для листания назад передай olderMsgId из прошлого ответа.
    patchVersion обязателен: 'init' для первого запроса."""
    params = {"sn": chat_sn, "fromMsgId": from_msg_id, "count": count,
              "lang": "ru", "mentions": {"resolve": False},
              "patchVersion": patch_version or "init"}
    res = await _rapi("getHistory", params)
    return {
        "messages": _fmt_messages(res),
        "olderMsgId": res.get("olderMsgId"),
        "newerMsgId": res.get("newerMsgId"),
        "lastMsgId": res.get("lastMsgId"),
        "unread": res.get("unreadCnt"),
        "patchVersion": res.get("patchVersion"),
    }


@mcp.tool()
async def rapi_call(method: str, params: dict) -> dict:
    """Произвольный rapi-метод, напр. 'getChatInfo', 'searchChatMembers', 'getCommonChats'."""
    return await _rapi(method, params)


@mcp.tool()
async def send_message(target: str, text: str) -> dict:
    """Отправить сообщение. target: логин собеседника (x@company.ru) или '…@chat.agent'.
    Отправляет от имени владельца аккаунта — вызывать только по явной просьбе пользователя."""
    params = {"target": target, "parts": {"mainPart": {"text": {"plain": text}}}}
    return await _rapi("message/send", params)


async def _fetch_events(timeout_ms: int = 1) -> list[dict]:
    _check_env()
    if not FETCH_URL:
        raise ToolError("Не задан VKTEAMS_FETCH_URL (URL запроса fetchEvents из DevTools, без query)")
    params = {"aimsid": AIMSID, "first": 1, "timeout": timeout_ms, "rnd": f"{time.time():.6f}"}
    h = {k: v for k, v in _headers().items() if k != "content-type"}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(FETCH_URL, params=params, headers=h)
    if r.status_code != 200:
        raise ToolError(f"fetchEvents: HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    resp = data.get("response", data)
    if resp.get("statusCode") not in (None, 200):
        raise ToolError(f"fetchEvents: {resp.get('statusCode')} {resp.get('statusText')}")
    return (resp.get("data") or {}).get("events") or []


@mcp.tool()
async def list_chats(query: str = "", limit: int = 100) -> dict:
    """Список чатов и контактов (из событий buddylist / histDlgState в fetchEvents).
    query — фильтр по названию или sn (без учёта регистра)."""
    events = await _fetch_events()
    chats: dict[str, dict] = {}
    for e in events:
        t, d = e.get("type"), e.get("eventData") or {}
        if t == "buddylist":
            for g in d.get("groups", []):
                for b in g.get("buddies", []):
                    sn = b.get("aimId") or b.get("sn")
                    if sn:
                        chats.setdefault(sn, {}).update({
                            "sn": sn, "name": b.get("friendly") or b.get("displayId") or sn,
                            "group": g.get("name"),
                            "type": "chat" if sn.endswith("@chat.agent") else "person"})
        elif t == "histDlgState":
            sn = d.get("sn")
            if sn:
                c = chats.setdefault(sn, {"sn": sn, "name": sn,
                                          "type": "chat" if sn.endswith("@chat.agent") else "person"})
                c["unread"] = d.get("unreadCnt")
                pers = {p.get("sn"): p.get("friendly") for p in d.get("persons", [])}
                if pers.get(sn):
                    c["name"] = pers[sn]
    if not chats:
        from collections import Counter
        return {"chats": [], "note": "в ответе нет buddylist/histDlgState",
                "event_types": dict(Counter(e.get("type") for e in events))}
    items = list(chats.values())
    if query:
        q = query.lower()
        items = [c for c in items if q in (c.get("name") or "").lower() or q in c["sn"].lower()]
    return {"total": len(items), "chats": items[:limit]}


if __name__ == "__main__":
    mcp.run()
