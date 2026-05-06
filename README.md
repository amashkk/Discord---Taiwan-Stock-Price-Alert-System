# 台灣股市到價提醒器 (Discord 版)

監控台股 (上市/上櫃) 即時股價，當價格突破設定的上緣或跌破下緣時，自動推送 Discord 通知。

## 功能特色

- 📈 即時抓取 TWSE 公開報價 API
- 🔔 突破上緣 / 跌破下緣自動發送 Discord 通知
- 🔁 觸發後自動 armed/disarmed，避免重複洗版
- 🕘 支援「僅盤中時段運作」(平日 09:00-13:30 台北時間)
- 📋 啟動時推送目前追蹤清單到 Discord
- ⚠️ 連線錯誤會通知，且 10 分鐘內只發一次避免洗頻
- 💾 狀態存檔到 `state.json`，重啟後不會重複通知

## 檔案結構

```
stock/
├── stock_alert.py   # 主程式
├── diagnose.py      # 診斷工具 (測試 TWSE / Discord 連線)
├── config.json      # 設定檔 (webhook、追蹤清單)
├── state.json       # 自動產生，記錄各標的觸發狀態
└── README.md
```

## 安裝與使用

### 1. 建立 Discord Webhook

在你的 Discord 頻道：**設定 → 整合 → Webhook → 新增 Webhook**，複製網址。

### 2. 編輯 `config.json`

```json
{
  "discord_webhook": "https://discord.com/api/webhooks/...",
  "interval_seconds": 60,
  "market_hours_only": true,
  "watch": [
    {"id": "2330", "market": "tse", "above": 1100, "below": 950, "note": "台積電"},
    {"id": "6488", "market": "otc", "above": 600,                "note": "環球晶"}
  ]
}
```

| 欄位 | 說明 |
|---|---|
| `discord_webhook` | Discord Webhook 網址 |
| `interval_seconds` | 檢查頻率 (秒)，建議 60 |
| `market_hours_only` | `true` 僅盤中運作; `false` 全天候 |
| `watch[].id` | 股票代號 |
| `watch[].market` | `tse` = 上市, `otc` = 上櫃 |
| `watch[].above` | 突破此價會通知 (可省略) |
| `watch[].below` | 跌破此價會通知 (可省略) |
| `watch[].note` | 備註 (顯示用) |

### 3. 執行

```bash
python3 stock_alert.py
```

只列出目前追蹤清單並推送到 Discord：

```bash
python3 stock_alert.py --list
```

## 診斷工具

如果 Discord 沒收到訊息，或抓不到報價，先跑一次：

```bash
python3 diagnose.py
```

它會檢查：
- Python 版本與執行路徑
- TWSE 即時報價 API 是否能連通
- Discord Webhook 是否有效

## 觸發邏輯

每檔標的對 `above` / `below` 各維護一個 `armed` 狀態：

- **突破**：`armed=true` 且現價 ≥ `above` → 發通知，狀態變 `armed=false`
- **復位**：現價回到 `above` 以下 → 重新 `armed=true`
- 跌破方向同理

這樣一筆突破只會通知一次；要再通知必須先「離開觸發區」再「進入」。

## 系統需求

- Python 3.8+ (僅使用標準函式庫，無需 `pip install`)
- 可連外網路 (能存取 `mis.twse.com.tw` 與 `discord.com`)

## 注意事項

- TWSE 公開 API 為延遲報價，非逐筆即時資料
- 盤後 / 假日抓不到當日成交價時，會以昨收 (`y`) 替代
- Python 3.13 對 TWSE 憑證較嚴格，程式已自動放寬 `VERIFY_X509_STRICT`
- `config.json` 內含 Webhook 網址，請勿提交到公開 repo
