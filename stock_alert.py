#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台灣股市到價提醒器 (Discord 版)
====================================

使用方式：
  1. 在 Discord 頻道建立 Webhook，把網址填到 config.json 的 discord_webhook
  2. 編輯 config.json 加入要監控的股票
  3. 執行: python3 stock_alert.py

設定檔範例 (config.json):
{
  "discord_webhook": "https://discord.com/api/webhooks/...",
  "interval_seconds": 60,
  "market_hours_only": true,
  "watch": [
    {"id": "2330", "market": "tse", "above": 1100, "below": 950, "note": "台積電"},
    {"id": "6488", "market": "otc", "above": 600,  "note": "環球晶"}
  ]
}

market: "tse" = 上市, "otc" = 上櫃
above / below 任一個或兩個都可以填，不想用就拿掉
"""

import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, time as dtime, timezone, timedelta

# TWSE 憑證少了 SKI 欄位，Python 3.13 的嚴格驗證會拒絕，這裡放寬 strict mode
_TWSE_SSL_CTX = ssl.create_default_context()
try:
    _TWSE_SSL_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT
except AttributeError:
    pass

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

TWSE_API = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TPE = timezone(timedelta(hours=8))  # 台北時區


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def in_market_hours(now=None):
    """台股盤中: 平日 09:00 - 13:30 (台北時間)"""
    now = now or datetime.now(TPE)
    if now.weekday() >= 5:
        return False
    return dtime(9, 0) <= now.time() <= dtime(13, 30)


def fetch_quotes(watch_list):
    """一次抓取所有股票報價，回傳 dict: {id: {price, name, time, ...}}"""
    if not watch_list:
        return {}
    ex_ch = "|".join(f"{w.get('market', 'tse')}_{w['id']}.tw" for w in watch_list)
    # 加上時間戳避免快取
    url = f"{TWSE_API}?ex_ch={ex_ch}&json=1&delay=0&_={int(time.time() * 1000)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (StockAlert/1.0)",
            "Referer": "https://mis.twse.com.tw/stock/fibest.jsp",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=_TWSE_SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except ssl.SSLError:
        # 退路：完全跳過憑證驗證 (TWSE 資料公開，沒有敏感資訊)
        with urllib.request.urlopen(req, timeout=15, context=ssl._create_unverified_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))

    quotes = {}
    for item in data.get("msgArray", []):
        # z = 最新成交價, y = 昨收, n = 公司名, t = 時間
        # 開盤前 z 可能是 "-"，改用試撮 (z) -> 最高 (h) -> 昨收 (y)
        raw_price = item.get("z", "-")
        if raw_price in ("-", ""):
            raw_price = item.get("y", "-")
        try:
            price = float(raw_price)
        except (ValueError, TypeError):
            continue
        try:
            prev_close = float(item.get("y", 0))
        except (ValueError, TypeError):
            prev_close = 0.0
        quotes[item.get("c")] = {
            "name": item.get("n", ""),
            "price": price,
            "prev_close": prev_close,
            "time": item.get("t", ""),
        }
    return quotes


def send_discord(webhook_url, content, embeds=None):
    payload = {"content": content}
    if embeds:
        payload["embeds"] = embeds
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 StockAlertBot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        print(f"[Discord] HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[Discord] 發送失敗: {e}", file=sys.stderr)
        return False


def build_alert_embed(watch, quote, direction, target):
    price = quote["price"]
    prev = quote["prev_close"] or price
    change = price - prev
    pct = (change / prev * 100) if prev else 0
    arrow = "📈" if direction == "above" else "📉"
    title_word = "突破上緣" if direction == "above" else "跌破下緣"
    color = 0xE74C3C if direction == "above" else 0x3498DB

    note = watch.get("note", "")
    name = quote["name"] or watch["id"]
    return {
        "title": f"{arrow} {name} ({watch['id']}) {title_word}",
        "color": color,
        "fields": [
            {"name": "現價",     "value": f"{price:.2f}",         "inline": True},
            {"name": "目標價",   "value": f"{target:.2f}",        "inline": True},
            {"name": "漲跌",     "value": f"{change:+.2f} ({pct:+.2f}%)", "inline": True},
        ],
        "footer": {"text": f"{note} | 資料時間 {quote['time']}"} if note else {"text": f"資料時間 {quote['time']}"},
        "timestamp": datetime.now(TPE).isoformat(),
    }


def check_alerts(config, state):
    quotes = fetch_quotes(config["watch"])
    triggered = []

    for watch in config["watch"]:
        sid = watch["id"]
        quote = quotes.get(sid)
        if not quote:
            print(f"[警告] 找不到 {sid} 的報價", file=sys.stderr)
            continue

        price = quote["price"]
        s = state.setdefault(sid, {})

        # 上緣: 突破時通知；跌回目標下方時復位 (首次遇到預設 armed)
        if "above" in watch:
            target = float(watch["above"])
            armed = s.get("above_armed", True)
            if armed and price >= target:
                triggered.append((watch, quote, "above", target))
                s["above_armed"] = False
            elif not armed and price < target:
                s["above_armed"] = True

        # 下緣: 跌破時通知；回到目標上方時復位
        if "below" in watch:
            target = float(watch["below"])
            armed = s.get("below_armed", True)
            if armed and price <= target:
                triggered.append((watch, quote, "below", target))
                s["below_armed"] = False
            elif not armed and price > target:
                s["below_armed"] = True

    return triggered, quotes


def build_watch_list_view(config):
    """組出追蹤清單的純文字 + Discord embed，供終端與 Discord 共用"""
    watch = config.get("watch", [])
    try:
        quotes = fetch_quotes(watch)
        if not quotes and watch:
            fetch_err = "TWSE API 回傳空資料 (盤後/假日可能無資料，或請求被擋)"
        else:
            fetch_err = None
    except Exception as e:
        quotes = {}
        fetch_err = f"{type(e).__name__}: {e}"

    lines = []
    lines.append(f"{'代號':<8}{'名稱':<14}{'現價':>10}  {'突破':>10}  {'跌破':>10}  備註")
    lines.append("-" * 78)
    fields = []
    for w in watch:
        sid = w["id"]
        q = quotes.get(sid)
        name = q["name"] if q else "?"
        price = f"{q['price']:.2f}" if q else "—"
        above = f"{w['above']}" if "above" in w else "—"
        below = f"{w['below']}" if "below" in w else "—"

        marks = []
        if q and "above" in w and q["price"] >= w["above"]:
            marks.append("⚠已在突破上")
        if q and "below" in w and q["price"] <= w["below"]:
            marks.append("⚠已在跌破下")
        note = w.get("note", "")
        full_note = (note + " " + " ".join(marks)).strip()
        lines.append(f"{sid:<8}{name:<14}{price:>10}  {above:>10}  {below:>10}  {full_note}")

        # Discord embed 用一個 field 一檔
        cond = []
        if "above" in w:
            cond.append(f"⬆ {w['above']}")
        if "below" in w:
            cond.append(f"⬇ {w['below']}")
        cond_str = "  ".join(cond) if cond else "（未設條件）"
        mark_str = "  " + " ".join(marks) if marks else ""
        fields.append({
            "name": f"{name} ({sid})",
            "value": f"現價 **{price}**　{cond_str}{mark_str}",
            "inline": False,
        })

    text = "\n".join(lines)
    if fetch_err:
        text = f"(無法抓取現價: {fetch_err})\n" + text

    embed = {
        "title": f"📋 目前追蹤 {len(watch)} 檔股票",
        "color": 0x5865F2,
        "fields": fields,
        "footer": {"text": "修改 config.json 的 watch 陣列可調整追蹤清單與條件"},
        "timestamp": datetime.now(TPE).isoformat(),
    }
    return text, embed


def print_watch_list(config, push_to_discord=False):
    text, embed = build_watch_list_view(config)
    watch_count = len(config.get("watch", []))
    print(f"\n📋 目前追蹤 {watch_count} 檔股票")
    print("=" * 78)
    print(text)
    print("=" * 78)
    print(f"設定檔位置: {CONFIG_PATH}")

    if push_to_discord:
        webhook = config.get("discord_webhook", "").strip()
        if webhook and "discord.com/api/webhooks" in webhook:
            ok = send_discord(webhook, "", embeds=[embed])
            print(f"Discord 推送: {'成功 ✅' if ok else '失敗 ❌'}")
        else:
            print("(未設定 discord_webhook，跳過 Discord 推送)")
    print()


def main():
    config = load_json(CONFIG_PATH, None)
    if config is None:
        print(f"找不到設定檔 {CONFIG_PATH}，請先建立。", file=sys.stderr)
        sys.exit(1)

    # --list / --status: 印一次清單就離開，並推到 Discord
    if len(sys.argv) > 1 and sys.argv[1] in ("--list", "--status", "-l"):
        print_watch_list(config, push_to_discord=True)
        return

    webhook = config.get("discord_webhook", "").strip()
    if not webhook or "discord.com/api/webhooks" not in webhook:
        print("config.json 的 discord_webhook 尚未設定。", file=sys.stderr)
        sys.exit(1)

    # 啟動時先印一次追蹤清單 (本地)
    print_watch_list(config, push_to_discord=False)

    interval = int(config.get("interval_seconds", 60))
    market_only = bool(config.get("market_hours_only", True))
    state = load_json(STATE_PATH, {})

    print(f"[啟動] 監控 {len(config['watch'])} 檔股票，每 {interval} 秒檢查一次")
    if market_only:
        print("[模式] 僅在台股盤中時段運作 (平日 09:00-13:30)")

    # 啟動時推一則 Discord 訊息，讓使用者立即看見服務上線
    startup_embed = {
        "title": "🟢 股價監控已啟動",
        "color": 0x2ECC71,
        "description": f"正在追蹤 **{len(config['watch'])}** 檔股票，每 {interval} 秒檢查一次。\n"
                       + ("僅在盤中 (平日 09:00-13:30) 觸發通知。" if market_only else "全天候運作。"),
        "footer": {"text": "到價時會自動推送通知 | 在終端按 Ctrl+C 可停止"},
        "timestamp": datetime.now(TPE).isoformat(),
    }
    send_discord(webhook, "", embeds=[startup_embed])

    last_heartbeat = 0
    HEARTBEAT_SEC = 300  # 盤後每 5 分鐘印一次 still alive
    last_error_notify = 0     # 避免錯誤訊息洗版

    while True:
        try:
            now_dt = datetime.now(TPE)
            currently_in_market = in_market_hours(now_dt)

            if market_only and not currently_in_market:
                now_ts = time.time()
                if now_ts - last_heartbeat >= HEARTBEAT_SEC:
                    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{now_str}] 💤 盤後等待中…（盤中時段才會檢查與通知）")
                    last_heartbeat = now_ts
                time.sleep(interval)
                continue

            triggered, quotes = check_alerts(config, state)

            now = now_dt.strftime("%H:%M:%S")
            summary = " | ".join(
                f"{q['name']}({sid}) {q['price']:.2f}"
                for sid, q in quotes.items()
            )
            print(f"[{now}] {summary}")

            for watch, quote, direction, target in triggered:
                embed = build_alert_embed(watch, quote, direction, target)
                ok = send_discord(webhook, "", embeds=[embed])
                if ok:
                    print(f"  ✓ 已通知: {watch['id']} {direction} {target}")
                else:
                    # 失敗時讓條件可重試
                    state[watch["id"]][f"{direction}_armed"] = True

            save_json(STATE_PATH, state)

        except KeyboardInterrupt:
            print("\n[結束] 使用者中斷")
            send_discord(webhook, "", embeds=[{
                "title": "🔴 監控已停止",
                "color": 0xE74C3C,
                "description": "由使用者按 Ctrl+C 停止。重新執行 `py stock_alert.py` 即可恢復。",
                "timestamp": datetime.now(TPE).isoformat(),
            }])
            break
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}"
            print(f"[錯誤] {err_msg}", file=sys.stderr)
            # 同類型錯誤 10 分鐘內只發一次，避免持續失敗時把頻道洗爆
            if time.time() - last_error_notify >= 600:
                send_discord(webhook, "", embeds=[{
                    "title": "⚠️ 監控發生錯誤（仍在重試）",
                    "color": 0xF39C12,
                    "description": f"```\n{err_msg}\n```",
                    "timestamp": datetime.now(TPE).isoformat(),
                }])
                last_error_notify = time.time()

        time.sleep(interval)


if __name__ == "__main__":
    main()
