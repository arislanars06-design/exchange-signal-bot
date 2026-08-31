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
    Candle, Setup, StreakState, Event, Counters,
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

    # ==================================================================
    # HOLAT BOSHQARUVI
    # ==================================================================

    def get_or_create_streak(self, pair: str, timeframe: str) -> StreakState:
        key = f"{pair}|{timeframe}"
        if key not in self.streaks:
            self.streaks[key] = StreakState(pair=pair, timeframe=timeframe)
        return self.streaks[key]

    def load_state(self, streaks: Dict[str, dict], setups: List[dict],
                   counters: dict, next_id: int) -> None:
        """State faylidan tiklash."""
        self.streaks = {k: StreakState.from_dict(v) for k, v in streaks.items()}
        self.setups = [Setup.from_dict(s) for s in setups]
        self.counters = Counters.from_dict(counters) if counters else Counters()
        self._next_id = next_id

    def dump_state(self) -> Tuple[Dict[str, dict], List[dict], dict, int]:
        """State'ni saqlash uchun serializatsiya."""
        streaks = {k: v.to_dict() for k, v in self.streaks.items()}
        setups = [s.to_dict() for s in self.setups]
        return streaks, setups, self.counters.to_dict(), self._next_id

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

        # 2) Streak yangilash
        self._update_streak(streak, candle)

        # 3) Yangi setup aniqlash
        sell_setup = (streak.bull_streak >= self.config.min_candles
                      and candle.close > streak.bull_first_open)
        buy_setup = (streak.bear_streak >= self.config.min_candles
                     and candle.close < streak.bear_first_open)

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

        streak.last_processed_ms = candle.timestamp_ms
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
            streak.reset_bear()
        elif candle.is_bear:
            if streak.bear_streak == 0:
                streak.bear_first_open = candle.open
                streak.bear_start_ms = candle.timestamp_ms
            streak.bear_streak += 1
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
        cfg = self.config
        if direction == Direction.SELL.value:
            first_open = streak.bull_first_open
            candle_cnt = streak.bull_streak
        else:
            first_open = streak.bear_first_open
            candle_cnt = streak.bear_streak

        box_top = max(first_open, candle.close)
        box_bot = min(first_open, candle.close)
        rng = box_top - box_bot

        if direction == Direction.SELL.value:
            # fib 0 = top, fib 1 = bot
            entry = first_open  # fib 1 (bottom)
            sl = box_top - cfg.fib_sl * rng  # ~box_top
            tp1 = box_top - cfg.fib_tp1 * rng
            tp2 = box_top - cfg.fib_tp2 * rng
            tp3 = box_top - cfg.fib_tp3 * rng
        else:
            # fib 0 = bot, fib 1 = top
            entry = first_open  # fib 1 (top)
            sl = box_bot + cfg.fib_sl * rng  # ~box_bot
            tp1 = box_bot + cfg.fib_tp1 * rng
            tp2 = box_bot + cfg.fib_tp2 * rng
            tp3 = box_bot + cfg.fib_tp3 * rng

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
            cz=candle.close,  # CZ = signal candle close (= SL uchun bir xil)
            status=Status.PENDING.value,
            candle_count=candle_cnt,
            created_at_ms=candle.timestamp_ms,
            signal_close=candle.close,
            risk_usd=cfg.risk_usd,
            realized_usd=0.0,
            box_top=box_top,
            box_bot=box_bot,
        )
        self._next_id += 1
        logger.info(f"[{pair} {timeframe}] Yangi setup #{setup.id} {direction} "
                    f"(sv={candle_cnt}) entry={entry} SL={sl}")
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
