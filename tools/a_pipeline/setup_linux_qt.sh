#!/usr/bin/env bash
set -euo pipefail
taskRoot="$HOME/.local/share/afh03-a-pipeline"
python3 -m venv "$taskRoot/venv"
"$taskRoot/venv/bin/python" -m pip install --disable-pip-version-check 'aqtinstall==3.3.0' 'numpy==2.5.3' 'psutil==7.2.2' 'pillow==12.3.0'
"$taskRoot/venv/bin/python" -m aqt install-qt linux desktop 6.8.3 linux_gcc_64 -O "$taskRoot/qt" --archives qtbase qttools icu
