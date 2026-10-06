# ThermoHygro Offline Android Sensor (°F, % RH, 3-Axis Accelerometer & Graphic Compass)

Zero-network native Android application (`ThermoHygro-Offline.apk`, package `com.thermohygro.offlinesensor`) that reads hardware `Sensor.TYPE_AMBIENT_TEMPERATURE` (13), `Sensor.TYPE_RELATIVE_HUMIDITY` (12), `Sensor.TYPE_ACCELEROMETER` (1), `Sensor.TYPE_MAGNETIC_FIELD` (2), and the compensated hardware thermistor fallback, displaying live results in **Fahrenheit (°F)** and a **rotating graphic compass rose** with 0 network permissions.

## Option 1: Install Pre-Built Native Android APK Over USB (`adb`)

Connect your phone via USB with **USB Debugging** enabled and run:
```sh
adb install -r --no-streaming ThermoHygro-Offline.apk
adb shell am start -n com.thermohygro.offlinesensor/.MainActivity
```
Or simply run:
```sh
sh ./install-to-phone.sh
```

## Option 2: Modify & Rebuild the APK Locally With Zero Android SDK (`scripts/build_apk.py`)

This archive includes the standalone Python Dalvik bytecode & APK Signature Scheme v2 compiler (`scripts/build_apk.py`) and your persistent signing key (`scripts/debug_key.pem`). To revise and rebuild the APK locally on Linux:
```sh
python3 scripts/build_apk.py
adb install -r --no-streaming public/ThermoHygro-Offline.apk
adb shell am start -n com.thermohygro.offlinesensor/.MainActivity
```
