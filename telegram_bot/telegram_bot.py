"""
Telegram Bot API wrapper - xabar yuborish uchun.
To'liq o'zbek tilida, hashtag'lar bilan (setup grouping uchun).

Stikerlar:
  SHORT/SELL — 📉  (pastga trend)
  LONG/BUY   — 📈  (yuqoriga trend)
  TP         — 🟢  (yashil)
  SL         — 🔴  (qizil)
  BE         — 🔵  (ko'k)
  Cancel     — 🟡  (sariq)

Har xabarda #Setup<ID> hashtag bor - Telegram'da bosib shu setupning
barcha xabarlarini ko'rish mumkin.
"""
import logging
import time
from typing import Optional
import requests

from config import Config
from models import Event, EventType, Setup, Direction

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """O'zbek tildagi batafsil formatdagi xabarlarni Telegram'ga yuboradi."""

    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    # Stikerlar (universal emoji lar - stiker fayllari kerak emas)
    EMO_SHORT = "📉"   # SHORT/SELL trend
    EMO_LONG  = "📈"   # LONG/BUY trend
    EMO_TP    = "🟢"   # Take Profit
    EMO_SL    = "🔴"   # Stop Loss
    EMO_BE    = "🔵"   # Break-Even
    EMO_CZ    = "🟡"   # Cancel Zone / Cancelled
    EMO_ENTRY = "📍"   # Entry point
    EMO_MONEY = "💰"
    EMO_TIME  = "⏰"
    EMO_CHART = "📊"
    EMO_TF    = "⏱"
    EMO_SETUP = "🎯"
    EMO_WON   = "🏆"

    def __init__(self, config: Config, price_formatter=None):
        self.config = config
        self.token = config.telegram_token
        self.chat_id = config.telegram_chat_id
        self.price_formatter = price_formatter or (lambda pair, p: f"{p:,.2f}")

    # ==================================================================
    # ASOSIY YUBORISH
    # ==================================================================

    def send_message(self, text: str, parse_mode: str = "HTML",
                     disable_notification: bool = False,
                     reply_markup: dict = None,
                     chat_id: str = None) -> bool:
        """Xabar yuborish. chat_id berilmasa - default (kanal)."""
        url = self.BASE_URL.format(token=self.token, method="sendMessage")
        target_chat = chat_id if chat_id else self.chat_id
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
            "disable_notification": disable_notification,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        for attempt in range(3):
            try:
                r = requests.post(url, json=payload, timeout=15)
                if r.status_code == 200:
                    return True
                if r.status_code == 429:
                    retry_after = r.json().get("parameters", {}).get("retry_after", 5)
                    logger.warning(f"Telegram rate limit, {retry_after}s kutish")
                    time.sleep(retry_after + 1)
                    continue
                logger.error(f"Telegram xato {r.status_code}: {r.text}")
            except requests.RequestException as e:
                logger.warning(f"Telegram request xatosi (urinish {attempt+1}): {e}")
                time.sleep(2)
        return False

    # ==================================================================
    # EVENT ROUTER
    # ==================================================================

    def notify_event(self, event: Event) -> None:
        try:
            method_map = {
                EventType.SETUP_CREATED.value: self._msg_setup_created,
                EventType.FILLED.value: self._msg_filled,
                EventType.TP1_HIT.value: self._msg_tp1,
                EventType.TP2_HIT.value: self._msg_tp2,
                EventType.TP3_HIT.value: self._msg_tp3_won,
                EventType.SL_HIT.value: self._msg_sl,
                EventType.BE_STOP.value: self._msg_be,
                EventType.CANCELLED_CZ.value: self._msg_cancelled_cz,
                EventType.CANCELLED_ROLLING.value: self._msg_cancelled_rolling,
            }
            builder = method_map.get(event.type)
            if not builder:
                logger.warning(f"Noma'lum event turi: {event.type}")
                return
            text = builder(event)
            self.send_message(text)
        except Exception as e:
            logger.exception(f"notify_event xatosi: {e}")

    # ==================================================================
    # HELPER'LAR
    # ==================================================================

    def _fmt(self, pair: str, price: float) -> str:
        return self.price_formatter(pair, price)

    def _dir_emo(self, s: Setup) -> str:
        """Yo'nalish uchun emoji: SHORT=📉, LONG=📈."""
        return self.EMO_SHORT if s.direction == Direction.SELL.value else self.EMO_LONG

    def _dir_name(self, s: Setup) -> str:
        """Yo'nalish nomi o'zbekcha."""
        return "SHORT" if s.direction == Direction.SELL.value else "LONG"

    def _pair_tag(self, pair: str) -> str:
        """Hashtag uchun juftlik nomi tayyorlash.
        BTC/USDT:USDT → BTCUSDT
        XAUUSD → XAUUSD
        """
        # Faqat asosiy qismini olamiz (`:` gacha)
        base = pair.split(":")[0] if ":" in pair else pair
        # Slash o'chirish
        return base.replace("/", "").replace("-", "").replace("=", "")

    def _hashtags(self, s: Setup, extra: Optional[str] = None) -> str:
        """Setup uchun hashtag qatori. Setup ID ni bosib klik qilib
        shu setupning barcha xabarlarini topish mumkin."""
        tags = [
            f"#Setup{s.id}",
            f"#{self._pair_tag(s.pair)}",
            f"#{self._dir_name(s)}",
        ]
        if extra:
            tags.append(extra)
        return " ".join(tags)

    def _fmt_time(self, ms: int) -> str:
        """UTC ms → chiroyli sana matni (Toshkent vaqti)."""
        from datetime import datetime, timezone
        try:
            from zoneinfo import ZoneInfo
            dt = datetime.fromtimestamp(ms / 1000, tz=ZoneInfo("Asia/Tashkent"))
            return dt.strftime("%Y-%m-%d %H:%M (Toshkent)")
        except Exception:
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M UTC")

    def _duration(self, s: Setup) -> str:
        """Setup davomiyligi (o'zbekcha)."""
        start = s.created_at_ms
        end = s.closed_at_ms or int(time.time() * 1000)
        secs = (end - start) // 1000
        if secs < 60:
            return f"{secs} soniya"
        mins = secs // 60
        if mins < 60:
            return f"{mins} daqiqa"
        hrs = mins // 60
        m = mins % 60
        if hrs < 24:
            return f"{hrs} soat {m} daq"
        days = hrs // 24
        h = hrs % 24
        return f"{days} kun {h} soat"

    # ==================================================================
    # XABAR YASOVCHILAR - EVENT'LAR
    # ==================================================================

    def _msg_setup_created(self, ev: Event) -> str:
        s = ev.setup
        cfg = self.config
        dir_emo = self._dir_emo(s)
        dir_name = self._dir_name(s)

        pnl_tp1 = s.risk_usd * (cfg.tp1_pct / 100.0) * cfg.rr_tp1
        pnl_tp2 = s.risk_usd * (cfg.tp2_pct / 100.0) * cfg.rr_tp2
        pnl_tp3 = s.risk_usd * (cfg.tp3_pct / 100.0) * cfg.rr_tp3
        total_pnl = pnl_tp1 + pnl_tp2 + pnl_tp3

        streak_type = "ko'tarilish" if s.direction == "SELL" else "tushish"
        reversal_type = "tushish" if s.direction == "SELL" else "ko'tarilish"
        cz_op = "&gt;" if s.direction == "SELL" else "&lt;"

        text = (
            f"{dir_emo} <b>{dir_name} SETUP #{s.id}</b>\n\n"
            f"{self.EMO_CHART} Juftlik: <code>{s.pair}</code>\n"
            f"{self.EMO_TF} Vaqt oralig'i: <b>{s.timeframe}</b>\n"
            f"📈 Ketma-ketlik: <b>{s.candle_count}</b> ta {streak_type} → "
            f"<b>1</b> ta {reversal_type} (burilish) ✅\n\n"
            f"{self.EMO_ENTRY} Kirish: <code>{self._fmt(s.pair, s.entry)}</code>\n"
            f"{self.EMO_SL} SL: <code>{self._fmt(s.pair, s.sl)}</code>  "
            f"(-${s.risk_usd:.2f})\n"
            f"{self.EMO_TP} TP1: <code>{self._fmt(s.pair, s.tp1)}</code>  "
            f"(+${pnl_tp1:.2f}, {cfg.tp1_pct:.0f}%)\n"
            f"{self.EMO_TP} TP2: <code>{self._fmt(s.pair, s.tp2)}</code>  "
            f"(+${pnl_tp2:.2f}, {cfg.tp2_pct:.0f}%)\n"
            f"{self.EMO_TP} TP3: <code>{self._fmt(s.pair, s.tp3)}</code>  "
            f"(+${pnl_tp3:.2f}, {cfg.tp3_pct:.0f}%)\n"
            f"{self.EMO_CZ} Bekor zonasi: {cz_op} "
            f"<code>{self._fmt(s.pair, s.cz)}</code>\n\n"
            f"{self.EMO_MONEY} Xavf: <b>${s.risk_usd:.2f}</b>  →  "
            f"Maks. foyda: <b>+${total_pnl:.2f}</b>\n"
            f"{self.EMO_TIME} Vaqt: {self._fmt_time(s.created_at_ms)}\n\n"
            f"{self._hashtags(s)}"
        )
        return text

    def _msg_filled(self, ev: Event) -> str:
        s = ev.setup
        dir_emo = self._dir_emo(s)
        return (
            f"🎬 <b>Setup #{s.id} — Bitim ochildi</b> {dir_emo}\n\n"
            f"{self.EMO_CHART} {s.pair} | {s.timeframe}\n"
            f"{self.EMO_ENTRY} Kirish: <code>{self._fmt(s.pair, ev.price)}</code>\n"
            f"{self.EMO_SL} SL: <code>{self._fmt(s.pair, s.sl)}</code>\n"
            f"{self.EMO_TP} TP: <code>{self._fmt(s.pair, s.tp1)}</code> / "
            f"<code>{self._fmt(s.pair, s.tp2)}</code> / "
            f"<code>{self._fmt(s.pair, s.tp3)}</code>\n\n"
            f"{self._hashtags(s)}"
        )

    def _msg_tp1(self, ev: Event) -> str:
        s = ev.setup
        dir_emo = self._dir_emo(s)
        be_txt = ""
        if s.be_moved:
            be_txt = f"\n{self.EMO_BE} <b>SL → Zararsizga (BE) siljidi</b> — endi xavfsiz"
        return (
            f"{self.EMO_TP} <b>Setup #{s.id} — TP1 ga tegdi</b> {dir_emo}\n\n"
            f"{self.EMO_CHART} {s.pair} | {s.timeframe}\n"
            f"{self.EMO_MONEY} Foyda: <b>+${ev.pnl_usd:.2f}</b> "
            f"(50% yopildi)\n"
            f"📊 Jami foyda: <b>${s.realized_usd:.2f}</b>"
            f"{be_txt}\n\n"
            f"{self._hashtags(s)}"
        )

    def _msg_tp2(self, ev: Event) -> str:
        s = ev.setup
        dir_emo = self._dir_emo(s)
        return (
            f"{self.EMO_TP}{self.EMO_TP} <b>Setup #{s.id} — TP2 ga tegdi</b> {dir_emo}\n\n"
            f"{self.EMO_CHART} {s.pair} | {s.timeframe}\n"
            f"{self.EMO_MONEY} Foyda: <b>+${ev.pnl_usd:.2f}</b> "
            f"(25% yopildi)\n"
            f"📊 Jami foyda: <b>${s.realized_usd:.2f}</b>\n"
            f"⏳ TP3 kutilmoqda...\n\n"
            f"{self._hashtags(s)}"
        )

    def _msg_tp3_won(self, ev: Event) -> str:
        s = ev.setup
        dir_emo = self._dir_emo(s)
        return (
            f"{self.EMO_WON}{self.EMO_WON}{self.EMO_WON} "
            f"<b>Setup #{s.id} — G'ALABA!</b> {dir_emo}\n\n"
            f"{self.EMO_CHART} {s.pair} | {s.timeframe}\n"
            f"{self.EMO_MONEY} Foyda: <b>+${ev.pnl_usd:.2f}</b> "
            f"(TP3, so'nggi 25%)\n"
            f"🎉 <b>Umumiy foyda: +${s.realized_usd:.2f}</b>\n"
            f"⏱ Davomiyligi: {self._duration(s)}\n\n"
            f"{self._hashtags(s, extra='#Won')}"
        )

    def _msg_sl(self, ev: Event) -> str:
        s = ev.setup
        dir_emo = self._dir_emo(s)
        partial_txt = ""
        if s.partial_level > 0:
            partial_txt = f" (qisman: TP{s.partial_level} tegilgan edi)"
        return (
            f"{self.EMO_SL} <b>Setup #{s.id} — SL ga tegdi</b> {dir_emo}\n\n"
            f"{self.EMO_CHART} {s.pair} | {s.timeframe}\n"
            f"💸 Zarar: <b>${ev.pnl_usd:.2f}</b>{partial_txt}\n"
            f"📊 Umumiy: <b>${s.realized_usd:.2f}</b>\n\n"
            f"{self._hashtags(s, extra='#Lost')}"
        )

    def _msg_be(self, ev: Event) -> str:
        s = ev.setup
        dir_emo = self._dir_emo(s)
        prior = "TP1"
        if s.partial_level == 2:
            prior = "TP1 + TP2"
        return (
            f"{self.EMO_BE} <b>Setup #{s.id} — Zararsiz (BE) to'xtash</b> {dir_emo}\n\n"
            f"{self.EMO_CHART} {s.pair} | {s.timeframe}\n"
            f"✅ SL kirish narxida ishladi — <b>zarar yo'q</b>\n"
            f"📊 Umumiy foyda: <b>+${s.realized_usd:.2f}</b> "
            f"({prior} dan)\n\n"
            f"{self._hashtags(s, extra='#BE')}"
        )

    def _msg_cancelled_cz(self, ev: Event) -> str:
        s = ev.setup
        dir_emo = self._dir_emo(s)
        return (
            f"{self.EMO_CZ} <b>Setup #{s.id} — Bekor bo'ldi</b> {dir_emo}\n\n"
            f"{self.EMO_CHART} {s.pair} | {s.timeframe}\n"
            f"📉 Bekor zonasi buzildi @ <code>{self._fmt(s.pair, ev.price)}</code>\n"
            f"ℹ️ Narx kirish nuqtasiga yetmadi\n\n"
            f"{self._hashtags(s, extra='#Cancel')}"
        )

    def _msg_cancelled_rolling(self, ev: Event) -> str:
        s = ev.setup
        dir_emo = self._dir_emo(s)
        return (
            f"{self.EMO_CZ} <b>Setup #{s.id} — Bekor</b> (rolling) {dir_emo}\n\n"
            f"{self.EMO_CHART} {s.pair} | {s.timeframe}\n"
            f"ℹ️ Yangi setup paydo bo'ldi — eski bekor qilindi\n\n"
            f"{self._hashtags(s, extra='#Cancel')}"
        )

    # ==================================================================
    # KUNLIK REPORT
    # ==================================================================

    def send_daily_report(self, daily_stats: dict, day: str,
                          tz_label: str = "UTC") -> None:
        if not daily_stats:
            text = (
                f"{self.EMO_CHART} <b>KUNLIK STATISTIKA</b>\n"
                f"📅 <b>{day}</b> ({tz_label})\n\n"
                f"ℹ️ Bugun hech qanday setup bo'lmadi."
            )
            self.send_message(text)
            return

        tot_setups = sum(s.setups_created for s in daily_stats.values())
        tot_won = sum(s.won for s in daily_stats.values())
        tot_lost = sum(s.lost for s in daily_stats.values())
        tot_be = sum(s.be for s in daily_stats.values())
        tot_cancelled = sum(s.cancelled for s in daily_stats.values())
        tot_partial = sum(s.partial_tp1 for s in daily_stats.values())
        tot_usd = sum(s.total_usd for s in daily_stats.values())
        pnl_emo = "📈" if tot_usd >= 0 else "📉"
        pnl_sign = "+" if tot_usd >= 0 else ""

        pair_blocks = []
        sorted_pairs = sorted(daily_stats.items(),
                              key=lambda kv: -kv[1].setups_created)
        for pair, s in sorted_pairs:
            if s.setups_created == 0 and s.total_usd == 0:
                continue
            pnl_pair = "+" if s.total_usd >= 0 else ""
            pair_pnl_emo = "🟢" if s.total_usd > 0 else ("🔴" if s.total_usd < 0 else "⚪")
            block = (
                f"\n<b>{pair}</b> {pair_pnl_emo}\n"
                f"  {self.EMO_SETUP} Setuplar: <b>{s.setups_created}</b>"
            )
            if s.won or s.be or s.lost or s.cancelled:
                block += (
                    f"\n  {self.EMO_WON} G'oliblar: {s.won}  |  "
                    f"{self.EMO_BE} BE: {s.be}  |  "
                    f"{self.EMO_SL} Zarar: {s.lost}  |  "
                    f"{self.EMO_CZ} Bekor: {s.cancelled}"
                )
            if s.partial_tp1:
                block += f"\n  {self.EMO_TP} TP1 qisman: {s.partial_tp1}"
            block += f"\n  {self.EMO_MONEY} F/Z: <b>{pnl_pair}${s.total_usd:.2f}</b>"
            pair_blocks.append(block)

        text = (
            f"{self.EMO_CHART} <b>KUNLIK STATISTIKA</b>\n"
            f"📅 <b>{day}</b> ({tz_label})\n"
            + "".join(pair_blocks) +
            f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>JAMI:</b>\n"
            f"  {self.EMO_SETUP} Setuplar: <b>{tot_setups}</b>  |  "
            f"{self.EMO_TP} TP1: {tot_partial}\n"
            f"  {self.EMO_WON} G'oliblar: <b>{tot_won}</b>  |  "
            f"{self.EMO_BE} BE: <b>{tot_be}</b>  |  "
            f"{self.EMO_SL} Zarar: <b>{tot_lost}</b>  |  "
            f"{self.EMO_CZ} Bekor: <b>{tot_cancelled}</b>\n"
            f"  {pnl_emo} <b>Foyda/Zarar: {pnl_sign}${tot_usd:.2f}</b>"
        )
        self.send_message(text)

    # ==================================================================
    # STARTUP / SHUTDOWN
    # ==================================================================

    def send_startup(self, pairs, timeframes, min_candles: int) -> None:
        pairs_str = ", ".join(pairs)
        tf_str = ", ".join(timeframes)
        be_state = "YOQILGAN ✅" if self.config.enable_be else "O'CHIRILGAN ❌"
        text = (
            f"🚀 <b>SERIYA Bot yoqildi</b>\n\n"
            f"{self.EMO_CHART} Juftliklar: <code>{pairs_str}</code>\n"
            f"{self.EMO_TF} Vaqt oralig'i: <code>{tf_str}</code>\n"
            f"📈 Min svechalar: <b>{min_candles}</b>\n"
            f"{self.EMO_MONEY} Xavf (har bitim): <b>${self.config.risk_usd:.2f}</b>\n"
            f"{self.EMO_BE} Zararsiz (BE): <b>{be_state}</b>\n\n"
            f"✅ Setuplar tez orada ko'rinadi..."
        )
        self.send_message(text)

    def send_shutdown(self) -> None:
        self.send_message("🛑 <b>SERIYA Bot to'xtatildi</b>")

    def send_error(self, err: str) -> None:
        safe = err.replace("<", "&lt;").replace(">", "&gt;")[:1000]
        self.send_message(f"⚠️ <b>Bot xatosi</b>\n<pre>{safe}</pre>")

    def send_stats(self, counters, active_count: int) -> None:
        """Umumiy statistika xabari (kunlik hisobot uchun ishlatilmaydi,
        alohida statistika so'rovi bo'lsa)."""
        total = counters.won + counters.lost + counters.be
        win_rate = (counters.won / total * 100) if total > 0 else 0.0
        profit_rate = ((counters.won + counters.be) / total * 100) if total > 0 else 0.0

        text = (
            f"{self.EMO_CHART} <b>SERIYA BOT — Statistika</b>\n\n"
            f"{self.EMO_SETUP} Jami setuplar: <b>{counters.total_setups}</b>\n"
            f"{self.EMO_WON} G'oliblar (TP3): <b>{counters.won}</b>\n"
            f"{self.EMO_TP} TP1 qisman: <b>{counters.partial_tp1}</b>\n"
            f"{self.EMO_BE} Zararsiz (BE): <b>{counters.be}</b>\n"
            f"{self.EMO_SL} Zarar (SL): <b>{counters.lost}</b>\n"
            f"{self.EMO_CZ} Bekor bo'lgan: <b>{counters.cancelled}</b>\n"
            f"⏳ Aktiv: <b>{active_count}</b>\n\n"
            f"📈 G'olib foizi: <b>{win_rate:.1f}%</b>\n"
            f"💚 Foydali foizi: <b>{profit_rate:.1f}%</b>\n\n"
            f"{self.EMO_MONEY} Umumiy F/Z: <b>${counters.total_usd:.2f}</b>\n"
            f"🚀 Eng yaxshi bitim: <b>+${counters.best_usd:.2f}</b>\n"
            f"💥 Eng yomon bitim: <b>${counters.worst_usd:.2f}</b>"
        )
        self.send_message(text)
