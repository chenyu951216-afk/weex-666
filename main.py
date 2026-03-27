#!/usr/bin/env python3
"""
WEEX 量化機器人 v3.3 雲端單檔版
Zeabur 部署：只需 main.py + requirements.txt
環境變數（Zeabur Variables）：
  WEEX_API_KEY      APIKey
  WEEX_SECRET_KEY   SecretKey
  WEEX_PASSPHRASE   Passphrase
"""
import hmac, hashlib, base64, time, json, math, uuid, logging, threading, os
import requests
from datetime import datetime
from collections import deque
from flask import Flask, jsonify, request as freq, Response
from flask_cors import CORS

# ── 從環境變數讀取（Zeabur Variables 設定）──
API_KEY    = os.environ.get("WEEX_API_KEY",    "")
SECRET_KEY = os.environ.get("WEEX_SECRET_KEY", "")
PASSPHRASE = os.environ.get("WEEX_PASSPHRASE", "")

BASE_URL        = "https://api-contract.weex.com"
LEVERAGE        = 200
RISK_PCT        = 0.05        # 每筆倉位 5%
INTERVAL        = "1m"
TOP_N           = 50
COIN_SCAN_DELAY = 0.2         # 幣間隔 0.2s
ROUND_INTERVAL  = 60          # 輪間隔 60s
POSITION_CHECK  = 5           # 持倉監控 5s
OPEN_THRESHOLD  = 40          # ★ 開倉閾值降低→更頻繁 (原65→40)
CLOSE_THRESHOLD = 35          # ★ 平倉閾值 (原55→35)
ATR_MIN_PCT     = 0.02        # ★ ATR 門檻降低 (原0.04→0.02)
MAX_POSITIONS   = 5           # 最多同時 5 倉
PORT            = int(os.environ.get("PORT", "5000"))

FAST_EMA=9; SLOW_EMA=21; RSI_P=14; MACD_F=12; MACD_S=26
MACD_SIG=9;  BB_P=20;   BB_STD=2.0; ATR_P=14; VOL_MA_P=20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WEEX 量化監控 v3.0</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap');

:root {
  --bg:#020510; --panel:#060d1f; --border:#0d2545;
  --accent:#00d4ff; --green:#00ff88; --red:#ff3366;
  --yellow:#ffcc00; --orange:#ff8800; --text:#c8d8f0; --dim:#3a5070;
}
*{margin:0;padding:0;box-sizing:border-box}
body{
  background:var(--bg); color:var(--text);
  font-family:'Share Tech Mono',monospace; min-height:100vh;
  background-image:
    radial-gradient(ellipse at 15% 15%,#001a3a18 0%,transparent 55%),
    radial-gradient(ellipse at 85% 85%,#00101820 0%,transparent 55%);
}
body::before{
  content:''; position:fixed; inset:0; pointer-events:none; z-index:0;
  background-image:linear-gradient(var(--border) 1px,transparent 1px),
                   linear-gradient(90deg,var(--border) 1px,transparent 1px);
  background-size:40px 40px; opacity:.25;
}
.wrap{position:relative;z-index:1;max-width:1600px;margin:0 auto;padding:12px}

/* ── header ── */
header{
  display:flex; align-items:center; justify-content:space-between;
  padding:12px 20px; margin-bottom:12px;
  background:linear-gradient(135deg,#060d1f,#0a1830);
  border:1px solid var(--border); border-top:2px solid var(--accent);
  clip-path:polygon(0 0,calc(100% - 18px) 0,100% 18px,100% 100%,0 100%);
}
.logo{font-family:'Orbitron',sans-serif;font-size:20px;font-weight:900;color:var(--accent);letter-spacing:4px}
.logo span{color:var(--green)}
.logo sub{font-size:10px;color:var(--dim);letter-spacing:2px;display:block;margin-top:-2px}
.hbar{display:flex;gap:20px;align-items:center}
.dot{width:9px;height:9px;border-radius:50%;background:var(--dim)}
.dot.on{background:var(--green);box-shadow:0 0 10px var(--green);animation:blink 1.4s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.htext{font-size:11px;letter-spacing:2px}
.btn{
  padding:7px 18px;border:none;cursor:pointer;
  font-family:'Orbitron',sans-serif;font-size:10px;font-weight:700;
  letter-spacing:2px;text-transform:uppercase;
  clip-path:polygon(7px 0,100% 0,calc(100% - 7px) 100%,0 100%);
  transition:all .2s;
}
.btn-go{background:#00ff8820;color:var(--green);border:1px solid var(--green)}
.btn-go:hover{background:#00ff8840;box-shadow:0 0 12px var(--green)}
.btn-stop{background:#ff336620;color:var(--red);border:1px solid var(--red)}
.btn-stop:hover{background:#ff336640;box-shadow:0 0 12px var(--red)}

/* ── top metrics ── */
.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:12px}
.mc{
  background:var(--panel);border:1px solid var(--border);
  border-bottom:2px solid var(--accent);padding:14px 16px;
}
.ml{font-size:9px;letter-spacing:2px;color:var(--dim);text-transform:uppercase;margin-bottom:6px}
.mv{font-family:'Orbitron',sans-serif;font-size:18px;font-weight:700;color:var(--accent)}
.mv.g{color:var(--green)} .mv.r{color:var(--red)} .mv.y{color:var(--yellow)}
.ms{font-size:10px;color:var(--dim);margin-top:3px}

/* ── scan progress bar ── */
.scan-strip{
  background:var(--panel);border:1px solid var(--border);
  padding:10px 16px;margin-bottom:12px;
  display:flex;align-items:center;gap:14px;
}
.scan-label{font-size:10px;letter-spacing:2px;color:var(--dim);white-space:nowrap}
.scan-coin{font-family:'Orbitron',sans-serif;font-size:12px;color:var(--accent);min-width:100px}
.prog-wrap{flex:1;background:#0a1428;height:5px;border-radius:0}
.prog-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--green));transition:width .3s ease}
.scan-pct{font-size:11px;color:var(--dim);min-width:36px;text-align:right}
.round-badge{font-size:10px;color:var(--yellow);border:1px solid #ffcc0030;padding:2px 10px;white-space:nowrap}

/* ── main layout ── */
.main{display:grid;grid-template-columns:1fr 1fr 340px;gap:12px}

/* ── panel ── */
.panel{background:var(--panel);border:1px solid var(--border);overflow:hidden}
.ph{
  display:flex;align-items:center;gap:10px;
  padding:9px 14px;background:linear-gradient(90deg,#0d2545,transparent);
  border-bottom:1px solid var(--border);
}
.pt{font-family:'Orbitron',sans-serif;font-size:10px;font-weight:700;letter-spacing:2px;color:var(--accent)}
.pb{padding:3px 8px;font-size:9px;background:#00d4ff12;border:1px solid #00d4ff30;color:var(--accent)}
.pbody{padding:12px}

/* ── 掃描結果表格 ── */
.scan-table{width:100%;border-collapse:collapse;font-size:11px}
.scan-table th{
  padding:5px 8px;text-align:left;font-size:9px;letter-spacing:2px;
  color:var(--dim);border-bottom:1px solid var(--border);background:#0a1428
}
.scan-table td{padding:6px 8px;border-bottom:1px solid #0d204015}
.scan-table tr:hover td{background:#0d2040}
.score-chip{
  display:inline-block;padding:2px 8px;font-size:10px;font-weight:bold;
  border:1px solid; min-width:46px;text-align:center;
}
.score-chip.bull{color:var(--green);border-color:#00ff8840;background:#00ff8812}
.score-chip.bear{color:var(--red);border-color:#ff336640;background:#ff336612}
.score-chip.n{color:var(--dim);border-color:#3a507040;background:#3a507010}
.reason-small{font-size:9px;color:var(--dim);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* ── 持倉面板 ── */
.pos-card{
  background:#0a1428;border:1px solid var(--border);
  padding:10px 12px;margin-bottom:8px;
  border-left:3px solid var(--dim);position:relative;
}
.pos-card.long{border-left-color:var(--green)}
.pos-card.short{border-left-color:var(--red)}
.pos-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.pos-sym{font-family:'Orbitron',sans-serif;font-size:13px;font-weight:700}
.pos-dir{font-size:9px;padding:2px 8px;border:1px solid;letter-spacing:1px}
.pos-dir.long{color:var(--green);border-color:#00ff8840}
.pos-dir.short{color:var(--red);border-color:#ff336640}
.pos-rows{display:grid;grid-template-columns:1fr 1fr;gap:3px}
.pr{display:flex;justify-content:space-between;font-size:10px;padding:2px 0}
.pk{color:var(--dim)} .pv{font-weight:bold}
.upnl-pos{color:var(--green)} .upnl-neg{color:var(--red)}
.close-btn{
  position:absolute;top:8px;right:8px;
  padding:2px 8px;font-size:9px;cursor:pointer;
  color:var(--red);border:1px solid #ff336640;background:transparent;
  font-family:'Share Tech Mono',monospace;letter-spacing:1px;
}
.close-btn:hover{background:#ff336620}
.no-pos{text-align:center;color:var(--dim);padding:30px;font-size:11px}

/* ── 交易記錄 ── */
.trade-table{width:100%;border-collapse:collapse;font-size:10px}
.trade-table th{padding:5px 8px;font-size:9px;letter-spacing:1px;color:var(--dim);border-bottom:1px solid var(--border);background:#0a1428;text-align:left}
.trade-table td{padding:5px 8px;border-bottom:1px solid #0d204012}
.trade-table tr:first-child td{animation:slid .3s ease}
@keyframes slid{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
.badge{padding:2px 6px;font-size:9px;letter-spacing:1px}
.badge.open{color:var(--green);background:#00ff8812;border:1px solid #00ff8840}
.badge.cls{color:var(--yellow);background:#ffcc0012;border:1px solid #ffcc0040}
.badge.autoc{color:var(--orange);background:#ff880012;border:1px solid #ff884040}
.pnl-g{color:var(--green)} .pnl-r{color:var(--red)}

/* ── 右側統計 ── */
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.si{background:#0a1428;border:1px solid var(--border);padding:10px 12px}
.sk{font-size:9px;letter-spacing:1px;color:var(--dim);margin-bottom:4px}
.sv{font-family:'Orbitron',sans-serif;font-size:16px;font-weight:700}

/* 勝率環 */
.wr-wrap{display:flex;align-items:center;gap:14px;padding:10px 0}
.wr-ring{position:relative;width:72px;height:72px;flex-shrink:0}
.wr-ring svg{transform:rotate(-90deg)}
.wr-inner{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.wr-num{font-family:'Orbitron',sans-serif;font-size:14px;font-weight:700;color:var(--green)}
.wr-sub{font-size:7px;color:var(--dim);letter-spacing:1px}
.wr-stats{flex:1}
.ws{display:flex;justify-content:space-between;font-size:11px;padding:2px 0}
.bar-w{background:#0a1428;height:5px;margin-top:8px}
.bar-f{height:100%;background:linear-gradient(90deg,var(--green),var(--accent));transition:width .5s}

/* TOP50 chips */
.coin-chips{display:flex;flex-wrap:wrap;gap:4px;max-height:120px;overflow-y:auto;padding:8px}
.chip{
  padding:2px 7px;font-size:9px;border:1px solid var(--border);
  color:var(--dim);cursor:default;transition:all .2s;
}
.chip.scanning{border-color:var(--accent);color:var(--accent);animation:pulse .8s infinite}
.chip.has-pos{border-color:var(--green);color:var(--green)}
.chip.bull-sig{border-color:#00ff8840;color:var(--green)}
.chip.bear-sig{border-color:#ff336640;color:var(--red)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* 錯誤日誌 */
.elog{max-height:100px;overflow-y:auto;font-size:10px;color:var(--red);background:#0a0510;border:1px solid #ff336615;padding:6px}
.ei{padding:1px 0;border-bottom:1px solid #ff336610}
.et{color:var(--dim);margin-right:6px}

/* 掃描結果分頁 */
.tab-bar{display:flex;gap:0;margin-bottom:0;border-bottom:1px solid var(--border)}
.tab{
  padding:7px 14px;font-size:10px;letter-spacing:1px;cursor:pointer;
  color:var(--dim);border-bottom:2px solid transparent;
  transition:all .2s;
}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab:hover{color:var(--text)}
.tab-content{display:none} .tab-content.active{display:block}

.scan-scroll{max-height:320px;overflow-y:auto}
.scan-scroll::-webkit-scrollbar{width:4px}
.scan-scroll::-webkit-scrollbar-thumb{background:#0d2545}

@media(max-width:1100px){
  .metrics{grid-template-columns:repeat(3,1fr)}
  .main{grid-template-columns:1fr 1fr}
}
@media(max-width:700px){
  .metrics{grid-template-columns:repeat(2,1fr)}
  .main{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="wrap">

<!-- header -->
<header>
  <div class="logo">WEEX <span>QUANT</span><sub>v3.0 多幣掃描版</sub></div>
  <div class="hbar">
    <div class="dot" id="dot"></div>
    <span class="htext" id="htext">OFFLINE</span>
    <span style="color:var(--dim);font-size:10px" id="htime">--:--:--</span>
  </div>
  <div style="display:flex;gap:8px">
    <button class="btn btn-go"   onclick="startBot()">▶ 啟動</button>
    <button class="btn btn-stop" onclick="stopBot()">■ 停止</button>
  </div>
</header>

<!-- metrics -->
<div class="metrics">
  <div class="mc"><div class="ml">帳戶餘額 USDT</div><div class="mv" id="bal">--</div><div class="ms">可用資金</div></div>
  <div class="mc"><div class="ml">浮動損益</div><div class="mv" id="upnl">--</div><div class="ms">持倉未實現</div></div>
  <div class="mc"><div class="ml">累計已實現</div><div class="mv" id="tpnl">--</div><div class="ms">本次運行</div></div>
  <div class="mc"><div class="ml">持倉數 / 上限</div><div class="mv y" id="posCount">0 / 5</div><div class="ms">最多同時 5 個</div></div>
  <div class="mc"><div class="ml">已完成輪數</div><div class="mv" id="rounds">0</div><div class="ms">每輪60秒</div></div>
  <div class="mc"><div class="ml">總交易 / 勝率</div><div class="mv g" id="wrText">0 / --%</div><div class="ms" id="wcText">--勝 --負</div></div>
</div>

<!-- scan progress -->
<div class="scan-strip">
  <span class="scan-label">掃描中</span>
  <span class="scan-coin" id="scanCoin">等待啟動...</span>
  <div class="prog-wrap"><div class="prog-fill" id="progFill" style="width:0%"></div></div>
  <span class="scan-pct" id="progPct">0%</span>
  <span class="round-badge" id="roundBadge">第 0 輪</span>
</div>

<!-- main -->
<div class="main">

  <!-- 左: 掃描結果 -->
  <div>
    <div class="panel" style="margin-bottom:12px">
      <div class="tab-bar">
        <div class="tab active" onclick="switchTab('top',this)">TOP訊號</div>
        <div class="tab" onclick="switchTab('all',this)">全部結果</div>
        <div class="tab" onclick="switchTab('coins',this)">TOP50幣種</div>
      </div>
      <div id="tab-top" class="tab-content active">
        <div class="scan-scroll">
          <table class="scan-table">
            <thead><tr><th>幣種</th><th>評分</th><th>RSI</th><th>MACD柱</th><th>量比</th><th>ATR%</th><th>訊號</th></tr></thead>
            <tbody id="topList"><tr><td colspan="7" style="text-align:center;color:var(--dim);padding:20px">等待掃描...</td></tr></tbody>
          </table>
        </div>
      </div>
      <div id="tab-all" class="tab-content">
        <div class="scan-scroll">
          <table class="scan-table">
            <thead><tr><th>幣種</th><th>評分</th><th>價格</th><th>原因</th><th>更新</th></tr></thead>
            <tbody id="allList"><tr><td colspan="5" style="text-align:center;color:var(--dim);padding:20px">等待掃描...</td></tr></tbody>
          </table>
        </div>
      </div>
      <div id="tab-coins" class="tab-content">
        <div class="coin-chips" id="coinChips">等待...</div>
      </div>
    </div>

    <!-- 交易記錄 -->
    <div class="panel">
      <div class="ph"><div class="pt">交易記錄</div><div class="pb">最近200筆</div></div>
      <div style="overflow-x:auto;max-height:240px;overflow-y:auto">
        <table class="trade-table">
          <thead><tr><th>時間</th><th>動作</th><th>幣種</th><th>方向</th><th>價格</th><th>盈虧/原因</th></tr></thead>
          <tbody id="tradeList"><tr><td colspan="6" style="text-align:center;color:var(--dim);padding:16px">暫無紀錄</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- 中: 持倉 -->
  <div>
    <div class="panel" style="margin-bottom:12px">
      <div class="ph">
        <div class="pt">當前持倉</div>
        <div class="pb" id="posCountBadge">0 / 5</div>
      </div>
      <div class="pbody" id="posPanel">
        <div class="no-pos">⬡ 無持倉<br><span style="font-size:9px">訊號達標後自動開倉</span></div>
      </div>
    </div>

    <!-- 策略說明 -->
    <div class="panel">
      <div class="ph"><div class="pt">策略說明</div></div>
      <div class="pbody" style="font-size:10px;line-height:2;color:var(--dim)">
        <div>📊 <span style="color:var(--text)">EMA(9/21)</span> 趨勢方向 <span style="color:var(--accent)">±25</span></div>
        <div>📈 <span style="color:var(--text)">RSI(14)</span> 超買超賣 <span style="color:var(--accent)">±20</span></div>
        <div>⚡ <span style="color:var(--text)">MACD(12/26/9)</span> 動能轉換 <span style="color:var(--accent)">±20</span></div>
        <div>🎯 <span style="color:var(--text)">Bollinger(20,2σ)</span> 壓力支撐 <span style="color:var(--accent)">±15</span></div>
        <div>📦 <span style="color:var(--text)">成交量比(20)</span> 量能確認 <span style="color:var(--accent)">±10</span></div>
        <div>🚀 <span style="color:var(--text)">5K動能</span> 趨勢慣性 <span style="color:var(--accent)">±10</span></div>
        <div>🌡 <span style="color:var(--text)">ATR(14)</span> 動態TP/SL 過濾低波</div>
        <div style="margin-top:8px;color:var(--yellow)">開倉閾值: ±65 | 平倉閾值: ±55</div>
        <div style="color:var(--yellow)">TP: 2.2x ATR | SL: 1.1x ATR</div>
        <div style="color:var(--red)">槓桿: 200x | 倉位: 帳戶5%</div>
      </div>
    </div>
  </div>

  <!-- 右: 統計+日誌 -->
  <div>
    <!-- 績效 -->
    <div class="panel" style="margin-bottom:10px">
      <div class="ph"><div class="pt">績效統計</div></div>
      <div class="pbody">
        <div class="wr-wrap">
          <div class="wr-ring">
            <svg width="72" height="72" viewBox="0 0 72 72">
              <circle cx="36" cy="36" r="28" fill="none" stroke="#0d2545" stroke-width="7"/>
              <circle cx="36" cy="36" r="28" fill="none" id="wArc"
                stroke="var(--green)" stroke-width="7" stroke-linecap="round"
                stroke-dasharray="175.9" stroke-dashoffset="175.9"
                style="transition:stroke-dashoffset .6s"/>
            </svg>
            <div class="wr-inner">
              <span class="wr-num" id="wrNum">0%</span>
              <span class="wr-sub">勝率</span>
            </div>
          </div>
          <div class="wr-stats">
            <div class="ws"><span style="color:var(--dim)">獲利</span><span style="color:var(--green)" id="wc">0</span></div>
            <div class="ws"><span style="color:var(--dim)">虧損</span><span style="color:var(--red)" id="lc">0</span></div>
            <div class="ws"><span style="color:var(--dim)">總計</span><span id="tc">0</span></div>
            <div class="ws"><span style="color:var(--dim)">已實現</span><span id="tp2">0</span></div>
          </div>
        </div>
        <div class="bar-w"><div class="bar-f" id="wBar" style="width:0%"></div></div>
      </div>
    </div>

    <!-- 帳戶資訊 -->
    <div class="panel" style="margin-bottom:10px">
      <div class="ph"><div class="pt">帳戶狀態</div></div>
      <div class="pbody">
        <div class="stat-grid">
          <div class="si"><div class="sk">餘額</div><div class="sv" id="s_bal">--</div></div>
          <div class="si"><div class="sk">浮動損益</div><div class="sv" id="s_upnl">--</div></div>
          <div class="si"><div class="sk">累計損益</div><div class="sv" id="s_tpnl">--</div></div>
          <div class="si"><div class="sk">持倉數量</div><div class="sv y" id="s_pos">0</div></div>
        </div>
      </div>
    </div>

    <!-- 錯誤日誌 -->
    <div class="panel">
      <div class="ph"><div class="pt">錯誤日誌</div></div>
      <div class="pbody" style="padding:8px">
        <div class="elog" id="eLog"><div style="color:var(--dim);text-align:center;padding:6px">無錯誤</div></div>
      </div>
    </div>
  </div>

</div>

<!-- 底部說明 -->
<div style="margin-top:12px;padding:14px 16px;background:var(--panel);border:1px solid var(--border);border-left:3px solid var(--yellow);font-size:11px;color:var(--dim);line-height:2.2">
  <b style="color:var(--yellow);font-size:12px">⚡ 正確啟動方式（全部在自己電腦跑）</b><br>
  <b style="color:var(--accent)">① 安裝：</b><span style="color:var(--text)">pip install flask flask-cors requests</span><br>
  <b style="color:var(--accent)">② 設定：</b><span style="color:var(--text)">開啟 weex_bot.py → 填入 PASSPHRASE（第24行）→ 填入新的 API_KEY / SECRET_KEY</span><br>
  <b style="color:var(--accent)">③ 啟動：</b><span style="color:var(--text)">python weex_bot.py</span><br>
  <b style="color:var(--accent)">④ 開啟：</b><span style="color:var(--text)">瀏覽器輸入 <b style="color:var(--green)">http://localhost:5000</b>（儀表板已內建，不需要另外開 HTML）</span><br>
  <b style="color:var(--accent)">⑤ 診斷：</b><span style="color:var(--text)">若連不到 WEEX API，先開 <b style="color:var(--green)">http://localhost:5000/api/ping</b> 查看詳細原因</span><br>
  <b style="color:var(--red)">⚠ 勿從 Zeabur/雲端開啟儀表板，必須從 localhost:5000 開啟才能正確連接後端</b><br>
  <b style="color:var(--red)">⚠ 200x槓桿極高風險！圖片中的API金鑰已暴露，請立即到WEEX刪除並重新建立新的金鑰。</b>
</div>

</div>

<script>
// ★ 相對路徑：無論部署在哪裡都能正確連到後端
const API = '';   // 空字串 = 與當前頁面同 origin
let scanData = {};
let _offlineCount = 0;

// ── tab 切換 ──
function switchTab(name, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}

// ── 連線診斷 ──
async function doPing() {
  try {
    const d = await (await fetch('/api/ping', {cache:'no-store'})).json();
    const warn = (d.warnings || []).join(' | ');
    if (warn) {
      document.getElementById('eLog').innerHTML =
        `<div class="ei" style="color:var(--yellow)">${warn}</div>` +
        document.getElementById('eLog').innerHTML;
    }
    return d;
  } catch(e) { return null; }
}

// ── 主資料刷新 ──
async function fetchStatus() {
  try {
    const d = await (await fetch(API + '/api/status', {cache:'no-store'})).json();
    _offlineCount = 0;
    updateHeader(d);
    updateMetrics(d);
    updateScanProgress(d);
    updatePositions(d);
    updateStats(d);
    scanData = d.scan_results || {};
    renderTopSignals(scanData);
    renderAllSignals(scanData);
    renderCoinChips(d.top50 || [], d.current_scan, d.positions || {}, scanData);
  } catch(e) {
    _offlineCount++;
    document.getElementById('htext').textContent =
      _offlineCount === 1 ? '連線中...' : 'API OFFLINE';
    document.getElementById('dot').classList.remove('on');
    if (_offlineCount === 2) {
      // 二次失敗才做 ping 診斷
      const ping = await doPing();
      if (!ping) {
        document.getElementById('eLog').innerHTML =
          `<div class="ei"><span class="et">${new Date().toLocaleTimeString()}</span>` +
          `無法連接後端。請確認 python weex_bot.py 正在執行，並從 <b>http://localhost:5000</b> 開啟此頁面</div>`;
      }
    }
  }
}

async function fetchTrades() {
  try {
    const trades = await (await fetch(API + '/api/trades', {cache:'no-store'})).json();
    renderTrades(trades);
  } catch(e) {}
}

async function fetchErrors() {
  try {
    const errs = await (await fetch(API + '/api/errors', {cache:'no-store'})).json();
    renderErrors(errs);
  } catch(e) {}
}

// ── 更新函數 ──
function updateHeader(d) {
  document.getElementById('dot').classList.toggle('on', d.running);
  document.getElementById('htext').textContent = d.running ? 'RUNNING' : 'STOPPED';
  document.getElementById('htime').textContent = d.last_update || '--';
}

function updateMetrics(d) {
  set('bal', fmt(d.balance), '');
  setColor('upnl', (d.unrealized_pnl >= 0 ? '+' : '') + fmt(d.unrealized_pnl), d.unrealized_pnl);
  setColor('tpnl', (d.total_pnl >= 0 ? '+' : '') + fmt(d.total_pnl), d.total_pnl);
  set('posCount', `${d.position_count || 0} / 5`, '');
  set('rounds', d.round_count || 0, '');
  const wr = d.win_rate || 0;
  set('wrText', `${d.total_trades} / ${wr}%`, '');
  set('wcText', `${d.win_count}勝 ${d.loss_count}負`, '');
}

function updateScanProgress(d) {
  const coin = d.current_scan || '';
  document.getElementById('scanCoin').textContent = coin || (d.running ? '輪間等待中...' : '未啟動');
  const pct = d.scan_progress || 0;
  document.getElementById('progFill').style.width = pct + '%';
  document.getElementById('progPct').textContent = pct + '%';
  document.getElementById('roundBadge').textContent = `第 ${d.round_count || 0} 輪`;
}

function updatePositions(d) {
  const pos = d.positions || {};
  const count = Object.keys(pos).length;
  document.getElementById('posCountBadge').textContent = `${count} / 5`;

  const panel = document.getElementById('posPanel');
  document.getElementById('s_pos').textContent = count;
  document.getElementById('posCount').textContent = `${count} / 5`;

  if (!count) {
    panel.innerHTML = '<div class="no-pos">⬡ 無持倉<br><span style="font-size:9px">訊號達標後自動開倉</span></div>';
    return;
  }

  panel.innerHTML = Object.entries(pos).map(([sym, p]) => {
    const side = p.side || (parseFloat(p.positionAmt) > 0 ? 'LONG' : 'SHORT');
    const entry = parseFloat(p.entryPrice || 0);
    const upnl  = parseFloat(p.unrealizedProfit || 0);
    const cls   = side === 'LONG' ? 'long' : 'short';
    const upnlCls = upnl >= 0 ? 'upnl-pos' : 'upnl-neg';
    const sig = scanData[sym] || {};
    const curPx = sig.price || 0;
    return `<div class="pos-card ${cls}">
      <button class="close-btn" onclick="closePos('${sym}')">平倉</button>
      <div class="pos-top">
        <span class="pos-sym">${sym.replace('USDT','')}<span style="color:var(--dim);font-size:9px">/USDT</span></span>
        <span class="pos-dir ${cls}">${side}</span>
      </div>
      <div class="pos-rows">
        <div class="pr"><span class="pk">開倉價</span><span class="pv">$${fmtP(entry)}</span></div>
        <div class="pr"><span class="pk">現價</span><span class="pv">$${fmtP(curPx)}</span></div>
        <div class="pr"><span class="pk">止盈</span><span class="pv" style="color:var(--green)">$${fmtP(p.tp)}</span></div>
        <div class="pr"><span class="pk">止損</span><span class="pv" style="color:var(--red)">$${fmtP(p.sl)}</span></div>
        <div class="pr"><span class="pk">浮盈虧</span><span class="pv ${upnlCls}">${upnl >= 0 ? '+' : ''}${upnl.toFixed(4)}</span></div>
        <div class="pr"><span class="pk">訊號分</span><span class="pv">${sig.score !== undefined ? (sig.score > 0 ? '+' : '') + sig.score : '--'}</span></div>
      </div>
    </div>`;
  }).join('');
}

function updateStats(d) {
  const wr = d.win_rate || 0;
  document.getElementById('wrNum').textContent = wr + '%';
  document.getElementById('wc').textContent  = d.win_count  || 0;
  document.getElementById('lc').textContent  = d.loss_count || 0;
  document.getElementById('tc').textContent  = d.total_trades || 0;
  const tp = d.total_pnl || 0;
  const t2 = document.getElementById('tp2');
  t2.textContent  = (tp >= 0 ? '+' : '') + fmt(tp);
  t2.style.color  = tp >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById('wBar').style.width = wr + '%';
  const arc = document.getElementById('wArc');
  arc.style.strokeDashoffset = 175.9 - 175.9 * (wr / 100);

  set('s_bal', fmt(d.balance), '');
  const upnlEl = document.getElementById('s_upnl');
  const upnl = d.unrealized_pnl || 0;
  upnlEl.textContent = (upnl >= 0 ? '+' : '') + fmt(upnl);
  upnlEl.style.color = upnl >= 0 ? 'var(--green)' : 'var(--red)';
  const tpEl = document.getElementById('s_tpnl');
  tpEl.textContent = (tp >= 0 ? '+' : '') + fmt(tp);
  tpEl.style.color = tp >= 0 ? 'var(--green)' : 'var(--red)';
}

function renderTopSignals(data) {
  const items = Object.values(data)
    .filter(s => Math.abs(s.score) >= 30)
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
    .slice(0, 20);
  const tbody = document.getElementById('topList');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--dim);padding:16px">等待掃描...</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(s => {
    const sc = s.score;
    const cls = sc > 0 ? 'bull' : sc < 0 ? 'bear' : 'n';
    return `<tr>
      <td style="font-weight:bold">${s.symbol.replace('USDT','')}<span style="color:var(--dim)">/U</span></td>
      <td><span class="score-chip ${cls}">${sc > 0 ? '+' : ''}${sc}</span></td>
      <td style="color:${s.rsi < 30 ? 'var(--green)' : s.rsi > 70 ? 'var(--red)' : 'var(--text)'}">${s.rsi || '--'}</td>
      <td style="color:${(s.macd_h || 0) > 0 ? 'var(--green)' : 'var(--red)'}">${s.macd_h ? s.macd_h.toFixed(4) : '--'}</td>
      <td style="color:${(s.vol_ratio || 1) > 1.5 ? 'var(--green)' : 'var(--dim)'}">${s.vol_ratio || '--'}x</td>
      <td>${s.atr_pct || '--'}%</td>
      <td class="reason-small">${(s.reasons || []).join(' ')}</td>
    </tr>`;
  }).join('');
}

function renderAllSignals(data) {
  const items = Object.values(data).sort((a,b) => Math.abs(b.score)-Math.abs(a.score));
  const tbody = document.getElementById('allList');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--dim);padding:16px">等待掃描...</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(s => {
    const sc = s.score;
    const cls = sc > 0 ? 'bull' : sc < 0 ? 'bear' : 'n';
    return `<tr>
      <td style="font-weight:bold">${s.symbol.replace('USDT','')}</td>
      <td><span class="score-chip ${cls}">${sc > 0 ? '+' : ''}${sc}</span></td>
      <td>$${fmtP(s.price)}</td>
      <td class="reason-small">${(s.reasons || []).slice(0,3).join(' ')}</td>
      <td style="color:var(--dim)">${s.ts || '--'}</td>
    </tr>`;
  }).join('');
}

function renderCoinChips(top50, current, positions, scanResults) {
  const el = document.getElementById('coinChips');
  if (!top50.length) { el.textContent = '等待獲取...'; return; }
  el.innerHTML = top50.map(sym => {
    let cls = '';
    if (sym === current) cls = 'scanning';
    else if (positions[sym]) cls = 'has-pos';
    else {
      const sc = (scanResults[sym] || {}).score || 0;
      if (sc >= 50) cls = 'bull-sig';
      else if (sc <= -50) cls = 'bear-sig';
    }
    return `<span class="chip ${cls}" title="${sym}">${sym.replace('USDT','')}</span>`;
  }).join('');
}

function renderTrades(trades) {
  if (!trades || !trades.length) return;
  const tbody = document.getElementById('tradeList');
  tbody.innerHTML = trades.map(t => {
    const isOpen = t.action === '開倉';
    const badgeCls = isOpen ? 'open' : t.action.includes('TP/SL') ? 'autoc' : 'cls';
    const right = t.pnl !== undefined
      ? `<span class="${t.pnl >= 0 ? 'pnl-g' : 'pnl-r'}">${t.pnl >= 0 ? '+' : ''}${t.pnl}</span>`
      : `<span style="color:var(--dim);font-size:9px">${(t.reason || '').slice(0,20)}</span>`;
    const sym = (t.symbol || '').replace('USDT', '');
    return `<tr>
      <td>${t.time || '--'}</td>
      <td><span class="badge ${badgeCls}">${t.action || '--'}</span></td>
      <td style="font-weight:bold">${sym}</td>
      <td style="color:${t.side === 'LONG' ? 'var(--green)' : 'var(--red)'}">${t.side || '--'}</td>
      <td>$${fmtP(t.price)}</td>
      <td>${right}</td>
    </tr>`;
  }).join('');
}

function renderErrors(errs) {
  if (!errs || !errs.length) return;
  document.getElementById('eLog').innerHTML =
    errs.map(e => `<div class="ei"><span class="et">${e.time}</span>${e.msg}</div>`).join('');
}

async function closePos(sym) {
  if (!confirm(`確定手動平倉 ${sym}？`)) return;
  try {
    const r = await (await fetch('/api/close_position', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({symbol: sym})
    })).json();
    alert(r.msg);
    fetchStatus();
  } catch(e) { alert('平倉請求失敗'); }
}

async function startBot() {
  try {
    const r = await (await fetch('/api/start', {method: 'POST'})).json();
    alert(r.msg);
    fetchStatus();
  } catch(e) { alert('無法連接後端！\\n請確認 python weex_bot.py 正在運行\\n並透過 http://localhost:5000 開啟此頁面'); }
}

async function stopBot() {
  try {
    const r = await (await fetch('/api/stop', {method: 'POST'})).json();
    alert(r.msg);
  } catch(e) { alert('無法連接後端'); }
}

// ── 工具函數 ──
function set(id, val) { const el = document.getElementById(id); if (el) el.textContent = val; }
function setColor(id, val, num) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = val;
  el.className = 'mv ' + (num > 0 ? 'g' : num < 0 ? 'r' : '');
}
function fmt(n) {
  const v = parseFloat(n);
  if (isNaN(v)) return '--';
  return v.toLocaleString('en-US', {maximumFractionDigits: 4});
}
function fmtP(n) {
  const v = parseFloat(n);
  if (!v || isNaN(v)) return '--';
  if (v > 1000) return v.toLocaleString('en-US', {maximumFractionDigits: 2});
  if (v > 1)    return v.toFixed(4);
  return v.toFixed(6);
}

// ── 啟動定時刷新 ──
fetchStatus();
fetchTrades();
fetchErrors();
setInterval(fetchStatus, 4000);
setInterval(fetchTrades, 8000);
setInterval(fetchErrors, 12000);
</script>
</body>
</html>
"""


# ── 全域狀態 ──
state = {
    "running": False, "balance": 0.0, "unrealized_pnl": 0.0,
    "total_pnl": 0.0, "positions": {}, "scan_results": {},
    "top50": [], "current_scan": "", "scan_progress": 0,
    "round_count": 0, "trades": deque(maxlen=200),
    "errors": deque(maxlen=30), "win_count": 0,
    "loss_count": 0, "last_update": "",
}
_lock = threading.Lock()


# ── WEEX API 簽名 ──
def _sign(method, path, query, body):
    ts = str(int(time.time() * 1000))
    raw = ts + method.upper() + path + ("?" + query if query else "") + (body or "")
    sig = base64.b64encode(
        hmac.new(SECRET_KEY.encode(), raw.encode(), hashlib.sha256).digest()
    ).decode()
    return {"ACCESS-KEY": API_KEY, "ACCESS-SIGN": sig,
            "ACCESS-PASSPHRASE": PASSPHRASE, "ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json"}

def _get(path, params=None, signed=True):
    query = "&".join(f"{k}={v}" for k, v in (params or {}).items())
    headers = _sign("GET", path, query, "") if signed else {"Content-Type":"application/json"}
    url = BASE_URL + path + ("?" + query if query else "")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        log.warning(f"GET {path} err:{e}"); return {}

def _post(path, body):
    payload = json.dumps(body, separators=(",",":"))
    headers = _sign("POST", path, "", payload)
    try:
        r = requests.post(BASE_URL+path, headers=headers, data=payload, timeout=10)
        return r.json()
    except Exception as e:
        log.warning(f"POST {path} err:{e}"); return {}


# ── 市場資料 ──
def get_top50():
    data = _get("/capi/v3/market/tickers", signed=False)
    items = data if isinstance(data,list) else (data.get("data") or [])
    pairs = []
    for item in items:
        sym = item.get("symbol","")
        if not sym.endswith("USDT"): continue
        try:
            vol = float(item.get("quoteVolume") or item.get("volume24h") or
                        item.get("vol") or item.get("turnover",0))
            pairs.append((sym,vol))
        except: continue
    pairs.sort(key=lambda x:x[1], reverse=True)
    result = [s for s,_ in pairs[:TOP_N]]
    if not result:
        result = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
                  "DOGEUSDT","ADAUSDT","AVAXUSDT","DOTUSDT","LTCUSDT",
                  "LINKUSDT","UNIUSDT","ATOMUSDT","ETCUSDT","BCHUSDT",
                  "NEARUSDT","APTUSDT","ARBUSDT","OPUSDT","INJUSDT",
                  "SUIUSDT","SEIUSDT","TIAUSDT","ORDIUSDT","WIFUSDT",
                  "JUPUSDT","RENDERUSDT","MATICUSDT","FTMUSDT","RUNEUSDT",
                  "ONDOUSDT","AAVEUSDT","MKRUSDT","LDOUSDT","STXUSDT",
                  "GMXUSDT","DYDXUSDT","CRVUSDT","APEUSDT","SANDUSDT",
                  "MANAUSDT","AXSUSDT","GALAUSDT","IMXUSDT","CFXUSDT",
                  "MASKUSDT","SNXUSDT","PYTHUSDT","STRKUSDT","ENSUSDT"]
    log.info(f"TOP{TOP_N} 更新: {len(result)} 個")
    return result

def get_klines(symbol, interval="1m", limit=150):
    data = _get("/capi/v3/market/klines",
                {"symbol":symbol,"interval":interval,"limit":limit}, signed=False)
    if isinstance(data,list): return data
    if isinstance(data,dict): return data.get("data") or data.get("klines") or []
    return []

def get_account_balance():
    data = _get("/capi/v3/account/balance")
    bal, upnl = 0.0, 0.0
    items = data if isinstance(data,list) else (data.get("data") or [])
    for item in items:
        if item.get("asset") == "USDT":
            bal  = float(item.get("balance",0))
            upnl = float(item.get("unrealizePnl",0))
    return bal, upnl

def get_all_positions():
    data = _get("/capi/v3/account/positions")
    items = data if isinstance(data,list) else (data.get("data") or [])
    result = {}
    for p in items:
        sym = p.get("symbol","")
        amt = float(p.get("positionAmt",0))
        if abs(amt)>0 and sym:
            result[sym] = p
    return result


# ── 槓桿 ──
_lev_done = set()
def ensure_leverage(symbol):
    if symbol in _lev_done: return
    try:
        _post("/capi/v3/account/leverage",{"symbol":symbol,"side":"LONG", "leverage":str(LEVERAGE)})
        _post("/capi/v3/account/leverage",{"symbol":symbol,"side":"SHORT","leverage":str(LEVERAGE)})
        _lev_done.add(symbol)
    except Exception as e:
        log.warning(f"[{symbol}] 槓桿設定:{e}")


# ── 技術指標 ──
def _ema(prices, period):
    k = 2/(period+1); r=[prices[0]]
    for p in prices[1:]: r.append(p*k + r[-1]*(1-k))
    return r

def calc_rsi(closes, period=14):
    if len(closes)<period+2: return 50.0
    gains,losses=[],[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[-period:])/period; al=sum(losses[-period:])/period
    return 100.0 if al==0 else 100-100/(1+ag/al)

def calc_macd(closes):
    if len(closes)<MACD_S+MACD_SIG: return 0,0,0,0
    ef=_ema(closes,MACD_F); es=_ema(closes,MACD_S)
    ml=[f-s for f,s in zip(ef,es)]
    sig=_ema(ml[MACD_S:],MACD_SIG)
    h=ml[-1]-sig[-1]; hp=ml[-2]-sig[-2] if len(sig)>=2 else h
    return ml[-1],sig[-1],h,hp

def calc_bb(closes,period=20,std_m=2.0):
    if len(closes)<period: return None,None,None
    w=closes[-period:]; m=sum(w)/period
    s=math.sqrt(sum((x-m)**2 for x in w)/period)
    return m+std_m*s, m, m-std_m*s

def calc_atr(highs,lows,closes,period=14):
    if len(closes)<period+2: return 0.0
    trs=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1]))
         for i in range(1,len(closes))]
    return sum(trs[-period:])/period

def calc_vol_ratio(volumes,period=20):
    if len(volumes)<period+1: return 1.0
    avg=sum(volumes[-period-1:-1])/period
    return volumes[-1]/avg if avg>0 else 1.0


# ── 訊號計算 ──
def compute_signals(symbol, klines):
    if len(klines)<60: return {"score":0,"symbol":symbol,"reasons":["資料不足"]}
    try:
        highs  =[float(k[2]) for k in klines]
        lows   =[float(k[3]) for k in klines]
        closes =[float(k[4]) for k in klines]
        volumes=[float(k[5]) for k in klines]
    except Exception as e:
        return {"score":0,"symbol":symbol,"reasons":[f"解析錯:{e}"]}

    score=0; reasons=[]

    fe=_ema(closes,FAST_EMA); se=_ema(closes,SLOW_EMA)
    if   fe[-1]>se[-1] and fe[-2]<=se[-2]: score+=25; reasons.append("EMA黃金叉↑")
    elif fe[-1]<se[-1] and fe[-2]>=se[-2]: score-=25; reasons.append("EMA死亡叉↓")
    elif fe[-1]>se[-1]: score+=10; reasons.append("EMA多排")
    else:               score-=10; reasons.append("EMA空排")

    r=calc_rsi(closes,RSI_P)
    if   r<30: score+=20; reasons.append(f"RSI超賣{r:.0f}")
    elif r>70: score-=20; reasons.append(f"RSI超買{r:.0f}")
    elif r>60: score+=8
    elif r<40: score-=8

    _,_,h,hp=calc_macd(closes)
    if   h>0 and hp<=0: score+=20; reasons.append("MACD翻正↑")
    elif h<0 and hp>=0: score-=20; reasons.append("MACD翻負↓")
    elif h>0: score+=8
    else:     score-=8

    p=closes[-1]; bbu,bbm,bbl=calc_bb(closes,BB_P,BB_STD)
    if bbu and bbl and bbm:
        if   p<=bbl: score+=15; reasons.append("BB下軌↑")
        elif p>=bbu: score-=15; reasons.append("BB上軌↓")
        elif p>bbm:  score+=5
        else:        score-=5
        if (bbu-bbl)/bbm<0.015: reasons.append("BB窄帶⚡")

    vr=calc_vol_ratio(volumes,VOL_MA_P)
    if   vr>1.5: score+=(10 if score>0 else -10); reasons.append(f"放量{vr:.1f}x")
    elif vr<0.6: score=int(score*0.65);            reasons.append("量縮弱化")

    if len(closes)>=6:
        mom=(closes[-1]-closes[-6])/closes[-6]*100
        if   mom>0.3: score+=10; reasons.append(f"動能+{mom:.2f}%")
        elif mom<-0.3:score-=10; reasons.append(f"動能{mom:.2f}%")

    atr_val=calc_atr(highs,lows,closes,ATR_P)
    atr_pct=atr_val/closes[-1]*100 if closes[-1] else 0

    return {
        "symbol":symbol, "score":max(-100,min(100,score)),
        "reasons":reasons, "price":round(closes[-1],6),
        "rsi":round(r,1), "macd_h":round(h,6),
        "ema_fast":round(fe[-1],6), "ema_slow":round(se[-1],6),
        "bb_upper":round(bbu,6) if bbu else None,
        "bb_lower":round(bbl,6) if bbl else None,
        "atr_pct":round(atr_pct,4), "vol_ratio":round(vr,2),
        "ts":datetime.now().strftime("%H:%M:%S"),
    }


# ── 下單 ──
def calc_qty(balance, price, symbol):
    notional = balance * RISK_PCT * LEVERAGE
    qty = notional / price
    if price>10000: qty=max(0.001,round(qty,3))
    elif price>100: qty=max(0.01, round(qty,2))
    elif price>1:   qty=max(0.1,  round(qty,1))
    else:           qty=max(1,    int(qty))
    return str(qty)

def open_order(symbol, side, qty, tp, sl):
    ensure_leverage(symbol)
    pos_side="LONG" if side=="BUY" else "SHORT"
    payload = {
        "symbol":symbol, "side":side, "positionSide":pos_side,
        "type":"MARKET", "quantity":qty,
        "newClientOrderId":f"bot_{uuid.uuid4().hex[:14]}",
        "tpTriggerPrice":str(round(tp,6)), "slTriggerPrice":str(round(sl,6)),
        "TpWorkingType":"MARK_PRICE", "SlWorkingType":"MARK_PRICE",
    }
    log.info(f"[{symbol}] 下單請求: {json.dumps(payload)}")
    result = _post("/capi/v3/order", payload)
    log.info(f"[{symbol}] API 響應: {json.dumps(result)}")
    return result


def close_order(symbol, pos):
    amt=float(pos.get("positionAmt",0))
    if abs(amt)<=0: return {}
    side="SELL" if amt>0 else "BUY"
    pos_side="LONG" if side=="SELL" else "SHORT"
    payload = {
        "symbol":symbol, "side":side, "positionSide":pos_side,
        "type":"MARKET", "quantity":str(abs(round(amt,3))),
        "newClientOrderId":f"cls_{uuid.uuid4().hex[:14]}",
        "reduceOnly":True,
    }
    log.info(f"[{symbol}] 平倉請求: {json.dumps(payload)}")
    result = _post("/capi/v3/order", payload)
    log.info(f"[{symbol}] 平倉響應: {json.dumps(result)}")
    return result


# ── 持倉監控執行緒 ──
def position_monitor():
    log.info("[持倉監控] 啟動")
    while state["running"]:
        try:
            real_pos = get_all_positions()
            with _lock:
                # 偵測 TP/SL 觸發
                for sym in list(state["positions"].keys()):
                    if sym not in real_pos:
                        old=state["positions"].pop(sym)
                        entry=float(old.get("entryPrice",0))
                        amt_raw=old.get("positionAmt","0")
                        amt=float(amt_raw) if old.get("side")!="SHORT" else -abs(float(str(amt_raw).replace("-","")))
                        sig=state["scan_results"].get(sym,{})
                        mark=float(sig.get("price",entry) or entry)
                        pnl=(mark-entry)*abs(amt) if amt>0 else (entry-mark)*abs(amt)
                        state["total_pnl"]+=pnl
                        if pnl>=0: state["win_count"]+=1
                        else:      state["loss_count"]+=1
                        state["trades"].appendleft({
                            "time":datetime.now().strftime("%H:%M:%S"),
                            "action":"自動平(TP/SL)","symbol":sym,
                            "side":"LONG" if amt>0 else "SHORT",
                            "price":round(mark,6),"pnl":round(pnl,4),"reason":"TP/SL觸發",
                        })
                        log.info(f"[{sym}] TP/SL觸發 pnl={pnl:.4f}")
                # 更新真實倉位資料
                for sym,pos in real_pos.items():
                    if sym in state["positions"]:
                        state["positions"][sym].update({
                            "unrealizedProfit":pos.get("unrealizedProfit",0),
                            "markPrice":pos.get("markPrice",0),
                        })
                    else:
                        state["positions"][sym]=pos
                # 更新浮盈
                state["unrealized_pnl"]=round(
                    sum(float(p.get("unrealizedProfit",0)) for p in state["positions"].values()),4)

            # 檢查每個持倉的反向訊號
            with _lock: pos_snap=dict(state["positions"])
            for sym, pos in pos_snap.items():
                try:
                    old_sig=state["scan_results"].get(sym)
                    need_refresh=True
                    if old_sig:
                        try:
                            ts=datetime.strptime(old_sig["ts"],"%H:%M:%S").replace(
                               year=datetime.now().year,month=datetime.now().month,day=datetime.now().day)
                            if (datetime.now()-ts).seconds<90: need_refresh=False
                        except: pass
                    if need_refresh:
                        klines=get_klines(sym,INTERVAL,150)
                        if klines and len(klines)>=60:
                            sig=compute_signals(sym,klines)
                            with _lock: state["scan_results"][sym]=sig
                        else: continue
                    else: sig=old_sig

                    score=sig.get("score",0)
                    amt_str=pos.get("positionAmt","0")
                    amt=float(amt_str)
                    side="LONG" if amt>0 else "SHORT"

                    if (side=="LONG" and score<=-CLOSE_THRESHOLD) or \
                       (side=="SHORT" and score>=CLOSE_THRESHOLD):
                        log.info(f"[{sym}] 反向訊號{score:+d}→平倉")
                        result=close_order(sym,pos)
                        if result.get("success") or result.get("orderId"):
                            entry=float(pos.get("entryPrice",0))
                            mark=sig.get("price",0)
                            pnl=(mark-entry)*abs(amt) if amt>0 else (entry-mark)*abs(amt)
                            with _lock:
                                state["positions"].pop(sym,None)
                                state["total_pnl"]+=pnl
                                if pnl>=0: state["win_count"]+=1
                                else:      state["loss_count"]+=1
                                state["trades"].appendleft({
                                    "time":datetime.now().strftime("%H:%M:%S"),
                                    "action":"主動平倉","symbol":sym,"side":side,
                                    "price":round(mark,6),"pnl":round(pnl,4),
                                    "reason":f"反向訊號{score:+d}",
                                })
                        time.sleep(0.3)
                except Exception as e: log.warning(f"[{sym}] 持倉處理:{e}")
        except Exception as e:
            log.error(f"[持倉監控] 異常:{e}")
            with _lock: state["errors"].appendleft({"time":datetime.now().strftime("%H:%M:%S"),"msg":f"持倉:{e}"})
        time.sleep(POSITION_CHECK)
    log.info("[持倉監控] 結束")


# ── 掃描執行緒 ──
def scan_loop():
    log.info("[掃描] 啟動")
    top50=get_top50()
    with _lock: state["top50"]=top50

    while state["running"]:
        t_start=time.time()
        with _lock:
            state["round_count"]+=1
            round_n=state["round_count"]
        log.info(f"=== 第{round_n}輪 共{len(top50)}幣 ===")

        if round_n%10==1:
            try:
                top50=get_top50()
                with _lock: state["top50"]=top50
            except: pass

        try:
            bal,_=get_account_balance()
            with _lock: state["balance"]=round(bal,4)
        except: bal=state["balance"]

        for i,symbol in enumerate(top50):
            if not state["running"]: break
            with _lock:
                state["current_scan"]=symbol
                state["scan_progress"]=int((i+1)/len(top50)*100)
                state["last_update"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                klines=get_klines(symbol,INTERVAL,150)
                if not klines or len(klines)<60:
                    time.sleep(COIN_SCAN_DELAY); continue
                sig=compute_signals(symbol,klines)
                score=sig["score"]
                with _lock:
                    state["scan_results"][symbol]=sig
                    pos_count=len(state["positions"])
                    has_pos=symbol in state["positions"]
                    balance=state["balance"]

                if not has_pos and abs(score)>=OPEN_THRESHOLD and \
                   pos_count<MAX_POSITIONS and balance>5:
                    atr_pct=sig.get("atr_pct",0)
                    if atr_pct>=ATR_MIN_PCT:
                        price=sig["price"]
                        side="BUY" if score>0 else "SELL"
                        qty=calc_qty(balance,price,symbol)
                        av=atr_pct/100*price
                        tp=price+av*2.0 if side=="BUY" else price-av*2.0
                        sl=price-av*1.0 if side=="BUY" else price+av*1.0
                        log.info(f"[{symbol}] 開{side} 分:{score:+d} qty:{qty}")
                        result=open_order(symbol,side,qty,tp,sl)
                        if result.get("success") or result.get("orderId"):
                            dir_str="LONG" if side=="BUY" else "SHORT"
                            with _lock:
                                state["positions"][symbol]={
                                    "symbol":symbol,
                                    "positionAmt":qty if side=="BUY" else f"-{qty}",
                                    "entryPrice":str(price),"side":dir_str,
                                    "leverage":LEVERAGE,"tp":round(tp,6),
                                    "sl":round(sl,6),"score":score,
                                    "openTime":datetime.now().strftime("%H:%M:%S"),
                                    "unrealizedProfit":0,
                                }
                                state["trades"].appendleft({
                                    "time":datetime.now().strftime("%H:%M:%S"),
                                    "action":"開倉","symbol":symbol,"side":dir_str,
                                    "price":round(price,6),"qty":qty,"score":score,
                                    "reason":" | ".join(sig.get("reasons",[])[:3]),
                                })
                        time.sleep(0.5)
            except Exception as e:
                log.warning(f"[{symbol}] 掃描:{e}")
                with _lock: state["errors"].appendleft({"time":datetime.now().strftime("%H:%M:%S"),"msg":f"[{symbol}]{e}"})
            time.sleep(COIN_SCAN_DELAY)

        elapsed=time.time()-t_start
        wait=max(0,ROUND_INTERVAL-elapsed)
        log.info(f"=== 第{round_n}輪結束 耗時:{elapsed:.1f}s 等待:{wait:.1f}s ===")
        with _lock: state["current_scan"]=""; state["scan_progress"]=0
        deadline=time.time()+wait
        while time.time()<deadline and state["running"]: time.sleep(1)
    log.info("[掃描] 結束")


# ── Flask 路由 ──
@app.route("/")
def index():
    return Response(DASHBOARD_HTML, mimetype="text/html")

@app.route("/api/ping")
def api_ping():
    ok=False; msg=""
    try:
        r=requests.get("https://api-contract.weex.com/capi/v3/market/time",timeout=5)
        ok=r.status_code==200; msg=f"HTTP {r.status_code}"
    except Exception as e: msg=str(e)
    return jsonify({
        "bot_alive":True, "weex_reachable":ok, "weex_msg":msg,
        "api_key_set":bool(API_KEY), "passphrase_set":bool(PASSPHRASE),
        "secret_key_set":bool(SECRET_KEY),
        "open_threshold":OPEN_THRESHOLD, "close_threshold":CLOSE_THRESHOLD,
        "timestamp":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "warnings":[w for w in [
            "" if ok          else "❌ 無法連接 WEEX API",
            "" if API_KEY     else "❌ WEEX_API_KEY 未設定",
            "" if SECRET_KEY  else "❌ WEEX_SECRET_KEY 未設定",
            "" if PASSPHRASE  else "❌ WEEX_PASSPHRASE 未設定",
        ] if w]
    })

@app.route("/api/status")
def api_status():
    with _lock:
        win=state["win_count"]; loss=state["loss_count"]; total=win+loss
        wr=round(win/total*100,1) if total>0 else 0
        return jsonify({
            "running":state["running"], "balance":state["balance"],
            "unrealized_pnl":state["unrealized_pnl"],
            "total_pnl":round(state["total_pnl"],4),
            "positions":state["positions"], "position_count":len(state["positions"]),
            "top50":state["top50"], "current_scan":state["current_scan"],
            "scan_progress":state["scan_progress"], "round_count":state["round_count"],
            "scan_results":state["scan_results"], "last_update":state["last_update"],
            "win_count":win, "loss_count":loss, "win_rate":wr, "total_trades":total,
        })

@app.route("/api/trades")
def api_trades():
    with _lock: return jsonify(list(state["trades"]))

@app.route("/api/errors")
def api_errors():
    with _lock: return jsonify(list(state["errors"]))

@app.route("/api/start", methods=["POST"])
def api_start():
    if state["running"]: return jsonify({"ok":False,"msg":"已在運行"})
    if not API_KEY or not SECRET_KEY or not PASSPHRASE:
        return jsonify({"ok":False,"msg":"❌ 環境變數未設定！請在 Zeabur Variables 設定 WEEX_API_KEY / WEEX_SECRET_KEY / WEEX_PASSPHRASE"})
    state["running"]=True
    threading.Thread(target=scan_loop,        daemon=True,name="Scan").start()
    threading.Thread(target=position_monitor, daemon=True,name="PosMon").start()
    return jsonify({"ok":True,"msg":f"已啟動｜開倉閾值:{OPEN_THRESHOLD}分｜平倉閾值:{CLOSE_THRESHOLD}分"})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    state["running"]=False
    return jsonify({"ok":True,"msg":"停止中..."})

@app.route("/api/close_position", methods=["POST"])
def api_close_pos():
    data=freq.json or {}; sym=data.get("symbol","")
    with _lock: pos=state["positions"].get(sym)
    if not pos: return jsonify({"ok":False,"msg":f"{sym} 無持倉"})
    result=close_order(sym,pos)
    if result.get("success") or result.get("orderId") or result.get("code") == "0" or "orderId" in str(result):

        with _lock: state["positions"].pop(sym,None)
        return jsonify({"ok":True,"msg":f"{sym} 平倉送出"})
    return jsonify({"ok":False,"msg":f"失敗:{result}"})


# ── 啟動診斷 ──
def _startup_check():
    log.info("="*50)
    log.info(f"WEEX Bot v3.3 啟動  PORT={PORT}")
    log.info(f"開倉閾值:{OPEN_THRESHOLD}  平倉閾值:{CLOSE_THRESHOLD}  ATR最小:{ATR_MIN_PCT}%")
    log.info(f"WEEX_API_KEY    : {'✅ 已設定' if API_KEY    else '❌ 未設定 (請加入 Zeabur Variables)'}")
    log.info(f"WEEX_SECRET_KEY : {'✅ 已設定' if SECRET_KEY else '❌ 未設定'}")
    log.info(f"WEEX_PASSPHRASE : {'✅ 已設定' if PASSPHRASE else '❌ 未設定'}")
    try:
        r=requests.get("https://api-contract.weex.com/capi/v3/market/time",timeout=8)
        log.info(f"WEEX API: ✅ HTTP {r.status_code}")
    except Exception as e:
        log.error(f"WEEX API: ❌ {e}")
    log.info("="*50)

_startup_check()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
