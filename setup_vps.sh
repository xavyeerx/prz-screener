#!/bin/bash
# PRZ Scanner - VPS Setup Script
# ================================
# Tested on: Ubuntu 20.04/22.04, Debian 11/12
# Jalankan: bash setup_vps.sh
#
# Script ini akan:
#   1. Install system dependencies (python3, pip, git)
#   2. Clone / update repo
#   3. Install Python dependencies
#   4. Setup .env dari .env.example
#   5. Set timezone ke WIB (Asia/Jakarta)
#   6. Buat folder logs/ dan output/
#   7. Tampilkan cara setup cron / scheduler

set -e

echo "========================================"
echo "  PRZ Scanner - VPS Setup"
echo "========================================"

# 1. System dependencies
echo "[1/7] Install system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv git libfreetype6-dev

# 2. Clone or update repo
REPO_DIR=~/prz-screener
if [ -d "$REPO_DIR/.git" ]; then
    echo "[2/7] Repo sudah ada, pull latest..."
    cd "$REPO_DIR" && git pull origin main
else
    echo "[2/7] Clone repo..."
    git clone https://github.com/xavyeerx/prz-screener.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

cd "$REPO_DIR"

# 3. Python venv + dependencies
echo "[3/7] Setup Python virtualenv & install dependencies..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "      Dependencies installed."

# 4. .env setup
echo "[4/7] Setup .env..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "      File .env dibuat dari .env.example."
    echo "      EDIT .env sekarang: nano .env"
else
    echo "      .env sudah ada, skip."
fi

# 5. Timezone
echo "[5/7] Set timezone ke Asia/Jakarta (WIB)..."
sudo timedatectl set-timezone Asia/Jakarta
echo "      Timezone: $(timedatectl | grep 'Time zone' | awk '{print $3}')"

# 6. Folder setup
echo "[6/7] Buat folder logs/ dan output/..."
mkdir -p logs output/daily output/weekly output/h4

# 7. Instruksi selanjutnya
echo ""
echo "[7/7] Setup selesai!"
echo ""
echo "========================================"
echo "  LANGKAH SELANJUTNYA:"
echo "========================================"
echo ""
echo "  1. Edit .env (isi bot token & chat ID):"
echo "     nano .env"
echo ""
echo "  OPTION A — Python scheduler (recommended):"
echo "     source venv/bin/activate"
echo "     screen -S prz"
echo "     python scheduler.py"
echo "     Ctrl+A, D  (detach)"
echo ""
echo "  OPTION B — Cron:"
echo "     crontab -e"
echo "     (tambahkan isi dari crontab.example)"
echo "     Ganti 'python3' dengan: ~/prz-screener/venv/bin/python"
echo ""
echo "  Test manual:"
echo "     source venv/bin/activate"
echo "     python run_daily.py --tickers BBCA BMRI --telegram --images-only"
echo ""
