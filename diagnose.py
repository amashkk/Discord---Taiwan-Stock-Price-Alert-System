import sys
import ssl
import json
import urllib.request

ctx = ssl.create_default_context()
try:
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
except AttributeError:
    pass

print("=== Python 環境 ===")
print(f"版本: {sys.version}")
print(f"執行檔: {sys.executable}")
print()

print("=== 測試 TWSE 即時報價 API ===")
url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw|tse_0050.tw&json=1&delay=0"
req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0 (StockAlert/1.0)",
    "Referer": "https://mis.twse.com.tw/stock/fibest.jsp",
})
try:
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
    except ssl.SSLError:
        with urllib.request.urlopen(req, timeout=15, context=ssl._create_unverified_context()) as resp:
            raw = resp.read().decode("utf-8")
    print(f"HTTP 狀態: OK")
    print(f"回傳長度: {len(raw)} bytes")
    data = json.loads(raw)
    arr = data.get("msgArray", [])
    print(f"msgArray 筆數: {len(arr)}")
    if arr:
        for it in arr:
            code = it.get("c", "?")
            name = it.get("n", "?")
            price = it.get("z", "-")
            prev = it.get("y", "-")
            print(f"  {code} {name}: z={price} y={prev} t={it.get('t', '?')}")
    else:
        print("⚠ 回傳但沒資料，前 500 字:")
        print(raw[:500])
except Exception as e:
    print(f"❌ 連線失敗: {type(e).__name__}: {e}")

print()
print("=== 測試 Discord Webhook ===")
try:
    cfg = json.load(open("config.json", "r", encoding="utf-8"))
    webhook = cfg.get("discord_webhook", "").strip()
    if not webhook:
        print("⚠ config.json 沒設定 discord_webhook")
    else:
        body = json.dumps({"content": "🔧 診斷測試訊息"}).encode("utf-8")
        req = urllib.request.Request(webhook, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 StockAlertBot/1.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"✅ Discord 回應: HTTP {resp.status}")
except Exception as e:
    print(f"❌ Discord 失敗: {type(e).__name__}: {e}")
