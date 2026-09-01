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
from keyboards import (
    MAIN_MENU, BUTTON_TO_COMMAND, settings_menu_kb,
    risk_preset_kb, min_preset_kb, be_toggle_kb, sl_buffer_preset_kb,
    tp_presets_kb, stats_period_kb, close_kb,
    stats_pairs_kb, stats_result_kb,
)

logger = logging.getLogger(__name__)


class CommandHandler:
    """Barcha /command'larni qayta ishlaydi va HTML matn qaytaradi."""

    def __init__(self, config: Config, engine: StrategyEngine, notifier,
                 state_mgr=None, exchange=None):
        self.config = config
        self.engine = engine
        self.notifier = notifier
        self.state_mgr = state_mgr
        self.exchange = exchange
        # Foydalanuvchidan input kutayotgan holat
        # {chat_id: "risk"|"sl_buffer"|"custom_date"|...}
        self._pending_input = {}
        # Statistika wizard holati
        # {chat_id: {"step": "pairs"|"period", "selected_pairs": set, "pairs_snapshot": list}}
        self._stats_wizard = {}

    # ==================================================================
    # ASOSIY ROUTER
    # ==================================================================

    def handle(self, chat_id: str, text: str):
        """Xabar matnini qayta ishlab, javob qaytaradi.

        Qaytish qiymati:
          None                          - hech qanday javob yuborilmasin
          str                           - oddiy HTML matn
          (str, dict)                   - matn + reply_markup (keyboard)
        """
        # Faqat admin
        if not self.config.admin_chat_id:
            return None
        if str(chat_id) != str(self.config.admin_chat_id):
            logger.warning(f"Notanish chat_id dan komanda: {chat_id}")
            return None

        text = text.strip()

        # Pending input state (masalan risk qiymatini kutayotgan bo'lsa)
        pending = getattr(self, "_pending_input", {}).get(str(chat_id))
        if pending and not text.startswith("/"):
            return self._handle_pending_input(chat_id, pending, text)

        # Menyu tugmalari - komanda ga tarjima qilish
        if text in BUTTON_TO_COMMAND:
            mapped = BUTTON_TO_COMMAND[text]
            if mapped == "__settings_menu__":
                return self._show_settings_menu()
            if mapped == "__stats_wizard__":
                return self._start_stats_wizard(chat_id)
            text = mapped

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
            "/menu": self.cmd_menu,
            "/help": self.cmd_help,
            "/status": self.cmd_status,
            "/stats": self.cmd_stats,
            "/pairs": self.cmd_pairs,
            "/tf": self.cmd_tf,
            "/config": self.cmd_config,
            "/setups": self.cmd_setups,
            "/setup": self.cmd_setup,
            "/pause": self.cmd_pause,
            "/resume": self.cmd_resume,
            "/mute": self.cmd_mute,
            "/unmute": self.cmd_unmute,
            "/muted": self.cmd_muted,
            "/risk": self.cmd_risk,
            "/set": self.cmd_set,
            "/report": self.cmd_report,
            "/version": self.cmd_version,
            "/debug": self.cmd_debug,
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

    def cmd_start(self, args):
        text = (
            f"👋 <b>Salom, admin!</b>\n\n"
            f"Men — SERIYA Bot. Signallar kanalingizga yuboradi va\n"
            f"siz bu yerdan meni boshqarasiz.\n\n"
            f"📱 <b>Menyu pastda joylashdi</b>\n"
            f"Har bir tugma tegishli amalni bajaradi.\n\n"
            f"💡 Yoki <code>/komanda</code> yozib to'g'ridan-to'g'ri chaqiring.\n\n"
            f"📖 Barcha komandalar: /help"
        )
        # Menyuni ham qo'shib yuborish
        return (text, MAIN_MENU)

    def cmd_menu(self, args):
        """Menyu klaviaturasini qayta ko'rsatish."""
        return ("📱 <b>Asosiy menyu</b>\n\nPastdagi tugmalardan tanlang.",
                MAIN_MENU)

    def _show_settings_menu(self):
        """Sozlamalar inline keyboard'ni ko'rsatish."""
        return (
            f"⚙️ <b>SOZLAMALAR</b>\n\n"
            f"Tegishli parametrni tanlang o'zgartirish uchun:",
            settings_menu_kb(self.config)
        )

    def cmd_help(self, args) -> str:
        return (
            f"📖 <b>KOMANDALAR RO'YXATI</b>\n\n"
            f"<b>📱 MENYU TUGMALAR:</b>\n"
            f"📊 <b>Statistika</b> — instrument+davr wizard\n"
            f"🎯 <b>Aktiv setups</b> — hozir kutilayotganlar\n"
            f"⚙️ <b>Sozlamalar</b> — inline sozlash\n"
            f"⏸ <b>Pause</b> / ▶️ <b>Resume</b> — to'xtatish/yoqish\n"
            f"📈 <b>Status</b> — bot holati\n\n"
            f"<b>💬 KOMANDALAR (yozib chaqirish):</b>\n"
            f"<code>/menu</code> — menyuni ko'rsatish\n"
            f"<code>/stats</code> — bugungi statistika\n"
            f"<code>/stats week</code>, <code>/stats month</code>\n"
            f"<code>/stats today pair BTC</code>\n"
            f"<code>/stats week tf 15m</code>\n"
            f"<code>/setups</code> — aktiv setuplar\n"
            f"<code>/setup 42</code> — bitta setup\n"
            f"<code>/pairs</code>, <code>/pairs add</code>, <code>/pairs remove</code>\n"
            f"<code>/tf</code>, <code>/tf add 30m</code>, <code>/tf remove 5m</code>\n"
            f"<code>/muted</code>, <code>/mute BTC</code>, <code>/unmute BTC</code>\n"
            f"<code>/set risk 5</code>, <code>/set min 4</code>, va h.k.\n"
            f"<code>/report</code> — kunlik reportni yuborish\n"
            f"<code>/config</code> — barcha sozlamalar\n"
            f"<code>/version</code>, <code>/status</code>\n\n"
            f"💡 <i>Har xabarda #Setup&lt;ID&gt; — bosib shu setupning barcha xabarlarini topasiz.</i>"
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
        """
        Filtrlangan statistika. Format:
          /stats                              - bugun, hammasi
          /stats today|yesterday|week|month|all
          /stats today pair BTC               - juftlik filtri (qisman mos)
          /stats week pair BTC,ETH            - bir necha juftlik
          /stats today tf 15m                 - timeframe filtri
          /stats week pair BTC tf 5m,15m      - kombinatsiya
          /stats 2026-08-31                   - aniq kun
        """
        try:
            period, pairs_f, tfs_f = self._parse_stats_args(args)
        except ValueError as e:
            return f"❓ {e}\n\nQo'llanma: /help"

        # Filtrlangan setuplar
        filtered = self._filter_setups(period, pairs_f, tfs_f)

        # Header
        title_parts = ["📊 <b>STATISTIKA</b>"]
        period_txt = self._period_label(period)
        title_parts.append(f"📅 Davr: <b>{period_txt}</b>")
        if pairs_f:
            title_parts.append(f"📊 Juftliklar: <b>{', '.join(pairs_f)}</b>")
        if tfs_f:
            title_parts.append(f"⏱ TF: <b>{', '.join(tfs_f)}</b>")

        if not filtered:
            return (
                "\n".join(title_parts) +
                "\n\nℹ️ Bu filtrlar bo'yicha hech qanday setup topilmadi.\n\n"
                f"<i>Diqqat: bot faqat oxirgi ~1000 setupni saqlaydi.</i>"
            )

        # Umumiy statistika
        stats = self._compute_stats(filtered)

        result_lines = list(title_parts)
        result_lines.append("")

        # Har juftlik uchun breakdown (agar ko'p bo'lsa)
        by_pair = self._group_by_pair(filtered)
        if len(by_pair) > 1:
            result_lines.append("<b>Juftlik bo'yicha:</b>")
            sorted_pairs = sorted(by_pair.items(), key=lambda kv: -len(kv[1]))
            for pair, pair_setups in sorted_pairs[:10]:  # max 10 juftlik
                ps = self._compute_stats(pair_setups)
                pnl_sign = "+" if ps["total_usd"] >= 0 else ""
                emo = "🟢" if ps["total_usd"] > 0 else ("🔴" if ps["total_usd"] < 0 else "⚪")
                result_lines.append(
                    f"\n<b>{pair}</b> {emo}\n"
                    f"  🎯 {ps['total']} setup  |  "
                    f"🏆 {ps['won']}  🔵 {ps['be']}  🔴 {ps['lost']}  🟡 {ps['cancelled']}\n"
                    f"  💰 <b>{pnl_sign}${ps['total_usd']:.2f}</b>"
                )

        # Timeframe breakdown (agar ko'p bo'lsa)
        by_tf = self._group_by_tf(filtered)
        if len(by_tf) > 1:
            result_lines.append("\n<b>Timeframe bo'yicha:</b>")
            for tf, tf_setups in sorted(by_tf.items()):
                ts = self._compute_stats(tf_setups)
                pnl_sign = "+" if ts["total_usd"] >= 0 else ""
                emo = "🟢" if ts["total_usd"] > 0 else ("🔴" if ts["total_usd"] < 0 else "⚪")
                result_lines.append(
                    f"  <b>{tf}</b> {emo}: {ts['total']} setup, "
                    f"🏆{ts['won']} 🔵{ts['be']} 🔴{ts['lost']} 🟡{ts['cancelled']}, "
                    f"<b>{pnl_sign}${ts['total_usd']:.2f}</b>"
                )

        # Jami
        pnl_sign = "+" if stats["total_usd"] >= 0 else ""
        pnl_emo = "📈" if stats["total_usd"] >= 0 else "📉"
        win_rate = (stats["won"] / stats["closed"] * 100) if stats["closed"] > 0 else 0.0
        profit_rate = ((stats["won"] + stats["be"]) / stats["closed"] * 100) if stats["closed"] > 0 else 0.0

        result_lines.append(
            f"\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>JAMI:</b> {stats['total']} setup"
        )
        if stats["closed"] > 0:
            result_lines.append(
                f"🏆 {stats['won']}  🔵 {stats['be']}  "
                f"🔴 {stats['lost']}  🟡 {stats['cancelled']}\n"
                f"📈 G'olib foizi: <b>{win_rate:.1f}%</b>  |  "
                f"💚 Foydali: <b>{profit_rate:.1f}%</b>"
            )
        if stats["active"] > 0:
            result_lines.append(f"⏳ Aktiv: {stats['active']}")
        result_lines.append(
            f"{pnl_emo} <b>F/Z: {pnl_sign}${stats['total_usd']:.2f}</b>"
        )
        if stats["best_usd"] != 0:
            result_lines.append(
                f"🚀 Eng yaxshi: <b>+${stats['best_usd']:.2f}</b>  |  "
                f"💥 Eng yomon: <b>${stats['worst_usd']:.2f}</b>"
            )

        return "\n".join(result_lines)

    # ==================================================================
    # STATS HELPER'LAR
    # ==================================================================

    def _parse_stats_args(self, args):
        """Args → (period, pairs_list, tfs_list). Xato bo'lsa ValueError."""
        period = None
        pairs = None
        tfs = None
        i = 0
        while i < len(args):
            arg = args[i].lower()
            # Davr kalit so'zlari
            if arg in ("today", "bugun"):
                period = "today"
            elif arg in ("yesterday", "kecha"):
                period = "yesterday"
            elif arg in ("week", "hafta", "7d"):
                period = "week"
            elif arg in ("month", "oy", "30d"):
                period = "month"
            elif arg == "all":
                period = "all"
            elif arg == "pair" and i + 1 < len(args):
                pairs = [p.strip().upper() for p in args[i + 1].split(",") if p.strip()]
                i += 1
            elif arg == "tf" and i + 1 < len(args):
                tfs = [t.strip().lower() for t in args[i + 1].split(",") if t.strip()]
                i += 1
            elif len(arg) == 10 and arg[4] == "-" and arg[7] == "-":
                # YYYY-MM-DD format
                period = arg
            else:
                raise ValueError(f"Tushunilmadi: <code>{arg}</code>")
            i += 1
        return period or "today", pairs, tfs

    def _period_label(self, period: str) -> str:
        labels = {
            "today": "Bugun",
            "yesterday": "Kecha",
            "week": "Oxirgi 7 kun",
            "month": "Oxirgi 30 kun",
            "all": "Barcha vaqt",
        }
        return labels.get(period, period)

    def _period_range_ms(self, period):
        """Davr uchun (start_ms, end_ms) qaytaradi.
        period tuple bo'lsa - to'g'ridan-to'g'ri qaytaradi."""
        # Custom range (tuple bilan kelgan)
        if isinstance(period, tuple):
            return period
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Asia/Tashkent")
        except Exception:
            from datetime import timezone
            tz = timezone.utc

        now = datetime.now(tz)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if period == "today":
            start = today_start
            end_ms = int(time.time() * 1000) + 1000
            return int(start.timestamp() * 1000), end_ms
        if period == "yesterday":
            from datetime import timedelta
            yesterday = today_start - timedelta(days=1)
            return int(yesterday.timestamp() * 1000), int(today_start.timestamp() * 1000)
        if period == "week":
            from datetime import timedelta
            start = today_start - timedelta(days=7)
            return int(start.timestamp() * 1000), int(time.time() * 1000) + 1000
        if period == "month":
            from datetime import timedelta
            start = today_start - timedelta(days=30)
            return int(start.timestamp() * 1000), int(time.time() * 1000) + 1000
        if period == "all":
            return 0, int(time.time() * 1000) + 1000
        # YYYY-MM-DD format
        try:
            from datetime import timedelta
            parts = period.split("-")
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            start = datetime(y, m, d, tzinfo=tz)
            end = start + timedelta(days=1)
            return int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        except Exception:
            return 0, int(time.time() * 1000) + 1000

    def _filter_setups(self, period, pairs_filter, tfs_filter):
        """engine.setups ni filtrlaydi.
        pairs_filter: to'liq nom (exact match) yoki qisman (BTC → BTC/USDT:USDT).
        """
        start_ms, end_ms = self._period_range_ms(period)
        result = []
        skipped_time = 0
        skipped_pair = 0
        skipped_tf = 0
        for s in self.engine.setups:
            ts = s.closed_at_ms or s.created_at_ms
            if ts < start_ms or ts >= end_ms:
                skipped_time += 1
                continue
            if pairs_filter:
                if s.pair in pairs_filter:
                    pass
                elif not any(self._pair_matches(s.pair, pf) for pf in pairs_filter):
                    skipped_pair += 1
                    continue
            if tfs_filter and s.timeframe not in tfs_filter:
                skipped_tf += 1
                continue
            result.append(s)
        # DEBUG log - filter natijalarini ko'rish uchun
        logger.info(
            f"FILTER DEBUG: period={period}, pairs_filter={pairs_filter}, "
            f"tfs_filter={tfs_filter}, "
            f"total_setups={len(self.engine.setups)}, kept={len(result)}, "
            f"skipped_time={skipped_time}, skipped_pair={skipped_pair}, "
            f"skipped_tf={skipped_tf}"
        )
        # Pair nomlarini ham log qilamiz - agar mos kelmasa ko'ramiz
        if pairs_filter and len(result) == 0:
            all_pairs = sorted(set(s.pair for s in self.engine.setups))
            logger.warning(
                f"FILTER: hech nima topilmadi. Filter={pairs_filter}, "
                f"engine.setups.pair unikal qiymatlar: {all_pairs}"
            )
        return result

    def _pair_matches(self, setup_pair: str, filter_pair: str) -> bool:
        """Setup pair filter'ga mos keladimi? BTC → BTC/USDT:USDT ham mos."""
        sp = setup_pair.upper()
        fp = filter_pair.upper()
        if sp == fp:
            return True
        # Base coin match: BTC/USDT:USDT ning 'BTC' qismi 'BTC' ga mos
        base = sp.split("/")[0]
        if base == fp:
            return True
        # Aniq mos: XAUUSD == XAUUSD
        if sp == fp:
            return True
        return False

    def _compute_stats(self, setups) -> dict:
        """Setuplar ro'yxatidan aggregate hisoblaydi."""
        r = {
            "total": len(setups),
            "won": 0, "lost": 0, "be": 0, "cancelled": 0, "partial_tp1": 0,
            "active": 0, "closed": 0,
            "total_usd": 0.0, "best_usd": 0.0, "worst_usd": 0.0,
        }
        for s in setups:
            if s.status == Status.WON.value:
                r["won"] += 1
                r["closed"] += 1
            elif s.status == Status.LOST.value:
                r["lost"] += 1
                r["closed"] += 1
            elif s.status == Status.BE.value:
                r["be"] += 1
                r["closed"] += 1
            elif s.status == Status.CANCELLED.value:
                r["cancelled"] += 1
                r["closed"] += 1
            else:
                r["active"] += 1
            if s.partial_level >= 1:
                r["partial_tp1"] += 1
            r["total_usd"] += s.realized_usd
            if s.realized_usd > r["best_usd"]:
                r["best_usd"] = s.realized_usd
            if s.realized_usd < r["worst_usd"]:
                r["worst_usd"] = s.realized_usd
        return r

    def _group_by_pair(self, setups) -> dict:
        d = {}
        for s in setups:
            d.setdefault(s.pair, []).append(s)
        return d

    def _group_by_tf(self, setups) -> dict:
        d = {}
        for s in setups:
            d.setdefault(s.timeframe, []).append(s)
        return d

    def cmd_pairs(self, args) -> str:
        """
        /pairs                          - ro'yxat
        /pairs add BTC/USDT:USDT        - qo'shish
        /pairs remove BTC/USDT:USDT     - o'chirish
        /pairs add XAUUSD               - Yahoo tickeri
        """
        if not args:
            return self._pairs_list()

        action = args[0].lower()
        if action in ("add", "qoshish", "+"):
            if len(args) < 2:
                return "❓ Juftlik kiriting: <code>/pairs add BTC/USDT:USDT</code>"
            return self._pairs_add(args[1])
        elif action in ("remove", "rm", "delete", "-", "olib"):
            if len(args) < 2:
                return "❓ Juftlik kiriting: <code>/pairs remove BTC/USDT:USDT</code>"
            return self._pairs_remove(args[1])
        else:
            return (
                f"❓ Noma'lum amal: <code>{action}</code>\n"
                f"Mavjud: <code>add</code>, <code>remove</code>"
            )

    def _pairs_list(self) -> str:
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

        lines.append(f"\n\n⏱ Vaqt oralig'i: <b>{', '.join(self.config.timeframes)}</b>")
        lines.append(f"📈 Min svechalar: <b>{self.config.min_candles}</b>")
        lines.append(f"\n💡 <i>Boshqarish:</i>")
        lines.append(f"  <code>/pairs add PAXG/USDT:USDT</code>")
        lines.append(f"  <code>/pairs remove NVDA</code>")
        return "\n".join(lines)

    def _pairs_add(self, pair: str) -> str:
        if pair in self.config.pairs:
            return f"ℹ️ <code>{pair}</code> allaqachon kuzatilyapti"
        # Exchange orqali tekshirish
        exchange = getattr(self, "exchange", None)
        if exchange:
            try:
                if not exchange.check_pair(pair):
                    return (
                        f"❌ <code>{pair}</code> topilmadi\n\n"
                        f"Kripto format: <code>BTC/USDT:USDT</code>\n"
                        f"Stocks/Forex: <code>NVDA</code>, <code>XAUUSD</code>"
                    )
            except Exception as e:
                logger.warning(f"pair check xatosi: {e}")
        self.config.pairs.append(pair)
        self._save_state()
        return (
            f"✅ <code>{pair}</code> qo'shildi\n\n"
            f"Bot keyingi iteratsiyada ({self.config.poll_interval}s) uni "
            f"kuzata boshlaydi. Warmup uchun bir necha daqiqa kutilishi mumkin."
        )

    def _pairs_remove(self, pair: str) -> str:
        matched = self._match_pair(pair)
        if not matched or matched not in self.config.pairs:
            return f"❌ <code>{pair}</code> ro'yxatda yo'q. /pairs"
        # Aktiv setuplar bor bo'lsa - bekor qilish
        cancelled = 0
        now_ms = int(time.time() * 1000)
        for s in self.engine.setups:
            if s.pair == matched and s.status in (
                Status.PENDING.value, Status.FILLED.value
            ):
                s.status = Status.CANCELLED.value
                s.closed_at_ms = now_ms
                self.engine.counters.cancelled += 1
                cancelled += 1
        self.config.pairs.remove(matched)
        self.engine.muted_pairs.discard(matched)
        self._save_state()
        msg = f"✅ <code>{matched}</code> olib tashlandi"
        if cancelled:
            msg += f"\n\n⚠️ {cancelled} ta aktiv setup bekor qilindi"
        return msg

    def cmd_tf(self, args) -> str:
        """
        /tf                 - ro'yxat
        /tf add 30m         - qo'shish
        /tf remove 5m       - o'chirish
        """
        if not args:
            return self._tf_list()

        action = args[0].lower()
        if action in ("add", "qoshish", "+"):
            if len(args) < 2:
                return "❓ Timeframe kiriting: <code>/tf add 30m</code>"
            return self._tf_add(args[1].lower())
        elif action in ("remove", "rm", "-", "olib"):
            if len(args) < 2:
                return "❓ Timeframe kiriting: <code>/tf remove 5m</code>"
            return self._tf_remove(args[1].lower())
        else:
            return f"❓ Mavjud: add, remove. Yoki <code>/tf</code> - ro'yxat"

    def _tf_list(self) -> str:
        return (
            f"⏱ <b>Timeframes</b>\n\n"
            f"Kuzatilayotgan: <b>{', '.join(self.config.timeframes)}</b>\n\n"
            f"Mavjud: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d\n\n"
            f"💡 Boshqarish:\n"
            f"  <code>/tf add 30m</code>\n"
            f"  <code>/tf remove 5m</code>"
        )

    def _tf_add(self, tf: str) -> str:
        valid_tfs = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}
        if tf not in valid_tfs:
            return f"❌ Noto'g'ri TF: <code>{tf}</code>. Mavjud: {', '.join(sorted(valid_tfs))}"
        if tf in self.config.timeframes:
            return f"ℹ️ <code>{tf}</code> allaqachon bor"
        self.config.timeframes.append(tf)
        self._save_state()
        return (
            f"✅ TF <code>{tf}</code> qo'shildi\n\n"
            f"Hozirgi: <b>{', '.join(self.config.timeframes)}</b>"
        )

    def _tf_remove(self, tf: str) -> str:
        if tf not in self.config.timeframes:
            return f"❌ <code>{tf}</code> ro'yxatda yo'q"
        if len(self.config.timeframes) <= 1:
            return "❌ Kamida bitta TF qolishi kerak"
        self.config.timeframes.remove(tf)
        self._save_state()
        return f"✅ TF <code>{tf}</code> olib tashlandi. Qolgan: <b>{', '.join(self.config.timeframes)}</b>"

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

    def cmd_debug(self, args) -> str:
        """Debug ma'lumot - filter muammosini topish uchun."""
        eng = self.engine
        cfg = self.config

        pair_counts = {}
        for s in eng.setups:
            pair_counts[s.pair] = pair_counts.get(s.pair, 0) + 1

        config_pairs = set(cfg.pairs)
        setup_pairs = set(pair_counts.keys())
        only_in_config = config_pairs - setup_pairs
        only_in_setups = setup_pairs - config_pairs

        wizard_state = "aktiv" if self._stats_wizard else "yoq"
        pending_state = (list(self._pending_input.values())
                         if self._pending_input else "yoq")

        lines = [
            f"🐛 <b>DEBUG INFO</b>\n",
            f"<b>Setuplar:</b> {len(eng.setups)} ta jami",
            f"<b>Wizard state:</b> {wizard_state}",
            f"<b>Pending input:</b> {pending_state}",
            f"",
            f"<b>Config pairs ({len(config_pairs)}):</b>",
        ]
        for p in sorted(config_pairs):
            lines.append(f"  • <code>{p}</code>")

        lines.append(f"\n<b>Setup pair'lari (unikal):</b>")
        for p in sorted(setup_pairs):
            cnt = pair_counts[p]
            problem_note = " ❌ config da YOQ!" if p not in config_pairs else " ✅"
            lines.append(f"  • <code>{p}</code> ({cnt} setup){problem_note}")

        if only_in_config:
            lines.append(f"\n⚠️ Config'da bor, setup'da yo'q:")
            for p in sorted(only_in_config):
                lines.append(f"  • <code>{p}</code>")

        if only_in_setups:
            lines.append(f"\n⚠️ Setup'da bor, config'da yo'q (BUG SABABI):")
            for p in sorted(only_in_setups):
                lines.append(f"  • <code>{p}</code>")

        lines.append(
            f"\n💡 Setup pair'lari config bilan mos kelmasa filter ishlamaydi."
        )
        return "\n".join(lines)

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

    def cmd_set(self, args) -> str:
        """
        Sozlamalarni o'zgartirish:
          /set risk 5           - risk (dollar)
          /set min 4            - minimum svechalar
          /set be on|off        - break-even yoqish/o'chirish
          /set sl_buffer 0.02   - SL buffer (foizda)
          /set tp1 40           - TP1 foizi
          /set tp2 30           - TP2 foizi (jami 100 bo'lsin)
          /set fib_sl 0.1       - Fibonacci SL darajasi
          /set fib_tp1 1.618    - Fibonacci TP1
        """
        if not args:
            return (
                f"⚙️ <b>SOZLAMALAR</b>\n\n"
                f"Foydalanish: <code>/set &lt;parametr&gt; &lt;qiymat&gt;</code>\n\n"
                f"<b>Mavjud parametrlar:</b>\n"
                f"  <code>/set risk 5.0</code> — xavf ($)\n"
                f"  <code>/set min 4</code> — min svechalar\n"
                f"  <code>/set be on</code> — BE yoqish\n"
                f"  <code>/set be off</code> — BE o'chirish\n"
                f"  <code>/set sl_buffer 0.02</code> — SL buffer %\n"
                f"  <code>/set tp1 50</code> — TP1 partial %\n"
                f"  <code>/set tp2 25</code> — TP2 partial %\n"
                f"  <code>/set fib_sl 0.0</code> — Fib SL\n"
                f"  <code>/set fib_tp1 1.618</code> — Fib TP1\n"
                f"  <code>/set fib_tp2 2.618</code> — Fib TP2\n"
                f"  <code>/set fib_tp3 3.618</code> — Fib TP3\n\n"
                f"Barcha sozlamalar: /config"
            )
        param = args[0].lower()
        if len(args) < 2:
            return f"❓ Qiymat kiriting: <code>/set {param} &lt;qiymat&gt;</code>"
        value = args[1]

        try:
            if param == "risk":
                v = float(value.replace(",", "."))
                if v <= 0 or v > 100000:
                    return "❌ Risk 0 dan katta, 100000 dan kichik bo'lsin"
                old = self.config.risk_usd
                self.config.risk_usd = v
                self._save_state()
                return f"💰 Risk: ${old:.2f} → <b>${v:.2f}</b> ✅"

            if param == "min":
                v = int(value)
                if v < 2 or v > 20:
                    return "❌ Min svechalar 2-20 oralig'ida bo'lsin"
                old = self.config.min_candles
                self.config.min_candles = v
                self._save_state()
                return f"📈 Min svechalar: {old} → <b>{v}</b> ✅"

            if param == "be":
                v = value.lower()
                if v in ("on", "yes", "true", "1", "yoq"):
                    self.config.enable_be = True
                    self._save_state()
                    return "🔵 Break-Even: <b>YOQILGAN</b> ✅"
                elif v in ("off", "no", "false", "0", "yoqmi"):
                    self.config.enable_be = False
                    self._save_state()
                    return "🔵 Break-Even: <b>O'CHIRILGAN</b>"
                else:
                    return "❌ Qiymat: on yoki off"

            if param in ("sl_buffer", "slbuffer", "buffer"):
                v = float(value.replace(",", "."))
                if v < 0 or v > 5:
                    return "❌ SL buffer 0-5% oralig'ida"
                old = self.config.sl_buffer_pct
                self.config.sl_buffer_pct = v
                self._save_state()
                return f"🔴 SL buffer: {old:.3f}% → <b>{v:.3f}%</b> ✅"

            if param in ("tp1", "tp1_pct"):
                v = float(value.replace(",", "."))
                new_sum = v + self.config.tp2_pct + self.config.tp3_pct
                if abs(new_sum - 100.0) > 0.5:
                    return (
                        f"❌ Jami 100% bo'lsin. Hozir: "
                        f"TP1={v} + TP2={self.config.tp2_pct} + "
                        f"TP3={self.config.tp3_pct} = {new_sum}"
                    )
                self.config.tp1_pct = v
                self._save_state()
                return f"🟢 TP1 %: <b>{v:.1f}%</b> ✅"

            if param in ("tp2", "tp2_pct"):
                v = float(value.replace(",", "."))
                new_sum = self.config.tp1_pct + v + self.config.tp3_pct
                if abs(new_sum - 100.0) > 0.5:
                    return f"❌ Jami 100% bo'lsin, hozir: {new_sum}"
                self.config.tp2_pct = v
                self._save_state()
                return f"🟢 TP2 %: <b>{v:.1f}%</b> ✅"

            if param in ("tp3", "tp3_pct"):
                v = float(value.replace(",", "."))
                new_sum = self.config.tp1_pct + self.config.tp2_pct + v
                if abs(new_sum - 100.0) > 0.5:
                    return f"❌ Jami 100% bo'lsin, hozir: {new_sum}"
                self.config.tp3_pct = v
                self._save_state()
                return f"🟢 TP3 %: <b>{v:.1f}%</b> ✅"

            if param == "fib_sl":
                v = float(value.replace(",", "."))
                if v < 0 or v >= 1:
                    return "❌ Fib SL 0-1 oralig'ida"
                self.config.fib_sl = v
                self._save_state()
                return f"📐 Fib SL: <b>{v}</b> ✅ (yangi setuplarga qo'llaniladi)"

            if param == "fib_tp1":
                v = float(value.replace(",", "."))
                if v <= 1:
                    return "❌ Fib TP1 1 dan katta bo'lsin"
                self.config.fib_tp1 = v
                self._save_state()
                return f"📐 Fib TP1: <b>{v}</b> ✅"

            if param == "fib_tp2":
                v = float(value.replace(",", "."))
                if v <= self.config.fib_tp1:
                    return f"❌ Fib TP2 (>{self.config.fib_tp1}) bo'lsin"
                self.config.fib_tp2 = v
                self._save_state()
                return f"📐 Fib TP2: <b>{v}</b> ✅"

            if param == "fib_tp3":
                v = float(value.replace(",", "."))
                if v <= self.config.fib_tp2:
                    return f"❌ Fib TP3 (>{self.config.fib_tp2}) bo'lsin"
                self.config.fib_tp3 = v
                self._save_state()
                return f"📐 Fib TP3: <b>{v}</b> ✅"

            return (
                f"❓ Noma'lum parametr: <code>{param}</code>\n"
                f"Barcha parametrlar: /set"
            )
        except ValueError as e:
            return f"❌ Noto'g'ri qiymat: <code>{value}</code>"

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

    # ==================================================================
    # CALLBACK QUERY HANDLER (inline button tap)
    # ==================================================================

    def handle_callback(self, chat_id: str, data: str):
        """Inline tugma bosilganda. Qaytadi (text, reply_markup) yoki str."""
        if not self.config.admin_chat_id:
            return None
        if str(chat_id) != str(self.config.admin_chat_id):
            return None

        try:
            # STATS WIZARD (yangi delimiter: |)
            if data.startswith("sw|"):
                return self._handle_stats_wizard(chat_id, data[3:])

            # Format: "action:arg1:arg2..."
            if ":" in data:
                action, rest = data.split(":", 1)
                parts_rest = rest.split(":")
            else:
                action = data
                parts_rest = []

            if action == "close":
                return ("✅ Yopildi.", None)

            if action == "settings":
                sub = parts_rest[0] if parts_rest else "menu"
                return self._cb_settings(sub)

            if action == "set":
                # set:param:value
                if len(parts_rest) < 2:
                    return "❌ Noto'g'ri format"
                return self._cb_set(parts_rest[0], ":".join(parts_rest[1:]))

            if action == "input":
                if not parts_rest:
                    return None
                return self._cb_await_input(chat_id, parts_rest[0])

            if action == "stats":
                # stats:today (old, bir bosgichli)
                if not parts_rest:
                    return None
                return (self.cmd_stats([parts_rest[0]]), None)

            return f"❓ Noma'lum callback: {data}"
        except Exception as e:
            logger.exception(f"Callback xatosi: {e}")
            return f"⚠️ Xato: {str(e)[:100]}"

    # ==================================================================
    # STATISTIKA WIZARD (instrument tanlash → davr → natija)
    # ==================================================================

    def _start_stats_wizard(self, chat_id):
        """Wizard boshlash - instrument tanlash bosqichiga o'tish."""
        # Wizard state
        self._stats_wizard[str(chat_id)] = {
            "step": "pairs",
            "selected_pairs": set(),
            # Snapshot juftliklar tartibi (index-based callback uchun)
            "pairs_snapshot": list(self.config.pairs),
        }
        return self._render_pairs_step(chat_id)

    def _render_pairs_step(self, chat_id):
        w = self._stats_wizard.get(str(chat_id))
        if not w:
            return self._start_stats_wizard(chat_id)
        selected = w["selected_pairs"]
        pairs = w["pairs_snapshot"]
        n = len(selected)
        # Tanlangan juftliklar ro'yxati
        sel_txt = ""
        if n > 0:
            sel_list = [p for p in pairs if p in selected]
            sel_txt = "\n<i>" + ", ".join(sel_list) + "</i>"
        text = (
            f"📊 <b>STATISTIKA</b>\n"
            f"<b>1️⃣ / 2️⃣</b>  Instrumentlarni tanlang\n\n"
            f"Tanlangan: <b>{n} ta</b>{sel_txt}\n\n"
            f"💡 <i>Tugmalarni bosib tanlang. \"HAMMASI\" — barcha juftliklar.</i>"
        )
        return (text, stats_pairs_kb(pairs, selected))

    def _render_period_step(self, chat_id):
        w = self._stats_wizard.get(str(chat_id))
        if not w:
            return self._start_stats_wizard(chat_id)
        selected = w["selected_pairs"]
        sel_txt = ", ".join(sorted(selected)) if selected else "hech qaysi"
        text = (
            f"📊 <b>STATISTIKA</b>\n"
            f"<b>2️⃣ / 2️⃣</b>  Davrni tanlang\n\n"
            f"Tanlangan instrumentlar ({len(selected)}):\n"
            f"<code>{sel_txt}</code>\n\n"
            f"Preset davr yoki maxsus sana:"
        )
        return (text, stats_period_kb())

    def _handle_stats_wizard(self, chat_id: str, action_path: str):
        """Wizard callback'lari: pair|N, all, next, back, cancel,
        period|today|week|..., period|custom, restart."""
        w = self._stats_wizard.get(str(chat_id))
        if not w:
            # Wizard eskirgan yoki qaytadan ochilyapti
            return self._start_stats_wizard(chat_id)

        # cancel/restart
        if action_path == "cancel":
            self._stats_wizard.pop(str(chat_id), None)
            self._pending_input.pop(str(chat_id), None)
            return ("❌ Wizard bekor qilindi.", None)

        if action_path == "restart":
            return self._start_stats_wizard(chat_id)

        # PAIRS STEP
        if w["step"] == "pairs":
            if action_path == "all":
                pairs = w["pairs_snapshot"]
                all_now = len(w["selected_pairs"]) == len(pairs)
                if all_now:
                    w["selected_pairs"].clear()
                else:
                    w["selected_pairs"] = set(pairs)
                return self._render_pairs_step(chat_id)

            if action_path.startswith("pair|"):
                try:
                    idx = int(action_path.split("|", 1)[1])
                    if 0 <= idx < len(w["pairs_snapshot"]):
                        p = w["pairs_snapshot"][idx]
                        if p in w["selected_pairs"]:
                            w["selected_pairs"].discard(p)
                        else:
                            w["selected_pairs"].add(p)
                except (ValueError, IndexError):
                    pass
                return self._render_pairs_step(chat_id)

            if action_path == "next":
                if not w["selected_pairs"]:
                    return (
                        f"⚠️ <b>Kamida bitta instrumentni tanlang</b>",
                        stats_pairs_kb(w["pairs_snapshot"], w["selected_pairs"])
                    )
                w["step"] = "period"
                return self._render_period_step(chat_id)

        # PERIOD STEP
        if w["step"] == "period":
            if action_path == "back":
                w["step"] = "pairs"
                return self._render_pairs_step(chat_id)

            if action_path.startswith("period|"):
                period_val = action_path.split("|", 1)[1]
                if period_val == "custom":
                    # Custom sana uchun matn kutish
                    self._pending_input[str(chat_id)] = "custom_date"
                    return (
                        f"📆 <b>Sana oralig'ini yozing</b>\n\n"
                        f"Format: <code>YYYY-MM-DD YYYY-MM-DD</code>\n"
                        f"Masalan: <code>2026-08-01 2026-08-31</code>\n\n"
                        f"Yoki bitta kun uchun:\n"
                        f"<code>2026-08-15</code>\n\n"
                        f"<i>Bekor qilish: /menu</i>",
                        None
                    )
                # Preset davr - stats chiqarish
                return self._show_wizard_result(chat_id, period_val)

        return self._render_pairs_step(chat_id)

    def _show_wizard_result(self, chat_id: str, period):
        """Yakuniy statistika. period: str yoki (start_ms, end_ms) tuple."""
        w = self._stats_wizard.get(str(chat_id))
        if not w:
            return ("❌ Wizard state topilmadi", None)

        pairs = list(w["selected_pairs"])
        filtered = self._filter_setups(period, pairs, None)

        # Header
        period_txt = self._period_label(period) if isinstance(period, str) else self._format_custom_period(period)
        pairs_txt = ", ".join(sorted(pairs))

        title = (
            f"📊 <b>STATISTIKA — NATIJA</b>\n"
            f"📅 <b>{period_txt}</b>\n"
            f"📊 Instrumentlar ({len(pairs)}): <code>{pairs_txt}</code>\n"
        )

        if not filtered:
            text = (
                title +
                f"\nℹ️ Bu filtrlar bo'yicha setup topilmadi.\n\n"
                f"<i>Diqqat: bot faqat oxirgi ~1000 setupni saqlaydi.</i>"
            )
            return (text, stats_result_kb())

        # Umumiy
        stats = self._compute_stats(filtered)
        result_lines = [title, ""]

        # Har juftlik uchun (agar > 1 juftlik)
        by_pair = self._group_by_pair(filtered)
        if len(by_pair) > 1:
            result_lines.append("<b>Juftlik bo'yicha:</b>")
            sorted_pairs = sorted(by_pair.items(), key=lambda kv: -len(kv[1]))
            for pair, pair_setups in sorted_pairs[:15]:
                ps = self._compute_stats(pair_setups)
                pnl_sign = "+" if ps["total_usd"] >= 0 else ""
                emo = "🟢" if ps["total_usd"] > 0 else ("🔴" if ps["total_usd"] < 0 else "⚪")
                result_lines.append(
                    f"\n<b>{pair}</b> {emo}\n"
                    f"  🎯 {ps['total']} setup  |  "
                    f"🏆 {ps['won']}  🔵 {ps['be']}  🔴 {ps['lost']}  🟡 {ps['cancelled']}\n"
                    f"  💰 <b>{pnl_sign}${ps['total_usd']:.2f}</b>"
                )

        # Timeframe breakdown
        by_tf = self._group_by_tf(filtered)
        if len(by_tf) > 1:
            result_lines.append("\n<b>Timeframe bo'yicha:</b>")
            for tf, tf_setups in sorted(by_tf.items()):
                ts = self._compute_stats(tf_setups)
                pnl_sign = "+" if ts["total_usd"] >= 0 else ""
                emo = "🟢" if ts["total_usd"] > 0 else ("🔴" if ts["total_usd"] < 0 else "⚪")
                result_lines.append(
                    f"  <b>{tf}</b> {emo}: {ts['total']} setup, "
                    f"🏆{ts['won']} 🔵{ts['be']} 🔴{ts['lost']} 🟡{ts['cancelled']}, "
                    f"<b>{pnl_sign}${ts['total_usd']:.2f}</b>"
                )

        # Jami
        pnl_sign = "+" if stats["total_usd"] >= 0 else ""
        pnl_emo = "📈" if stats["total_usd"] >= 0 else "📉"
        win_rate = (stats["won"] / stats["closed"] * 100) if stats["closed"] > 0 else 0.0
        profit_rate = ((stats["won"] + stats["be"]) / stats["closed"] * 100) if stats["closed"] > 0 else 0.0

        result_lines.append(
            f"\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>JAMI:</b> {stats['total']} setup"
        )
        if stats["closed"] > 0:
            result_lines.append(
                f"🏆 {stats['won']}  🔵 {stats['be']}  "
                f"🔴 {stats['lost']}  🟡 {stats['cancelled']}\n"
                f"📈 G'olib foizi: <b>{win_rate:.1f}%</b>  |  "
                f"💚 Foydali: <b>{profit_rate:.1f}%</b>"
            )
        if stats["active"] > 0:
            result_lines.append(f"⏳ Aktiv: {stats['active']}")
        result_lines.append(
            f"{pnl_emo} <b>F/Z: {pnl_sign}${stats['total_usd']:.2f}</b>"
        )
        if stats["best_usd"] != 0 or stats["worst_usd"] != 0:
            result_lines.append(
                f"🚀 Eng yaxshi: <b>+${stats['best_usd']:.2f}</b>  |  "
                f"💥 Eng yomon: <b>${stats['worst_usd']:.2f}</b>"
            )

        return ("\n".join(result_lines), stats_result_kb())

    def _format_custom_period(self, period_tuple) -> str:
        """(start_ms, end_ms) → 'YYYY-MM-DD dan YYYY-MM-DD gacha'."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Asia/Tashkent")
        except Exception:
            from datetime import timezone
            tz = timezone.utc
        start_ms, end_ms = period_tuple
        start = datetime.fromtimestamp(start_ms / 1000, tz=tz)
        end = datetime.fromtimestamp(end_ms / 1000, tz=tz)
        # end exclusive - 1 kun ayirib
        from datetime import timedelta
        end_disp = end - timedelta(days=1)
        if start.strftime("%Y-%m-%d") == end_disp.strftime("%Y-%m-%d"):
            return start.strftime("%Y-%m-%d")
        return (
            f"{start.strftime('%Y-%m-%d')} dan "
            f"{end_disp.strftime('%Y-%m-%d')} gacha"
        )

    def _parse_custom_date_range(self, text: str):
        """'2026-08-01 2026-08-31' yoki '2026-08-15' → (start_ms, end_ms)."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Asia/Tashkent")
        except Exception:
            from datetime import timezone
            tz = timezone.utc
        from datetime import timedelta

        parts = text.strip().split()
        dates = []
        for p in parts:
            try:
                y, m, d = p.split("-")
                dt = datetime(int(y), int(m), int(d), tzinfo=tz)
                dates.append(dt)
            except Exception:
                return None
        if len(dates) == 1:
            start = dates[0]
            end = start + timedelta(days=1)
        elif len(dates) == 2:
            start, end = dates
            end = end + timedelta(days=1)  # end inclusive
        else:
            return None
        return int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    def _cb_settings(self, sub: str):
        """Sozlamalar submenulari."""
        if sub == "menu":
            return self._show_settings_menu()
        if sub == "risk":
            return (
                f"💰 <b>Risk qiymati</b>\n\n"
                f"Hozirgi: <b>${self.config.risk_usd:.2f}</b>\n\n"
                f"Tayyor qiymatdan tanlang yoki o'zingiz kiriting:",
                risk_preset_kb()
            )
        if sub == "min":
            return (
                f"📈 <b>Minimum svechalar soni</b>\n\n"
                f"Hozirgi: <b>{self.config.min_candles}</b>\n\n"
                f"Yangi qiymatni tanlang:",
                min_preset_kb()
            )
        if sub == "be":
            be_state = "YOQILGAN ✅" if self.config.enable_be else "OCHIRILGAN ❌"
            return (
                f"🔵 <b>Break-Even (BE)</b>\n\n"
                f"BE — TP1 tegilganda SL avtomatik entry narxiga siljiydi.\n"
                f"Bu qolgan pozitsiyada risk yo'q qiladi.\n\n"
                f"Hozirgi: <b>{be_state}</b>",
                be_toggle_kb(self.config.enable_be)
            )
        if sub == "sl_buffer":
            return (
                f"🔴 <b>SL Buffer</b>\n\n"
                f"Kichik wick'lar SL ni urib ketmasligi uchun buffer.\n"
                f"Hozirgi: <b>{self.config.sl_buffer_pct:.3f}%</b>\n\n"
                f"Tayyor qiymatdan tanlang:",
                sl_buffer_preset_kb()
            )
        if sub in ("tp1", "tp2", "tp3", "tp_ratios", "tp_all", "fib_tps"):
            return (
                f"🟢 <b>TP Partial foizlar</b>\n\n"
                f"Hozirgi: {self.config.tp1_pct:.0f} / "
                f"{self.config.tp2_pct:.0f} / {self.config.tp3_pct:.0f}\n\n"
                f"Tayyor kombinatsiyalardan tanlang:",
                tp_presets_kb()
            )
        if sub == "fib_sl":
            return (
                f"📐 <b>Fibonacci SL</b>\n\n"
                f"Hozirgi: <b>{self.config.fib_sl}</b>\n\n"
                f"0 = karobka chekkasi (default)\n"
                f"0.1 = ichkariroqqa 10%\n"
                f"0.382 = klassik fib retracement\n\n"
                f"O'zgartirish uchun:\n"
                f"<code>/set fib_sl 0.1</code>",
                None
            )
        if sub == "close":
            return ("✅ Sozlamalar yopildi.", None)
        return f"❓ Noma'lum sub-menyu: {sub}"

    def _cb_set(self, param: str, value: str):
        """Callback orqali sozlamani o'rnatish (preset qiymat)."""
        # Special: TP presets ("tp:50,25,25")
        if param == "tp":
            vals = value.split(",")
            if len(vals) == 3:
                try:
                    v1, v2, v3 = float(vals[0]), float(vals[1]), float(vals[2])
                    if abs(v1 + v2 + v3 - 100.0) > 0.5:
                        return (
                            f"❌ Jami 100% bo'lsin (hozir: {v1+v2+v3})",
                            settings_menu_kb(self.config)
                        )
                    self.config.tp1_pct = v1
                    self.config.tp2_pct = v2
                    self.config.tp3_pct = v3
                    self._save_state()
                    return (
                        f"🟢 TP foizlar: <b>{v1:.0f} / {v2:.0f} / {v3:.0f}</b> ✅\n\n"
                        f"⚙️ Boshqa sozlama:",
                        settings_menu_kb(self.config)
                    )
                except ValueError:
                    return ("❌ Noto'g'ri qiymat", settings_menu_kb(self.config))

        # Boshqa oddiy setlar
        result = self.cmd_set([param, value])
        # Muvaffaqiyat belgisi bo'lsa - menyuga qaytish
        success_prefixes = ("💰", "📈", "🔵", "🔴", "🟢", "📐")
        if result.startswith(success_prefixes):
            return (
                f"{result}\n\n"
                f"⚙️ Boshqa sozlama:",
                settings_menu_kb(self.config)
            )
        return (result, None)

    def _cb_await_input(self, chat_id: str, param: str):
        """Foydalanuvchidan matn kutish holatini yoqish."""
        prompts = {
            "risk": "💰 Yangi risk qiymatini yozing (masalan: <code>7.5</code>)",
            "sl_buffer": "🔴 Yangi SL buffer % yozing (masalan: <code>0.03</code>)",
            "min": "📈 Yangi min svechalar sonini yozing",
        }
        prompt = prompts.get(param)
        if not prompt:
            return f"❓ Bu parametr uchun matn kiritish qo'llab-quvvatlanmaydi"
        self._pending_input[str(chat_id)] = param
        return (
            f"{prompt}\n\n"
            f"<i>Bekor qilish uchun /menu</i>",
            None
        )

    def _handle_pending_input(self, chat_id: str, param: str, text: str):
        """Kutilayotgan input keldi."""
        self._pending_input.pop(str(chat_id), None)

        # Custom sana oralig'i (wizard uchun)
        if param == "custom_date":
            date_range = self._parse_custom_date_range(text)
            if not date_range:
                # Qayta so'rash
                self._pending_input[str(chat_id)] = "custom_date"
                return (
                    f"❌ <b>Noto'g'ri format</b>\n\n"
                    f"To'g'ri format:\n"
                    f"<code>2026-08-01 2026-08-31</code>\n"
                    f"yoki bitta kun:\n"
                    f"<code>2026-08-15</code>\n\n"
                    f"Qayta yozing yoki /menu bilan bekor qiling",
                    None
                )
            # Yakuniy statistika
            return self._show_wizard_result(chat_id, date_range)

        # Sozlamalar uchun
        result = self.cmd_set([param, text.strip()])
        return (
            f"{result}\n\n"
            f"⚙️ Boshqa sozlama:",
            settings_menu_kb(self.config)
        )

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
