@echo off
echo ========================================================
echo  ThermoHygro Offline Sensor (F) - Native Android APK
echo ========================================================

where adb >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
  echo [!] Error: adb not found in PATH.
  exit /b 1
)

echo [1/3] Waiting for connected physical Android phone...
adb wait-for-device
adb devices -l

echo [2/3] Installing signed native Android APK (ThermoHygro-Offline.apk)...
adb install -r ThermoHygro-Offline.apk

echo [3/3] Launching native Android app on phone...
adb shell am start -n com.thermohygro.offlinesensor/.MainActivity
echo [OK] Native Android app ThermoHygro F installed and launched!
