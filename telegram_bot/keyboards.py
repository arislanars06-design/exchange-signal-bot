"""
Telegram Reply Keyboards va Inline Keyboards.

Reply keyboard yozish paneli o'rniga ko'rinib turadi va tapishda
tegishli komanda ishga tushiriladi.
"""

# ==================================================================
# ASOSIY MENU (Reply Keyboard - doim ko'rinadi)
# ==================================================================

MAIN_MENU = {
    "keyboard": [
        [{"text": "📊 Statistika"}],
        [{"text": "🎯 Aktiv setups"}],
        [{"text": "⚙️ Sozlamalar"}],
        [{"text": "⏸ Pause"}, {"text": "▶️ Resume"}],
        [{"text": "📈 Status"}, {"text": "ℹ️ Yordam"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
    "input_field_placeholder": "Menyudan tanlang yoki /komanda yozing...",
}

# Menyu tugmasi → komanda mapping
BUTTON_TO_COMMAND = {
    "📊 Statistika": "__stats_wizard__",       # instrument+davr wizard
    "🎯 Aktiv setups": "/setups active",
    "⚙️ Sozlamalar": "__settings_menu__",
    "⏸ Pause": "/pause",
    "▶️ Resume": "/resume",
    "📈 Status": "/status",
    "ℹ️ Yordam": "/help",
}


# ==================================================================
# STATISTIKA WIZARD KEYBOARDS
# ==================================================================

def stats_pairs_kb(all_pairs, selected_set) -> dict:
    """Instrument tanlash uchun checkbox-style inline keyboard."""
    rows = []
    # Har bir juftlik uchun bitta qator (checkbox bilan)
    for i, p in enumerate(all_pairs):
        check = "✅" if p in selected_set else "⬜"
        rows.append([{
            "text": f"{check} {p}",
            "callback_data": f"sw|pair|{i}"
        }])
    # "HAMMASI" tugmasi
    all_selected = len(selected_set) == len(all_pairs) and len(all_pairs) > 0
    check_all = "✅" if all_selected else "⬜"
    rows.append([{
        "text": f"{check_all} HAMMASI",
        "callback_data": "sw|all"
    }])
    # Boshqaruv tugmalari
    rows.append([
        {"text": "▶️ Davom", "callback_data": "sw|next"},
        {"text": "❌ Bekor", "callback_data": "sw|cancel"},
    ])
    return {"inline_keyboard": rows}


def stats_period_kb() -> dict:
    """Davr tanlash uchun inline keyboard."""
    return {
        "inline_keyboard": [
            [
                {"text": "📅 Bugun", "callback_data": "sw|period|today"},
                {"text": "📅 Kecha", "callback_data": "sw|period|yesterday"},
            ],
            [
                {"text": "📅 Hafta", "callback_data": "sw|period|week"},
                {"text": "📅 Oy", "callback_data": "sw|period|month"},
            ],
            [
                {"text": "📅 Barcha vaqt", "callback_data": "sw|period|all"},
            ],
            [
                {"text": "📆 Sana: dan-gacha", "callback_data": "sw|period|custom"},
            ],
            [
                {"text": "◀️ Orqaga", "callback_data": "sw|back"},
                {"text": "❌ Bekor", "callback_data": "sw|cancel"},
            ],
        ]
    }


def stats_result_kb() -> dict:
    """Statistika ko'rsatilgandan keyingi tugmalar."""
    return {
        "inline_keyboard": [
            [{"text": "🔄 Yangi statistika", "callback_data": "sw|restart"}],
            [{"text": "❌ Yopish", "callback_data": "close"}],
        ]
    }


# ==================================================================
# SOZLAMALAR MENU (Inline Keyboard)
# ==================================================================

def settings_menu_kb(config) -> dict:
    """Sozlamalar menyusi - hozirgi qiymatlar bilan."""
    return {
        "inline_keyboard": [
            [
                {"text": f"💰 Risk: ${config.risk_usd:.2f}",
                 "callback_data": "settings:risk"},
                {"text": f"📈 Min: {config.min_candles}",
                 "callback_data": "settings:min"},
            ],
            [
                {"text": f"🔵 BE: {'ON' if config.enable_be else 'OFF'}",
                 "callback_data": "settings:be"},
                {"text": f"🔴 SL buf: {config.sl_buffer_pct:.3f}%",
                 "callback_data": "settings:sl_buffer"},
            ],
            [
                {"text": f"🟢 TP1: {config.tp1_pct:.0f}%",
                 "callback_data": "settings:tp1"},
                {"text": f"🟢 TP2: {config.tp2_pct:.0f}%",
                 "callback_data": "settings:tp2"},
                {"text": f"🟢 TP3: {config.tp3_pct:.0f}%",
                 "callback_data": "settings:tp3"},
            ],
            [
                {"text": f"📐 Fib SL: {config.fib_sl}",
                 "callback_data": "settings:fib_sl"},
                {"text": f"📐 Fib TP: {config.fib_tp1}/{config.fib_tp2}/{config.fib_tp3}",
                 "callback_data": "settings:fib_tps"},
            ],
            [{"text": "❌ Yopish", "callback_data": "settings:close"}],
        ]
    }


# ==================================================================
# PRESET VALUES (Inline Keyboards)
# ==================================================================

def risk_preset_kb() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "$1", "callback_data": "set:risk:1"},
                {"text": "$3", "callback_data": "set:risk:3"},
                {"text": "$5", "callback_data": "set:risk:5"},
            ],
            [
                {"text": "$10", "callback_data": "set:risk:10"},
                {"text": "$25", "callback_data": "set:risk:25"},
                {"text": "$50", "callback_data": "set:risk:50"},
            ],
            [
                {"text": "$100", "callback_data": "set:risk:100"},
                {"text": "$250", "callback_data": "set:risk:250"},
                {"text": "$500", "callback_data": "set:risk:500"},
            ],
            [
                {"text": "✏️ Boshqa qiymat (yozib kiriting)",
                 "callback_data": "input:risk"},
            ],
            [{"text": "◀️ Orqaga", "callback_data": "settings:menu"}],
        ]
    }


def min_preset_kb() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "2", "callback_data": "set:min:2"},
                {"text": "3", "callback_data": "set:min:3"},
                {"text": "4", "callback_data": "set:min:4"},
                {"text": "5", "callback_data": "set:min:5"},
            ],
            [
                {"text": "6", "callback_data": "set:min:6"},
                {"text": "7", "callback_data": "set:min:7"},
                {"text": "8", "callback_data": "set:min:8"},
                {"text": "10", "callback_data": "set:min:10"},
            ],
            [{"text": "◀️ Orqaga", "callback_data": "settings:menu"}],
        ]
    }


def be_toggle_kb(current: bool) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ YOQILGAN" if current else "🔘 YOQMOQ",
                 "callback_data": "set:be:on"},
                {"text": "🔘 O'CHIRMOQ" if current else "❌ O'CHIRILGAN",
                 "callback_data": "set:be:off"},
            ],
            [{"text": "◀️ Orqaga", "callback_data": "settings:menu"}],
        ]
    }


def sl_buffer_preset_kb() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "0%", "callback_data": "set:sl_buffer:0"},
                {"text": "0.01%", "callback_data": "set:sl_buffer:0.01"},
                {"text": "0.02%", "callback_data": "set:sl_buffer:0.02"},
            ],
            [
                {"text": "0.05%", "callback_data": "set:sl_buffer:0.05"},
                {"text": "0.10%", "callback_data": "set:sl_buffer:0.1"},
                {"text": "0.25%", "callback_data": "set:sl_buffer:0.25"},
            ],
            [
                {"text": "✏️ Boshqa qiymat",
                 "callback_data": "input:sl_buffer"},
            ],
            [{"text": "◀️ Orqaga", "callback_data": "settings:menu"}],
        ]
    }


def tp_presets_kb() -> dict:
    """TP partial foizlari uchun tayyor variantlar."""
    return {
        "inline_keyboard": [
            [{"text": "50 / 25 / 25 (default)",
              "callback_data": "set:tp:50,25,25"}],
            [{"text": "40 / 30 / 30",
              "callback_data": "set:tp:40,30,30"}],
            [{"text": "33 / 33 / 34",
              "callback_data": "set:tp:33,33,34"}],
            [{"text": "60 / 20 / 20",
              "callback_data": "set:tp:60,20,20"}],
            [{"text": "70 / 20 / 10",
              "callback_data": "set:tp:70,20,10"}],
            [{"text": "100 / 0 / 0 (faqat TP1)",
              "callback_data": "set:tp:100,0,0"}],
            [{"text": "◀️ Orqaga", "callback_data": "settings:menu"}],
        ]
    }


def stats_period_kb() -> dict:
    """Stats davri tanlash uchun."""
    return {
        "inline_keyboard": [
            [
                {"text": "📅 Bugun", "callback_data": "stats:today"},
                {"text": "📅 Kecha", "callback_data": "stats:yesterday"},
            ],
            [
                {"text": "📅 Hafta", "callback_data": "stats:week"},
                {"text": "📅 Oy", "callback_data": "stats:month"},
            ],
            [{"text": "📅 Barcha vaqt", "callback_data": "stats:all"}],
            [{"text": "❌ Yopish", "callback_data": "close"}],
        ]
    }


def close_kb() -> dict:
    """Faqat yopish tugmasi."""
    return {
        "inline_keyboard": [
            [{"text": "❌ Yopish", "callback_data": "close"}],
        ]
    }


# ==================================================================
# REMOVE KEYBOARD (yopish uchun)
# ==================================================================

REMOVE_KEYBOARD = {
    "remove_keyboard": True,
}
