"""
SERIYA Bot - asosiy entrypoint.

Loop mantiqi:
  1. Har `poll_interval` soniyada:
     a) Har bir (pair, timeframe) uchun:
        - Oxirgi yopilgan svechalarni olamiz
        - Yangi svecha bo'lsa - process_closed_candle chaqiramiz
     b) Bir marotaba barcha juftliklar uchun joriy narxlarni olamiz
     c) Har bir aktiv setup uchun check_live_price chaqiramiz
  2. Har bir event - Telegram'ga yuboriladi
  3. State har `poll_interval` da diskga saqlanadi
"""
import logging
import signal
import sys
import time
from typing import Dict, List, Optional

from config import config
from exchange import BinanceFutures
from strategy import StrategyEngine
from telegram_bot import TelegramNotifier
from state import StateManager
from models import Event, Status, Candle


# ==============================
# LOGGING
# ==============================
logging.basicConfig(
    level=config.log_level,
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


# ==============================
# GRACEFUL SHUTDOWN
# ==============================
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info(f"Signal {signum} qabul qilindi - to'xtatilmoqda...")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ==============================
# ASOSIY
# ==============================

def warmup(
    engine: StrategyEngine,
    exchange: BinanceFutures,
    config,
) -> None:
    """
    Cold start (bo'sh state) uchun tarixiy svechalarni jimgina qayta ishlab,
    streak holatini qurish. Bu spam'ning oldini oladi:
    Bot yoqilganda tarixiy setuplar Telegram'ga yuborilmaydi -
    faqat KELAJAKDAGI yangi setuplar alert qiladi.
    """
    if engine.streaks:
        logger.info("Warmup o'tkazilmadi - state fayldan yuklandi")
        return

    logger.info("Warmup boshlandi - tarixiy svechalar (silent, no alerts)...")
    total = 0
    now_ms = int(time.time() * 1000)

    for pair in config.pairs:
        for tf in config.timeframes:
            try:
                candles = exchange.fetch_candles(pair, tf, limit=100)
            except Exception as e:
                logger.warning(f"[{pair} {tf}] warmup fetch xatosi: {e}")
                continue
            tf_ms = _timeframe_to_ms(tf)
            for c in candles:
                # Faqat to'liq yopilgan svechalar
                if c.timestamp_ms + tf_ms <= now_ms:
                    engine.process_closed_candle_silent(pair, tf, c)
                    total += 1
            logger.debug(f"[{pair} {tf}] warmup: {len(candles)} sv")

    logger.info(f"Warmup tugadi: {total} tarixiy svecha ishlandi, "
                f"{len(engine.streaks)} streak state qurildi. "
                f"Endi faqat YANGI setuplar alert qiladi.")


def process_pair_timeframe(
    engine: StrategyEngine,
    exchange: BinanceFutures,
    pair: str,
    timeframe: str,
) -> List[Event]:
    """
    Bir (pair, tf) uchun yangi yopilgan svechalarni qayta ishlaydi.
    """
    events: List[Event] = []
    # Oxirgi 100 svecha (streak tracking uchun yetarli)
    candles = exchange.fetch_candles(pair, timeframe, limit=100)
    if not candles:
        return events

    streak = engine.get_or_create_streak(pair, timeframe)

    # ccxt: oxirgi candle "yopilmagan" bo'lishi mumkin (joriy interval)
    # Uni chiqarib tashlaymiz - faqat yopilganlarni qayta ishlaymiz
    now_ms = int(time.time() * 1000)
    tf_ms = _timeframe_to_ms(timeframe)

    processed: List[Candle] = []
    for c in candles:
        # Svecha to'liq yopilganmi tekshirish
        if c.timestamp_ms + tf_ms <= now_ms:
            processed.append(c)

    # Yangi svechalarni qayta ishlash (streak.last_processed_ms dan yangi)
    new_candles = [c for c in processed if c.timestamp_ms > streak.last_processed_ms]
    if not new_candles:
        return events

    logger.debug(f"[{pair} {timeframe}] {len(new_candles)} yangi svecha")
    for candle in new_candles:
        evs = engine.process_closed_candle(pair, timeframe, candle)
        events.extend(evs)

    return events


def _timeframe_to_ms(tf: str) -> int:
    """'15m' → 900_000 ms."""
    unit = tf[-1]
    n = int(tf[:-1])
    if unit == "m":
        return n * 60 * 1000
    if unit == "h":
        return n * 60 * 60 * 1000
    if unit == "d":
        return n * 24 * 60 * 60 * 1000
    if unit == "s":
        return n * 1000
    raise ValueError(f"Noma'lum timeframe: {tf}")


def main() -> int:
    # Sozlamalarni tekshirish
    try:
        config.validate()
    except ValueError as e:
        logger.error(str(e))
        return 1

    logger.info("=" * 60)
    logger.info("SERIYA BOT ishga tushmoqda")
    logger.info(f"  Juftliklar: {config.pairs}")
    logger.info(f"  Timeframes: {config.timeframes}")
    logger.info(f"  Min svechalar: {config.min_candles}")
    logger.info(f"  Risk: ${config.risk_usd}")
    logger.info(f"  Break-Even: {config.enable_be}")
    logger.info(f"  Poll interval: {config.poll_interval}s")
    logger.info("=" * 60)

    # Komponentlarni init qilish
    exchange = BinanceFutures(
        api_key=config.binance_api_key,
        api_secret=config.binance_api_secret,
    )
    try:
        exchange.load_markets()
    except Exception as e:
        logger.error(f"Binance'ga ulanib bo'lmadi: {e}")
        return 1

    # Juftliklarni tekshirish
    invalid = [p for p in config.pairs if not exchange.check_pair(p)]
    if invalid:
        logger.error(f"Bu juftliklar Binance Futures'da topilmadi: {invalid}")
        return 1

    engine = StrategyEngine(config)
    notifier = TelegramNotifier(config, price_formatter=exchange.format_price)
    state_mgr = StateManager(config.state_file)

    # Eski holatni yuklash
    state_mgr.load(engine)

    # SILENT WARMUP - agar cold start bo'lsa, tarixiy svechalarni jimgina
    # ishlash. Bu Telegram spam'ning oldini oladi.
    try:
        warmup(engine, exchange, config)
    except Exception as e:
        logger.warning(f"Warmup xatosi (davom etamiz): {e}")

    # Startup xabari
    notifier.send_startup(config.pairs, config.timeframes, config.min_candles)

    logger.info("Loop boshlandi...")

    last_save = 0
    save_every_s = 60  # har daqiqada bir marta state saqlash

    while not _shutdown:
        iter_start = time.time()

        try:
            # ========= 1) Yopilgan svechalarni qayta ishlash =========
            for pair in config.pairs:
                for tf in config.timeframes:
                    if _shutdown:
                        break
                    try:
                        events = process_pair_timeframe(engine, exchange, pair, tf)
                        for ev in events:
                            notifier.notify_event(ev)
                    except Exception as e:
                        logger.exception(f"[{pair} {tf}] process xatosi: {e}")

            # ========= 2) Live narxlar bilan tekshirish =========
            if not _shutdown:
                try:
                    prices = exchange.fetch_prices(config.pairs)
                    now_ms = int(time.time() * 1000)
                    for pair, current_price in prices.items():
                        for tf in config.timeframes:
                            live_events = engine.check_live_price(
                                pair, tf, current_price, now_ms
                            )
                            for ev in live_events:
                                notifier.notify_event(ev)
                except Exception as e:
                    logger.exception(f"Live price tekshirish xatosi: {e}")

            # ========= 3) Cleanup + save =========
            engine.cleanup_closed(keep_last=200)

            now = time.time()
            if now - last_save > save_every_s:
                if state_mgr.save(engine):
                    last_save = now
                    logger.debug("State saqlandi")

        except Exception as e:
            logger.exception(f"Loop iteratsiya xatosi: {e}")
            try:
                notifier.send_error(str(e))
            except Exception:
                pass

        # Sleep - lekin shutdown signalini tez sezish uchun kichik qadamlar
        elapsed = time.time() - iter_start
        remaining = max(0.0, config.poll_interval - elapsed)
        end_time = time.time() + remaining
        while time.time() < end_time and not _shutdown:
            time.sleep(min(1.0, end_time - time.time()))

    # ========= SHUTDOWN =========
    logger.info("Shutdown - state saqlanmoqda...")
    state_mgr.save(engine)
    try:
        notifier.send_shutdown()
    except Exception:
        pass
    logger.info("SERIYA Bot to'xtatildi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
