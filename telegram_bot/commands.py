"""
Admin komandalar handleri. Foydalanuvchi bot bilan shaxsiy chat orqali
/stats, /pause, /setup 42 va boshqa komandalar yuboradi.

Xavfsizlik: faqat config.admin_chat_id dan kelgan komandalar bajariladi.
"""
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

from config import Config
from models import Status, Direction, EventType
from strategy import StrategyEngine

logger = logging.getLogger(__name__)


class CommandHandler:
    """Barcha /command'larni qayta ishlaydi va HTML matn qaytaradi."""

    def __init__(self, config: Config, engine: StrategyEngine, notifier,
                 state_mgr=None):
        self.config = config
        self.engine = engine
        self.notifier = notifier
        self.state_mgr = state_mgr

    # ==================================================================
    # ASOSIY ROUTER
    # ==================================================================

    def handle(self, chat_id: str, text: str) -> Optional[str]:
        """Xabar matnini qayta ishlab, javob HTML matni qaytaradi.
        None qaytarsa - hech qanday javob yuborilmasin."""
        # Faqat admin komandalar
        if not self.config.admin_chat_id:
            return None
        if str(chat_id) != str(self.config.admin_chat_id):
            logger.warning(f"Notanish chat_id dan komanda: {chat_id}")
            return None

        text = text.strip()
        if not text.startswith("/"):
            return None

        # /command@BotName formatidan bot nomini olib tashlash
        parts = text.split()
        cmd_raw = parts[0].lower()
        if "@" in cmd_raw:
            cmd_raw = cmd_raw.split("@")[0]
        args = parts[1:]

        handler_map = {
            "/start": self.cmd_start,
            "/help": self.cmd_help,
            "/status": self.cmd_status,
            "/stats": self.cmd_stats,
            "/pairs": self.cmd_pairs,
            "/config": self.cmd_config,
            "/setups": self.cmd_setups,
            "/setup": self.cmd_setup,
            "/pause": self.cmd_pause,
            "/resume": self.cmd_resume,
            "/mute": self.cmd_mute,
            "/unmute": self.cmd_unmute,
            "/muted": self.cmd_muted,
            "/risk": self.cmd_risk,
            "/report": self.cmd_report,
            "/version": self.cmd_version,
        }

        handler = handler_map.get(cmd_raw)
        if not handler:
            return (
                f"❓ Noma'lum komanda: <code>{cmd_raw}</code>\n\n"
                f"Barcha komandalar uchun: /help"
            )

        try:
            return handler(args)
        except Exception as e:
            logger.exception(f"Komanda xatosi ({cmd_raw}): {e}")
            return f"⚠️ Komanda bajarishda xato: <code>{str(e)[:200]}</code>"

    # ==================================================================
    # BASIC KOMANDALAR
    # ==================================================================

    def cmd_start(self, args) -> str:
        return (
            f"👋 <b>Salom, admin!</b>\n\n"
            f"Men — SERIYA Bot. Signallar kanalingizga yuboradi va\n"
            f"siz bu yerdan meni boshqarasiz.\n\n"
            f"📖 Barcha komandalar: /help\n"
            f"📊 Bugungi statistika: /stats\n"
            f"⚙️ Sozlamalar: /config"
        )

    def cmd_help(self, args) -> str:
        return (
            f"📖 <b>KOMANDALAR RO'YXATI</b>\n\n"
            f"<b>📊 Ma'lumot:</b>\n"
            f"/status — bot holati\n"
            f"/stats — bugungi statistika\n"
            f"/stats week — haftalik (jami)\n"
            f"/pairs — kuzatilayotgan juftliklar\n"
            f"/config — hozirgi sozlamalar\n"
            f"/version — bot versiyasi\n\n"
            f"<b>🎯 Setuplar:</b>\n"
            f"/setups — aktiv setuplar\n"
            f"/setups today — bugungi barcha\n"
            f"/setups closed — yopilgan (oxirgi 10)\n"
            f"/setup 42 — aniq setup tafsilotlari\n\n"
            f"<b>⚙️ Boshqaruv:</b>\n"
            f"/pause — yangi setuplarni to'xtatish\n"
            f"/resume — qayta yoqish\n"
            f"/mute BTC — juftlikni signalsiz qilish\n"
            f"/unmute BTC — qayta yoqish\n"
            f"/muted — mute qilingan juftliklar\n"
            f"/risk 5 — risk miqdorini o'zgartirish ($)\n"
            f"/report — kunlik reportni hozir yuborish\n\n"
            f"💡 <i>Har xabarda #Setup{{ID}} hashtag bor — Telegram'da bosib shu setupning barcha xabarlarini topasiz.</i>"
        )

    def cmd_status(self, args) -> str:
        eng = self.engine
        cfg = self.config

        # Setup hisoblari
        active_pending = sum(1 for s in eng.setups if s.status == Status.PENDING.value)
        active_filled = sum(1 for s in eng.setups if s.status == Status.FILLED.value)
        total_setups = eng.counters.total_setups

        # Muted holati
        muted_str = ", ".join(sorted(eng.muted_pairs)) if eng.muted_pairs else "yo'q"

        # Uptime (approx - state faylidan aniqlab bo'lmaydi, hozirgi jarayon bo'yicha)
        state_status = "🟢 <b>ISHLAYAPTI</b>" if not eng.paused else "⏸ <b>TO'XTATILGAN</b> (/resume)"

        be_txt = "YOQILGAN" if cfg.enable_be else "YOQ"
        return (
            f"📊 <b>BOT HOLATI</b>\n\n"
            f"Holat: {state_status}\n"
            f"Kuzatilayotgan: {len(cfg.pairs)} ta juftlik, {len(cfg.timeframes)} ta TF\n"
            f"Mute qilingan: {muted_str}\n\n"
            f"<b>Setuplar:</b>\n"
            f"⏳ Kutilyapti (pending): {active_pending}\n"
            f"🎬 Ochilgan (filled): {active_filled}\n"
            f"📋 Jami umumiy: {total_setups}\n\n"
            f"<b>Sozlamalar:</b>\n"
            f"💰 Risk: ${cfg.risk_usd:.2f}\n"
            f"🔵 BE: {be_txt}\n"
            f"⏱ Poll: {cfg.poll_interval}s"
        )

    def cmd_stats(self, args) -> str:
        eng = self.engine
        period = args[0].lower() if args else "today"

        if period in ("today", "bugun", ""):
            return self._stats_today()
        elif period in ("week", "hafta"):
            return self._stats_total()
        else:
            return f"❓ Noma'lum davr: <code>{period}</code>\nMavjud: today, week"

    def _stats_today(self) -> str:
        stats = self.engine.daily_stats
        if not stats:
            return "📊 <b>BUGUNGI STATISTIKA</b>\n\nHozircha hech qanday setup yo'q."

        tot_setups = sum(s.setups_created for s in stats.values())
        tot_won = sum(s.won for s in stats.values())
        tot_lost = sum(s.lost for s in stats.values())
        tot_be = sum(s.be for s in stats.values())
        tot_cancelled = sum(s.cancelled for s in stats.values())
        tot_usd = sum(s.total_usd for s in stats.values())
        pnl_emo = "📈" if tot_usd >= 0 else "📉"
        pnl_sign = "+" if tot_usd >= 0 else ""

        lines = [f"📊 <b>BUGUNGI STATISTIKA</b>\n"]

        sorted_pairs = sorted(stats.items(), key=lambda kv: -kv[1].setups_created)
        for pair, s in sorted_pairs:
            if s.setups_created == 0 and s.total_usd == 0:
                continue
            pnl_pair_sign = "+" if s.total_usd >= 0 else ""
            pair_emo = "🟢" if s.total_usd > 0 else ("🔴" if s.total_usd < 0 else "⚪")
            line = (
                f"\n<b>{pair}</b> {pair_emo}\n"
                f"  🎯 {s.setups_created} setup  |  "
                f"🏆 {s.won}  🔵 {s.be}  🔴 {s.lost}  🟡 {s.cancelled}\n"
                f"  💰 <b>{pnl_pair_sign}${s.total_usd:.2f}</b>"
            )
            lines.append(line)

        lines.append(
            f"\n\n━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>JAMI:</b> {tot_setups} setup\n"
            f"🏆 {tot_won}  🔵 {tot_be}  🔴 {tot_lost}  🟡 {tot_cancelled}\n"
            f"{pnl_emo} <b>{pnl_sign}${tot_usd:.2f}</b>"
        )
        return "".join(lines)

    def _stats_total(self) -> str:
        c = self.engine.counters
        total = c.won + c.lost + c.be
        win_rate = (c.won / total * 100) if total > 0 else 0.0
        profit_rate = ((c.won + c.be) / total * 100) if total > 0 else 0.0
        pnl_emo = "📈" if c.total_usd >= 0 else "📉"
        pnl_sign = "+" if c.total_usd >= 0 else ""

        return (
            f"📊 <b>UMUMIY STATISTIKA</b>\n"
            f"<i>(bot ishga tushganidan buyon)</i>\n\n"
            f"🎯 Jami setuplar: <b>{c.total_setups}</b>\n"
            f"🏆 G'oliblar (TP3): <b>{c.won}</b>\n"
            f"🟢 TP1 qisman: <b>{c.partial_tp1}</b>\n"
            f"🔵 Zararsiz (BE): <b>{c.be}</b>\n"
            f"🔴 Zarar (SL): <b>{c.lost}</b>\n"
            f"🟡 Bekor: <b>{c.cancelled}</b>\n\n"
            f"📈 G'olib foizi: <b>{win_rate:.1f}%</b>\n"
            f"💚 Foydali foizi: <b>{profit_rate:.1f}%</b>\n\n"
            f"{pnl_emo} <b>F/Z: {pnl_sign}${c.total_usd:.2f}</b>\n"
            f"🚀 Eng yaxshi: <b>+${c.best_usd:.2f}</b>\n"
            f"💥 Eng yomon: <b>${c.worst_usd:.2f}</b>"
        )

    def cmd_pairs(self, args) -> str:
        cfg = self.config
        eng = self.engine
        binance_pairs = [p for p in cfg.pairs if "/" in p]
        yahoo_pairs = [p for p in cfg.pairs if "/" not in p]

        lines = ["📊 <b>KUZATILAYOTGAN JUFTLIKLAR</b>\n"]

        if binance_pairs:
            lines.append("\n<b>Binance Futures</b> (kripto, 24/7):")
            for p in binance_pairs:
                muted = " 🔇" if p in eng.muted_pairs else ""
                lines.append(f"  • <code>{p}</code>{muted}")

        if yahoo_pairs:
            lines.append("\n<b>Yahoo Finance</b> (forex/stocks):")
            for p in yahoo_pairs:
                muted = " 🔇" if p in eng.muted_pairs else ""
                lines.append(f"  • <code>{p}</code>{muted}")

        lines.append(f"\n\n⏱ Vaqt oralig'i: <b>{', '.join(cfg.timeframes)}</b>")
        lines.append(f"📈 Min svechalar: <b>{cfg.min_candles}</b>")
        return "\n".join(lines)

    def cmd_config(self, args) -> str:
        cfg = self.config
        return (
            f"⚙️ <b>HOZIRGI SOZLAMALAR</b>\n\n"
            f"📊 Juftliklar: {len(cfg.pairs)}\n"
            f"⏱ Timeframes: <code>{', '.join(cfg.timeframes)}</code>\n"
            f"📈 Min svechalar: <b>{cfg.min_candles}</b>\n"
            f"💰 Risk: <b>${cfg.risk_usd:.2f}</b>\n"
            f"🔵 BE (break-even): "
            f"<b>{'ON' if cfg.enable_be else 'OFF'}</b>\n\n"
            f"<b>Fibonacci:</b>\n"
            f"  SL buffer: <b>+{cfg.sl_buffer_pct:.3f}%</b>\n"
            f"  TP1/TP2/TP3: "
            f"{cfg.fib_tp1}/{cfg.fib_tp2}/{cfg.fib_tp3}\n"
            f"  Partial: {cfg.tp1_pct:.0f}/{cfg.tp2_pct:.0f}/{cfg.tp3_pct:.0f}%\n\n"
            f"<b>Report:</b>\n"
            f"  Timezone: <code>{cfg.report_tz}</code>\n"
            f"  Soat: <b>{cfg.report_hour:02d}:00</b>\n\n"
            f"<i>O'zgartirish uchun: /opt/seriya-bot/.env</i>"
        )

    def cmd_version(self, args) -> str:
        return (
            f"🤖 <b>SERIYA Bot</b>\n\n"
            f"Versiya: <b>v1.2</b>\n"
            f"Fitchalar:\n"
            f"  ✅ Reversal setup logic\n"
            f"  ✅ Break-Even avto\n"
            f"  ✅ SL buffer +0.01%\n"
            f"  ✅ Setup hashtags\n"
            f"  ✅ To'liq o'zbek UI\n"
            f"  ✅ Multi-source (Binance + Yahoo)\n"
            f"  ✅ Kunlik report\n"
            f"  ✅ Admin komandalar (bu!)"
        )

    # ==================================================================
    # SETUP KOMANDALAR
    # ==================================================================

    def cmd_setups(self, args) -> str:
        filter_type = args[0].lower() if args else "active"
        eng = self.engine

        if filter_type == "active":
            setups = [s for s in eng.setups if s.status in
                     (Status.PENDING.value, Status.FILLED.value)]
            title = "AKTIV SETUPLAR"
        elif filter_type == "today":
            today_start = self._today_start_ms()
            setups = [s for s in eng.setups if s.created_at_ms >= today_start]
            title = "BUGUNGI SETUPLAR"
        elif filter_type == "closed":
            setups = [s for s in eng.setups if s.status in
                     (Status.WON.value, Status.LOST.value,
                      Status.BE.value, Status.CANCELLED.value)]
            setups = sorted(setups, key=lambda x: -(x.closed_at_ms or 0))[:10]
            title = "OXIRGI YOPILGAN 10 TA"
        else:
            return (
                f"❓ Noma'lum turi: <code>{filter_type}</code>\n"
                f"Mavjud: active, today, closed"
            )

        if not setups:
            return f"📋 <b>{title}</b>\n\nBo'sh."

        lines = [f"📋 <b>{title}</b> ({len(setups)} ta)\n"]
        for s in setups[:20]:  # max 20 ta ko'rsatamiz
            dir_emo = "📉" if s.direction == "SELL" else "📈"
            status_emo = self._status_emoji(s.status)
            pnl = ""
            if s.status in (Status.WON.value, Status.LOST.value,
                            Status.BE.value):
                pnl_sign = "+" if s.realized_usd >= 0 else ""
                pnl = f"  {pnl_sign}${s.realized_usd:.2f}"
            lines.append(
                f"\n{status_emo} <b>#{s.id}</b> {dir_emo} "
                f"<code>{s.pair}</code> {s.timeframe}{pnl}"
            )

        if len(setups) > 20:
            lines.append(f"\n\n<i>... va yana {len(setups) - 20} ta</i>")
        lines.append("\n\n💡 <i>Tafsilot uchun: /setup &lt;ID&gt;</i>")
        return "\n".join(lines)

    def cmd_setup(self, args) -> str:
        if not args:
            return "❓ Setup ID kiriting: <code>/setup 42</code>"
        try:
            setup_id = int(args[0])
        except ValueError:
            return f"❓ ID raqam bo'lishi kerak: <code>{args[0]}</code>"

        setup = next((s for s in self.engine.setups if s.id == setup_id), None)
        if not setup:
            return f"❌ Setup #{setup_id} topilmadi (eski bo'lishi mumkin)"

        return self._format_setup_details(setup)

    def _format_setup_details(self, s) -> str:
        dir_emo = "📉" if s.direction == "SELL" else "📈"
        dir_name = "SHORT" if s.direction == "SELL" else "LONG"
        status_emo = self._status_emoji(s.status)
        status_name = self._status_name(s.status)

        # Partial progress
        tp_progress = "⚪⚪⚪"
        if s.partial_level == 1:
            tp_progress = "🟢⚪⚪"
        elif s.partial_level == 2:
            tp_progress = "🟢🟢⚪"
        elif s.status == Status.WON.value:
            tp_progress = "🟢🟢🟢"

        be_txt = ""
        if s.be_moved:
            be_txt = "\n🔵 <i>SL break-even'da</i>"

        pnl_txt = ""
        if s.realized_usd != 0:
            pnl_sign = "+" if s.realized_usd >= 0 else ""
            pnl_txt = f"\n💰 Realizatsiya: <b>{pnl_sign}${s.realized_usd:.2f}</b>"

        duration_txt = ""
        if s.closed_at_ms:
            secs = (s.closed_at_ms - s.created_at_ms) // 1000
            duration_txt = f"\n⏱ Davomiyligi: {self._fmt_duration(secs)}"

        # Prices
        fmt = self._fmt_price

        return (
            f"{dir_emo} <b>Setup #{s.id} — {dir_name}</b>\n\n"
            f"📊 {s.pair} | {s.timeframe}\n"
            f"Holat: <b>{status_emo} {status_name}</b>\n"
            f"TP progress: {tp_progress}"
            f"{be_txt}\n\n"
            f"📍 Entry: <code>{fmt(s.entry)}</code>\n"
            f"🔴 SL: <code>{fmt(s.sl)}</code>\n"
            f"🟢 TP1/TP2/TP3: <code>{fmt(s.tp1)}</code> / "
            f"<code>{fmt(s.tp2)}</code> / <code>{fmt(s.tp3)}</code>\n"
            f"🟡 CZ: <code>{fmt(s.cz)}</code>\n\n"
            f"📈 Ketma-ketlik: {s.candle_count} sv + reversal\n"
            f"💰 Xavf: <b>${s.risk_usd:.2f}</b>"
            f"{pnl_txt}\n"
            f"⏰ Yaratilgan: {self._fmt_time(s.created_at_ms)}"
            f"{duration_txt}\n\n"
            f"#Setup{s.id} #{self._pair_tag(s.pair)}"
        )

    def _status_emoji(self, status: str) -> str:
        return {
            Status.PENDING.value: "⏳",
            Status.FILLED.value: "🎬",
            Status.WON.value: "🏆",
            Status.LOST.value: "🔴",
            Status.BE.value: "🔵",
            Status.CANCELLED.value: "🟡",
        }.get(status, "❓")

    def _status_name(self, status: str) -> str:
        return {
            Status.PENDING.value: "Kutilyapti",
            Status.FILLED.value: "Ochilgan",
            Status.WON.value: "G'ALABA",
            Status.LOST.value: "Zarar",
            Status.BE.value: "Zararsiz (BE)",
            Status.CANCELLED.value: "Bekor bo'lgan",
        }.get(status, status)

    # ==================================================================
    # BOSHQARUV KOMANDALAR
    # ==================================================================

    def cmd_pause(self, args) -> str:
        if self.engine.paused:
            return "⏸ Bot allaqachon <b>to'xtatilgan</b>. /resume bilan yoqing."
        self.engine.paused = True
        self._save_state()
        return (
            f"⏸ <b>Bot to'xtatildi</b>\n\n"
            f"• Yangi setuplar aniqlanmaydi\n"
            f"• Mavjud setuplar (kutilayotgan/ochilgan) davom etadi\n"
            f"• TP/SL/BE eventlari yuboriladi\n\n"
            f"Qaytadan yoqish: /resume"
        )

    def cmd_resume(self, args) -> str:
        if not self.engine.paused:
            return "▶️ Bot allaqachon <b>ishlayapti</b>."
        self.engine.paused = False
        self._save_state()
        return (
            f"▶️ <b>Bot qayta yoqildi</b>\n\n"
            f"Endi yangi setuplar avtomatik aniqlanadi va signal yuboriladi."
        )

    def cmd_mute(self, args) -> str:
        if not args:
            return (
                f"❓ Juftlik kiriting: <code>/mute BTC/USDT:USDT</code>\n"
                f"yoki <code>/mute XAUUSD</code>"
            )
        pair = args[0].upper()
        # Ba'zi variantlar
        matched = self._match_pair(pair)
        if not matched:
            return (
                f"❌ Juftlik topilmadi: <code>{pair}</code>\n"
                f"Kuzatilayotganlar: /pairs"
            )
        self.engine.muted_pairs.add(matched)
        self._save_state()
        return (
            f"🔇 <b>{matched}</b> mute qilindi\n\n"
            f"Bu juftlik hali ham kuzatiladi, ammo <b>Telegram signal yuborilmaydi</b>.\n"
            f"Qaytadan yoqish: <code>/unmute {matched}</code>"
        )

    def cmd_unmute(self, args) -> str:
        if not args:
            return f"❓ Juftlik kiriting: <code>/unmute BTC/USDT:USDT</code>"
        pair = args[0].upper()
        matched = self._match_pair(pair)
        if not matched or matched not in self.engine.muted_pairs:
            return f"❌ <code>{pair}</code> mute qilinmagan. /muted"
        self.engine.muted_pairs.discard(matched)
        self._save_state()
        return f"🔊 <b>{matched}</b> qayta yoqildi. Signal yana keladi."

    def cmd_muted(self, args) -> str:
        muted = self.engine.muted_pairs
        if not muted:
            return "🔊 Hech qanday juftlik mute qilinmagan."
        lines = ["🔇 <b>MUTE QILINGAN JUFTLIKLAR</b>\n"]
        for p in sorted(muted):
            lines.append(f"  • <code>{p}</code>")
        return "\n".join(lines)

    def cmd_risk(self, args) -> str:
        if not args:
            return (
                f"❓ Yangi risk miqdorini kiriting: <code>/risk 5</code>\n"
                f"Hozirgi: <b>${self.config.risk_usd:.2f}</b>"
            )
        try:
            new_risk = float(args[0].replace(",", "."))
            if new_risk <= 0:
                return "❌ Risk musbat bo'lishi kerak"
            if new_risk > 10000:
                return "❌ Juda katta qiymat"
        except ValueError:
            return f"❌ Raqam kiriting: <code>{args[0]}</code>"

        old = self.config.risk_usd
        self.config.risk_usd = new_risk
        return (
            f"💰 <b>Risk yangilandi</b>\n\n"
            f"Eski: ${old:.2f}\n"
            f"Yangi: <b>${new_risk:.2f}</b>\n\n"
            f"<i>⚠️ Diqqat: Bu o'zgarish faqat YANGI setuplar uchun. "
            f"Mavjud setuplar eski risk bilan davom etadi.</i>\n"
            f"<i>Bot restart bo'lsa .env dan qayta o'qiladi.</i>"
        )

    def cmd_report(self, args) -> str:
        stats = self.engine.daily_stats
        day = self.engine.daily_stats_day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            self.notifier.send_daily_report(stats, day, self.config.report_tz)
        except Exception as e:
            return f"⚠️ Report yuborishda xato: {e}"
        return "✅ Kunlik report kanalga yuborildi."

    # ==================================================================
    # HELPER'LAR
    # ==================================================================

    def _save_state(self):
        """State fayl'ni saqlash - runtime o'zgarishlarni saqlab qolish uchun."""
        if self.state_mgr:
            try:
                self.state_mgr.save(self.engine)
            except Exception as e:
                logger.warning(f"State saqlash xatosi: {e}")

    def _match_pair(self, query: str) -> Optional[str]:
        """Foydalanuvchi 'BTC' yozganda BTC/USDT:USDT ni topish."""
        q = query.upper()
        # Aniq mos
        for p in self.config.pairs:
            if p.upper() == q:
                return p
        # Qisman mos (masalan 'BTC' → 'BTC/USDT:USDT')
        matches = [p for p in self.config.pairs
                   if p.upper().startswith(q + "/") or
                   p.upper() == q or
                   p.upper().split("/")[0] == q]
        if len(matches) == 1:
            return matches[0]
        return None

    def _pair_tag(self, pair: str) -> str:
        base = pair.split(":")[0] if ":" in pair else pair
        return base.replace("/", "").replace("-", "").replace("=", "")

    def _fmt_price(self, price: float) -> str:
        if price is None:
            return "N/A"
        if price >= 1000:
            return f"{price:,.2f}"
        if price >= 10:
            return f"{price:,.3f}"
        if price >= 1:
            return f"{price:,.4f}"
        return f"{price:.5f}"

    def _fmt_time(self, ms: int) -> str:
        try:
            from zoneinfo import ZoneInfo
            dt = datetime.fromtimestamp(ms / 1000, tz=ZoneInfo("Asia/Tashkent"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M UTC")

    def _fmt_duration(self, secs: int) -> str:
        if secs < 60:
            return f"{secs} soniya"
        m = secs // 60
        if m < 60:
            return f"{m} daqiqa"
        h = m // 60
        m2 = m % 60
        if h < 24:
            return f"{h} soat {m2} daq"
        d = h // 24
        h2 = h % 24
        return f"{d} kun {h2} soat"

    def _today_start_ms(self) -> int:
        """Bugungi kunning 00:00 (Toshkent) ms timestamp."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Asia/Tashkent")
            now = datetime.now(tz)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return int(start.timestamp() * 1000)
        except Exception:
            return int(time.time() * 1000) - 86400 * 1000
