"""iR (ir-japan.net) の BMW/MINI 在庫から
F54 クラブマン クーパーS・支払総額200万円以下 を監視し、
新着 / 値下げ / 掲載終了 を ntfy でスマホに通知する。
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

BASE = "https://ir-japan.net/stocks/bmw/"
MAX_PRICE = 2_000_000          # 支払総額の上限（円）
TARGET_CODE = "F54"
STATE_FILE = "state.json"
STATUS_FILE = "STATUS.md"
MAX_PAGES = 60
JST = timezone(timedelta(hours=9))
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
UA = {"User-Agent": "Mozilla/5.0 (personal stock watcher; 1-2 checks/day)"}

ID_RE = re.compile(r"stocks/bmw/(\d+)\.html")


def page_url(n):
    return BASE if n == 1 else f"{BASE}page/{n}/?paged={n}"


def fetch(url):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:  # noqa
            if attempt == 2:
                raise
            time.sleep(5)


def card_for(anchor):
    """リンクから親をたどり、支払総額を含み かつ 他の車両IDを含まない最小の要素を返す"""
    my_id = ID_RE.search(anchor["href"]).group(1)
    node = anchor
    for _ in range(20):
        node = node.parent
        if node is None:
            return None
        ids = {ID_RE.search(a["href"]).group(1)
               for a in node.find_all("a", href=ID_RE)}
        if len(ids) > 1 or my_id not in ids:
            return None
        if "支払総額" in re.sub(r"\s+", "", node.get_text()):
            return node
    return None


def parse_card(car_id, node):
    text = re.sub(r"\s+", " ", node.get_text(" ")).strip()
    compact = re.sub(r"\s+", "", node.get_text())
    m_price = re.search(r"支払総額[^\d]{0,10}([\d,]+(?:\.\d+)?)万円", compact)
    if not m_price:
        return None
    price = round(float(m_price.group(1).replace(",", "")) * 10000)
    m_code = re.search(r"モデル\s*([A-Z]\d{2})", text) or re.search(r"\b([FRUG]\d{2})\b", text)
    code = m_code.group(1) if m_code else ""
    head = text.split("モデル")[0]            # 車名・装備部分
    m_name = re.search(r"(ミニ\S+)\s+((?:クーパー|ワン|ジョン|JCW)\s?\S*)((?:\s+(?:ALL4|\S+ED|\S*エディション|ワンオーナー))*)", head)
    name = " ".join(x.strip() for x in m_name.groups() if x and x.strip()) if m_name else head[:40]
    m_color = re.search(r"ボディカラー\s*([^/／]+?)\s*(?:[/／]|ミッション|年式|$)", text)
    m_year = re.search(r"(\d{4})年式", text)
    m_km = re.search(r"([\d,]+)km", compact)
    return {
        "id": car_id,
        "name": name,
        "code": code,
        "color": m_color.group(1).strip() if m_color else "",
        "year": int(m_year.group(1)) if m_year else None,
        "km": int(m_km.group(1).replace(",", "")) if m_km else None,
        "price": price,
        "url": f"{BASE}{car_id}.html",
    }


def is_target(car):
    if car["code"] != TARGET_CODE:
        return False
    # クーパーS（クーパーSD・SE は除外、ALL4 などの付記は可）
    if not re.search(r"クーパー\s?S(?![A-Za-z])", car["name"]):
        return False
    return car["price"] <= MAX_PRICE


def debug_dump(html, soup):
    links = soup.find_all("a", href=ID_RE)
    print("=== DEBUG ===")
    print("html length:", len(html), " 支払総額 count:", html.count("支払総額"),
          " 総額 count:", html.count("総額"), " detail links:", len(links))
    print("sample hrefs:", [a.get("href") for a in soup.find_all("a", href=True)][:60])
    for key in ("支払総額", "総額", "F55", "クーパー"):
        i = html.find(key)
        if i >= 0:
            print(f"--- around '{key}' ---")
            print(html[max(0, i - 2500): i + 800])
            break
    else:
        print("--- head of html ---")
        print(html[:4000])
    print("=== END DEBUG ===")


def scrape_all():
    cars, n = {}, 1
    while n <= MAX_PAGES:
        html = fetch(page_url(n))
        soup = BeautifulSoup(html, "html.parser")
        found = 0
        for a in soup.find_all("a", href=ID_RE):
            car_id = ID_RE.search(a["href"]).group(1)
            if car_id in cars:
                continue
            node = card_for(a)
            if node is None:
                continue
            car = parse_card(car_id, node)
            if car:
                cars[car_id] = car
                found += 1
        print(f"page {n}: +{found} (total {len(cars)})")
        if n == 1 and found == 0:
            debug_dump(html, soup)
        if "これ以上は車両がありません" in html and "Next Page" not in html and found == 0:
            break
        if not re.search(rf"/page/{n + 1}/", html):
            break
        n += 1
        time.sleep(2)
    return cars


def man(yen):
    return f"{yen / 10000:.1f}万円"


def desc(c):
    parts = [c["name"]]
    if c.get("color"):
        parts.append(c["color"])
    if c.get("year"):
        parts.append(f"{c['year']}年")
    if c.get("km") is not None:
        parts.append(f"{c['km'] / 10000:.1f}万km")
    return " ".join(parts)


def notify(title, message, click=None, tags=None):
    print(f"[notify] {title}\n{message}\n")
    if not NTFY_TOPIC:
        return
    body = {"topic": NTFY_TOPIC, "title": title, "message": message}
    if click:
        body["click"] = click
    if tags:
        body["tags"] = tags
    requests.post("https://ntfy.sh/", json=body, timeout=30)


def write_status(matches, sold_log, total, now):
    lines = [
        "# F54 クーパーS・支払総額200万円以下",
        "",
        f"最終チェック: {now:%Y-%m-%d %H:%M} JST（全在庫 {total} 台）",
        "",
        f"## 現在 {len(matches)} 台（安い順）",
        "",
        "| 支払総額 | 車名 | 色 | 年式 | 走行 | 掲載確認日 |",
        "|---|---|---|---|---|---|",
    ]
    for c in sorted(matches.values(), key=lambda c: c["price"]):
        km = f"{c['km'] / 10000:.1f}万km" if c.get("km") is not None else "-"
        lines.append(f"| {man(c['price'])} | [{c['name']}]({c['url']}) | {c.get('color') or '-'} | {c.get('year') or '-'} | {km} | {c['first_seen']} |")
    lines += ["", "## 最近掲載終了した車（売約など）", ""]
    for s in sold_log[:20]:
        lines.append(f"- {s['gone']}：[{desc(s)}]({s['url']}) {man(s['price'])}（{s['first_seen']}〜）")
    if not sold_log:
        lines.append("- まだありません")
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {"matches": {}, "sold": [], "last_total": 0}

    try:
        cars = scrape_all()
    except Exception as e:
        notify("⚠️ MINI監視エラー", f"サイトの取得に失敗しました: {e}")
        sys.exit(1)

    total = len(cars)
    # 取得失敗やサイト改修で「全部売れた」と誤判定しないための安全装置
    if total < 30 or (state["last_total"] and total < state["last_total"] * 0.5):
        notify("⚠️ MINI監視エラー",
               f"在庫が {total} 台しか読めませんでした（前回 {state['last_total']} 台）。"
               "サイトの構造が変わった可能性があります。今回は結果を保存しません。")
        sys.exit(1)

    first_run = not state["matches"] and state["last_total"] == 0
    old = state["matches"]
    new_matches = {}
    for cid, c in cars.items():
        if is_target(c):
            prev = old.get(cid)
            c["first_seen"] = prev["first_seen"] if prev else today
            new_matches[cid] = c

    added = [c for cid, c in new_matches.items() if cid not in old]
    dropped = [c for cid, c in new_matches.items()
               if cid in old and c["price"] < old[cid]["price"]]
    gone, out_of_range = [], []
    for cid, c in old.items():
        if cid in new_matches:
            continue
        if cid in cars:          # まだ掲載中だが条件外（値上げ等）
            out_of_range.append((c, cars[cid]))
        else:
            gone.append(c)

    if first_run:
        cheapest = sorted(new_matches.values(), key=lambda c: c["price"])
        msg = "\n".join(f"・{man(c['price'])} {desc(c)}\n  {c['url']}" for c in cheapest) or "該当なし"
        notify(f"🚗 監視を開始しました（現在 {len(new_matches)} 台）", msg, tags=["car"])
    else:
        for c in added:
            notify(f"🆕 新着 {man(c['price'])}", f"{desc(c)}\n{c['url']}", click=c["url"], tags=["new"])
        for c in dropped:
            notify(f"💴 値下げ {man(old[c['id']]['price'])} → {man(c['price'])}",
                   f"{desc(c)}\n{c['url']}", click=c["url"], tags=["moneybag"])
        for c in gone:
            notify(f"✅ 掲載終了 {man(c['price'])}", f"{desc(c)}（{c['first_seen']}から掲載）\n{c['url']}",
                   tags=["checkered_flag"])
        for c, now_c in out_of_range:
            notify(f"↗️ 条件外に {man(c['price'])} → {man(now_c['price'])}", f"{desc(c)}\n{c['url']}",
                   click=c["url"])

    sold = [dict(c, gone=today) for c in gone] + state.get("sold", [])
    state = {"matches": new_matches, "sold": sold[:100], "last_total": total,
             "checked_at": now.isoformat(timespec="minutes")}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    write_status(new_matches, state["sold"], total, now)
    print(f"done: total={total} matches={len(new_matches)} added={len(added)} "
          f"dropped={len(dropped)} gone={len(gone)}")


if __name__ == "__main__":
    main()
