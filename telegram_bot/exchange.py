"""
Binance USDT-M Futures API wrapper (ccxt orqali).
Faqat public endpoints ishlatiladi - API key majburiy emas.
"""
import logging
import time
from typing import List, Dict, Optional
import ccxt

from models import Candle

logger = logging.getLogger(__name__)


class BinanceFutures:
    """Binance USDT-M Futures uchun oddiy wrapper."""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        params = {
            "options": {
                "defaultType": "future",  # USDT-M perpetual futures
                "adjustForTimeDifference": True,
            },
            "enableRateLimit": True,
            "timeout": 20000,
        }
        if api_key and api_secret:
            params["apiKey"] = api_key
            params["secret"] = api_secret

        self.exchange = ccxt.binanceusdm(params)
        self._markets_loaded = False

    def load_markets(self) -> None:
        """Bozorlar ro'yxatini yuklash (bir marta)."""
        if not self._markets_loaded:
            try:
                self.exchange.load_markets()
                self._markets_loaded = True
                logger.info(f"Binance Futures: {len(self.exchange.markets)} bozor yuklandi")
            except Exception as e:
                logger.error(f"load_markets xatosi: {e}")
                raise

    def check_pair(self, pair: str) -> bool:
        """Juftlik Binance Futures'da bormi tekshirish."""
        self.load_markets()
        return pair in self.exchange.markets

    def fetch_candles(self, pair: str, timeframe: str, limit: int = 100) -> List[Candle]:
        """
        Oxirgi `limit` ta yopilgan svechalarni oladi.
        Qaytadigan ro'yxat: eski → yangi tartibda.
        """
        try:
            # ccxt fetch_ohlcv: [[ts, open, high, low, close, volume], ...]
            raw = self.exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
        except ccxt.NetworkError as e:
            logger.warning(f"[{pair} {timeframe}] Network xatosi: {e}")
            return []
        except ccxt.ExchangeError as e:
            logger.error(f"[{pair} {timeframe}] Exchange xatosi: {e}")
            return []
        except Exception as e:
            logger.exception(f"[{pair} {timeframe}] fetch_ohlcv xatosi: {e}")
            return []

        candles: List[Candle] = []
        for row in raw:
            candles.append(Candle(
                timestamp_ms=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]) if row[5] is not None else 0.0,
            ))
        return candles

    def fetch_price(self, pair: str) -> Optional[float]:
        """Joriy narx (last trade price)."""
        try:
            ticker = self.exchange.fetch_ticker(pair)
            return float(ticker["last"])
        except Exception as e:
            logger.warning(f"[{pair}] fetch_ticker xatosi: {e}")
            return None

    def fetch_prices(self, pairs: List[str]) -> Dict[str, float]:
        """Bir necha juftlik uchun joriy narxlarni bir marotaba olish."""
        result: Dict[str, float] = {}
        try:
            tickers = self.exchange.fetch_tickers(pairs)
            for p, t in tickers.items():
                if t.get("last") is not None:
                    result[p] = float(t["last"])
        except Exception as e:
            logger.warning(f"fetch_tickers xatosi: {e} - individual fallback")
            # Fallback - bittalab
            for p in pairs:
                pr = self.fetch_price(p)
                if pr is not None:
                    result[p] = pr
                time.sleep(0.1)
        return result

    def get_price_precision(self, pair: str) -> int:
        """Narx uchun necha xona vergul kerakligini qaytaradi."""
        self.load_markets()
        try:
            m = self.exchange.markets[pair]
            p = m.get("precision", {}).get("price", 2)
            # ccxt precision: agar tick size ko'rinishida bo'lsa - qayta ishlash
            if isinstance(p, float) and p < 1:
                # tick size formatida (masalan 0.01) → xonalar sonini hisoblash
                s = f"{p:.10f}".rstrip("0")
                if "." in s:
                    return len(s.split(".")[1])
                return 0
            return int(p)
        except Exception:
            return 2

    def format_price(self, pair: str, price: float) -> str:
        """Narxni formatlab beradi (mos xonalar bilan)."""
        prec = self.get_price_precision(pair)
        return f"{price:,.{prec}f}"
