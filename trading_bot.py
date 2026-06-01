import requests
import time
import pandas as pd
import numpy as np
from datetime import datetime

# ============================================================
#  BEÁLLÍTÁSOK – csak ezt kell módosítani
# ============================================================
DISCORD_WEBHOOK_URL = "IDE_ILLESZD_BE_A_DISCORD_WEBHOOK_URL-T"
SYMBOL = "bitcoin"        # CoinGecko ID: bitcoin, ethereum, stb.
SYMBOL_DISPLAY = "BTCUSDT"
CHECK_EVERY_SECONDS = 300  # 5 perc
# ============================================================


def get_klines(coin_id: str, limit: int = 100) -> pd.DataFrame:
    """Gyertyaadatok lekérése a CoinGecko API-ról (ingyenes, nincs blokkolva)."""
    # 1 napos OHLC adatok (max 90 nap ingyen)
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": "90"}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    df = pd.DataFrame(data, columns=["open_time", "open", "high", "low", "close"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["volume"] = 0.0  # CoinGecko OHLC nem ad volume-ot, placeholder
    df = df.tail(limit).reset_index(drop=True)
    return df


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """RSI, EMA20, EMA50, MACD számítása."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    return df


def detect_signal(df: pd.DataFrame):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = last["close"]
    rsi = last["rsi"]
    ema20 = last["ema20"]
    ema50 = last["ema50"]
    macd = last["macd"]
    macd_sig = last["macd_signal"]

    bullish_points = 0
    bearish_points = 0

    if ema20 > ema50:
        bullish_points += 2
    else:
        bearish_points += 2

    if rsi < 35:
        bullish_points += 2
    elif rsi > 65:
        bearish_points += 2
    elif 45 < rsi < 60:
        bullish_points += 1

    if prev["macd"] < prev["macd_signal"] and macd > macd_sig:
        bullish_points += 3
    elif prev["macd"] > prev["macd_signal"] and macd < macd_sig:
        bearish_points += 3

    if price > ema20:
        bullish_points += 1
    else:
        bearish_points += 1

    total = bullish_points + bearish_points
    if total == 0:
        return None

    bull_conf = (bullish_points / total) * 100
    bear_conf = (bearish_points / total) * 100

    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]

    if bull_conf >= 65:
        entry = round(price, 1)
        stop = round(price - 1.5 * atr, 1)
        target = round(price + 2.5 * atr, 1)
        pattern = detect_pattern(df)
        return ("Bullish", pattern, entry, stop, target, round(bull_conf))

    elif bear_conf >= 65:
        entry = round(price, 1)
        stop = round(price + 1.5 * atr, 1)
        target = round(price - 2.5 * atr, 1)
        pattern = detect_pattern(df, bearish=True)
        return ("Bearish", pattern, entry, stop, target, round(bear_conf))

    return None


def detect_pattern(df: pd.DataFrame, bearish: bool = False) -> str:
    last3 = df.iloc[-3:]
    highs = last3["high"].values
    lows = last3["low"].values

    if not bearish:
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            return "Bull Flag"
        if lows[-1] > lows[-2] > lows[-3]:
            return "Higher Lows (uptrend)"
        return "Bullish Momentum"
    else:
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            return "Bear Flag"
        if highs[-1] < highs[-2] < highs[-3]:
            return "Lower Highs (downtrend)"
        return "Bearish Momentum"


def send_discord(signal_data: tuple, symbol: str):
    trend, pattern, entry, stop, target, confidence = signal_data

    emoji = "🟢" if trend == "Bullish" else "🔴"
    rr = abs(target - entry) / abs(entry - stop) if abs(entry - stop) > 0 else 0

    message = {
        "embeds": [{
            "title": f"{emoji} {symbol} – Trading Jelzés",
            "color": 0x00ff88 if trend == "Bullish" else 0xff4444,
            "fields": [
                {"name": "📈 Trend", "value": trend, "inline": True},
                {"name": "🔍 Pattern", "value": pattern, "inline": True},
                {"name": "⬇️ Belépő", "value": f"**{entry:,}**", "inline": True},
                {"name": "🛑 Stop Loss", "value": f"{stop:,}", "inline": True},
                {"name": "🎯 Target", "value": f"{target:,}", "inline": True},
                {"name": "⚖️ R:R arány", "value": f"1 : {rr:.1f}", "inline": True},
                {"name": "💡 Bizalom", "value": f"{confidence}%", "inline": True},
            ],
            "footer": {"text": f"Bot | {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"},
            "thumbnail": {"url": "https://cryptologos.cc/logos/bitcoin-btc-logo.png"}
        }]
    }

    resp = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=10)
    if resp.status_code in (200, 204):
        print(f"[{datetime.now()}] ✅ Jelzés elküldve: {trend} @ {entry}")
    else:
        print(f"[{datetime.now()}] ❌ Discord hiba: {resp.status_code} – {resp.text}")


def main():
    print(f"🤖 Trading bot elindult – {SYMBOL_DISPLAY} figyelése (napi gyertyák, CoinGecko)")
    print(f"   Ellenőrzés: minden {CHECK_EVERY_SECONDS // 60} percben\n")

    while True:
        try:
            df = get_klines(SYMBOL)
            df = calculate_indicators(df)
            signal = detect_signal(df)

            if signal:
                send_discord(signal, SYMBOL_DISPLAY)
            else:
                print(f"[{datetime.now()}] Nincs elég erős jelzés most.")

        except requests.RequestException as e:
            print(f"[{datetime.now()}] ❌ Hálózati hiba: {e}")
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Váratlan hiba: {e}")

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
