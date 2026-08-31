# 📊 Exchange Signal Bot — Seriya Strategiyasi

Fibonacci asosidagi **SERIYA (ketma-ket svechalar)** strategiyasi uchun to'liq to'plam:

- 📈 **TradingView Pine Script v5** — vizualizatsiya + backtest
- 🤖 **Python Telegram Bot** — Binance Futures'dan real-time signal

---

## 🗂 Loyiha tuzilmasi

```
.
├── two_candles_strategy.pine   # TradingView Pine Script (v5.2, 632 qator)
├── telegram_bot/               # Python bot - Binance + Telegram
│   ├── main.py                 # Asosiy loop
│   ├── strategy.py             # SERIYA logikasi
│   ├── exchange.py             # Binance Futures (ccxt)
│   ├── telegram_bot.py         # Telegram xabarlar
│   ├── ...
│   ├── deploy/                 # VPS o'rnatish
│   └── README.md               # 🔗 To'liq deploy qo'llanmasi
└── README.md                   # bu fayl
```

---

## 🚀 Tez boshlash

### TradingView Pine Script (vizual)
1. `two_candles_strategy.pine` faylni oching
2. TradingView Pine Editor'ga joylang
3. Ma'lumot: [Strategiya izohi](telegram_bot/README.md)

### Python Telegram Bot (real-time signallar)

**VPS'da tez o'rnatish:**

```bash
git clone https://github.com/arislanars06-design/exchange-signal-bot.git
cd exchange-signal-bot/telegram_bot
sudo bash deploy/install.sh
sudo nano /opt/seriya-bot/.env    # tokenlar va sozlamalar
sudo systemctl enable --now seriya-bot
```

**To'liq qo'llanma**: [`telegram_bot/README.md`](telegram_bot/README.md)

---

## 📋 Strategiya qisqacha

- **SELL**: 3+ ketma-ket bullish svecha + `close > firstOpen`
- **BUY**: 3+ ketma-ket bearish svecha + `close < firstOpen`
- **Entry** = fib 1 (firstOpen)
- **SL** = fib 0 (last close)
- **TP1/TP2/TP3** = fib 1.618/2.618/3.618 (50/25/25% partial)
- **Break-even**: TP1 dan keyin SL → entry
- **Cancel Zone**: signal candle close narxi

---

## 🔒 Xavfsizlik

- `.env` **hech qachon** git'ga commit qilinmasin (`.gitignore` da bor)
- Bot **faqat public API** ishlatadi — savdo qilmaydi, faqat signal beradi
- Faqat sizning Telegram chat/kanalingizga xabar yuboradi

---

## 📄 Litsenziya

Shaxsiy loyiha. Ochiq kod, foydalanish uchun bepul.
