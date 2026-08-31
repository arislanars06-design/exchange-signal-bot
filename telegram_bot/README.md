# 🤖 SERIYA Bot — Binance Futures + Telegram Alerts

**Fibonacci asosidagi seriya strategiyasi** uchun avtomatik signal bot.
Binance Futures'dan real-time ma'lumot oladi, seriya patterni aniqlaydi,
va Telegram'ga batafsil signallar yuboradi.

TradingView'ga muhtoj emas — mustaqil ishlaydi.

---

## 📋 Mundarija

1. [Xususiyatlar](#-xususiyatlar)
2. [Telegram bot yaratish](#-1-telegram-bot-yaratish)
3. [VPS tayyorlash](#-2-vps-tayyorlash)
4. [O'rnatish](#-3-orrnatish)
5. [Sozlash](#-4-sozlash)
6. [Ishga tushirish](#-5-ishga-tushirish)
7. [Boshqarish](#-6-boshqarish)
8. [Muammolarni tuzatish](#-muammolarni-tuzatish)
9. [Fayllar haqida](#-fayllar-haqida)

---

## 🎯 Xususiyatlar

- ✅ **Binance Futures** (USDT-M perpetual) — public API, key kerak emas
- ✅ **Ko'p juftlik + ko'p timeframe** — `.env` orqali sozlanadi
- ✅ **Real-time monitoring** — 30 soniyada bir marta poll
- ✅ **Fibonacci asosida SL/TP** — 3 tier partial (50/25/25%)
- ✅ **Break-Even avtomatik** — TP1 dan keyin SL entry'ga siljiydi
- ✅ **Batafsil Telegram xabarlar** — Setup/Fill/TP/SL/BE/Cancel eventlari
- ✅ **State persistence** — bot restart qilinganda ham setup'lar yo'qolmaydi
- ✅ **Systemd service** — VPS'da 24/7 avtomatik ishlaydi
- ✅ **Graceful shutdown** — ctrl+c yoki systemd stop'da toza yopiladi

---

## 📱 1. Telegram bot yaratish

### 1.1. Bot yaratish (BotFather)

1. Telegram'da **@BotFather** ni oching → `/start` bosing
2. `/newbot` yozing
3. Bot nomi kiriting (masalan: `Mening Seriya Botim`)
4. Bot username kiriting — **`bot`** bilan tugashi kerak (masalan: `myseriya_bot`)
5. BotFather sizga **token** beradi — bu ko'rinishda:
   ```
   1234567890:AAAA-BBBBBBBBBBBBBBBBBBBBBBBBBB
   ```
   **Bu tokenni saqlab qo'ying!** — bu bot uchun parol.

### 1.2. Chat ID topish

Bot signallarni **qayerga** yuborishi kerak? Sizning shaxsiy chat'ingizga yoki kanalga.

**Variant A — Shaxsiy chat:**

1. Yaratgan botingizni Telegram'da qidiring va oching
2. **`/start`** yuboring
3. Brauzerda quyidagi URL'ga o'ting (`<TOKEN>` o'rniga o'z tokeningizni qo'ying):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
4. Javobda `"chat":{"id":123456789,...}` ko'rinadi — o'sha raqam **chat_id**

**Variant B — Kanal:**

1. Telegram'da yangi **channel** yarating
2. Bot'ni channel administratorlariga qo'shing (postlash huquqi bilan)
3. Channel'ga bironta xabar yuboring
4. Yuqoridagi URL orqali `chat_id` ni oling — bu manfiy son bo'ladi (masalan `-1001234567890`)

**Variant C — Guruh:**

1. Bot'ni guruhga qo'shing
2. Guruhda `/start@your_bot` yozing
3. `getUpdates` orqali chat_id ni oling

---

## 🖥 2. VPS tayyorlash

### 2.1. VPS tanlash

Tavsiya etiladigan opsiyalar:

| Provider | Narx | Xarakteristika |
|----------|------|----------------|
| **Oracle Cloud Free Tier** | Bepul (abadiy) | 1 GB RAM, ARM CPU ⭐ |
| **Hetzner Cloud** | €4/oy | CX11 - 2 vCPU, 2 GB RAM |
| **Contabo** | €4/oy | 4 vCPU, 8 GB RAM |
| **DigitalOcean** | $6/oy | Basic Droplet |
| **Vultr** | $6/oy | Regular Cloud |

**Minimal talablar:**
- Ubuntu 22.04 yoki Debian 12
- 512 MB RAM
- 5 GB disk
- Root/sudo huquqi

### 2.2. VPS'ga SSH orqali kirish

VPS provayder sizga IP manzil va parol/kalit beradi:

```bash
ssh root@YOUR_VPS_IP
```

---

## ⚙️ 3. O'rnatish

### 3.1. Kodni VPS'ga yuklash

**Variant A — GitHub'dan clone (agar sizda repo bor bo'lsa):**

```bash
cd /tmp
git clone https://github.com/USERNAME/REPO.git seriya-bot-source
cd seriya-bot-source/telegram_bot
```

**Variant B — SCP orqali fayllarni ko'chirish:**

Lokal kompyuteringizdan:
```bash
scp -r /path/to/telegram_bot root@YOUR_VPS_IP:/tmp/
```

Keyin VPS'da:
```bash
cd /tmp/telegram_bot
```

**Variant C — Fayllarni qo'lda yaratish:**

VPS'da har bir faylni `nano` bilan yarating (agar internet cheklangan bo'lsa).

### 3.2. Install skriptni ishga tushirish

```bash
sudo bash deploy/install.sh
```

Bu skript quyidagilarni bajaradi:
- Python 3 va kerakli paketlarni o'rnatadi
- `seriya` foydalanuvchisini yaratadi (xavfsizlik uchun)
- Kod'ni `/opt/seriya-bot/` ga nusxalaydi
- Virtualenv yaratadi va dependency'larni o'rnatadi
- Systemd service'ni ro'yxatga oladi

---

## 🔧 4. Sozlash

### 4.1. `.env` faylni tahrirlash

```bash
sudo nano /opt/seriya-bot/.env
```

Kamida quyidagilarni to'ldiring:

```env
# Telegram
TELEGRAM_TOKEN=1234567890:AAAA-BBBBBBBBBBBBBBBBBBBBBBBBBB
TELEGRAM_CHAT_ID=123456789

# Kuzatiladigan juftliklar (Binance Futures format)
PAIRS=BTC/USDT,ETH/USDT,SOL/USDT

# Timeframes
TIMEFRAMES=15m,1h

# Strategiya
MIN_CANDLES=3
ENABLE_BE=true
RISK_USD=10.0
```

**Muhim:** `Ctrl+O` → `Enter` → `Ctrl+X` — nano'da saqlash.

### 4.2. Ruxsatlarni tekshirish

```bash
sudo chown seriya:seriya /opt/seriya-bot/.env
sudo chmod 600 /opt/seriya-bot/.env
```

### 4.3. Konfiguratsiyani tekshirish (sinov)

Bot'ni bir marta qo'lda ishga tushirib, xato yo'qligini tekshiring:

```bash
sudo -u seriya /opt/seriya-bot/venv/bin/python /opt/seriya-bot/main.py
```

Agar barchasi to'g'ri bo'lsa — Telegram'ga **"🚀 SERIYA Bot yoqildi"** xabari keladi.

To'xtatish: `Ctrl+C`

---

## 🚀 5. Ishga tushirish

Bot 24/7 fon'da ishlashi uchun systemd service'ni yoqing:

```bash
sudo systemctl enable --now seriya-bot
```

Holatini tekshirish:
```bash
sudo systemctl status seriya-bot
```

Loglarni ko'rish (real-time):
```bash
sudo journalctl -u seriya-bot -f
```

Loglarni oxirgi 100 satr:
```bash
sudo journalctl -u seriya-bot -n 100 --no-pager
```

---

## 🎛 6. Boshqarish

### Odatiy komandalar

| Komanda | Qaytaradi |
|---------|-----------|
| `sudo systemctl start seriya-bot` | Botni ishga tushirish |
| `sudo systemctl stop seriya-bot` | Botni to'xtatish |
| `sudo systemctl restart seriya-bot` | Qayta ishga tushirish |
| `sudo systemctl status seriya-bot` | Holatini ko'rish |
| `sudo systemctl disable seriya-bot` | Auto-start'ni o'chirish |
| `sudo journalctl -u seriya-bot -f` | Real-time loglar |

### Sozlamalarni o'zgartirish

```bash
sudo nano /opt/seriya-bot/.env
sudo systemctl restart seriya-bot
```

### Kod yangilash

Yangi versiya kelgan bo'lsa:

```bash
# Lokal papkangizdan
scp -r /path/to/telegram_bot root@VPS_IP:/tmp/

# VPS'da
cd /tmp/telegram_bot
sudo bash deploy/install.sh   # .env qayta yozilmaydi
sudo systemctl restart seriya-bot
```

### State faylni tozalash

Bot'ni "toza" holatdan boshlash uchun:

```bash
sudo systemctl stop seriya-bot
sudo rm /opt/seriya-bot/state.json
sudo systemctl start seriya-bot
```

---

## 🐛 Muammolarni tuzatish

### Bot ishlamayapti

```bash
sudo systemctl status seriya-bot
sudo journalctl -u seriya-bot -n 50 --no-pager
```

### Telegram xabar kelmayapti

1. `.env` da token va chat_id to'g'rimi tekshiring
2. Bot'ga `/start` yuborilganmi?
3. Chat_id manfiy bo'lsa (kanal/guruh) — bot admin qilib qo'shilganmi?
4. Log'da xato ko'rinadi:
   ```
   sudo journalctl -u seriya-bot | grep -i telegram
   ```

### "Juftlik topilmadi" xatosi

Binance Futures juftlik format: `BTC/USDT` (spot format bilan bir xil, lekin
faqat USDT-M perpetual mavjud coinlar).

Tekshirish:
```bash
curl -s https://fapi.binance.com/fapi/v1/exchangeInfo | \
  grep -o '"symbol":"[^"]*"' | head -20
```

### Rate limit xatolari

`.env` da `POLL_INTERVAL_SECONDS` ni oshirning (masalan 60).

### Signal juda ko'p keladi

`.env` da:
- `MIN_CANDLES` ni oshiring (3 → 4 yoki 5)
- Kamroq juftlik/timeframe qoldiring

### Signal umuman kelmayapti

- Timeframe kattamikan? (`4h`, `1d` da signal kam bo'ladi)
- Bozor sokinmi? (yon harakatda seriya kam)
- Log'da qanday svechalar qayta ishlanayotganini tekshiring:
  ```bash
  sudo journalctl -u seriya-bot | grep "yangi setup"
  ```

---

## 📁 Fayllar haqida

```
telegram_bot/
├── main.py              # Asosiy entrypoint, poll loop
├── config.py            # .env dan sozlamalar
├── models.py            # Setup, StreakState, Event dataclass'lari
├── exchange.py          # Binance Futures API (ccxt)
├── strategy.py          # SERIYA logikasi (Pine Script'dan port)
├── telegram_bot.py      # Telegram xabar yuborish
├── state.py             # JSON persistence
├── requirements.txt     # ccxt, requests, python-dotenv
├── .env.example         # Sozlamalar shabloni
├── .env                 # Sizning real sozlamalaringiz (git'ga qo'shmang!)
├── state.json           # Bot holati (avtomatik yaratiladi)
├── README.md            # Bu fayl
└── deploy/
    ├── install.sh              # VPS o'rnatish skripti
    └── seriya-bot.service      # Systemd unit
```

---

## ⚠️ Xavfsizlik eslatmalari

1. **`.env` faylni hech qachon Git'ga commit qilmang** — token bor
2. **`chmod 600 .env`** — faqat egasiga o'qish
3. **VPS'da firewall yoqing** (`ufw enable` + faqat SSH port ochiq)
4. **SSH kalit** parol o'rniga (kalit-based auth)
5. **Bot faqat public API** ishlatadi — savdo qilmaydi, faqat signal beradi

---

## 📊 Xabar formati namunasi

### Setup yaratildi:
```
🔴 SELL Setup #12
📊 Pair: BTC/USDT
⏱ Timeframe: 15m
📈 Series: 4 bullish candles

📍 Entry: 45,000.00
🛑 SL: 45,500.00 (-$10.00)
🎯 TP1: 44,500.00 (+$3.09, 50%)
🎯 TP2: 44,000.00 (+$4.05, 25%)
🎯 TP3: 43,500.00 (+$6.55, 25%)
❌ Cancel Zone: > 45,500.00

💰 Risk: $10.00  → Max reward: +$13.69
⏰ Time: 2026-08-29 14:23 UTC
```

### TP1 tegdi (BE bilan):
```
🎯 Setup #12 TP1 hit 🔴
📊 BTC/USDT | 15m
💵 +$3.09 (50% partial closed)
📊 Total P/L: $3.09
🩵 SL → Break-Even (endi risksiz)
```

### WON:
```
🏆🏆🏆 Setup #12 WON! 🔴
📊 BTC/USDT | 15m
💵 +$6.55 (TP3, final 25%)
🎉 Total P/L: +$13.69
⏱ Duration: 2h 15m
```

---

## 🔗 Foydali havolalar

- [Binance Futures API docs](https://binance-docs.github.io/apidocs/futures/en/)
- [ccxt library](https://github.com/ccxt/ccxt)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [systemd service reference](https://www.freedesktop.org/software/systemd/man/systemd.service.html)

---

**Muvaffaqiyat!** 🚀 Savol bo'lsa yoki muammo chiqsa — log'larni ko'ring va debug qiling.
