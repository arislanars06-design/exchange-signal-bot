"""
Holatni JSON faylga saqlash va tiklash.
Bu bot qayta ishga tushirilganda ham setup'lar yo'qolmaydi.
"""
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from strategy import StrategyEngine

logger = logging.getLogger(__name__)


class StateManager:
    """Strategiya engine'ining holatini disk'ga saqlaydi/tiklaydi."""

    VERSION = 1

    def __init__(self, path: str):
        p = Path(path).expanduser()
        if not p.is_absolute():
            # Nisbiy yo'l: skriptning papkasiga nisbatan qaraymiz.
            # Bu foydalanuvchi qayerdan bot'ni ishga tushirsa ham
            # state.json bir joyda qoladi (deploy papkasida).
            script_dir = Path(__file__).parent.resolve()
            p = script_dir / p
        self.path = p.resolve()

    def load(self, engine: StrategyEngine) -> bool:
        """Fayl mavjud bo'lsa - engine'ga yuklaydi. True agar yuklandi."""
        if not self.path.exists():
            logger.info(f"State fayl topilmadi: {self.path} - yangi state")
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"State faylini o'qish xatosi: {e}")
            # Faylni backup qilamiz va yangidan boshlaymiz
            backup = self.path.with_suffix(".broken.json")
            try:
                self.path.rename(backup)
                logger.warning(f"Buzilgan state fayl backup: {backup}")
            except Exception:
                pass
            return False

        if data.get("version") != self.VERSION:
            logger.warning(f"State fayl versiyasi mos emas: "
                           f"{data.get('version')} vs {self.VERSION}")
            return False

        try:
            engine.load_state(data)
            logger.info(f"State yuklandi: {len(engine.setups)} setup, "
                        f"{len(engine.streaks)} streak, "
                        f"{len(engine.daily_stats)} daily stats")
            return True
        except Exception as e:
            logger.exception(f"State yuklash xatosi: {e}")
            return False

    def save(self, engine: StrategyEngine) -> bool:
        """Engine holatini atomik saqlaydi (tmp + rename)."""
        data = engine.dump_state()
        data["version"] = self.VERSION
        try:
            # Papkani yaratish (agar yo'q bo'lsa)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Vaqtinchalik faylga yozib, keyin rename - shu bilan atomik
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.path.parent),
                prefix=self.path.name + ".",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.path)
            except Exception:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
            return True
        except Exception as e:
            logger.exception(f"State saqlash xatosi: {e}")
            return False
