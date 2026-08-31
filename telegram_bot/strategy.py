"""
SERIYA strategiyasi - Pine Script v5.2 dan Python'ga port.

Lifecycle:
    PENDING → FILLED → WON / LOST / BE
    PENDING → CANCELLED (CZ break yoki rolling)
"""
import logging
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timezone

from config import Config
from models import (
    Candle, Setup, StreakState, Event, Counters, DailyPairStats,
    Status, Direction, EventType,
)

logger = logging.getLogger(__name__)


class StrategyEngine:
    """
    Barcha (pair, timeframe) uchun umumiy strategiya engine.
    Har bir (pair, tf) alohida StreakState ga ega.
    """

    def __init__(self, config: Config):
        self.config = config
        self.streaks: Dict[str, StreakState] = {}  # key: "pair|tf"
        self.setups: List[Setup] = []
        self.counters = Counters()
        self._next_id = 1
        # Kunlik statistika (00:00 da report + reset)
        self.daily_stats: Dict[str, DailyPairStats] = {}  # key: pair
        self.daily_stats_day: str = ""  # YYYY-MM-DD - hozirgi tracker kuni
        self.last_reported_day: str = ""  # YYYY-MM-DD - oxirgi yuborilgan report kuni

    # ==================================================================
    # SILENT WARMUP - bot birinchi start'da tarixiy candles'ni
    # streak holatini qurish uchun ishlatadi, lekin setup yaratmaydi
    # va Telegram alertlarini yubormaydi.
    # ==================================================================

    def process_closed_candle_silent(self, pair: str, timeframe: str,
                                     candle: Candle) -> None:
        """
        Tarixiy svechani QAYTA ishlash - faqat streak update.
        Setup yaratmaydi va event qaytarmaydi.
        Cold start'da spam'ning oldini olish uchun.
        """
        streak = self.get_or_create_streak(pair, timeframe)
        if candle.timestamp_ms <= streak.last_processed_ms:
            return
        self._update_streak(streak, candle)
        streak.last_processed_ms = candle.timestamp_ms

    # ==================================================================
    # HOLAT BOSHQARUVI
    # ==================================================================

    def get_or_create_streak(self, pair: str, timeframe: str) -> StreakState:
        key = f"{pair}|{timeframe}"
        if key not in self.streaks:
            self.streaks[key] = StreakState(pair=pair, timeframe=timeframe)
        return self.streaks[key]

    def load_state(self, data: dict) -> None:
        """State faylidan tiklash. `data` — dict from JSON."""
        streaks_raw = data.get("streaks", {})
        setups_raw = data.get("setups", [])
        counters_raw = data.get("counters", {})
        daily_raw = data.get("daily_stats", {})
        self.streaks = {k: StreakState.from_dict(v) for k, v in streaks_raw.items()}
        self.setups = [Setup.from_dict(s) for s in setups_raw]
        self.counters = Counters.from_dict(counters_raw) if counters_raw else Counters()
        self.daily_stats = {k: DailyPairStats.from_dict(v)
                           for k, v in daily_raw.items()}
        self.daily_stats_day = data.get("daily_stats_day", "")
        self.last_reported_day = data.get("last_reported_day", "")
        self._next_id = data.get("next_id", 1)

    def dump_state(self) -> dict:
        """State'ni saqlash uchun to'liq dict (JSON-friendly)."""
        return {
            "streaks": {k: v.to_dict() for k, v in self.streaks.items()},
            "setups": [s.to_dict() for s in self.setups],
            "counters": self.counters.to_dict(),
            "daily_stats": {k: v.to_dict() for k, v in self.daily_stats.items()},
            "daily_stats_day": self.daily_stats_day,
            "last_reported_day": self.last_reported_day,
            "next_id": self._next_id,
        }

    # ==================================================================
    # KUNLIK STATISTIKA
    # ==================================================================

    def _get_daily(self, pair: str) -> DailyPairStats:
        if pair not in self.daily_stats:
            self.daily_stats[pair] = DailyPairStats(pair=pair)
        return self.daily_stats[pair]

    def _apply_events_to_daily(self, events: List[Event]) -> None:
        """Har bir event uchun daily stats yangilash."""
        for ev in events:
            ps = self._get_daily(ev.setup.pair)
            if ev.type == EventType.SETUP_CREATED.value:
                ps.setups_created += 1
            elif ev.type == EventType.TP3_HIT.value:
                ps.won += 1
                ps.total_usd += ev.pnl_usd
            elif ev.type == EventType.SL_HIT.value:
                ps.lost += 1
                ps.total_usd += ev.pnl_usd
            elif ev.type == EventType.BE_STOP.value:
                ps.be += 1
            elif ev.type in (EventType.CANCELLED_CZ.value,
                             EventType.CANCELLED_ROLLING.value):
                ps.cancelled += 1
            elif ev.type == EventType.TP1_HIT.value:
                ps.partial_tp1 += 1
                ps.total_usd += ev.pnl_usd
            elif ev.type == EventType.TP2_HIT.value:
                ps.total_usd += ev.pnl_usd

    def reset_daily_stats(self, new_day: str) -> None:
        """Kunlik statistikani tozalash (report yuborilgandan keyin)."""
        self.daily_stats = {}
        self.daily_stats_day = new_day
        logger.info(f"Daily stats reset. New day: {new_day}")

    # ==================================================================
    # ASOSIY: yangi svecha yopildi
    # ==================================================================

    def process_closed_candle(self, pair: str, timeframe: str,
                              candle: Candle) -> List[Event]:
        """
        Yangi yopilgan svecha keldi.
        1) Pending/Filled setup'larni yangilash (fill, SL, TP, CZ)
        2) Streak'ni yangilash
        3) Yangi setup aniqlash
        """
        events: List[Event] = []
        streak = self.get_or_create_streak(pair, timeframe)

        # Takroriylikning oldini olish
        if candle.timestamp_ms <= streak.last_processed_ms:
            return events

        # 1) Mavjud setup'larni yangilash
        for setup in list(self.setups):
            if setup.pair != pair or setup.timeframe != timeframe:
                continue
            if setup.status not in (Status.PENDING.value, Status.FILLED.value):
                continue
            events.extend(self._update_setup_on_candle(setup, candle))

        # 2) REVERSAL detektsiyasi — streak update'dan OLDIN, eski state bilan
        #    SELL: bull_streak >= min VA joriy svecha BEARISH (reversal)
        #    BUY:  bear_streak >= min VA joriy svecha BULLISH (reversal)
        #    Qo'shimcha shart: streak'ning box'i valid bo'lishi kerak
        #    (bull_last_close > bull_first_open, ya'ni streak haqiqatan yuqoriga)
        sell_setup = (streak.bull_streak >= self.config.min_candles
                      and candle.is_bear
                      and streak.bull_last_close > streak.bull_first_open)
        buy_setup = (streak.bear_streak >= self.config.min_candles
                     and candle.is_bull
                     and streak.bear_last_close < streak.bear_first_open)

        if sell_setup:
            # Rolling cancel — bir xil turdagi eski pending'larni bekor qilish
            events.extend(self._rolling_cancel(pair, timeframe,
                                               Direction.SELL.value, candle))
            new_setup = self._create_setup(pair, timeframe,
                                            Direction.SELL.value, streak, candle)
            self.setups.append(new_setup)
            self.counters.total_setups += 1
            events.append(Event(
                type=EventType.SETUP_CREATED.value,
                setup=new_setup,
                price=candle.close,
            ))

        if buy_setup:
            events.extend(self._rolling_cancel(pair, timeframe,
                                               Direction.BUY.value, candle))
            new_setup = self._create_setup(pair, timeframe,
                                            Direction.BUY.value, streak, candle)
            self.setups.append(new_setup)
            self.counters.total_setups += 1
            events.append(Event(
                type=EventType.SETUP_CREATED.value,
                setup=new_setup,
                price=candle.close,
            ))

        # 3) Streak yangilash — reversal check'dan KEYIN
        self._update_streak(streak, candle)

        streak.last_processed_ms = candle.timestamp_ms

        # Daily stats yangilash
        self._apply_events_to_daily(events)
        return events

    # ==================================================================
    # STREAK YANGILASH
    # ==================================================================

    def _update_streak(self, streak: StreakState, candle: Candle) -> None:
        """Bullish/bearish ketma-ketligini yangilash."""
        if candle.is_bull:
            if streak.bull_streak == 0:
                streak.bull_first_open = candle.open
                streak.bull_start_ms = candle.timestamp_ms
            streak.bull_streak += 1
            streak.bull_last_close = candle.close  # box top uchun kerak
            streak.reset_bear()
        elif candle.is_bear:
            if streak.bear_streak == 0:
                streak.bear_first_open = candle.open
                streak.bear_start_ms = candle.timestamp_ms
            streak.bear_streak += 1
            streak.bear_last_close = candle.close  # box bot uchun kerak
            streak.reset_bull()
        else:
            # doji — ikkalasini reset
            streak.reset_bull()
            streak.reset_bear()

    # ==================================================================
    # SETUP YARATISH
    # ==================================================================

    def _create_setup(self, pair: str, timeframe: str, direction: str,
                      streak: StreakState, candle: Candle) -> Setup:
        """
        Setup yaratish. `candle` — REVERSAL svecha (SELL uchun bearish,
        BUY uchun bullish). Box streak'ning first_open va last_close bilan
        aniqlanadi. `candle.close` bu yerda faqat signal_close sifatida
        ishlatiladi (informational).
        """
        cfg = self.config
        if direction == Direction.SELL.value:
            first_open = streak.bull_first_open
            last_close = streak.bull_last_close  # streak'ning tepasi
            candle_cnt = streak.bull_streak
        else:
            first_open = streak.bear_first_open
            last_close = streak.bear_last_close  # streak'ning tagi
            candle_cnt = streak.bear_streak

        # Box: streak'ning first_open va last_close bilan aniqlanadi
        box_top = max(first_open, last_close)
        box_bot = min(first_open, last_close)
        rng = box_top - box_bot

        if direction == Direction.SELL.value:
            # fib 0 = top (streak tepasi = SL), fib 1 = bot (streak boshi = Entry)
            entry = first_open   # fib 1
            sl = box_top - cfg.fib_sl * rng  # fib 0 (~box_top)
            tp1 = box_top - cfg.fib_tp1 * rng
            tp2 = box_top - cfg.fib_tp2 * rng
            tp3 = box_top - cfg.fib_tp3 * rng
        else:
            # fib 0 = bot (streak tagi = SL), fib 1 = top (streak boshi = Entry)
            entry = first_open   # fib 1
            sl = box_bot + cfg.fib_sl * rng  # fib 0 (~box_bot)
            tp1 = box_bot + cfg.fib_tp1 * rng
            tp2 = box_bot + cfg.fib_tp2 * rng
            tp3 = box_bot + cfg.fib_tp3 * rng

        # CZ = SL narx bilan bir xil (streak chekkasi).
        # Pending vaqtida close CZ ustida bo'lsa (SELL uchun) → cancel.
        setup = Setup(
            id=self._next_id,
            pair=pair,
            timeframe=timeframe,
            direction=direction,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            cz=sl,
            status=Status.PENDING.value,
            candle_count=candle_cnt,
            created_at_ms=candle.timestamp_ms,
            signal_close=candle.close,  # reversal candle close
            risk_usd=cfg.risk_usd,
            realized_usd=0.0,
            box_top=box_top,
            box_bot=box_bot,
        )
        self._next_id += 1
        reversal = "bearish" if direction == Direction.SELL.value else "bullish"
        logger.info(f"[{pair} {timeframe}] Yangi setup #{setup.id} {direction} "
                    f"(streak={candle_cnt}sv + {reversal} reversal) "
                    f"entry={entry} SL={sl}")
        return setup

    # ==================================================================
    # SETUP YANGILASH (svecha ustida)
    # ==================================================================

    def _update_setup_on_candle(self, setup: Setup, candle: Candle) -> List[Event]:
        """Setup PENDING yoki FILLED bo'lsa - svecha OHLC ustida tekshirish."""
        # Setup shu candle'da yaratilgan bo'lsa - tekshirmaymiz
        if candle.timestamp_ms <= setup.created_at_ms:
            return []

        events: List[Event] = []

        if setup.status == Status.PENDING.value:
            # Fill tekshirish - entry svecha oralig'iga tushdimi?
            filled = candle.low <= setup.entry <= candle.high
            if filled:
                setup.status = Status.FILLED.value
                setup.filled_at_ms = candle.timestamp_ms
                events.append(Event(
                    type=EventType.FILLED.value,
                    setup=setup,
                    price=setup.entry,
                ))
                # Xuddi shu candle'da SL tegishi mumkin - konservativ tekshiruv
                events.extend(self._check_sl_and_tp(setup, candle))
            else:
                # CZ break tekshirish
                cz_broken = self._is_cz_broken(setup, candle.close)
                if cz_broken:
                    self._close_setup(setup, Status.CANCELLED.value, candle.timestamp_ms)
                    self.counters.cancelled += 1
                    events.append(Event(
                        type=EventType.CANCELLED_CZ.value,
                        setup=setup,
                        price=candle.close,
                    ))

        elif setup.status == Status.FILLED.value:
            events.extend(self._check_sl_and_tp(setup, candle))

        return events

    def _is_cz_broken(self, setup: Setup, close: float) -> bool:
        """SELL uchun close > cz, BUY uchun close < cz."""
        if setup.direction == Direction.SELL.value:
            return close > setup.cz
        return close < setup.cz

    # ==================================================================
    # SL + TP tekshiruvi (FILLED holatida)
    # ==================================================================

    def _check_sl_and_tp(self, setup: Setup, candle: Candle) -> List[Event]:
        """
        Konservativ tekshiruv:
        1) Avval SL tekshiriladi (agar tegsa - LOST/BE)
        2) Keyin TP1/TP2/TP3 kaskadli tekshirilar
        Bir svechada bir necha TP tegishi mumkin.
        """
        events: List[Event] = []
        cfg = self.config

        # 1) SL tegdimi
        if self._is_price_hit(setup.sl, setup.direction, candle,
                              is_sl=True):
            if setup.be_moved:
                # Break-even stop - foyda bilan chiqdi
                self._close_setup(setup, Status.BE.value, candle.timestamp_ms)
                self.counters.be += 1
                if setup.realized_usd > self.counters.best_usd:
                    self.counters.best_usd = setup.realized_usd
                events.append(Event(
                    type=EventType.BE_STOP.value,
                    setup=setup,
                    price=setup.sl,
                    pnl_usd=0.0,
                ))
            else:
                # Oddiy LOST
                rem_pct = 100.0
                if setup.partial_level == 1:
                    rem_pct = 100.0 - cfg.tp1_pct
                elif setup.partial_level == 2:
                    rem_pct = 100.0 - cfg.tp1_pct - cfg.tp2_pct
                pnl = -setup.risk_usd * (rem_pct / 100.0)
                setup.realized_usd += pnl
                self.counters.total_usd += pnl
                if setup.realized_usd < self.counters.worst_usd:
                    self.counters.worst_usd = setup.realized_usd
                self._close_setup(setup, Status.LOST.value, candle.timestamp_ms)
                self.counters.lost += 1
                events.append(Event(
                    type=EventType.SL_HIT.value,
                    setup=setup,
                    price=setup.sl,
                    pnl_usd=pnl,
                ))
            return events

        # 2) TP kaskadi
        # TP1
        if setup.partial_level == 0 and self._is_price_hit(setup.tp1, setup.direction, candle):
            pnl1 = setup.risk_usd * (cfg.tp1_pct / 100.0) * cfg.rr_tp1
            setup.realized_usd += pnl1
            self.counters.total_usd += pnl1
            setup.partial_level = 1
            self.counters.partial_tp1 += 1

            # Break-even siljitish
            if cfg.enable_be:
                setup.sl = setup.entry
                setup.be_moved = True

            events.append(Event(
                type=EventType.TP1_HIT.value,
                setup=setup,
                price=setup.tp1,
                pnl_usd=pnl1,
            ))

        # TP2 (agar TP1 allaqachon bo'lgan bo'lsa yoki shu svechada tegdi)
        if setup.partial_level == 1 and self._is_price_hit(setup.tp2, setup.direction, candle):
            pnl2 = setup.risk_usd * (cfg.tp2_pct / 100.0) * cfg.rr_tp2
            setup.realized_usd += pnl2
            self.counters.total_usd += pnl2
            setup.partial_level = 2
            events.append(Event(
                type=EventType.TP2_HIT.value,
                setup=setup,
                price=setup.tp2,
                pnl_usd=pnl2,
            ))

        # TP3 - WON
        if setup.partial_level == 2 and self._is_price_hit(setup.tp3, setup.direction, candle):
            pnl3 = setup.risk_usd * (cfg.tp3_pct / 100.0) * cfg.rr_tp3
            setup.realized_usd += pnl3
            self.counters.total_usd += pnl3
            if setup.realized_usd > self.counters.best_usd:
                self.counters.best_usd = setup.realized_usd
            self._close_setup(setup, Status.WON.value, candle.timestamp_ms)
            self.counters.won += 1
            events.append(Event(
                type=EventType.TP3_HIT.value,
                setup=setup,
                price=setup.tp3,
                pnl_usd=pnl3,
            ))

        return events

    def _is_price_hit(self, level: float, direction: str, candle: Candle,
                      is_sl: bool = False) -> bool:
        """
        Narx candle oralig'ida `level` ga teggan-tegmaganini tekshirish.
        SL uchun:
          SELL — high >= sl (yuqoriga chiqib SL uradi)
          BUY  — low <= sl (pastga tushib SL uradi)
        TP uchun:
          SELL — low <= tp (pastga tushib TP uradi)
          BUY  — high >= tp (yuqoriga chiqib TP uradi)
        """
        if is_sl:
            if direction == Direction.SELL.value:
                return candle.high >= level
            return candle.low <= level
        # TP
        if direction == Direction.SELL.value:
            return candle.low <= level
        return candle.high >= level

    # ==================================================================
    # ROLLING CANCEL
    # ==================================================================

    def _rolling_cancel(self, pair: str, timeframe: str,
                        direction: str, candle: Candle) -> List[Event]:
        """Shu (pair, tf, direction) uchun barcha PENDING'larni bekor qilish."""
        events: List[Event] = []
        for s in self.setups:
            if (s.pair == pair and s.timeframe == timeframe
                    and s.direction == direction
                    and s.status == Status.PENDING.value):
                self._close_setup(s, Status.CANCELLED.value, candle.timestamp_ms)
                self.counters.cancelled += 1
                events.append(Event(
                    type=EventType.CANCELLED_ROLLING.value,
                    setup=s,
                    price=candle.close,
                ))
        return events

    def _close_setup(self, setup: Setup, new_status: str, closed_at_ms: int) -> None:
        setup.status = new_status
        setup.closed_at_ms = closed_at_ms

    # ==================================================================
    # LIVE NARX TEKSHIRUVI (candle'lar orasida)
    # ==================================================================

    def check_live_price(self, pair: str, timeframe: str,
                         current_price: float, now_ms: int) -> List[Event]:
        """
        Live narx bilan - candle yopilishini kutmasdan.
        Bu quyidagilarni tekshiradi:
          - PENDING fill (agar joriy narx entry ga o'tgan bo'lsa)
          - FILLED SL/TP hit
        CZ break faqat yopilgan candle'da tekshirilganligi sabab bu yerda emas.
        """
        events: List[Event] = []
        for setup in list(self.setups):
            if setup.pair != pair or setup.timeframe != timeframe:
                continue
            if setup.status == Status.PENDING.value:
                # Fill tekshirish - narx entry darajasidan o'tdimi
                # SELL: entry pastroq (< signal close), narx pastga tushdi
                # BUY: entry yuqoriroq (> signal close), narx yuqoriga chiqdi
                filled = False
                if setup.direction == Direction.SELL.value:
                    filled = current_price <= setup.entry
                else:
                    filled = current_price >= setup.entry
                if filled:
                    setup.status = Status.FILLED.value
                    setup.filled_at_ms = now_ms
                    events.append(Event(
                        type=EventType.FILLED.value,
                        setup=setup,
                        price=setup.entry,
                    ))
            elif setup.status == Status.FILLED.value:
                # SL tegdimi
                sl_hit = False
                if setup.direction == Direction.SELL.value:
                    sl_hit = current_price >= setup.sl
                else:
                    sl_hit = current_price <= setup.sl
                if sl_hit:
                    events.extend(self._handle_live_sl(setup, current_price, now_ms))
                    continue

                # TP tekshiruvi
                events.extend(self._handle_live_tp(setup, current_price, now_ms))

        # Daily stats yangilash
        self._apply_events_to_daily(events)
        return events

    def _handle_live_sl(self, setup: Setup, price: float, now_ms: int) -> List[Event]:
        cfg = self.config
        events: List[Event] = []
        if setup.be_moved:
            self._close_setup(setup, Status.BE.value, now_ms)
            self.counters.be += 1
            if setup.realized_usd > self.counters.best_usd:
                self.counters.best_usd = setup.realized_usd
            events.append(Event(
                type=EventType.BE_STOP.value,
                setup=setup,
                price=setup.sl,
                pnl_usd=0.0,
            ))
        else:
            rem_pct = 100.0
            if setup.partial_level == 1:
                rem_pct = 100.0 - cfg.tp1_pct
            elif setup.partial_level == 2:
                rem_pct = 100.0 - cfg.tp1_pct - cfg.tp2_pct
            pnl = -setup.risk_usd * (rem_pct / 100.0)
            setup.realized_usd += pnl
            self.counters.total_usd += pnl
            if setup.realized_usd < self.counters.worst_usd:
                self.counters.worst_usd = setup.realized_usd
            self._close_setup(setup, Status.LOST.value, now_ms)
            self.counters.lost += 1
            events.append(Event(
                type=EventType.SL_HIT.value,
                setup=setup,
                price=setup.sl,
                pnl_usd=pnl,
            ))
        return events

    def _handle_live_tp(self, setup: Setup, price: float, now_ms: int) -> List[Event]:
        cfg = self.config
        events: List[Event] = []

        def hit_tp(level: float) -> bool:
            if setup.direction == Direction.SELL.value:
                return price <= level
            return price >= level

        if setup.partial_level == 0 and hit_tp(setup.tp1):
            pnl1 = setup.risk_usd * (cfg.tp1_pct / 100.0) * cfg.rr_tp1
            setup.realized_usd += pnl1
            self.counters.total_usd += pnl1
            setup.partial_level = 1
            self.counters.partial_tp1 += 1
            if cfg.enable_be:
                setup.sl = setup.entry
                setup.be_moved = True
            events.append(Event(
                type=EventType.TP1_HIT.value,
                setup=setup,
                price=setup.tp1,
                pnl_usd=pnl1,
            ))
        if setup.partial_level == 1 and hit_tp(setup.tp2):
            pnl2 = setup.risk_usd * (cfg.tp2_pct / 100.0) * cfg.rr_tp2
            setup.realized_usd += pnl2
            self.counters.total_usd += pnl2
            setup.partial_level = 2
            events.append(Event(
                type=EventType.TP2_HIT.value,
                setup=setup,
                price=setup.tp2,
                pnl_usd=pnl2,
            ))
        if setup.partial_level == 2 and hit_tp(setup.tp3):
            pnl3 = setup.risk_usd * (cfg.tp3_pct / 100.0) * cfg.rr_tp3
            setup.realized_usd += pnl3
            self.counters.total_usd += pnl3
            if setup.realized_usd > self.counters.best_usd:
                self.counters.best_usd = setup.realized_usd
            self._close_setup(setup, Status.WON.value, now_ms)
            self.counters.won += 1
            events.append(Event(
                type=EventType.TP3_HIT.value,
                setup=setup,
                price=setup.tp3,
                pnl_usd=pnl3,
            ))
        return events

    # ==================================================================
    # CLEANUP
    # ==================================================================

    def cleanup_closed(self, keep_last: int = 200) -> None:
        """Eski yopilgan setup'larni tozalash - keyingi keep_last ta qoladi."""
        closed = [s for s in self.setups if s.status not in
                  (Status.PENDING.value, Status.FILLED.value)]
        if len(closed) <= keep_last:
            return
        closed.sort(key=lambda x: x.closed_at_ms or 0)
        to_remove = closed[:len(closed) - keep_last]
        remove_ids = {s.id for s in to_remove}
        self.setups = [s for s in self.setups if s.id not in remove_ids]
