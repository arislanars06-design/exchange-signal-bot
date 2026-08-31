"""
Bot sozlamalari - .env fayldan o'qiladi.
"""
import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


def _get_str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _get_int(key: str, default: int) -> int:
    val = os.getenv(key, "").strip()
    if not val:
        return default
    # Vergul va nuqta ikkalasini ham qo'llab-quvvatlash (locale-safe)
    val = val.replace(",", ".").strip()
    try:
        return int(float(val))
    except ValueError as e:
        raise ValueError(f"{key} raqam emas: '{os.getenv(key)}' ({e})")


def _get_float(key: str, default: float) -> float:
    val = os.getenv(key, "").strip()
    if not val:
        return default
    # Vergul va nuqta ikkalasini ham qo'llab-quvvatlash (locale-safe)
    val = val.replace(",", ".").strip()
    try:
        return float(val)
    except ValueError as e:
        raise ValueError(f"{key} raqam emas: '{os.getenv(key)}' ({e})")


def _get_bool(key: str, default: bool) -> bool:
    val = os.getenv(key, "").lower()
    if val in ("true", "1", "yes", "on"):
        return True
    if val in ("false", "0", "no", "off"):
        return False
    return default


def _get_list(key: str, default: List[str]) -> List[str]:
    val = os.getenv(key, "")
    if not val:
        return default
    return [x.strip() for x in val.split(",") if x.strip()]


@dataclass
class Config:
    # Telegram
    telegram_token: str = field(default_factory=lambda: _get_str("TELEGRAM_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _get_str("TELEGRAM_CHAT_ID"))

    # Binance
    binance_api_key: str = field(default_factory=lambda: _get_str("BINANCE_API_KEY"))
    binance_api_secret: str = field(default_factory=lambda: _get_str("BINANCE_API_SECRET"))

    # Kuzatiladigan bozorlar
    pairs: List[str] = field(default_factory=lambda: _get_list("PAIRS", ["BTC/USDT"]))
    timeframes: List[str] = field(default_factory=lambda: _get_list("TIMEFRAMES", ["15m"]))

    # Strategiya
    min_candles: int = field(default_factory=lambda: _get_int("MIN_CANDLES", 3))
    enable_be: bool = field(default_factory=lambda: _get_bool("ENABLE_BE", True))
    fib_sl: float = field(default_factory=lambda: _get_float("FIB_SL", 0.0))
    fib_tp1: float = field(default_factory=lambda: _get_float("FIB_TP1", 1.618))
    fib_tp2: float = field(default_factory=lambda: _get_float("FIB_TP2", 2.618))
    fib_tp3: float = field(default_factory=lambda: _get_float("FIB_TP3", 3.618))

    # SL buffer (foizda) - wick urib ketmasligi uchun SL ni uzoqroqqa siljitish
    # Default 0.01% (SELL: yuqoriroqqa, BUY: pastroqqa)
    sl_buffer_pct: float = field(default_factory=lambda: _get_float("SL_BUFFER_PCT", 0.01))

    # Partial close foizlari
    tp1_pct: float = field(default_factory=lambda: _get_float("TP1_PCT", 50.0))
    tp2_pct: float = field(default_factory=lambda: _get_float("TP2_PCT", 25.0))
    tp3_pct: float = field(default_factory=lambda: _get_float("TP3_PCT", 25.0))

    # Risk
    risk_usd: float = field(default_factory=lambda: _get_float("RISK_USD", 10.0))

    # Texnik
    poll_interval: int = field(default_factory=lambda: _get_int("POLL_INTERVAL_SECONDS", 30))
    log_level: str = field(default_factory=lambda: _get_str("LOG_LEVEL", "INFO"))
    state_file: str = field(default_factory=lambda: _get_str("STATE_FILE", "state.json"))

    # Kunlik report vaqt mintaqasi
    report_tz: str = field(default_factory=lambda: _get_str("REPORT_TZ", "Asia/Tashkent"))
    report_hour: int = field(default_factory=lambda: _get_int("REPORT_HOUR", 0))

    # Hisoblangan R/R
    @property
    def risk_range(self) -> float:
        return 1.0 - self.fib_sl

    @property
    def rr_tp1(self) -> float:
        return (self.fib_tp1 - 1.0) / self.risk_range

    @property
    def rr_tp2(self) -> float:
        return (self.fib_tp2 - 1.0) / self.risk_range

    @property
    def rr_tp3(self) -> float:
        return (self.fib_tp3 - 1.0) / self.risk_range

    def validate(self) -> None:
        """Sozlamalarni tekshirish - noto'g'ri bo'lsa xatolik chiqaradi."""
        errors = []
        if not self.telegram_token:
            errors.append("TELEGRAM_TOKEN belgilanmagan")
        if not self.telegram_chat_id:
            errors.append("TELEGRAM_CHAT_ID belgilanmagan")
        if not self.pairs:
            errors.append("PAIRS ro'yxati bo'sh")
        if not self.timeframes:
            errors.append("TIMEFRAMES ro'yxati bo'sh")
        if self.min_candles < 2:
            errors.append("MIN_CANDLES 2 dan kam bo'lmasin")
        total_pct = self.tp1_pct + self.tp2_pct + self.tp3_pct
        if abs(total_pct - 100.0) > 0.01:
            errors.append(f"TP foizlari jami 100 bo'lishi kerak, hozir: {total_pct}")
        if self.risk_usd <= 0:
            errors.append("RISK_USD musbat bo'lishi kerak")

        if errors:
            msg = "Sozlamalar xatosi:\n  - " + "\n  - ".join(errors)
            raise ValueError(msg)


# Global config instance
config = Config()
