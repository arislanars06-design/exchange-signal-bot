#!/usr/bin/env bash
#
# SERIYA Bot - VPS o'rnatish skripti (Ubuntu/Debian).
# Root sifatida ishga tushiring: sudo bash install.sh
#
set -euo pipefail

INSTALL_DIR="/opt/seriya-bot"
SERVICE_USER="seriya"
SERVICE_NAME="seriya-bot"
REPO_SOURCE=""  # ixtiyoriy: git URL. Bo'sh bo'lsa - joriy papka ishlatiladi

echo "======================================"
echo "SERIYA Bot - VPS O'rnatish"
echo "======================================"

# Root tekshiruv
if [[ $EUID -ne 0 ]]; then
    echo "Xato: root sifatida ishga tushiring (sudo bash install.sh)"
    exit 1
fi

# 1) Tizimni yangilash + python o'rnatish
echo ""
echo "[1/6] Python va kerakli paketlar o'rnatilmoqda..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git

# 2) Foydalanuvchi yaratish
echo ""
echo "[2/6] Xizmat foydalanuvchisi yaratilmoqda..."
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" \
            --create-home "$SERVICE_USER"
    echo "   ✓ Foydalanuvchi '$SERVICE_USER' yaratildi"
else
    echo "   ✓ Foydalanuvchi '$SERVICE_USER' allaqachon mavjud"
fi

# 3) Kod faylini nusxalash
echo ""
echo "[3/6] Kod nusxalanmoqda..."
mkdir -p "$INSTALL_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# .env faylini himoya qilish - eskisini qayta yozmaslik
for f in main.py config.py exchange.py strategy.py telegram_bot.py state.py models.py requirements.txt; do
    if [[ -f "$SCRIPT_DIR/$f" ]]; then
        cp "$SCRIPT_DIR/$f" "$INSTALL_DIR/$f"
    fi
done

# .env.example ni nusxalash
if [[ -f "$SCRIPT_DIR/.env.example" ]]; then
    cp "$SCRIPT_DIR/.env.example" "$INSTALL_DIR/.env.example"
fi

# Agar .env bo'lmasa - .env.example dan yaratish
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    if [[ -f "$INSTALL_DIR/.env.example" ]]; then
        cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
        echo "   ⚠️  .env yaratildi (.env.example dan) - uni tahrirlashni unutmang!"
    fi
fi

# 4) Virtualenv + pip install
echo ""
echo "[4/6] Python virtualenv yaratilmoqda..."
if [[ ! -d "$INSTALL_DIR/venv" ]]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

# 5) Ruxsatlar
echo ""
echo "[5/6] Ruxsatlar sozlanmoqda..."
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/.env" 2>/dev/null || true

# 6) systemd service o'rnatish
echo ""
echo "[6/6] Systemd service o'rnatilmoqda..."
cp "$SCRIPT_DIR/deploy/$SERVICE_NAME.service" "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload

echo ""
echo "======================================"
echo "✅ O'rnatish yakunlandi!"
echo "======================================"
echo ""
echo "Keyingi qadamlar:"
echo ""
echo "  1. .env faylni tahrirlang:"
echo "       sudo nano $INSTALL_DIR/.env"
echo ""
echo "  2. Botni ishga tushiring:"
echo "       sudo systemctl enable --now $SERVICE_NAME"
echo ""
echo "  3. Loglarni ko'rish:"
echo "       sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "  4. To'xtatish:"
echo "       sudo systemctl stop $SERVICE_NAME"
echo ""
echo "  5. Qayta ishga tushirish (o'zgarishlardan keyin):"
echo "       sudo systemctl restart $SERVICE_NAME"
echo ""
