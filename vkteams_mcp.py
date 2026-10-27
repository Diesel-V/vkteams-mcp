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

# Сессия из файла (перечитывается при каждом вызове, перезапуск не нужен).
# Пишется после входа во встроенном браузере Claude: {"aimsid": "...", "fetch_url": "..."}
SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vkteams_session.json")


def _load_session() -> None:
    global AIMSID, FETCH_URL
    try:
        import json
        with open(SESSION_FILE) as f:
            d = json.load(f)
        AIMSID = d.get("aimsid") or AIMSID
        FETCH_URL = (d.get("fetch_url") or FETCH_URL).split("?")[0]
    except FileNotFoundError:
        pass
    except Exception as e:
        raise ToolError(f"Не читается {SESSION_FILE}: {e}")


EXPIRED_HINT = ("Сессия VK Teams протухла. Войди в VK Teams во встроенном браузере Claude "
                "(myteam.mail.ru) и попроси Claude обновить сессию — перезапуск не нужен.")

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
    _load_session()
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


async def _fetch_events(timeout_ms: int = 1, max_rounds: int = 8) -> list[dict]:
    """Первый fetchEvents (first=1) + дочитывание по fetchBaseURL, пока идут события."""
    _check_env()
    if not FETCH_URL:
        raise ToolError("Не задан VKTEAMS_FETCH_URL (URL запроса fetchEvents из DevTools, без query)")
    h = {k: v for k, v in _headers().items() if k != "content-type"}
    events: list[dict] = []
    url, params = FETCH_URL, {"aimsid": AIMSID, "first": 1, "timeout": timeout_ms}
    alt = os.environ.get("VKTEAMS_FETCH_URL_FALLBACK", "")
    tried_alt = False
    async with httpx.AsyncClient(timeout=30) as c:
        for i in range(max_rounds):
            params["rnd"] = f"{time.time():.6f}"
            r = await c.get(url, params=params, headers=h)
            if r.status_code != 200:
                raise ToolError(f"fetchEvents: HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            resp = data.get("response", data)
            if resp.get("statusCode") == 460 and i == 0 and not tried_alt and alt and alt != url:
                tried_alt, url = True, alt
                continue
            if resp.get("statusCode") not in (None, 200):
                sc = resp.get('statusCode')
                raise ToolError(f"fetchEvents: {sc} {resp.get('statusText')}" + (f". {EXPIRED_HINT}" if sc in (401, 460, 607) else ""))
            d = resp.get("data") or {}
            batch = d.get("events") or []
            events.extend(batch)
            nxt = d.get("fetchBaseURL")
            if not nxt or (i > 0 and not batch):
                break
            url, params = nxt, {"timeout": 500 if i == 0 else timeout_ms}
    return events


@mcp.tool()
async def list_chats(query: str = "", limit: int = 30, unread_only: bool = False) -> dict:
    """Групповые чаты: непрочитанные, время и превью последнего сообщения, сортировка по свежести.
    Список чатов берётся из контакт-листа (fetchEvents), состояние — getHistory по 1 сообщению на чат.
    unread_only — только чаты с непрочитанными. query — фильтр по названию/sn."""
    import asyncio
    events = await _fetch_events(max_rounds=1)
    groups: dict[str, str] = {}
    for e in events:
        if e.get("type") != "buddylist":
            continue
        for g in (e.get("eventData") or {}).get("groups", []):
            for b in g.get("buddies", []):
                sn = b.get("aimId") or b.get("sn") or ""
                if sn.endswith("@chat.agent"):
                    groups[sn] = b.get("friendly") or b.get("displayId") or sn
    if query:
        q = query.lower()
        groups = {sn: nm for sn, nm in groups.items() if q in nm.lower() or q in sn.lower()}
    sem = asyncio.Semaphore(6)

    async def probe(sn: str, name: str) -> dict:
        row = {"sn": sn, "name": name}
        async with sem:
            try:
                res = await _rapi("getHistory", {"sn": sn, "fromMsgId": "-1", "count": -1, "lang": "ru",
                                                 "mentions": {"resolve": False}, "patchVersion": "init"})
            except Exception as ex:
                row["error"] = str(ex)[:120]
                row["_ts"] = 0
                return row
        row["unread"] = res.get("unreadCnt") or 0
        msgs = _fmt_messages(res)
        if msgs:
            m = msgs[-1]
            row.update({"last_time": m["time"], "last_from": m["sender"], "last_text": (m["text"] or "")[:200]})
            row["_ts"] = max((x.get("time", 0) for x in res.get("messages", [])), default=0)
        else:
            row["_ts"] = 0
        return row

    rows = await asyncio.gather(*(probe(sn, nm) for sn, nm in groups.items()))
    rows.sort(key=lambda r: r["_ts"], reverse=True)
    for r in rows:
        r.pop("_ts", None)
    if unread_only:
        rows = [r for r in rows if r.get("unread")]
    return {"total": len(rows), "unread_chats": sum(1 for r in rows if r.get("unread")), "chats": rows[:limit]}

@mcp.tool()
async def wim_call(method: str, params: dict | None = None, base: str = "") -> dict:
    """Служебный GET к WIM-слою под aimsid: {U_DOMAIN}/api/{ver}/wim/<method>.
    base — переопределить префикс целиком (напр. полный URL fetchEvents). Только для диагностики."""
    _check_env()
    url = (base.rstrip("/") + "/" + method.lstrip("/")) if base else f"{U_DOMAIN}/api/{API_VER}/wim/{method.lstrip('/')}"
    q = {"aimsid": AIMSID, "f": "json", "r": f"{next(_req_counter)}-{int(time.time())}"}
    q.update(params or {})
    h = {k: v for k, v in _headers().items() if k != "content-type"}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, params=q, headers=h)
    try:
        body = r.json()
    except Exception:
        body = r.text[:1500]
    if isinstance(body, dict):
        txt = __import__("json").dumps(body, ensure_ascii=False)
        if len(txt) > 6000:
            body = {"truncated": txt[:6000]}
    return {"url": url, "http": r.status_code, "body": body}


@mcp.tool()
async def mark_read(chats: list[str] | None = None, all_groups: bool = False,
                    exclude: list[str] | None = None) -> dict:
    """Отметить прочитанными. chats — список sn; all_groups=True — все групповые чаты с непрочитанными.
    exclude — sn или подстроки названий, которые не трогать. Личные чаты при all_groups не трогаются."""
    import asyncio
    targets: dict[str, str] = {sn: sn for sn in (chats or [])}
    if all_groups:
        res = await list_chats(limit=1000, unread_only=True)
        for c in res["chats"]:
            targets[c["sn"]] = c.get("name") or c["sn"]
    ex = [x.lower() for x in (exclude or [])]
    targets = {sn: nm for sn, nm in targets.items()
               if not any(x == sn.lower() or x in nm.lower() for x in ex)}
    sem = asyncio.Semaphore(6)

    async def one(sn: str, nm: str) -> dict:
        async with sem:
            try:
                h = await _rapi("getHistory", {"sn": sn, "fromMsgId": "-1", "count": -1, "lang": "ru",
                                               "mentions": {"resolve": False}, "patchVersion": "init"})
                last, unread = h.get("lastMsgId"), h.get("unreadCnt") or 0
                if last and unread:
                    await _rapi("setDlgState", {"sn": sn, "lastRead": str(last)})
                return {"name": nm, "sn": sn, "was_unread": unread}
            except Exception as e:
                return {"name": nm, "sn": sn, "error": str(e)[:120]}

    done = await asyncio.gather(*(one(sn, nm) for sn, nm in targets.items()))
    return {"marked": sum(1 for d in done if d.get("was_unread")),
            "total_unread_cleared": sum(d.get("was_unread") or 0 for d in done),
            "chats": done}


FILES_GET_PREFIX = os.environ.get("VKTEAMS_FILES_GET", "https://files.myteam.mail.ru/get/")


def _find_key(obj, keys):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and v:
                return v
        for v in obj.values():
            r = _find_key(v, keys)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, keys)
            if r:
                return r
    return None


async def _upload_file(target: str, filename: str, data: bytes) -> dict:
    """files/init → POST на выданный upload-URL → fileid / ссылка files.../get/<id>."""
    _check_env()
    q = {"aimsid": AIMSID, "ts": str(int(time.time())), "size": str(len(data)),
         "filename": filename, "client": "VKTeams", "target": target}
    h = {k: v for k, v in _headers().items() if k != "content-type"}
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(f"{U_DOMAIN}/api/{API_VER}/files/init", params=q, headers=h)
        try:
            init = r.json()
        except Exception:
            raise ToolError(f"files/init: HTTP {r.status_code}: {r.text[:300]}")
        res = init.get("result") or {}
        if r.status_code != 200 or not res.get("host") or not res.get("url"):
            raise ToolError(f"files/init: HTTP {r.status_code}: {str(init)[:300]}")
        up_url = f"https://{res['host']}{res['url']}"
        uh = dict(h)
        uh.update({
            "content-type": "application/octet-stream",
            "content-disposition": f'attachment; filename="{filename}"',
            "content-range": f"bytes 0-{len(data) - 1}/{len(data)}",
            "x-requested-with": "XMLHttpRequest",
        })
        u = await c.post(up_url, params={"aimsid": AIMSID}, content=data, headers=uh)
    try:
        up = u.json()
    except Exception:
        raise ToolError(f"files/upload: HTTP {u.status_code}: {u.text[:300]}")
    if u.status_code != 200:
        raise ToolError(f"files/upload: HTTP {u.status_code}: {str(up)[:300]}")
    link = _find_key(up, {"static_url", "staticUrl"})
    fid = _find_key(up, {"fileid", "fileId", "file_id"})
    if not link and fid:
        link = FILES_GET_PREFIX + fid
    if not link:
        raise ToolError(f"files/upload: в ответе нет fileid: {str(up)[:300]}")
    return {"fileid": fid, "url": link}


@mcp.tool()
async def send_file(target: str, filename: str, content_b64: str = "", path: str = "",
                    caption: str = "") -> dict:
    """Отправить файл. target: логин (x@company.ru) или '…@chat.agent'.
    Содержимое: content_b64 (base64) или path (локальный путь). caption — подпись отдельным сообщением.
    Отправляет от имени владельца аккаунта — вызывать только по явной просьбе пользователя."""
    import base64
    if content_b64:
        data = base64.b64decode(content_b64)
    elif path:
        with open(os.path.expanduser(path), "rb") as f:
            data = f.read()
    else:
        raise ToolError("Нужен content_b64 или path")
    if not data:
        raise ToolError("Пустой файл")
    up = await _upload_file(target, filename, data)
    sent = await _rapi("message/send", {"target": target,
                                        "parts": {"mainPart": {"text": {"plain": up["url"]}}}})
    out = {"file_url": up["url"], "fileid": up["fileid"], "sent": sent}
    if caption:
        out["caption"] = await _rapi("message/send", {"target": target,
                                                      "parts": {"mainPart": {"text": {"plain": caption}}}})
    return out


if __name__ == "__main__":
    mcp.run()
