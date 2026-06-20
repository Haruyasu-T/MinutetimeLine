@echo off
REM タイムラインタイマーを単体 .exe にビルドするスクリプト（Windows用）
REM 事前準備:  pip install -r requirements.txt pyinstaller
REM 実行後、dist\TimelineTimer.exe が生成されます。

pyinstaller --noconfirm --onefile --windowed ^
  --name TimelineTimer ^
  --icon timer.ico ^
  --add-data "timer.ico;." ^
  --collect-data customtkinter ^
  timer.py

echo.
echo ビルド完了: dist\TimelineTimer.exe
pause
