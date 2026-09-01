"""
Telegram getUpdates long-polling - foydalanuvchi komandalarini tinglaydi.
Alohida thread'da main loop bilan parallel ishlaydi.
"""
import logging
import threading
import time
from typing import Callable, Optional
import requests

logger = logging.getLogger(__name__)


class TelegramPoller:
    """
    Telegram Bot API getUpdates (long-polling) uchun background thread.

    Foydalanuvchi bot bilan shaxsiy chat orqali /command yuborsa,
    handler chaqiriladi va javob avtomatik yuboriladi.
    """

    def __init__(self, token: str, command_handler: Callable[[str, str], Optional[str]]):
        """
        Args:
            token: Telegram bot token
            command_handler: (chat_id, text) -> reply_text | None
        """
        self.token = token
        self.command_handler = command_handler
        self._thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()
        self._last_update_id = 0

    def start(self) -> None:
        """Background thread'ni ishga tushirish."""
        if self._thread and self._thread.is_alive():
            logger.warning("Poller allaqachon ishlayapti")
            return
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._loop, name="TgPoller",
                                        daemon=True)
        self._thread.start()
        logger.info("Telegram poller ishga tushdi")

    def stop(self) -> None:
        """Thread'ni to'xtatish (asosiy dastur yopilganda)."""
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        """Long-polling loop."""
        # Boshlanishda oxirgi update_id ni olish (eski xabarlarga javob bermaslik)
        self._skip_pending_updates()

        while not self._shutdown.is_set():
            try:
                updates = self._fetch_updates(timeout=25)
                for update in updates:
                    self._last_update_id = update.get("update_id", self._last_update_id)
                    self._handle_update(update)
            except Exception as e:
                logger.exception(f"Poller xatosi: {e}")
                time.sleep(5)

    def _skip_pending_updates(self) -> None:
        """Boshlanishda kutilib turgan xabarlarni o'tkazib yuborish."""
        try:
            url = f"https://api.telegram.org/bot{self.token}/getUpdates"
            r = requests.get(url, params={"offset": -1, "timeout": 0}, timeout=10)
            data = r.json()
            if data.get("ok") and data.get("result"):
                last = data["result"][-1]
                self._last_update_id = last.get("update_id", 0)
                logger.info(f"Poller: eski xabarlar o'tkazildi (last_id={self._last_update_id})")
        except Exception as e:
            logger.warning(f"skip_pending xatosi: {e}")

    def _fetch_updates(self, timeout: int = 25) -> list:
        """Yangi update'larni olish (long-poll)."""
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        params = {
            "offset": self._last_update_id + 1,
            "timeout": timeout,
            "allowed_updates": ["message"],  # faqat matn xabarlar
        }
        try:
            r = requests.get(url, params=params, timeout=timeout + 10)
            data = r.json()
            if not data.get("ok"):
                logger.warning(f"getUpdates javobi xato: {data}")
                return []
            return data.get("result", [])
        except requests.Timeout:
            return []
        except requests.RequestException as e:
            logger.warning(f"getUpdates network xatosi: {e}")
            time.sleep(3)
            return []

    def _handle_update(self, update: dict) -> None:
        """Bitta update'ni qayta ishlash."""
        msg = update.get("message")
        if not msg:
            return
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "")
        if not text or not chat_id:
            return

        logger.debug(f"Poller: xabar chat_id={chat_id}: {text[:50]}")

        # Komandani qayta ishlash
        try:
            reply = self.command_handler(str(chat_id), text)
        except Exception as e:
            logger.exception(f"Handler xatosi: {e}")
            reply = f"⚠️ Xato: {str(e)[:200]}"

        if reply is None:
            return  # Javob shart emas

        # Javobni yuborish
        self._send_reply(chat_id, reply)

    def _send_reply(self, chat_id, text: str) -> None:
        """Javobni orqaga yuborish."""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code != 200:
                logger.error(f"Reply yuborish xatosi {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            logger.warning(f"Reply network xatosi: {e}")
