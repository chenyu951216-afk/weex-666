#!/usr/bin/env python3
"""
WEEX 量化交易機器人 v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
架構: 雙執行緒 — 掃描執行緒 + 持倉監控執行緒
掃描: 市場成交量 TOP 50 合約幣種
節奏: 幣與幣間隔 0.2s  輪與輪間隔 60s
持倉: 獨立執行緒每 5 秒追蹤一次，即時進出場
策略: EMA + RSI + MACD + BB + ATR + 量比 + 動能
槓桿: 200x  倉位: 帳戶總資金 5%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import hmac, hashlib, base64, time, json, math, uuid, logging, threading
import requests
from datetime import datetime
from collections import deque
from flask import Flask, jsonify, request as freq
from flask_cors import CORS

# ============== 設定區 ==============
API_KEY    = "weex_daaae7ef113a0c31629162734b86c26d"
SECRET_KEY = "70597e9e9359e4c9b01d86982b9385a3d381f83ea1c0ed599b2f2c5e6a48a9bd"
PASSPHRASE = ""          # 必填！建立 API 時設定的 Passphrase

BASE_URL         = "https://api-contract.weex.com"
LEVERAGE         = 200
RISK_PCT         = 0.05        # 每筆倉位佔帳戶 5%
INTERVAL         = "1m"        # K線週期
TOP_N            = 50          # 掃描成交量前 N 名
COIN_SCAN_DELAY  = 0.2         # 幣與幣掃描間隔 (秒)
ROUND_INTERVAL   = 60          # 輪與輪間隔 (秒)
POSITION_CHECK   = 5           # 持倉監控間隔 (秒)
OPEN_THRESHOLD   = 65          # 開倉訊號閾值
CLOSE_THRESHOLD  = 55          # 反向平倉閾值
ATR_MIN_PCT      = 0.04        # ATR 最低波動過濾
MAX_POSITIONS    = 5           # 最多同時持倉數
LOG_FILE         = "weex_bot.log"

# 技術指標參數
FAST_EMA  = 9
SLOW_EMA  = 21
RSI_P     = 14
MACD_F    = 12
MACD_S    = 26
MACD_SIG  = 9
BB_P      = 20
BB_STD    = 2.0
ATR_P     = 14
VOL_MA_P  = 20
# ====================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ============== 全域狀態 ==============
state = {
    "running":        False,
    "balance":        0.0,
    "unrealized_pnl": 0.0,
    "total_pnl":      0.0,
    "positions":      {},      # symbol -> position dict
    "scan_results":   {},      # symbol -> signal dict
    "top50":          [],
    "current_scan":   "",
    "scan_progress":  0,
    "round_count":    0,
    "trades":         deque(maxlen=200),
    "errors":         deque(maxlen=30),
    "win_count":      0,
    "loss_count":     0,
    "last_update":    "",
}
_lock = threading.Lock()


# ============== WEEX API ==============
def _sign(method, path, query, body):
    ts = str(int(time.time() * 1000))
    raw = ts + method.upper() + path
    if query:
        raw += "?" + query
    raw += (body or "")
    sig = base64.b64encode(
        hmac.new(SECRET_KEY.encode(), raw.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "ACCESS-KEY":        API_KEY,
        "ACCESS-SIGN":       sig,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP":  ts,
        "Content-Type":      "application/json",
    }

def _get(path, params=None, signed=True):
    query = "&".join(f"{k}={v}" for k, v in (params or {}).items())
    headers = _sign("GET", path, query, "") if signed else {"Content-Type": "application/json"}
    url = BASE_URL + path + ("?" + query if query else "")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        log.warning(f"GET {path} err: {e}")
        return {}

def _post(path, body):
    payload = json.dumps(body, separators=(",", ":"))
    headers = _sign("POST", path, "", payload)
    try:
        r = requests.post(BASE_URL + path, headers=headers, data=payload, timeout=10)
        return r.json()
    except Exception as e:
        log.warning(f"POST {path} err: {e}")
        return {}


# ============== 市場資料 ==============
def get_top50_symbols():
    """取得合約市場成交量 TOP50 USDT 幣種"""
    data = _get("/capi/v3/market/tickers", signed=False)
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data") or data.get("tickers") or []

    pairs = []
    for item in items:
        sym = item.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        try:
            vol = float(item.get("quoteVolume") or item.get("volume24h") or
                        item.get("vol") or item.get("turnover", 0))
            pairs.append((sym, vol))
        except Exception:
            continue

    pairs.sort(key=lambda x: x[1], reverse=True)
    result = [s for s, _ in pairs[:TOP_N]]

    if not result:
        result = [
            "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
            "DOGEUSDT","ADAUSDT","AVAXUSDT","DOTUSDT","LTCUSDT",
            "LINKUSDT","UNIUSDT","ATOMUSDT","ETCUSDT","BCHUSDT",
            "NEARUSDT","APTUSDT","ARBUSDT","OPUSDT","INJUSDT",
            "SUIUSDT","SEIUSDT","TIAUSDT","ORDIUSDT","WIFUSDT",
            "JUPUSDT","RENDERUSDT","MATICUSDT","FTMUSDT","RUNEUSDT",
            "ONDOUSDT","PYTHUSDT","STRKUSDT","AAVEUSDT","MKRUSDT",
            "SNXUSDT","GMXUSDT","DYDXUSDT","CRVUSDT","LDOUSDT",
            "STXUSDT","CFXUSDT","MASKUSDT","APEUSDT","SANDUSDT",
            "MANAUSDT","AXSUSDT","GALAUSDT","ILVUSDT","IMXUSDT"
        ]
    log.info(f"TOP{TOP_N} 更新完成，共 {len(result)} 個")
    return result

def get_klines(symbol, interval="1m", limit=150):
    data = _get("/capi/v3/market/klines",
                {"symbol": symbol, "interval": interval, "limit": limit},
                signed=False)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data") or data.get("klines") or []
    return []

def get_account_balance():
    data = _get("/capi/v3/account/balance")
    balance, upnl = 0.0, 0.0
    items = data if isinstance(data, list) else (data.get("data") or [])
    for item in items:
        if item.get("asset") == "USDT":
            balance = float(item.get("balance", 0))
            upnl    = float(item.get("unrealizePnl", 0))
    return balance, upnl

def get_all_positions():
    """回傳 {symbol: pos_dict} 所有非零倉位"""
    data = _get("/capi/v3/account/positions")
    items = data if isinstance(data, list) else (data.get("data") or [])
    result = {}
    for p in items:
        sym = p.get("symbol", "")
        amt = float(p.get("positionAmt", 0))
        if abs(amt) > 0 and sym:
            result[sym] = p
    return result


# ============== 槓桿設定 ==============
_lev_done = set()

def ensure_leverage(symbol):
    if symbol in _lev_done:
        return
    try:
        _post("/capi/v3/account/leverage", {"symbol": symbol, "side": "LONG",  "leverage": str(LEVERAGE)})
        _post("/capi/v3/account/leverage", {"symbol": symbol, "side": "SHORT", "leverage": str(LEVERAGE)})
        _lev_done.add(symbol)
    except Exception as e:
        log.warning(f"[{symbol}] 槓桿設定失敗: {e}")


# ============== 技術指標 ==============
def _ema(prices, period):
    k = 2 / (period + 1)
    r = [prices[0]]
    for p in prices[1:]:
        r.append(p * k + r[-1] * (1 - k))
    return r

def calc_rsi(closes, period=14):
    if len(closes) < period + 2:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)

def calc_macd(closes):
    if len(closes) < MACD_S + MACD_SIG:
        return 0, 0, 0, 0
    ef = _ema(closes, MACD_F)
    es = _ema(closes, MACD_S)
    ml = [f - s for f, s in zip(ef, es)]
    sig = _ema(ml[MACD_S:], MACD_SIG)
    h     = ml[-1] - sig[-1]
    h_prv = ml[-2] - sig[-2] if len(sig) >= 2 else h
    return ml[-1], sig[-1], h, h_prv

def calc_bb(closes, period=20, std_m=2.0):
    if len(closes) < period:
        return None, None, None
    w = closes[-period:]
    m = sum(w) / period
    s = math.sqrt(sum((x - m)**2 for x in w) / period)
    return m + std_m * s, m, m - std_m * s

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < period + 2:
        return 0.0
    trs = [max(highs[i] - lows[i],
               abs(highs[i] - closes[i-1]),
               abs(lows[i]  - closes[i-1]))
           for i in range(1, len(closes))]
    return sum(trs[-period:]) / period

def calc_vol_ratio(volumes, period=20):
    if len(volumes) < period + 1:
        return 1.0
    avg = sum(volumes[-period-1:-1]) / period
    return volumes[-1] / avg if avg > 0 else 1.0


# ============== 訊號計算引擎 ==============
def compute_signals(symbol, klines):
    if len(klines) < 60:
        return {"score": 0, "symbol": symbol, "reasons": ["資料不足"]}
    try:
        highs   = [float(k[2]) for k in klines]
        lows    = [float(k[3]) for k in klines]
        closes  = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
    except Exception as e:
        return {"score": 0, "symbol": symbol, "reasons": [f"解析錯:{e}"]}

    score = 0
    reasons = []

    # 1. EMA 交叉 +-25
    fe = _ema(closes, FAST_EMA)
    se = _ema(closes, SLOW_EMA)
    if   fe[-1] > se[-1] and fe[-2] <= se[-2]: score += 25; reasons.append("EMA黃金叉↑")
    elif fe[-1] < se[-1] and fe[-2] >= se[-2]: score -= 25; reasons.append("EMA死亡叉↓")
    elif fe[-1] > se[-1]: score += 10; reasons.append("EMA多排")
    else:                 score -= 10; reasons.append("EMA空排")

    # 2. RSI +-20
    r = calc_rsi(closes, RSI_P)
    if   r < 28:  score += 20; reasons.append(f"RSI超賣{r:.0f}")
    elif r > 72:  score -= 20; reasons.append(f"RSI超買{r:.0f}")
    elif r > 60:  score += 8
    elif r < 40:  score -= 8

    # 3. MACD +-20
    _, _, h, hp = calc_macd(closes)
    if   h > 0 and hp <= 0: score += 20; reasons.append("MACD翻正↑")
    elif h < 0 and hp >= 0: score -= 20; reasons.append("MACD翻負↓")
    elif h > 0: score += 8
    else:       score -= 8

    # 4. Bollinger Bands +-15
    p = closes[-1]
    bbu, bbm, bbl = calc_bb(closes, BB_P, BB_STD)
    if bbu and bbl and bbm:
        if   p <= bbl: score += 15; reasons.append("BB下軌↑")
        elif p >= bbu: score -= 15; reasons.append("BB上軌↓")
        elif p > bbm:  score += 5
        else:          score -= 5
        bw = (bbu - bbl) / bbm
        if bw < 0.015: reasons.append("BB窄帶⚡")

    # 5. 成交量 +-10
    vr = calc_vol_ratio(volumes, VOL_MA_P)
    if   vr > 1.5: score += (10 if score > 0 else -10); reasons.append(f"放量{vr:.1f}x")
    elif vr < 0.6: score = int(score * 0.65);            reasons.append("量縮弱化")

    # 6. 動能 +-10
    if len(closes) >= 6:
        mom = (closes[-1] - closes[-6]) / closes[-6] * 100
        if   mom >  0.4: score += 10; reasons.append(f"動能+{mom:.2f}%")
        elif mom < -0.4: score -= 10; reasons.append(f"動能{mom:.2f}%")

    atr_val = calc_atr(highs, lows, closes, ATR_P)
    atr_pct = atr_val / closes[-1] * 100 if closes[-1] else 0

    return {
        "symbol":   symbol,
        "score":    max(-100, min(100, score)),
        "reasons":  reasons,
        "price":    round(closes[-1], 6),
        "rsi":      round(r, 1),
        "macd_h":   round(h, 6),
        "ema_fast": round(fe[-1], 6),
        "ema_slow": round(se[-1], 6),
        "bb_upper": round(bbu, 6) if bbu else None,
        "bb_lower": round(bbl, 6) if bbl else None,
        "atr_pct":  round(atr_pct, 4),
        "vol_ratio":round(vr, 2),
        "ts":       datetime.now().strftime("%H:%M:%S"),
    }


# ============== 下單函數 ==============
def calc_qty(balance, price, symbol):
    notional = balance * RISK_PCT * LEVERAGE
    qty = notional / price
    if price > 10000: qty = max(0.001, round(qty, 3))
    elif price > 100: qty = max(0.01,  round(qty, 2))
    elif price > 1:   qty = max(0.1,   round(qty, 1))
    else:             qty = max(1,     int(qty))
    return str(qty)

def open_order(symbol, side, qty, tp, sl):
    ensure_leverage(symbol)
    pos_side = "LONG" if side == "BUY" else "SHORT"
    return _post("/capi/v3/order", {
        "symbol":           symbol,
        "side":             side,
        "positionSide":     pos_side,
        "type":             "MARKET",
        "quantity":         qty,
        "newClientOrderId": f"bot_{uuid.uuid4().hex[:14]}",
        "tpTriggerPrice":   str(round(tp, 6)),
        "slTriggerPrice":   str(round(sl, 6)),
        "TpWorkingType":    "MARK_PRICE",
        "SlWorkingType":    "MARK_PRICE",
    })

def close_order(symbol, pos):
    amt = float(pos.get("positionAmt", 0))
    if abs(amt) <= 0:
        return {}
    side     = "SELL" if amt > 0 else "BUY"
    pos_side = "LONG" if side == "SELL" else "SHORT"
    return _post("/capi/v3/order", {
        "symbol":           symbol,
        "side":             side,
        "positionSide":     pos_side,
        "type":             "MARKET",
        "quantity":         str(abs(round(amt, 3))),
        "newClientOrderId": f"cls_{uuid.uuid4().hex[:14]}",
        "reduceOnly":       True,
    })


# ============== 持倉監控執行緒 ==============
def position_monitor():
    """
    每 5 秒執行一次：
    1. 從交易所同步真實倉位（偵測 TP/SL 自動觸發）
    2. 對每個持倉幣重新計算訊號，反向則主動平倉
    3. 更新帳面浮虧浮盈
    """
    log.info("[持倉監控] 啟動")
    while state["running"]:
        try:
            real_pos = get_all_positions()

            with _lock:
                # 偵測被 TP/SL 觸發平掉的倉位
                for sym in list(state["positions"].keys()):
                    if sym not in real_pos:
                        old  = state["positions"].pop(sym)
                        entry = float(old.get("entryPrice", 0))
                        amt   = float(old.get("positionAmt", 0) or
                                      (old.get("qty", "0") if old.get("side") == "LONG"
                                       else f"-{old.get('qty','0')}"))
                        sig   = state["scan_results"].get(sym, {})
                        mark  = float(sig.get("price", entry) or entry)
                        pnl   = (mark - entry) * abs(amt) if amt > 0 else (entry - mark) * abs(amt)
                        state["total_pnl"] += pnl
                        if pnl >= 0: state["win_count"] += 1
                        else:        state["loss_count"] += 1
                        state["trades"].appendleft({
                            "time":   datetime.now().strftime("%H:%M:%S"),
                            "action": "自動平(TP/SL)",
                            "symbol": sym,
                            "side":   "LONG" if amt > 0 else "SHORT",
                            "price":  round(mark, 6),
                            "pnl":    round(pnl, 4),
                            "reason": "TP/SL觸發",
                        })
                        log.info(f"[{sym}] TP/SL平倉 PnL={pnl:.4f}")

                # 更新交易所同步回來的倉位資料
                for sym, pos in real_pos.items():
                    if sym in state["positions"]:
                        state["positions"][sym].update({
                            "unrealizedProfit": pos.get("unrealizedProfit", 0),
                            "markPrice":        pos.get("markPrice", 0),
                        })
                    else:
                        state["positions"][sym] = pos

            # 對每個持倉重新評訊號
            with _lock:
                pos_snap = dict(state["positions"])

            for sym, pos in pos_snap.items():
                try:
                    # 取最新訊號 (若上次掃描超過 2 分鐘則重新計算)
                    old_sig = state["scan_results"].get(sym)
                    need_refresh = True
                    if old_sig:
                        try:
                            ts = datetime.strptime(old_sig["ts"], "%H:%M:%S").replace(
                                year=datetime.now().year,
                                month=datetime.now().month,
                                day=datetime.now().day)
                            if (datetime.now() - ts).seconds < 120:
                                need_refresh = False
                        except Exception:
                            pass

                    if need_refresh:
                        klines = get_klines(sym, INTERVAL, 150)
                        if klines and len(klines) >= 60:
                            sig = compute_signals(sym, klines)
                            with _lock:
                                state["scan_results"][sym] = sig
                        else:
                            continue
                    else:
                        sig = old_sig

                    score = sig.get("score", 0)
                    amt   = float(pos.get("positionAmt", 0) or
                                  (pos.get("qty", "0") if pos.get("side") == "LONG"
                                   else f"-{pos.get('qty','0')}"))
                    side  = "LONG" if amt > 0 else "SHORT"

                    should_close = (
                        (side == "LONG"  and score <= -CLOSE_THRESHOLD) or
                        (side == "SHORT" and score >= CLOSE_THRESHOLD)
                    )

                    if should_close:
                        log.info(f"[{sym}] 反向訊號 {score:+d} -> 主動平倉")
                        result = close_order(sym, pos)
                        if result.get("success") or result.get("orderId"):
                            entry = float(pos.get("entryPrice", 0))
                            mark  = sig.get("price", 0)
                            pnl   = (mark - entry)*abs(amt) if amt > 0 else (entry - mark)*abs(amt)
                            with _lock:
                                state["positions"].pop(sym, None)
                                state["total_pnl"] += pnl
                                if pnl >= 0: state["win_count"] += 1
                                else:        state["loss_count"] += 1
                                state["trades"].appendleft({
                                    "time":   datetime.now().strftime("%H:%M:%S"),
                                    "action": "主動平倉",
                                    "symbol": sym,
                                    "side":   side,
                                    "price":  round(mark, 6),
                                    "pnl":    round(pnl, 4),
                                    "reason": f"反向訊號{score:+d}",
                                })
                        time.sleep(0.3)

                except Exception as e:
                    log.warning(f"[{sym}] 持倉處理異常: {e}")

            # 更新總浮虧浮盈
            with _lock:
                state["unrealized_pnl"] = round(
                    sum(float(p.get("unrealizedProfit", 0)) for p in state["positions"].values()), 4
                )

        except Exception as e:
            log.error(f"[持倉監控] 異常: {e}", exc_info=True)
            with _lock:
                state["errors"].appendleft({"time": datetime.now().strftime("%H:%M:%S"), "msg": f"持倉監控:{e}"})

        time.sleep(POSITION_CHECK)
    log.info("[持倉監控] 結束")


# ============== 掃描主執行緒 ==============
def scan_loop():
    """
    每輪掃描 TOP50，幣間隔 0.2s，輪間隔 60s
    發現訊號時開倉，並允許同時持有最多 MAX_POSITIONS 個倉位
    """
    log.info("[掃描] 啟動")
    top50 = get_top50_symbols()
    with _lock:
        state["top50"] = top50

    while state["running"]:
        t_start = time.time()
        with _lock:
            state["round_count"] += 1
            round_n = state["round_count"]

        log.info(f"=== 第 {round_n} 輪開始，共 {len(top50)} 幣 ===")

        # 每 10 輪刷新一次 TOP50
        if round_n % 10 == 1:
            try:
                top50 = get_top50_symbols()
                with _lock:
                    state["top50"] = top50
            except Exception:
                pass

        # 每輪開始時更新餘額
        try:
            bal, _ = get_account_balance()
            with _lock:
                state["balance"] = round(bal, 4)
        except Exception:
            bal = state["balance"]

        for i, symbol in enumerate(top50):
            if not state["running"]:
                break

            with _lock:
                state["current_scan"] = symbol
                state["scan_progress"] = int((i + 1) / len(top50) * 100)
                state["last_update"]   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            try:
                klines = get_klines(symbol, INTERVAL, 150)
                if not klines or len(klines) < 60:
                    time.sleep(COIN_SCAN_DELAY)
                    continue

                sig   = compute_signals(symbol, klines)
                score = sig["score"]

                with _lock:
                    state["scan_results"][symbol] = sig
                    pos_count    = len(state["positions"])
                    has_position = symbol in state["positions"]
                    balance      = state["balance"]

                # 開倉條件
                if (not has_position
                        and abs(score) >= OPEN_THRESHOLD
                        and pos_count < MAX_POSITIONS
                        and balance > 5):

                    atr_pct = sig.get("atr_pct", 0)
                    if atr_pct >= ATR_MIN_PCT:
                        price = sig["price"]
                        side  = "BUY" if score > 0 else "SELL"
                        qty   = calc_qty(balance, price, symbol)
                        av    = atr_pct / 100 * price
                        if side == "BUY":
                            tp = price + av * 2.2
                            sl = price - av * 1.1
                        else:
                            tp = price - av * 2.2
                            sl = price + av * 1.1

                        log.info(f"[{symbol}] 開{side} 分:{score:+d} qty:{qty} TP:{tp:.4f} SL:{sl:.4f}")
                        result = open_order(symbol, side, qty, tp, sl)
                        log.info(f"[{symbol}] 回應: {result}")

                        if result.get("success") or result.get("orderId"):
                            dir_str = "LONG" if side == "BUY" else "SHORT"
                            with _lock:
                                state["positions"][symbol] = {
                                    "symbol":      symbol,
                                    "positionAmt": qty if side == "BUY" else f"-{qty}",
                                    "entryPrice":  str(price),
                                    "side":        dir_str,
                                    "leverage":    LEVERAGE,
                                    "tp":          round(tp, 6),
                                    "sl":          round(sl, 6),
                                    "score":       score,
                                    "openTime":    datetime.now().strftime("%H:%M:%S"),
                                    "unrealizedProfit": 0,
                                }
                                state["trades"].appendleft({
                                    "time":   datetime.now().strftime("%H:%M:%S"),
                                    "action": "開倉",
                                    "symbol": symbol,
                                    "side":   dir_str,
                                    "price":  round(price, 6),
                                    "qty":    qty,
                                    "score":  score,
                                    "reason": " | ".join(sig.get("reasons", [])[:3]),
                                })
                        time.sleep(0.5)

            except Exception as e:
                log.warning(f"[{symbol}] 掃描異常: {e}")
                with _lock:
                    state["errors"].appendleft({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "msg":  f"[{symbol}] {e}"
                    })

            time.sleep(COIN_SCAN_DELAY)

        elapsed = time.time() - t_start
        wait    = max(0, ROUND_INTERVAL - elapsed)
        log.info(f"=== 第 {round_n} 輪結束 耗時:{elapsed:.1f}s 等待:{wait:.1f}s ===")

        with _lock:
            state["current_scan"]  = ""
            state["scan_progress"] = 0

        deadline = time.time() + wait
        while time.time() < deadline and state["running"]:
            time.sleep(1)

    log.info("[掃描] 結束")


# ============== Flask API ==============
@app.route("/api/status")
def api_status():
    with _lock:
        win   = state["win_count"]
        loss  = state["loss_count"]
        total = win + loss
        wr    = round(win / total * 100, 1) if total > 0 else 0
        return jsonify({
            "running":        state["running"],
            "balance":        state["balance"],
            "unrealized_pnl": state["unrealized_pnl"],
            "total_pnl":      round(state["total_pnl"], 4),
            "positions":      state["positions"],
            "position_count": len(state["positions"]),
            "top50":          state["top50"],
            "current_scan":   state["current_scan"],
            "scan_progress":  state["scan_progress"],
            "round_count":    state["round_count"],
            "scan_results":   state["scan_results"],
            "last_update":    state["last_update"],
            "win_count":      win,
            "loss_count":     loss,
            "win_rate":       wr,
            "total_trades":   total,
        })

@app.route("/api/trades")
def api_trades():
    with _lock:
        return jsonify(list(state["trades"]))

@app.route("/api/errors")
def api_errors():
    with _lock:
        return jsonify(list(state["errors"]))

@app.route("/api/scan_results")
def api_scan_results():
    with _lock:
        items = sorted(state["scan_results"].values(),
                       key=lambda x: abs(x.get("score", 0)), reverse=True)
        return jsonify(items[:50])

@app.route("/api/start", methods=["POST"])
def api_start():
    if state["running"]:
        return jsonify({"ok": False, "msg": "已在運行中"})
    state["running"] = True
    threading.Thread(target=scan_loop,        daemon=True, name="ScanLoop").start()
    threading.Thread(target=position_monitor, daemon=True, name="PosMonitor").start()
    return jsonify({"ok": True, "msg": "已啟動 掃描執行緒 + 持倉監控執行緒"})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    state["running"] = False
    return jsonify({"ok": True, "msg": "停止中，當前輪結束後關閉..."})

@app.route("/api/close_position", methods=["POST"])
def api_close_pos():
    data = freq.json or {}
    sym  = data.get("symbol", "")
    with _lock:
        pos = state["positions"].get(sym)
    if not pos:
        return jsonify({"ok": False, "msg": f"{sym} 無持倉"})
    result = close_order(sym, pos)
    if result.get("success") or result.get("orderId"):
        with _lock:
            state["positions"].pop(sym, None)
        return jsonify({"ok": True, "msg": f"{sym} 手動平倉送出"})
    return jsonify({"ok": False, "msg": f"失敗: {result}"})

@app.route("/")
def index():
    return "WEEX Bot v3.0 — Open dashboard.html"

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════╗")
    print("║   WEEX 量化機器人 v3.0  多幣掃描版          ║")
    print("║   掃描: TOP50 成交量合約幣種                 ║")
    print("║   節奏: 幣間 0.2s | 輪間 60s                ║")
    print("║   持倉: 獨立執行緒每 5s 追蹤，即時進出場    ║")
    print("║   API : http://localhost:5000                ║")
    print("╠══════════════════════════════════════════════╣")
    print("║   填入 PASSPHRASE 後執行此檔即可             ║")
    print("║   ⚠  200x 槓桿極高風險，請謹慎使用          ║")
    print("╚══════════════════════════════════════════════╝")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
