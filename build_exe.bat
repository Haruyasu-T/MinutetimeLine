@echo off
REM タイムラインタイマーを単体 .exe にビルドするスクリプト（Windows用）
REM 事前準備:  pip install -r requirements.txt pyinstaller
REM 実行後、dist\TimelineTimer.exe が生成されます。

pyinstaller --noconfirm --onefile --windowed ^
  --name MinutetimeLine ^
  --icon timer.ico ^
  --version-file version_info.txt ^
  --add-data "timer.ico;." ^
  --add-data "defaults/timer_settings.json;." ^
  --add-data "defaults/timer_presets.json;." ^
  --collect-data customtkinter ^
  timer.py

echo.
echo ビルド完了: dist\MinutetimeLine.exe
pause
