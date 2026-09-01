"""
Telegram getUpdates long-polling - foydalanuvchi komandalari va
inline tugma bosishlarini tinglaydi.
"""
import logging
import threading
import time
from typing import Callable, Optional
import requests

logger = logging.getLogger(__name__)


class TelegramPoller:
    """
    Message va callback_query yangilanishlarini olib, handler'lariga uzatadi.

    Handler qaytishi mumkin:
      - None: hech qanday javob yubormaslik
      - str: oddiy matn (HTML)
      - (text, reply_markup): matn + keyboard
    """

    def __init__(self, token: str,
                 command_handler: Callable[[str, str], object],
                 callback_handler: Optional[Callable[[str, str], object]] = None):
        self.token = token
        self.command_handler = command_handler
        self.callback_handler = callback_handler
        self._thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()
        self._last_update_id = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("Poller allaqachon ishlayapti")
            return
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._loop, name="TgPoller",
                                        daemon=True)
        self._thread.start()
        logger.info("Telegram poller ishga tushdi")

    def stop(self) -> None:
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        self._skip_pending_updates()
        while not self._shutdown.is_set():
            try:
                updates = self._fetch_updates(timeout=25)
                for update in updates:
                    self._last_update_id = update.get("update_id",
                                                     self._last_update_id)
                    self._handle_update(update)
            except Exception as e:
                logger.exception(f"Poller xatosi: {e}")
                time.sleep(5)

    def _skip_pending_updates(self) -> None:
        try:
            url = f"https://api.telegram.org/bot{self.token}/getUpdates"
            r = requests.get(url, params={"offset": -1, "timeout": 0},
                             timeout=10)
            data = r.json()
            if data.get("ok") and data.get("result"):
                last = data["result"][-1]
                self._last_update_id = last.get("update_id", 0)
                logger.info(f"Poller: eski xabarlar o'tkazildi "
                           f"(last_id={self._last_update_id})")
        except Exception as e:
            logger.warning(f"skip_pending xatosi: {e}")

    def _fetch_updates(self, timeout: int = 25) -> list:
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        params = {
            "offset": self._last_update_id + 1,
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
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
        if "message" in update:
            self._handle_message(update["message"])
        elif "callback_query" in update:
            self._handle_callback(update["callback_query"])

    def _handle_message(self, msg: dict) -> None:
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "")
        if not text or not chat_id:
            return
        logger.debug(f"Message chat_id={chat_id}: {text[:50]}")

        try:
            reply = self.command_handler(str(chat_id), text)
        except Exception as e:
            logger.exception(f"Handler xatosi: {e}")
            reply = f"⚠️ Xato: {str(e)[:200]}"

        if reply is None:
            return
        self._send_reply(chat_id, reply)

    def _handle_callback(self, cb: dict) -> None:
        cb_id = cb.get("id")
        chat_id = cb.get("message", {}).get("chat", {}).get("id")
        msg_id = cb.get("message", {}).get("message_id")
        data = cb.get("data", "")

        # Loading spinner ni yopish
        self._answer_callback(cb_id)

        if not self.callback_handler:
            return
        try:
            reply = self.callback_handler(str(chat_id), data)
        except Exception as e:
            logger.exception(f"Callback handler xatosi: {e}")
            reply = f"⚠️ Xato: {str(e)[:200]}"

        if reply is None:
            return

        # Callback natijasi: yangilangan xabar yoki alohida javob
        text, markup = self._normalize_reply(reply)

        # Xabarni edit qilish (agar mavjud)
        if msg_id and text:
            self._edit_message(chat_id, msg_id, text, markup)
        elif text:
            self._send_reply(chat_id, reply)

    def _answer_callback(self, cb_id: str) -> None:
        """Loading indikatorni yopish."""
        try:
            url = f"https://api.telegram.org/bot{self.token}/answerCallbackQuery"
            requests.post(url, json={"callback_query_id": cb_id}, timeout=5)
        except Exception as e:
            logger.debug(f"answerCallback xatosi: {e}")

    def _normalize_reply(self, reply):
        """Reply → (text, reply_markup) tuple ga aylantirish."""
        if isinstance(reply, tuple):
            return reply[0], reply[1] if len(reply) > 1 else None
        return reply, None

    def _send_reply(self, chat_id, reply) -> None:
        text, markup = self._normalize_reply(reply)
        if not text:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if markup:
            payload["reply_markup"] = markup
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code != 200:
                logger.error(f"Reply yuborish xatosi {r.status_code}: "
                            f"{r.text[:200]}")
        except requests.RequestException as e:
            logger.warning(f"Reply network xatosi: {e}")

    def _edit_message(self, chat_id, msg_id, text: str,
                      reply_markup: Optional[dict] = None) -> None:
        """Mavjud xabarni yangilash."""
        url = f"https://api.telegram.org/bot{self.token}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code != 200:
                # Ba'zan xabar allaqachon shu holatda bo'ladi - OK
                if "message is not modified" in r.text.lower():
                    return
                logger.error(f"Edit xatosi {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            logger.warning(f"Edit network xatosi: {e}")
