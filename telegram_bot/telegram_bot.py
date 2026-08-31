"""
Telegram Bot API wrapper - xabar yuborish uchun.
Faqat 'requests' kutubxonasi ishlatiladi (minimal dependency).
"""
import logging
import time
from typing import Optional
import requests

from config import Config
from models import Event, EventType, Setup, Direction

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Batafsil formatdagi xabarlarni Telegram'ga yuboradi (Markdown v2 style)."""

    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, config: Config, price_formatter=None):
        self.config = config
        self.token = config.telegram_token
        self.chat_id = config.telegram_chat_id
        # Narxni formatlash uchun callable (BinanceFutures.format_price)
        self.price_formatter = price_formatter or (lambda pair, p: f"{p:,.2f}")

    # ==================================================================
    # ASOSIY YUBORISH
    # ==================================================================

    def send_message(self, text: str, parse_mode: str = "HTML",
                     disable_notification: bool = False) -> bool:
        """Bitta xabar yuboradi. True qaytaradi agar muvaffaqiyatli bo'lsa."""
        url = self.BASE_URL.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
            "disable_notification": disable_notification,
        }
        for attempt in range(3):
            try:
                r = requests.post(url, json=payload, timeout=15)
                if r.status_code == 200:
                    return True
                if r.status_code == 429:
                    # Rate limit - kutamiz
                    retry_after = r.json().get("parameters", {}).get("retry_after", 5)
                    logger.warning(f"Telegram rate limit, {retry_after}s kutish")
                    time.sleep(retry_after + 1)
                    continue
                logger.error(f"Telegram xato {r.status_code}: {r.text}")
            except requests.RequestException as e:
                logger.warning(f"Telegram request xatosi (attempt {attempt+1}): {e}")
                time.sleep(2)
        return False

    # ==================================================================
    # EVENT XABARLARI
    # ==================================================================

    def notify_event(self, event: Event) -> None:
        """Event turiga qarab tegishli xabarni yuboradi."""
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
    # XABAR YASOVCHILAR
    # ==================================================================

    def _fmt(self, pair: str, price: float) -> str:
        return self.price_formatter(pair, price)

    def _dir_emoji(self, s: Setup) -> str:
        return "🔴" if s.direction == Direction.SELL.value else "🟢"

    def _fmt_time(self, ms: int) -> str:
        """UTC vaqtni chiroyli format'da qaytaradi."""
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")

    def _msg_setup_created(self, ev: Event) -> str:
        s = ev.setup
        cfg = self.config
        emo = self._dir_emoji(s)
        pnl_tp1 = s.risk_usd * (cfg.tp1_pct / 100.0) * cfg.rr_tp1
        pnl_tp2 = s.risk_usd * (cfg.tp2_pct / 100.0) * cfg.rr_tp2
        pnl_tp3 = s.risk_usd * (cfg.tp3_pct / 100.0) * cfg.rr_tp3
        total_pnl = pnl_tp1 + pnl_tp2 + pnl_tp3

        # Reversal candle turi (SELL uchun bearish reversal, BUY uchun bullish)
        streak_type = "bullish" if s.direction == "SELL" else "bearish"
        reversal_type = "bearish" if s.direction == "SELL" else "bullish"

        text = (
            f"{emo} <b>{s.direction} Setup #{s.id}</b>\n"
            f"📊 Pair: <code>{s.pair}</code>\n"
            f"⏱ Timeframe: <b>{s.timeframe}</b>\n"
            f"📈 Series: <b>{s.candle_count}</b> {streak_type} → "
            f"<b>1</b> {reversal_type} reversal ✅\n\n"
            f"📍 Entry: <code>{self._fmt(s.pair, s.entry)}</code>\n"
            f"🛑 SL: <code>{self._fmt(s.pair, s.sl)}</code> "
            f"(-${s.risk_usd:.2f})\n"
            f"🎯 TP1: <code>{self._fmt(s.pair, s.tp1)}</code> "
            f"(+${pnl_tp1:.2f}, {cfg.tp1_pct:.0f}%)\n"
            f"🎯 TP2: <code>{self._fmt(s.pair, s.tp2)}</code> "
            f"(+${pnl_tp2:.2f}, {cfg.tp2_pct:.0f}%)\n"
            f"🎯 TP3: <code>{self._fmt(s.pair, s.tp3)}</code> "
            f"(+${pnl_tp3:.2f}, {cfg.tp3_pct:.0f}%)\n"
            f"❌ Cancel Zone: "
            f"{'&gt;' if s.direction == 'SELL' else '&lt;'} "
            f"<code>{self._fmt(s.pair, s.cz)}</code>\n\n"
            f"💰 Risk: <b>${s.risk_usd:.2f}</b>  "
            f"→ Max reward: <b>+${total_pnl:.2f}</b>\n"
            f"⏰ Time: {self._fmt_time(s.created_at_ms)}"
        )
        return text

    def _msg_filled(self, ev: Event) -> str:
        s = ev.setup
        return (
            f"🎬 <b>Setup #{s.id} FILLED</b> {self._dir_emoji(s)}\n"
            f"📊 {s.pair} | {s.timeframe}\n"
            f"📍 Entry: <code>{self._fmt(s.pair, ev.price)}</code>\n"
            f"🛑 SL: <code>{self._fmt(s.pair, s.sl)}</code>\n"
            f"🎯 TP1/2/3: <code>{self._fmt(s.pair, s.tp1)}</code> / "
            f"<code>{self._fmt(s.pair, s.tp2)}</code> / "
            f"<code>{self._fmt(s.pair, s.tp3)}</code>"
        )

    def _msg_tp1(self, ev: Event) -> str:
        s = ev.setup
        be_txt = "\n🩵 <b>SL → Break-Even</b> (endi risksiz)" if s.be_moved else ""
        return (
            f"🎯 <b>Setup #{s.id} TP1 hit</b> {self._dir_emoji(s)}\n"
            f"📊 {s.pair} | {s.timeframe}\n"
            f"💵 <b>+${ev.pnl_usd:.2f}</b> "
            f"(50% partial closed)\n"
            f"📊 Total P/L: <b>${s.realized_usd:.2f}</b>"
            f"{be_txt}"
        )

    def _msg_tp2(self, ev: Event) -> str:
        s = ev.setup
        return (
            f"🎯🎯 <b>Setup #{s.id} TP2 hit</b> {self._dir_emoji(s)}\n"
            f"📊 {s.pair} | {s.timeframe}\n"
            f"💵 <b>+${ev.pnl_usd:.2f}</b> "
            f"(25% partial closed)\n"
            f"📊 Total P/L: <b>${s.realized_usd:.2f}</b>\n"
            f"⏳ TP3 kutilmoqda..."
        )

    def _msg_tp3_won(self, ev: Event) -> str:
        s = ev.setup
        return (
            f"🏆🏆🏆 <b>Setup #{s.id} WON!</b> {self._dir_emoji(s)}\n"
            f"📊 {s.pair} | {s.timeframe}\n"
            f"💵 <b>+${ev.pnl_usd:.2f}</b> (TP3, final 25%)\n"
            f"🎉 <b>Total P/L: +${s.realized_usd:.2f}</b>\n"
            f"⏱ Duration: {self._duration(s)}"
        )

    def _msg_sl(self, ev: Event) -> str:
        s = ev.setup
        partial_txt = ""
        if s.partial_level > 0:
            partial_txt = f" (partial: TP{s.partial_level} tegilgan edi)"
        return (
            f"🔴 <b>Setup #{s.id} SL hit</b> {self._dir_emoji(s)}\n"
            f"📊 {s.pair} | {s.timeframe}\n"
            f"💸 <b>${ev.pnl_usd:.2f}</b>{partial_txt}\n"
            f"📊 Total P/L: <b>${s.realized_usd:.2f}</b>"
        )

    def _msg_be(self, ev: Event) -> str:
        s = ev.setup
        return (
            f"🩵 <b>Setup #{s.id} Break-Even Stop</b> {self._dir_emoji(s)}\n"
            f"📊 {s.pair} | {s.timeframe}\n"
            f"✅ SL entry'da ishladi - <b>0 zarar</b>\n"
            f"📊 Total P/L: <b>+${s.realized_usd:.2f}</b> "
            f"(TP1{'+TP2' if s.partial_level == 2 else ''} dan)"
        )

    def _msg_cancelled_cz(self, ev: Event) -> str:
        s = ev.setup
        return (
            f"❌ <b>Setup #{s.id} CANCELLED</b> {self._dir_emoji(s)}\n"
            f"📊 {s.pair} | {s.timeframe}\n"
            f"📉 CZ buzildi @ <code>{self._fmt(s.pair, ev.price)}</code>\n"
            f"ℹ️ Narx entry'ga tegmadi"
        )

    def _msg_cancelled_rolling(self, ev: Event) -> str:
        s = ev.setup
        return (
            f"🔄 <b>Setup #{s.id} CANCELLED</b> (rolling) {self._dir_emoji(s)}\n"
            f"📊 {s.pair} | {s.timeframe}\n"
            f"ℹ️ Yangi setup paydo bo'ldi - eski bekor qilindi"
        )

    def _duration(self, s: Setup) -> str:
        """Setup davomiyligini chiroyli formatlash."""
        start = s.created_at_ms
        end = s.closed_at_ms or int(time.time() * 1000)
        secs = (end - start) // 1000
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m"
        hrs = mins // 60
        mins = mins % 60
        if hrs < 24:
            return f"{hrs}h {mins}m"
        days = hrs // 24
        hrs = hrs % 24
        return f"{days}d {hrs}h"

    # ==================================================================
    # DAILY REPORT (ixtiyoriy)
    # ==================================================================

    def send_stats(self, counters, active_count: int) -> None:
        """Statistika xabarini yuboradi (kunlik/haftalik hisobot uchun)."""
        total = counters.won + counters.lost + counters.be
        win_rate = (counters.won / total * 100) if total > 0 else 0.0
        profit_rate = ((counters.won + counters.be) / total * 100) if total > 0 else 0.0

        text = (
            f"📊 <b>SERIYA BOT - Statistika</b>\n\n"
            f"🎯 Jami setup: <b>{counters.total_setups}</b>\n"
            f"🏆 WON (TP3): <b>{counters.won}</b>\n"
            f"🎯 TP1 partial: <b>{counters.partial_tp1}</b>\n"
            f"🩵 BE stop: <b>{counters.be}</b>\n"
            f"🔴 LOST (SL): <b>{counters.lost}</b>\n"
            f"❌ CANCELLED: <b>{counters.cancelled}</b>\n"
            f"⏳ Aktiv: <b>{active_count}</b>\n\n"
            f"📈 Win Rate: <b>{win_rate:.1f}%</b>\n"
            f"💚 Profit Rate: <b>{profit_rate:.1f}%</b>\n\n"
            f"💰 Total P/L: <b>${counters.total_usd:.2f}</b>\n"
            f"🚀 Best trade: <b>+${counters.best_usd:.2f}</b>\n"
            f"💥 Worst trade: <b>${counters.worst_usd:.2f}</b>"
        )
        self.send_message(text)

    def send_startup(self, pairs, timeframes, min_candles: int) -> None:
        """Bot yoqilganda xabar yuborish."""
        pairs_str = ", ".join(pairs)
        tf_str = ", ".join(timeframes)
        text = (
            f"🚀 <b>SERIYA Bot yoqildi</b>\n\n"
            f"📊 Juftliklar: <code>{pairs_str}</code>\n"
            f"⏱ Timeframes: <code>{tf_str}</code>\n"
            f"📈 Min svechalar: <b>{min_candles}</b>\n"
            f"💰 Risk / bitim: <b>${self.config.risk_usd:.2f}</b>\n"
            f"🩵 Break-Even: <b>{'ON' if self.config.enable_be else 'OFF'}</b>\n\n"
            f"✅ Setuplar yaqinda paydo bo'ladi..."
        )
        self.send_message(text)

    def send_shutdown(self) -> None:
        self.send_message("🛑 <b>SERIYA Bot to'xtatildi</b>")

    def send_daily_report(self, daily_stats: dict, day: str,
                          tz_label: str = "UTC") -> None:
        """
        Kunlik statistika hisobotini yuboradi.
        `daily_stats`: {pair: DailyPairStats} - engine.daily_stats
        `day`: YYYY-MM-DD (report kuni)
        `tz_label`: masalan "UTC" yoki "Asia/Tashkent"
        """
        if not daily_stats:
            text = (
                f"📊 <b>KUNLIK STATISTIKA</b>\n"
                f"📅 <b>{day}</b> ({tz_label})\n\n"
                f"ℹ️ Bugun hech qanday setup bo'lmadi."
            )
            self.send_message(text)
            return

        # Umumiy yig'indi
        tot_setups = sum(s.setups_created for s in daily_stats.values())
        tot_won = sum(s.won for s in daily_stats.values())
        tot_lost = sum(s.lost for s in daily_stats.values())
        tot_be = sum(s.be for s in daily_stats.values())
        tot_cancelled = sum(s.cancelled for s in daily_stats.values())
        tot_partial = sum(s.partial_tp1 for s in daily_stats.values())
        tot_usd = sum(s.total_usd for s in daily_stats.values())
        pnl_emo = "📈" if tot_usd >= 0 else "📉"
        pnl_sign = "+" if tot_usd >= 0 else ""

        # Har bir juftlik uchun blok
        pair_blocks = []
        # Setup soniga qarab tartiblash (eng aktivlari birinchi)
        sorted_pairs = sorted(daily_stats.items(),
                              key=lambda kv: -kv[1].setups_created)
        for pair, s in sorted_pairs:
            if s.setups_created == 0 and s.total_usd == 0:
                continue
            pnl_pair = "+" if s.total_usd >= 0 else ""
            pair_pnl_emo = "🟢" if s.total_usd > 0 else ("🔴" if s.total_usd < 0 else "⚪")
            block = (
                f"\n<b>{pair}</b> {pair_pnl_emo}\n"
                f"  🎯 Setups: <b>{s.setups_created}</b>"
            )
            if s.won or s.be or s.lost or s.cancelled:
                block += (
                    f"\n  🏆 Won: {s.won} | 🩵 BE: {s.be} | "
                    f"🔴 Lost: {s.lost} | ❌ Cancel: {s.cancelled}"
                )
            if s.partial_tp1:
                block += f"\n  🎯 TP1 partial: {s.partial_tp1}"
            block += f"\n  💰 P/L: <b>{pnl_pair}${s.total_usd:.2f}</b>"
            pair_blocks.append(block)

        text = (
            f"📊 <b>KUNLIK STATISTIKA</b>\n"
            f"📅 <b>{day}</b> ({tz_label})\n"
            + "".join(pair_blocks) +
            f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>JAMI:</b>\n"
            f"  🎯 Setups: <b>{tot_setups}</b> | "
            f"🎯 TP1: {tot_partial}\n"
            f"  🏆 Won: <b>{tot_won}</b> | "
            f"🩵 BE: <b>{tot_be}</b> | "
            f"🔴 Lost: <b>{tot_lost}</b> | "
            f"❌ Cancel: <b>{tot_cancelled}</b>\n"
            f"  {pnl_emo} <b>P/L: {pnl_sign}${tot_usd:.2f}</b>"
        )
        self.send_message(text)

    def send_error(self, err: str) -> None:
        # Xato xabari - HTML escape
        safe = err.replace("<", "&lt;").replace(">", "&gt;")[:1000]
        self.send_message(f"⚠️ <b>Bot xatosi</b>\n<pre>{safe}</pre>")
