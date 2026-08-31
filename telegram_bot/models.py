"""
Data model'lar: Setup, StreakState, Candle, Event.
"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List
from datetime import datetime, timezone


class Status(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    WON = "WON"
    LOST = "LOST"
    CANCELLED = "CANCELLED"
    BE = "BE"


class Direction(str, Enum):
    SELL = "SELL"
    BUY = "BUY"


class EventType(str, Enum):
    """Har xil eventlar - Telegram xabarlari uchun."""
    SETUP_CREATED = "SETUP_CREATED"
    FILLED = "FILLED"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    TP3_HIT = "TP3_HIT"  # WON
    SL_HIT = "SL_HIT"
    BE_STOP = "BE_STOP"
    CANCELLED_CZ = "CANCELLED_CZ"
    CANCELLED_ROLLING = "CANCELLED_ROLLING"


@dataclass
class Candle:
    """Bitta svecha ma'lumoti."""
    timestamp_ms: int  # UTC ms
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def is_bull(self) -> bool:
        return self.close > self.open

    @property
    def is_bear(self) -> bool:
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        return self.close == self.open

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ms / 1000, tz=timezone.utc)


@dataclass
class Setup:
    """Bitta trading setup - to'liq lifecycle bilan."""
    id: int
    pair: str
    timeframe: str
    direction: str  # "SELL" or "BUY"
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    cz: float
    status: str = Status.PENDING.value
    partial_level: int = 0  # 0, 1, 2
    be_moved: bool = False
    candle_count: int = 0

    # Vaqtlar (UTC ms)
    created_at_ms: int = 0
    filled_at_ms: Optional[int] = None
    closed_at_ms: Optional[int] = None

    # Signal svechaning yopilish narxi (CZ referent uchun)
    signal_close: float = 0.0

    # Dollar hisobi
    risk_usd: float = 0.0
    realized_usd: float = 0.0

    # Fibonacci karobkasi (vizual/tooltip uchun)
    box_top: float = 0.0
    box_bot: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Setup":
        return cls(**d)


@dataclass
class StreakState:
    """Bitta (pair, timeframe) uchun ketma-ket svechalar holati."""
    pair: str
    timeframe: str
    bull_streak: int = 0
    bear_streak: int = 0
    bull_first_open: float = 0.0
    bear_first_open: float = 0.0
    bull_start_ms: int = 0
    bear_start_ms: int = 0
    # Oxirgi qayta ishlangan svecha timestamp — takroriylikning oldini olish uchun
    last_processed_ms: int = 0

    @property
    def key(self) -> str:
        return f"{self.pair}|{self.timeframe}"

    def reset_bull(self) -> None:
        self.bull_streak = 0
        self.bull_first_open = 0.0
        self.bull_start_ms = 0

    def reset_bear(self) -> None:
        self.bear_streak = 0
        self.bear_first_open = 0.0
        self.bear_start_ms = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StreakState":
        return cls(**d)


@dataclass
class Event:
    """Strategy engine'dan chiqadigan event - Telegram uchun."""
    type: str  # EventType
    setup: Setup
    price: float = 0.0
    pnl_usd: float = 0.0
    extra: str = ""


@dataclass
class Counters:
    """Global statistika hisoblagichlari."""
    won: int = 0
    lost: int = 0
    be: int = 0
    cancelled: int = 0
    partial_tp1: int = 0
    total_setups: int = 0
    total_usd: float = 0.0
    best_usd: float = 0.0
    worst_usd: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Counters":
        return cls(**d)
