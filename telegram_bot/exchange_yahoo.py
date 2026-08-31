"""
Yahoo Finance data source (yfinance kutubxonasi orqali).

Ushbu manba forex (XAUUSD), stocks (NVDA, TSLA), ETF (DXYZ, ARKX),
indekslar (^GSPC) va futures (GC=F) narxlarini bepul beradi.

Cheklovlar:
  - 5m/15m ma'lumot faqat oxirgi 60 kun uchun mavjud
  - Stock narxlar 15 daqiqagacha kechikishi mumkin (Yahoo tomonidan)
  - Bozor yopiq vaqtida (weekend, holidays) yangi svecha yo'q
"""
import logging
import time
from typing import Dict, List, Optional

from models import Candle

logger = logging.getLogger(__name__)


class YahooFinance:
    """Yahoo Finance orqali forex/stocks/ETF ma'lumotlari."""

    # Foydalanuvchi tikeri → yfinance kanonik ticker
    # Muhim: Yahoo XAUUSD=X ni bloklagan (2025 dan boshlab), shuning uchun
    # GC=F (Gold Futures) - XAU/USD spot bilan ~99.5% mos keladi
    ALIASES = {
        # Metallar (futures - Yahoo spot forex'ni bloklagan)
        "XAUUSD": "GC=F",       # Gold futures - XAU/USD spot proxysi
        "XAGUSD": "SI=F",       # Silver futures
        "XPTUSD": "PL=F",       # Platinum futures
        "GOLD":   "GC=F",       # Gold futures
        "SILVER": "SI=F",       # Silver futures
        # ETF proxy (agar futures ishlamasa)
        "GLD":    "GLD",        # SPDR Gold ETF
        "IAU":    "IAU",        # iShares Gold Trust ETF
        # Neft
        "OIL":    "CL=F",       # WTI crude
        "WTI":    "CL=F",
        "BRENT":  "BZ=F",
        # Indekslar
        "SPX":    "^GSPC",      # S&P 500 index
        "SPX500": "^GSPC",
        "SP500":  "^GSPC",
        "NASDAQ": "^IXIC",
        "NAS100": "^IXIC",
        "DOW":    "^DJI",
        "US30":   "^DJI",
        "DXY":    "DX-Y.NYB",   # US Dollar Index
        "VIX":    "^VIX",       # Volatility Index
        # Kripto (Yahoo variantda)
        "BTC":    "BTC-USD",
        "ETH":    "ETH-USD",
    }

    # Timeframe → yfinance interval
    INTERVAL_MAP = {
        "1m":  "1m",
        "2m":  "2m",
        "5m":  "5m",
        "15m": "15m",
        "30m": "30m",
        "60m": "60m",
        "1h":  "60m",   # yfinance 60m
        "90m": "90m",
        "1d":  "1d",
    }

    # Timeframe → yfinance period (maksimum tarixiy oralik)
    PERIOD_MAP = {
        "1m":  "7d",
        "2m":  "60d",
        "5m":  "60d",
        "15m": "60d",
        "30m": "60d",
        "60m": "730d",
        "1h":  "730d",
        "90m": "60d",
        "1d":  "max",
    }

    def __init__(self):
        self._precision_cache: Dict[str, int] = {}
        # Lazy import - yfinance sekin yuklanadi
        self._yf = None

    def _yf_lib(self):
        if self._yf is None:
            import yfinance
            self._yf = yfinance
        return self._yf

    def normalize(self, symbol: str) -> str:
        """Foydalanuvchi tikeri → yfinance kanonik format."""
        return self.ALIASES.get(symbol.upper(), symbol)

    def load_markets(self) -> None:
        """Yahoo'da bozorlar ro'yxati yo'q - no-op."""
        logger.info("Yahoo Finance: markets endpoint yo'q - lazy check ishlatiladi")

    def check_pair(self, symbol: str) -> bool:
        """Ticker mavjudmi tekshirish (1 kunlik ma'lumot olib)."""
        ticker = self.normalize(symbol)
        try:
            yf = self._yf_lib()
            t = yf.Ticker(ticker)
            # 5 kunlik 1d interval - hafta oxiri ham ishlaydi
            df = t.history(period="5d", interval="1d")
            if df.empty:
                logger.warning(f"[{symbol}] Yahoo: ma'lumot topilmadi ({ticker})")
                return False
            return True
        except Exception as e:
            logger.warning(f"[{symbol}] Yahoo check xatosi: {e}")
            return False

    def fetch_candles(self, symbol: str, timeframe: str,
                      limit: int = 100) -> List[Candle]:
        """Yopilgan svechalarni oladi - eski → yangi tartibda."""
        interval = self.INTERVAL_MAP.get(timeframe)
        if interval is None:
            logger.error(f"[{symbol}] Yahoo: timeframe qo'llab-quvvatlanmaydi: {timeframe}")
            return []

        period = self.PERIOD_MAP.get(timeframe, "60d")
        ticker = self.normalize(symbol)

        try:
            yf = self._yf_lib()
            t = yf.Ticker(ticker)
            df = t.history(period=period, interval=interval, prepost=False,
                          auto_adjust=False, back_adjust=False)
        except Exception as e:
            logger.warning(f"[{symbol}] Yahoo fetch_candles xatosi: {e}")
            return []

        if df.empty:
            logger.debug(f"[{symbol} {timeframe}] Yahoo: bo'sh natija "
                        f"(bozor yopiq bo'lishi mumkin)")
            return []

        candles: List[Candle] = []
        for idx, row in df.iterrows():
            # Timestamp'ni UTC ms ga aylantirish
            try:
                if idx.tz is None:
                    ts = idx.tz_localize("UTC")
                else:
                    ts = idx.tz_convert("UTC")
                ts_ms = int(ts.timestamp() * 1000)
            except Exception:
                continue

            try:
                o = float(row["Open"])
                h = float(row["High"])
                l = float(row["Low"])
                c = float(row["Close"])
                v_raw = row.get("Volume", 0)
                v = float(v_raw) if v_raw is not None else 0.0
            except (ValueError, KeyError, TypeError):
                continue

            # NaN tekshiruvi
            if any(x != x for x in (o, h, l, c)):
                continue
            # 0 narx tekshiruvi (yahoo ba'zan 0 qaytaradi)
            if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                continue

            candles.append(Candle(ts_ms, o, h, l, c, v))

        # Oxirgi `limit` ta
        return candles[-limit:] if len(candles) > limit else candles

    def fetch_price(self, symbol: str) -> Optional[float]:
        """Joriy narx (last close)."""
        ticker = self.normalize(symbol)
        try:
            yf = self._yf_lib()
            t = yf.Ticker(ticker)
            # fast_info - yangi ma'lumot beradi
            try:
                fi = t.fast_info
                price = fi["last_price"] if hasattr(fi, "__getitem__") else None
                if price is not None and price > 0:
                    return float(price)
            except (KeyError, AttributeError, Exception):
                pass

            # Fallback: oxirgi 1d 1m candle close
            df = t.history(period="1d", interval="1m")
            if not df.empty:
                last = df["Close"].iloc[-1]
                if last is not None and last > 0:
                    return float(last)
        except Exception as e:
            logger.warning(f"[{symbol}] Yahoo fetch_price xatosi: {e}")
        return None

    def fetch_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Bir necha ticker uchun narxlar."""
        result: Dict[str, float] = {}
        for s in symbols:
            p = self.fetch_price(s)
            if p is not None:
                result[s] = p
            # yfinance'ni ortiqcha yuklamaslik
            time.sleep(0.15)
        return result

    def get_price_precision(self, symbol: str) -> int:
        """Narx uchun xonalar soni (cache bilan)."""
        if symbol in self._precision_cache:
            return self._precision_cache[symbol]
        price = self.fetch_price(symbol)
        if price is None or price <= 0:
            prec = 2
        elif price >= 1000:
            prec = 2
        elif price >= 10:
            prec = 3
        elif price >= 1:
            prec = 4
        else:
            prec = 5
        self._precision_cache[symbol] = prec
        return prec

    def format_price(self, symbol: str, price: float) -> str:
        prec = self.get_price_precision(symbol)
        return f"{price:,.{prec}f}"
