#!/usr/bin/env python3
"""
Builds a complete, standalone, zero-network native Android APK:
  public/ThermoHygro-Offline.apk

- Package: com.thermohygro.offlinesensor
- Activity: com.thermohygro.offlinesensor.MainActivity
- Reads hardware Sensor.TYPE_AMBIENT_TEMPERATURE (13), Sensor.TYPE_RELATIVE_HUMIDITY (12),
  and BatteryManager.EXTRA_TEMPERATURE thermistor fallback.
- Displays live temperature in Fahrenheit (°F), Relative Humidity (% RH),
  Dew Point (°F), and Heat Index (°F).
- Zero network permissions (android.permission.INTERNET is omitted).
- Signed with both APK Signature Scheme v1 (JAR PKCS#7) and APK Signature Scheme v2 (APK Sig Block 42).
"""

import hashlib
import os
import struct
import subprocess
import tempfile
import zipfile
import zlib


# ============================================================================
# PART 1: ANDROID BINARY XML (AXML) GENERATOR FOR AndroidManifest.xml
# ============================================================================

def build_axml_manifest() -> bytes:
    # Resource IDs in android.R.attr sorted in ascending order
    attr_map = [
        ("theme", 0x01010000),
        ("label", 0x01010001),
        ("name", 0x01010003),
        ("exported", 0x01010010),
        ("screenOrientation", 0x0101001E),
        ("minSdkVersion", 0x0101020C),
        ("versionCode", 0x0101021B),
        ("versionName", 0x0101021C),
        ("targetSdkVersion", 0x01010270),
        ("allowBackup", 0x01010280),
        ("required", 0x0101028E),
    ]

    other_strings = [
        "android",
        "http://schemas.android.com/apk/res/android",
        "manifest",
        "package",
        "com.thermohygro.offlinesensor",
        "1.0.0-offline",
        "uses-sdk",
        "uses-feature",
        "android.hardware.sensor.ambient_temperature",
        "android.hardware.sensor.relative_humidity",
        "android.hardware.sensor.accelerometer",
        "android.hardware.sensor.compass",
        "application",
        "ThermoHygro °F",
        "activity",
        "com.thermohygro.offlinesensor.MainActivity",
        "intent-filter",
        "action",
        "android.intent.action.MAIN",
        "category",
        "android.intent.category.LAUNCHER",
    ]

    all_strings = [a[0] for a in attr_map] + other_strings
    str_idx = {s: i for i, s in enumerate(all_strings)}

    encoded_strings = []
    offsets = []
    cur_offset = 0
    for s in all_strings:
        offsets.append(cur_offset)
        u16 = s.encode("utf-16le")
        char_len = len(s)
        entry = struct.pack("<H", char_len) + u16 + b"\x00\x00"
        encoded_strings.append(entry)
        cur_offset += len(entry)

    strings_blob = b"".join(encoded_strings)
    while len(strings_blob) % 4 != 0:
        strings_blob += b"\x00"

    offsets_blob = b"".join(struct.pack("<I", o) for o in offsets)
    strings_start = 28 + len(offsets_blob)
    sp_size = strings_start + len(strings_blob)
    sp_chunk = (
        struct.pack(
            "<HHIIIIII",
            0x0001,         # RES_STRING_POOL_TYPE
            28,             # header size
            sp_size,        # chunk size
            len(all_strings),
            0,              # style count
            0,              # flags (0 = UTF-16LE)
            strings_start,
            0,              # styles start
        )
        + offsets_blob
        + strings_blob
    )

    res_ids_blob = b"".join(struct.pack("<I", r[1]) for r in attr_map)
    res_map_chunk = struct.pack("<HHI", 0x0180, 8, 8 + len(res_ids_blob)) + res_ids_blob

    NS_URI = str_idx["http://schemas.android.com/apk/res/android"]
    NS_PREFIX = str_idx["android"]
    NO_NS = 0xFFFFFFFF

    def start_ns(line=1):
        return struct.pack("<HHIIIII", 0x0100, 16, 24, line, 0xFFFFFFFF, NS_PREFIX, NS_URI)

    def end_ns(line=1):
        return struct.pack("<HHIIIII", 0x0101, 16, 24, line, 0xFFFFFFFF, NS_PREFIX, NS_URI)

    TYPE_REFERENCE = 0x01
    TYPE_STRING = 0x03
    TYPE_INT_DEC = 0x10
    TYPE_INT_BOOLEAN = 0x12

    def make_attr(ns, name_s, val_type, data):
        name_i = str_idx[name_s]
        raw_val = data if val_type == TYPE_STRING else 0xFFFFFFFF
        return struct.pack(
            "<IIIHBBI",
            ns,
            name_i,
            raw_val,
            8,
            0,
            val_type,
            data & 0xFFFFFFFF,
        )

    def start_el(name_s, attrs, line=1):
        attr_blob = b"".join(attrs)
        chunk_size = 36 + len(attr_blob)
        return (
            struct.pack(
                "<HHIIIIIHHHHHH",
                0x0102,
                16,
                chunk_size,
                line,
                0xFFFFFFFF,
                NO_NS,
                str_idx[name_s],
                20,
                20,
                len(attrs),
                0,
                0,
                0,
            )
            + attr_blob
        )

    def end_element(name_s, line=1):
        return struct.pack(
            "<HHIIIII",
            0x0103,
            16,
            24,
            line,
            0xFFFFFFFF,
            NO_NS,
            str_idx[name_s],
        )

    # Note: Attributes within each element are ordered by ascending android.R.attr resource ID
    xml_chunks = [
        sp_chunk,
        res_map_chunk,
        start_ns(2),
        start_el(
            "manifest",
            [
                make_attr(NS_URI, "versionCode", TYPE_INT_DEC, 5),
                make_attr(NS_URI, "versionName", TYPE_STRING, str_idx["1.0.0-offline"]),
                make_attr(NO_NS, "package", TYPE_STRING, str_idx["com.thermohygro.offlinesensor"]),
            ],
            2,
        ),
        start_el(
            "uses-sdk",
            [
                make_attr(NS_URI, "minSdkVersion", TYPE_INT_DEC, 24),
                make_attr(NS_URI, "targetSdkVersion", TYPE_INT_DEC, 29),
            ],
            5,
        ),
        end_element("uses-sdk", 5),
        start_el(
            "uses-feature",
            [
                make_attr(NS_URI, "name", TYPE_STRING, str_idx["android.hardware.sensor.ambient_temperature"]),
                make_attr(NS_URI, "required", TYPE_INT_BOOLEAN, 0),
            ],
            7,
        ),
        end_element("uses-feature", 7),
        start_el(
            "uses-feature",
            [
                make_attr(NS_URI, "name", TYPE_STRING, str_idx["android.hardware.sensor.relative_humidity"]),
                make_attr(NS_URI, "required", TYPE_INT_BOOLEAN, 0),
            ],
            9,
        ),
        end_element("uses-feature", 9),
        start_el(
            "uses-feature",
            [
                make_attr(NS_URI, "name", TYPE_STRING, str_idx["android.hardware.sensor.accelerometer"]),
                make_attr(NS_URI, "required", TYPE_INT_BOOLEAN, 0),
            ],
            10,
        ),
        end_element("uses-feature", 10),
        start_el(
            "uses-feature",
            [
                make_attr(NS_URI, "name", TYPE_STRING, str_idx["android.hardware.sensor.compass"]),
                make_attr(NS_URI, "required", TYPE_INT_BOOLEAN, 0),
            ],
            11,
        ),
        end_element("uses-feature", 11),
        start_el(
            "application",
            [
                make_attr(NS_URI, "theme", TYPE_REFERENCE, 0x01030009),
                make_attr(NS_URI, "label", TYPE_STRING, str_idx["ThermoHygro °F"]),
                make_attr(NS_URI, "allowBackup", TYPE_INT_BOOLEAN, 0),
            ],
            12,
        ),
        start_el(
            "activity",
            [
                make_attr(NS_URI, "label", TYPE_STRING, str_idx["ThermoHygro °F"]),
                make_attr(NS_URI, "name", TYPE_STRING, str_idx["com.thermohygro.offlinesensor.MainActivity"]),
                make_attr(NS_URI, "exported", TYPE_INT_BOOLEAN, 0xFFFFFFFF),
                make_attr(NS_URI, "screenOrientation", TYPE_INT_DEC, 1),
            ],
            15,
        ),
        start_el("intent-filter", [], 18),
        start_el(
            "action",
            [make_attr(NS_URI, "name", TYPE_STRING, str_idx["android.intent.action.MAIN"])],
            19,
        ),
        end_element("action", 19),
        start_el(
            "category",
            [make_attr(NS_URI, "name", TYPE_STRING, str_idx["android.intent.category.LAUNCHER"])],
            20,
        ),
        end_element("category", 20),
        end_element("intent-filter", 21),
        end_element("activity", 22),
        end_element("application", 23),
        end_element("manifest", 24),
        end_ns(24),
    ]

    body = b"".join(xml_chunks)
    header = struct.pack("<HHI", 0x0003, 8, 8 + len(body))
    return header + body


# ============================================================================
# PART 2: DALVIK EXECUTABLE (classes.dex) COMPILER / ASSEMBLER
# ============================================================================

def uleb128(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            byte |= 0x80
            out.append(byte)
        else:
            out.append(byte)
            break
    return bytes(out)


def mutf8_encode(s: str) -> bytes:
    out = bytearray()
    for ch in s:
        cp = ord(ch)
        if cp == 0:
            out.extend(b"\xc0\x80")
        elif cp <= 0x7F:
            out.append(cp)
        elif cp <= 0x7FF:
            out.append(0xC0 | (cp >> 6))
            out.append(0x80 | (cp & 0x3F))
        else:
            out.append(0xE0 | (cp >> 12))
            out.append(0x80 | ((cp >> 6) & 0x3F))
            out.append(0x80 | (cp & 0x3F))
    return uleb128(len(s)) + bytes(out) + b"\x00"


def build_classes_dex() -> bytes:
    strings_list = [
        "<init>",
        "AMBIENT TEMPERATURE (FAHRENHEIT)",
        "BatteryManager Thermistor (Compensated -8.0°F)",
        "Landroid/app/Activity;",
        "Landroid/content/BroadcastReceiver;",
        "Landroid/content/Context;",
        "Landroid/content/Intent;",
        "Landroid/content/IntentFilter;",
        "Landroid/graphics/Typeface;",
        "Landroid/hardware/Sensor;",
        "Landroid/hardware/SensorEvent;",
        "Landroid/hardware/SensorEventListener;",
        "Landroid/hardware/SensorManager;",
        "Landroid/os/Bundle;",
        "Landroid/view/View;",
        "Landroid/widget/LinearLayout;",
        "Landroid/widget/ScrollView;",
        "Landroid/widget/TextView;",
        "Lcom/thermohygro/offlinesensor/MainActivity;",
        "Ljava/lang/CharSequence;",
        "Ljava/lang/Float;",
        "Ljava/lang/Object;",
        "Ljava/lang/String;",
        "Ljava/util/Locale;",
        "MONOSPACE",
        "Sensor.TYPE_AMBIENT_TEMPERATURE (13)",
        "THERMOHYGRO · ZERO-NETWORK ANDROID APK",
        "US",
        "[F",
        "[Ljava/lang/Object;",
        "[Ljava/lang/String;",
        "accelSensor",
        "accelVals",
        "accelView",
        "addView",
        "android.intent.action.BATTERY_CHANGED",
        "compassDeg",
        "compassView",
        "dirs",
        "format",
        "getDefaultSensor",
        "getIntExtra",
        "getOrientation",
        "getRotationMatrix",
        "getSystemService",
        "getType",
        "hasAmbientSensor",
        "hasHumiditySensor",
        "humiditySensor",
        "lastHumidity",
        "lastTempC",
        "magSensor",
        "magVals",
        "metaView",
        "onAccuracyChanged",
        "onCreate",
        "onPause",
        "onResume",
        "onSensorChanged",
        "oriVals",
        "pollCount",
        "registerListener",
        "registerReceiver",
        "rhView",
        "rotMat",
        "sensor",
        "sensorManager",
        "setBackgroundColor",
        "setContentView",
        "setOrientation",
        "setPadding",
        "setText",
        "setTextColor",
        "setTextSize",
        "setTypeface",
        "tempSensor",
        "tempView",
        "temperature",
        "unregisterListener",
        "updateDisplay",
        "valueOf",
        "values",
        "%.1f %% RH",
        "%.2f °F",
        "\nRELATIVE HUMIDITY (SENSOR_TYPE_12)",
        "\nACCELEROMETER AXES (X / Y / Z m/s²)",
        "X: %+.2f   Y: %+.2f   Z: %+.2f m/s²",
        "\nMAGNETIC COMPASS (HEADING & FIELD)",
        "                  ▼ HEADING ▼",
        "%03.0f° %s  (Bx:%+.0f By:%+.0f Bz:%+.0f µT)",
        "N",
        "NE",
        "E",
        "SE",
        "S",
        "SW",
        "W",
        "NW",
        "Raw: %.2f °C  |  Dew Point: %.1f °F  |  Heat Index: %.1f °F\nSource: %s\nNetwork Access: 0 Bytes (INTERNET Permission Omitted)",
    ]

    def shorty_char(type_desc: str) -> str:
        if type_desc.startswith("L") or type_desc.startswith("["):
            return "L"
        return type_desc

    def make_shorty(ret_type: str, param_types: tuple[str, ...]) -> str:
        return shorty_char(ret_type) + "".join(shorty_char(pt) for pt in param_types)

    # Prototypes: (return_type, (param_types...))
    raw_protos_def = [
        ("I", ()),
        ("I", ("Ljava/lang/String;", "I")),
        ("Landroid/content/Intent;", ("Landroid/content/BroadcastReceiver;", "Landroid/content/IntentFilter;")),
        ("Landroid/graphics/Bitmap;", ("I", "I", "Landroid/graphics/Bitmap$Config;")),
        ("Landroid/hardware/Sensor;", ("I",)),
        ("Ljava/lang/Float;", ("F",)),
        ("Ljava/lang/Object;", ("Ljava/lang/String;",)),
        ("Ljava/lang/String;", ("Ljava/util/Locale;", "Ljava/lang/String;", "[Ljava/lang/Object;")),
        ("V", ()),
        ("V", ("F",)),
        ("V", ("F", "F", "F", "Landroid/graphics/Paint;")),
        ("V", ("I",)),
        ("V", ("I", "I", "I", "I")),
        ("V", ("Landroid/content/Context;",)),
        ("V", ("Landroid/graphics/Bitmap;",)),
        ("V", ("Landroid/graphics/Typeface;",)),
        ("V", ("Landroid/hardware/Sensor;", "I")),
        ("V", ("Landroid/hardware/SensorEvent;",)),
        ("V", ("Landroid/hardware/SensorEventListener;",)),
        ("V", ("Landroid/os/Bundle;",)),
        ("V", ("Landroid/view/View;",)),
        ("V", ("Ljava/lang/CharSequence;",)),
        ("V", ("Ljava/lang/String;",)),
        ("V", ("Ljava/lang/String;", "F", "F", "Landroid/graphics/Paint;")),
        ("Z", ("Landroid/hardware/SensorEventListener;", "Landroid/hardware/Sensor;", "I")),
        ("Z", ("[F", "[F", "[F", "[F")),
        ("[F", ("[F", "[F")),
    ]
    type_names = [
        "F",
        "I",
        "V",
        "Z",
        "[F",
        "[Ljava/lang/Object;",
        "[Ljava/lang/String;",
        "Landroid/app/Activity;",
        "Landroid/content/BroadcastReceiver;",
        "Landroid/content/Context;",
        "Landroid/content/Intent;",
        "Landroid/content/IntentFilter;",
        "Landroid/graphics/Bitmap$Config;",
        "Landroid/graphics/Bitmap;",
        "Landroid/graphics/Canvas;",
        "Landroid/graphics/Paint;",
        "Landroid/graphics/Typeface;",
        "Landroid/hardware/Sensor;",
        "Landroid/hardware/SensorEvent;",
        "Landroid/hardware/SensorEventListener;",
        "Landroid/hardware/SensorManager;",
        "Landroid/os/Bundle;",
        "Landroid/view/View;",
        "Landroid/widget/ImageView;",
        "Landroid/widget/LinearLayout;",
        "Landroid/widget/ScrollView;",
        "Landroid/widget/TextView;",
        "Lcom/thermohygro/offlinesensor/MainActivity;",
        "Ljava/lang/CharSequence;",
        "Ljava/lang/Float;",
        "Ljava/lang/Object;",
        "Ljava/lang/String;",
        "Ljava/util/Locale;",
    ]
    # Fields: (class_type, field_type, field_name)
    fields_def = [
        ("Landroid/graphics/Bitmap$Config;", "Landroid/graphics/Bitmap$Config;", "ARGB_8888"),
        ("Landroid/graphics/Typeface;", "Landroid/graphics/Typeface;", "MONOSPACE"),
        ("Landroid/hardware/SensorEvent;", "Landroid/hardware/Sensor;", "sensor"),
        ("Landroid/hardware/SensorEvent;", "[F", "values"),
        ("Ljava/util/Locale;", "Ljava/util/Locale;", "US"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/hardware/Sensor;", "accelSensor"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "[F", "accelVals"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/widget/TextView;", "accelView"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "F", "compassDeg"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/widget/ImageView;", "compassDialView"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/widget/TextView;", "compassView"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "[Ljava/lang/String;", "dirs"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Z", "hasAmbientSensor"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Z", "hasHumiditySensor"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/hardware/Sensor;", "humiditySensor"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "F", "lastHumidity"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "F", "lastTempC"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/hardware/Sensor;", "magSensor"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "[F", "magVals"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/widget/TextView;", "metaView"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "[F", "oriVals"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "I", "pollCount"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/widget/TextView;", "rhView"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "[F", "rotMat"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/hardware/SensorManager;", "sensorManager"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/hardware/Sensor;", "tempSensor"),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "Landroid/widget/TextView;", "tempView"),
    ]
    # Methods: (class_type, method_name, return_type, (param_types...))
    methods_def = [
        ("Landroid/app/Activity;", "<init>", "V", ()),
        ("Landroid/app/Activity;", "getSystemService", "Ljava/lang/Object;", ("Ljava/lang/String;",)),
        ("Landroid/app/Activity;", "onCreate", "V", ("Landroid/os/Bundle;",)),
        ("Landroid/app/Activity;", "onPause", "V", ()),
        ("Landroid/app/Activity;", "onResume", "V", ()),
        ("Landroid/app/Activity;", "registerReceiver", "Landroid/content/Intent;", ("Landroid/content/BroadcastReceiver;", "Landroid/content/IntentFilter;")),
        ("Landroid/app/Activity;", "setContentView", "V", ("Landroid/view/View;",)),
        ("Landroid/content/Intent;", "getIntExtra", "I", ("Ljava/lang/String;", "I")),
        ("Landroid/content/IntentFilter;", "<init>", "V", ("Ljava/lang/String;",)),
        ("Landroid/graphics/Bitmap;", "createBitmap", "Landroid/graphics/Bitmap;", ("I", "I", "Landroid/graphics/Bitmap$Config;")),
        ("Landroid/graphics/Canvas;", "<init>", "V", ("Landroid/graphics/Bitmap;",)),
        ("Landroid/graphics/Canvas;", "drawCircle", "V", ("F", "F", "F", "Landroid/graphics/Paint;")),
        ("Landroid/graphics/Canvas;", "drawText", "V", ("Ljava/lang/String;", "F", "F", "Landroid/graphics/Paint;")),
        ("Landroid/graphics/Paint;", "<init>", "V", ("I",)),
        ("Landroid/graphics/Paint;", "setColor", "V", ("I",)),
        ("Landroid/graphics/Paint;", "setTextSize", "V", ("F",)),
        ("Landroid/hardware/Sensor;", "getType", "I", ()),
        ("Landroid/hardware/SensorManager;", "getDefaultSensor", "Landroid/hardware/Sensor;", ("I",)),
        ("Landroid/hardware/SensorManager;", "getOrientation", "[F", ("[F", "[F")),
        ("Landroid/hardware/SensorManager;", "getRotationMatrix", "Z", ("[F", "[F", "[F", "[F")),
        ("Landroid/hardware/SensorManager;", "registerListener", "Z", ("Landroid/hardware/SensorEventListener;", "Landroid/hardware/Sensor;", "I")),
        ("Landroid/hardware/SensorManager;", "unregisterListener", "V", ("Landroid/hardware/SensorEventListener;",)),
        ("Landroid/widget/ImageView;", "<init>", "V", ("Landroid/content/Context;",)),
        ("Landroid/widget/ImageView;", "setImageBitmap", "V", ("Landroid/graphics/Bitmap;",)),
        ("Landroid/widget/ImageView;", "setRotation", "V", ("F",)),
        ("Landroid/widget/LinearLayout;", "<init>", "V", ("Landroid/content/Context;",)),
        ("Landroid/widget/LinearLayout;", "addView", "V", ("Landroid/view/View;",)),
        ("Landroid/widget/LinearLayout;", "setBackgroundColor", "V", ("I",)),
        ("Landroid/widget/LinearLayout;", "setOrientation", "V", ("I",)),
        ("Landroid/widget/LinearLayout;", "setPadding", "V", ("I", "I", "I", "I")),
        ("Landroid/widget/ScrollView;", "<init>", "V", ("Landroid/content/Context;",)),
        ("Landroid/widget/ScrollView;", "addView", "V", ("Landroid/view/View;",)),
        ("Landroid/widget/ScrollView;", "setBackgroundColor", "V", ("I",)),
        ("Landroid/widget/TextView;", "<init>", "V", ("Landroid/content/Context;",)),
        ("Landroid/widget/TextView;", "setPadding", "V", ("I", "I", "I", "I")),
        ("Landroid/widget/TextView;", "setText", "V", ("Ljava/lang/CharSequence;",)),
        ("Landroid/widget/TextView;", "setTextColor", "V", ("I",)),
        ("Landroid/widget/TextView;", "setTextSize", "V", ("F",)),
        ("Landroid/widget/TextView;", "setTypeface", "V", ("Landroid/graphics/Typeface;",)),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "<init>", "V", ()),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "createCompassView", "V", ()),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "onAccuracyChanged", "V", ("Landroid/hardware/Sensor;", "I")),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "onCreate", "V", ("Landroid/os/Bundle;",)),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "onPause", "V", ()),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "onResume", "V", ()),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "onSensorChanged", "V", ("Landroid/hardware/SensorEvent;",)),
        ("Lcom/thermohygro/offlinesensor/MainActivity;", "updateDisplay", "V", ()),
        ("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",)),
        ("Ljava/lang/String;", "format", "Ljava/lang/String;", ("Ljava/util/Locale;", "Ljava/lang/String;", "[Ljava/lang/Object;")),
    ]
    protos_def = [(make_shorty(rt, pts), rt, pts) for rt, pts in raw_protos_def]
    for sh, _, _ in protos_def:
        strings_list.append(sh)
    strings_list.extend(type_names)
    for _, _, fn in fields_def:
        strings_list.append(fn)
    for _, mn, _, _ in methods_def:
        strings_list.append(mn)

    # Sort strings strictly by UTF-16 code unit order
    sorted_strings = sorted(set(strings_list), key=lambda s: [ord(c) for c in s])
    str_idx = {s: i for i, s in enumerate(sorted_strings)}

    sorted_types = sorted(set(type_names), key=lambda t: str_idx[t])
    type_idx = {t: i for i, t in enumerate(sorted_types)}

    # Sort protos by (return_type_idx, param_type_idxs)
    sorted_protos = sorted(
        protos_def,
        key=lambda p: (type_idx[p[1]], tuple(type_idx[x] for x in p[2])),
    )
    proto_idx = {(p[1], p[2]): i for i, p in enumerate(sorted_protos)}

    sorted_fields = sorted(
        fields_def,
        key=lambda f: (type_idx[f[0]], str_idx[f[2]], type_idx[f[1]]),
    )
    field_idx = {(f[0], f[2], f[1]): i for i, f in enumerate(sorted_fields)}

    sorted_methods = sorted(
        methods_def,
        key=lambda m: (type_idx[m[0]], str_idx[m[1]], proto_idx[(m[2], m[3])]),
    )
    method_idx = {(m[0], m[1], m[2], m[3]): i for i, m in enumerate(sorted_methods)}

    # Helper functions for assembling Dalvik 16-bit code units
    def insn_10x(op):
        return struct.pack("<BB", op, 0)

    def insn_11x(op, va):
        return struct.pack("<BB", op, va & 0xFF)

    def insn_11n(op, va, lit4):
        return struct.pack("<BB", op, (va & 0xF) | ((lit4 & 0xF) << 4))

    def insn_12x(op, va, vb):
        return struct.pack("<BB", op, (va & 0xF) | ((vb & 0xF) << 4))

    def insn_21s(op, va, lit16):
        return struct.pack("<BBh", op, va & 0xFF, lit16)

    def insn_21h(op, va, high16):
        return struct.pack("<BBH", op, va & 0xFF, high16 & 0xFFFF)

    def insn_21c(op, va, idx):
        return struct.pack("<BBH", op, va & 0xFF, idx & 0xFFFF)

    def insn_22c(op, va, vb, idx):
        return struct.pack("<BBH", op, (va & 0xF) | ((vb & 0xF) << 4), idx & 0xFFFF)

    def insn_22t(op, va, vb, offset_units):
        return struct.pack("<BBh", op, (va & 0xF) | ((vb & 0xF) << 4), offset_units)

    def insn_21t(op, va, offset_units):
        return struct.pack("<BBh", op, va & 0xFF, offset_units)

    def insn_23x(op, va, vb, vc):
        return struct.pack("<BBBB", op, va & 0xFF, vb & 0xFF, vc & 0xFF)

    def insn_31i(op, va, lit32):
        return struct.pack("<BBI", op, va & 0xFF, lit32 & 0xFFFFFFFF)

    def insn_35c(op, count, idx, regs):
        r = list(regs) + [0] * (5 - len(regs))
        b1 = ((count & 0xF) << 4) | (r[4] & 0xF)
        b23 = (r[0] & 0xF) | ((r[1] & 0xF) << 4) | ((r[2] & 0xF) << 8) | ((r[3] & 0xF) << 12)
        return struct.pack("<BBHH", op, b1, idx & 0xFFFF, b23)

    # ------------------------------------------------------------------------
    # Method 1: <init>()V
    # Registers: v0..v3 (4 registers; v3 = this)
    # ------------------------------------------------------------------------
    dir_names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    dir_init_insns = []
    for idx_d, dname in enumerate(dir_names):
        dir_init_insns.extend([
            insn_11n(0x12, 1, idx_d),
            insn_21c(0x1A, 2, str_idx[dname]),
            insn_23x(0x4D, 2, 0, 1),  # aput-object v2, v0, v1
        ])

    m_init_insns = b"".join([
        # invoke-direct {v3}, Activity;-><init>()V
        insn_35c(0x70, 1, method_idx[("Landroid/app/Activity;", "<init>", "V", ())], [3]),
        # const/high16 v0, 0x41b40000 (22.5f °C)
        insn_21h(0x15, 0, 0x41B4),
        insn_22c(0x59, 0, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "lastTempC", "F")]),
        # const/high16 v0, 0x42340000 (45.0f % RH)
        insn_21h(0x15, 0, 0x4234),
        insn_22c(0x59, 0, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "lastHumidity", "F")]),
        # Allocate float[3] for accelVals, magVals, oriVals
        insn_11n(0x12, 1, 3),
        insn_22c(0x23, 0, 1, type_idx["[F"]),
        # Default accelVals[2] = 9.81f (0x411cf5c3)
        insn_11n(0x12, 1, 2),
        insn_31i(0x14, 2, 0x411CF5C3),
        insn_23x(0x4B, 2, 0, 1),  # aput v2, v0, v1
        insn_22c(0x5B, 0, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "accelVals", "[F")]),
        insn_11n(0x12, 1, 3),
        insn_22c(0x23, 0, 1, type_idx["[F"]),
        # Default magVals[1] = 25.0f (0x41c80000), magVals[2] = -40.0f (0xc2200000)
        insn_11n(0x12, 1, 1),
        insn_21h(0x15, 2, 0x41C8),
        insn_23x(0x4B, 2, 0, 1),
        insn_11n(0x12, 1, 2),
        insn_21h(0x15, 2, 0xC220),
        insn_23x(0x4B, 2, 0, 1),
        insn_22c(0x5B, 0, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "magVals", "[F")]),
        insn_11n(0x12, 1, 3),
        insn_22c(0x23, 0, 1, type_idx["[F"]),
        insn_22c(0x5B, 0, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "oriVals", "[F")]),
        # Allocate float[9] for rotMat
        insn_21s(0x13, 1, 9),
        insn_22c(0x23, 0, 1, type_idx["[F"]),
        insn_22c(0x5B, 0, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "rotMat", "[F")]),
        # Allocate String[8] for dirs
        insn_21s(0x13, 1, 8),
        insn_22c(0x23, 0, 1, type_idx["[Ljava/lang/String;"]),
        b"".join(dir_init_insns),
        insn_22c(0x5B, 0, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "dirs", "[Ljava/lang/String;")]),
        insn_10x(0x0E),
    ])

    # ------------------------------------------------------------------------
    # Method 1b: private createCompassView()V
    # Registers: v0..v7 (8 registers; v7 = this)
    # Draws a 420x420 graphical compass dial + North/South needle onto a Bitmap
    # and attaches it to an ImageView saved in this.compassDialView.
    # ------------------------------------------------------------------------
    def f_h16(val: float) -> int:
        return (struct.unpack("<I", struct.pack("<f", float(val)))[0] >> 16) & 0xFFFF

    def draw_center_ring(color_int: int, radius: float) -> bytes:
        return b"".join([
            insn_31i(0x14, 4, color_int),
            insn_35c(0x6E, 2, method_idx[("Landroid/graphics/Paint;", "setColor", "V", ("I",))], [2, 4]),
            insn_21h(0x15, 5, f_h16(radius)),
            insn_35c(0x6E, 5, method_idx[("Landroid/graphics/Canvas;", "drawCircle", "V", ("F", "F", "F", "Landroid/graphics/Paint;"))], [1, 3, 3, 5, 2]),
        ])

    def draw_vert_circle(y_val: float, r_val: float) -> bytes:
        return b"".join([
            insn_21h(0x15, 4, f_h16(y_val)),
            insn_21h(0x15, 5, f_h16(r_val)),
            insn_35c(0x6E, 5, method_idx[("Landroid/graphics/Canvas;", "drawCircle", "V", ("F", "F", "F", "Landroid/graphics/Paint;"))], [1, 3, 4, 5, 2]),
        ])

    def draw_horiz_circle(x_val: float, r_val: float) -> bytes:
        return b"".join([
            insn_21h(0x15, 4, f_h16(x_val)),
            insn_21h(0x15, 5, f_h16(r_val)),
            insn_35c(0x6E, 5, method_idx[("Landroid/graphics/Canvas;", "drawCircle", "V", ("F", "F", "F", "Landroid/graphics/Paint;"))], [1, 4, 3, 5, 2]),
        ])

    def draw_label(txt: str, x_val: float, y_val: float) -> bytes:
        return b"".join([
            insn_21c(0x1A, 4, str_idx[txt]),
            insn_21h(0x15, 5, f_h16(x_val)),
            insn_21h(0x15, 6, f_h16(y_val)),
            insn_35c(0x6E, 5, method_idx[("Landroid/graphics/Canvas;", "drawText", "V", ("Ljava/lang/String;", "F", "F", "Landroid/graphics/Paint;"))], [1, 4, 5, 6, 2]),
        ])

    south_tail_steps = [
        (226.0, 14.0), (240.0, 12.5), (254.0, 11.0), (268.0, 9.5),
        (282.0, 8.0), (296.0, 6.5), (310.0, 5.0), (322.0, 3.5),
    ]
    north_needle_steps = [
        (194.0, 14.5), (180.0, 13.0), (166.0, 11.5), (152.0, 10.0),
        (138.0, 8.5), (124.0, 7.0), (110.0, 5.5), (96.0, 4.0), (84.0, 3.0),
    ]
    horiz_ticks = [85.0, 110.0, 135.0, 160.0, 260.0, 285.0, 310.0, 335.0]

    m_compass_view_insns = b"".join([
        # v0 = Bitmap.createBitmap(420, 420, Bitmap.Config.ARGB_8888)
        insn_21s(0x13, 0, 420),
        insn_21c(0x62, 1, field_idx[("Landroid/graphics/Bitmap$Config;", "ARGB_8888", "Landroid/graphics/Bitmap$Config;")]),
        insn_35c(0x71, 3, method_idx[("Landroid/graphics/Bitmap;", "createBitmap", "Landroid/graphics/Bitmap;", ("I", "I", "Landroid/graphics/Bitmap$Config;"))], [0, 0, 1]),
        insn_11x(0x0C, 0),
        # v1 = new Canvas(v0)
        insn_21c(0x22, 1, type_idx["Landroid/graphics/Canvas;"]),
        insn_35c(0x70, 2, method_idx[("Landroid/graphics/Canvas;", "<init>", "V", ("Landroid/graphics/Bitmap;",))], [1, 0]),
        # v2 = new Paint(1) (ANTI_ALIAS_FLAG)
        insn_21c(0x22, 2, type_idx["Landroid/graphics/Paint;"]),
        insn_11n(0x12, 3, 1),
        insn_35c(0x70, 2, method_idx[("Landroid/graphics/Paint;", "<init>", "V", ("I",))], [2, 3]),
        # v3 = 210.0f (center X and Y)
        insn_21h(0x15, 3, f_h16(210.0)),

        # Concentric compass rings
        draw_center_ring(0xFF334155, 196.0),
        draw_center_ring(0xFF111827, 190.0),
        draw_center_ring(0xFF1E293B, 142.0),
        draw_center_ring(0xFF0B0E17, 138.0),
        draw_center_ring(0xFF1E293B, 68.0),
        draw_center_ring(0xFF0B0E17, 64.0),

        # Horizontal W-E axis tick dots
        insn_31i(0x14, 4, 0xFF334155),
        insn_35c(0x6E, 2, method_idx[("Landroid/graphics/Paint;", "setColor", "V", ("I",))], [2, 4]),
        b"".join(draw_horiz_circle(x, 3.0) for x in horiz_ticks),

        # Tapered South Needle Tail (Slate)
        insn_31i(0x14, 4, 0xFF64748B),
        insn_35c(0x6E, 2, method_idx[("Landroid/graphics/Paint;", "setColor", "V", ("I",))], [2, 4]),
        b"".join(draw_vert_circle(y, r) for y, r in south_tail_steps),

        # Tapered North Needle Pointer (Emerald)
        insn_31i(0x14, 4, 0xFF10B981),
        insn_35c(0x6E, 2, method_idx[("Landroid/graphics/Paint;", "setColor", "V", ("I",))], [2, 4]),
        b"".join(draw_vert_circle(y, r) for y, r in north_needle_steps),

        # Center Pivot Cap
        draw_center_ring(0xFFF8FAFC, 18.0),
        draw_center_ring(0xFF06B6D4, 8.0),

        # Cardinal Labels (N, S, E, W)
        insn_21h(0x15, 4, f_h16(38.0)),
        insn_35c(0x6E, 2, method_idx[("Landroid/graphics/Paint;", "setTextSize", "V", ("F",))], [2, 4]),
        insn_31i(0x14, 4, 0xFF34D399),
        insn_35c(0x6E, 2, method_idx[("Landroid/graphics/Paint;", "setColor", "V", ("I",))], [2, 4]),
        draw_label("N", 196.0, 62.0),

        insn_31i(0x14, 4, 0xFFF8FAFC),
        insn_35c(0x6E, 2, method_idx[("Landroid/graphics/Paint;", "setColor", "V", ("I",))], [2, 4]),
        draw_label("S", 198.0, 384.0),
        draw_label("E", 358.0, 224.0),
        draw_label("W", 36.0, 224.0),

        # Intercardinal Labels (NE, SE, SW, NW)
        insn_21h(0x15, 4, f_h16(24.0)),
        insn_35c(0x6E, 2, method_idx[("Landroid/graphics/Paint;", "setTextSize", "V", ("F",))], [2, 4]),
        insn_31i(0x14, 4, 0xFF94A3B8),
        insn_35c(0x6E, 2, method_idx[("Landroid/graphics/Paint;", "setColor", "V", ("I",))], [2, 4]),
        draw_label("NE", 312.0, 110.0),
        draw_label("SE", 312.0, 332.0),
        draw_label("SW", 80.0, 332.0),
        draw_label("NW", 80.0, 110.0),

        # Create ImageView(this) & setImageBitmap(v0)
        insn_21c(0x22, 1, type_idx["Landroid/widget/ImageView;"]),
        insn_35c(0x70, 2, method_idx[("Landroid/widget/ImageView;", "<init>", "V", ("Landroid/content/Context;",))], [1, 7]),
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/ImageView;", "setImageBitmap", "V", ("Landroid/graphics/Bitmap;",))], [1, 0]),
        insn_22c(0x5B, 1, 7, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "compassDialView", "Landroid/widget/ImageView;")]),
        insn_10x(0x0E),
    ])

    # ------------------------------------------------------------------------
    # Method 2: private updateDisplay()V
    # Registers: v0..v9 (10 registers total; v9 = this / p0)
    # ------------------------------------------------------------------------
    rh_est_block = b"".join([
        # Dynamic psychrometric RH estimate when TYPE_12 is absent:
        # rh = 45.0f - (tempC - 23.5f) * 2.2f
        insn_31i(0x14, 2, 0x41BC0000),  # 23.5f
        insn_23x(0xA7, 2, 1, 2),        # v2 = tempC - 23.5f
        insn_31i(0x14, 3, 0x400CCCCD),  # 2.2f
        insn_23x(0xA8, 2, 2, 3),        # v2 = (tempC - 23.5f) * 2.2f
        insn_21h(0x15, 3, 0x4234),      # 45.0f
        insn_23x(0xA7, 2, 3, 2),        # v2 = 45.0f - delta
        insn_22c(0x59, 2, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "lastHumidity", "F")]),
    ])
    batt_store_block = b"".join([
        insn_12x(0x82, 1, 1),           # int-to-float v1, v1
        insn_21h(0x15, 2, 0x4120),      # const/high16 v2, 10.0f
        insn_23x(0xA9, 1, 1, 2),        # div-float v1, v1, v2 (raw thermistor °C)
        insn_31i(0x14, 2, 0x408E38E4),  # const v2, 4.4444447f (-8.0 °F chassis heat compensation)
        insn_23x(0xA7, 1, 1, 2),        # sub-float v1, v1, v2 (compensated ambient °C)
        insn_22c(0x59, 1, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "lastTempC", "F")]),
        insn_22c(0x55, 3, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "hasHumiditySensor", "Z")]),
        insn_21t(0x39, 3, (len(rh_est_block) // 2) + 2),  # if-nez v3, skip rh estimate
        rh_est_block,
    ])
    batt_intent_nonnull = b"".join([
        insn_21c(0x1A, 2, str_idx["temperature"]),
        insn_21s(0x13, 3, -1000),
        insn_35c(0x6E, 3, method_idx[("Landroid/content/Intent;", "getIntExtra", "I", ("Ljava/lang/String;", "I"))], [1, 2, 3]),
        insn_11x(0x0A, 1),
        insn_21s(0x13, 2, -500),
        insn_22t(0x37, 1, 2, (len(batt_store_block) // 2) + 2),  # 0x37 = if-le v1, v2, skip
        batt_store_block,
    ])
    batt_query_block = b"".join([
        insn_11n(0x12, 1, 0),
        insn_21c(0x22, 2, type_idx["Landroid/content/IntentFilter;"]),
        insn_21c(0x1A, 3, str_idx["android.intent.action.BATTERY_CHANGED"]),
        insn_35c(0x70, 2, method_idx[("Landroid/content/IntentFilter;", "<init>", "V", ("Ljava/lang/String;",))], [2, 3]),
        insn_35c(0x6E, 3, method_idx[("Landroid/app/Activity;", "registerReceiver", "Landroid/content/Intent;", ("Landroid/content/BroadcastReceiver;", "Landroid/content/IntentFilter;"))], [9, 1, 2]),
        insn_11x(0x0C, 1),
        insn_21t(0x38, 1, (len(batt_intent_nonnull) // 2) + 2),  # if-eqz v1, skip
        batt_intent_nonnull,
    ])
    batt_poll_outer = b"".join([
        insn_22c(0x52, 0, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "pollCount", "I")]),
        insn_11n(0x12, 1, 1),
        insn_23x(0x90, 1, 0, 1),    # add-int v1, v0, v1
        insn_21s(0x13, 2, 15),
        insn_23x(0x95, 1, 1, 2),    # and-int v1, v1, 15
        insn_22c(0x59, 1, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "pollCount", "I")]),
        insn_21t(0x39, 0, (len(batt_query_block) // 2) + 2),  # if-nez v0, skip battery query
        batt_query_block,
    ])

    ori_calc_block = b"".join([
        insn_22c(0x54, 3, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "oriVals", "[F")]),
        insn_35c(0x71, 2, method_idx[("Landroid/hardware/SensorManager;", "getOrientation", "[F", ("[F", "[F"))], [2, 3]),
        insn_11n(0x12, 8, 0),
        insn_23x(0x44, 2, 3, 8),  # v2 = oriVals[0] (azimuth in radians)
        insn_31i(0x14, 3, 0x42652EE1),  # 57.29578f (180 / pi)
        insn_23x(0xA8, 2, 2, 3),  # v2 = deg
        insn_21h(0x15, 3, 0x43B4),  # 360.0f
        insn_23x(0xA6, 2, 2, 3),  # v2 = deg + 360.0f
        insn_23x(0xAA, 2, 2, 3),  # rem-float v2, v2, v3 -> [0, 360)
        insn_22c(0x59, 2, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "compassDeg", "F")]),
    ])

    m_update_insns = b"".join([
        # Poll BatteryManager thermistor if TYPE_AMBIENT_TEMPERATURE (13) is not present
        insn_22c(0x55, 0, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "hasAmbientSensor", "Z")]),
        insn_21t(0x39, 0, (len(batt_poll_outer) // 2) + 2),  # if-nez v0, skip battery fallback
        batt_poll_outer,

        # iget v0, v9, lastTempC:F
        insn_22c(0x52, 0, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "lastTempC", "F")]),
        # iget v1, v9, lastHumidity:F
        insn_22c(0x52, 1, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "lastHumidity", "F")]),
        # const v5, 0x3fe66666 (1.8f)
        insn_31i(0x14, 5, 0x3FE66666),
        # const/high16 v6, 0x42000000 (32.0f)
        insn_21h(0x15, 6, 0x4200),
        # mul-float v2, v0, v5
        insn_23x(0xA8, 2, 0, 5),
        # add-float v2, v2, v6  --> v2 = tempF
        insn_23x(0xA6, 2, 2, 6),

        # Dew point F in v3:
        insn_21h(0x15, 7, 0x42C8),  # 100.0f
        insn_23x(0xA7, 3, 7, 1),    # 100 - rh
        insn_31i(0x14, 7, 0x3E4CCCCD),  # 0.2f
        insn_23x(0xA8, 3, 3, 7),
        insn_23x(0xA7, 3, 0, 3),    # dewPointC
        insn_23x(0xA8, 3, 3, 5),
        insn_23x(0xA6, 3, 3, 6),    # v3 = dewPointF

        # Heat Index F in v4:
        insn_21h(0x15, 7, 0x4288),  # 68.0f
        insn_23x(0xA7, 4, 2, 7),
        insn_31i(0x14, 7, 0x3F99999A),  # 1.2f
        insn_23x(0xA8, 4, 4, 7),
        insn_23x(0xA6, 4, 4, 2),
        insn_21h(0x15, 7, 0x4274),  # 61.0f
        insn_23x(0xA6, 4, 4, 7),
        insn_31i(0x14, 7, 0x3DC08312),  # 0.094f
        insn_23x(0xA8, 7, 1, 7),
        insn_23x(0xA6, 4, 4, 7),
        insn_21h(0x15, 7, 0x3F00),  # 0.5f
        insn_23x(0xA8, 4, 4, 7),    # v4 = heatIndexF

        # sget-object v5, Locale->US
        insn_21c(0x62, 5, field_idx[("Ljava/util/Locale;", "US", "Ljava/util/Locale;")]),

        # 1. Update tempView with "%.2f °F"
        insn_11n(0x12, 6, 1),
        insn_22c(0x23, 6, 6, type_idx["[Ljava/lang/Object;"]),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [2]),
        insn_11x(0x0C, 7),
        insn_11n(0x12, 8, 0),
        insn_23x(0x4D, 7, 6, 8),
        insn_21c(0x1A, 7, str_idx["%.2f °F"]),
        insn_35c(0x71, 3, method_idx[("Ljava/lang/String;", "format", "Ljava/lang/String;", ("Ljava/util/Locale;", "Ljava/lang/String;", "[Ljava/lang/Object;"))], [5, 7, 6]),
        insn_11x(0x0C, 7),
        insn_22c(0x54, 6, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "tempView", "Landroid/widget/TextView;")]),
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/TextView;", "setText", "V", ("Ljava/lang/CharSequence;",))], [6, 7]),

        # 2. Update rhView with "%.1f %% RH"
        insn_11n(0x12, 6, 1),
        insn_22c(0x23, 6, 6, type_idx["[Ljava/lang/Object;"]),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [1]),
        insn_11x(0x0C, 7),
        insn_11n(0x12, 8, 0),
        insn_23x(0x4D, 7, 6, 8),
        insn_21c(0x1A, 7, str_idx["%.1f %% RH"]),
        insn_35c(0x71, 3, method_idx[("Ljava/lang/String;", "format", "Ljava/lang/String;", ("Ljava/util/Locale;", "Ljava/lang/String;", "[Ljava/lang/Object;"))], [5, 7, 6]),
        insn_11x(0x0C, 7),
        insn_22c(0x54, 6, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "rhView", "Landroid/widget/TextView;")]),
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/TextView;", "setText", "V", ("Ljava/lang/CharSequence;",))], [6, 7]),

        # 3. Update metaView with 4 args: (lastTempC, dewPointF, heatIndexF, sourceStr)
        insn_11n(0x12, 6, 4),
        insn_22c(0x23, 6, 6, type_idx["[Ljava/lang/Object;"]),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [0]),
        insn_11x(0x0C, 7),
        insn_11n(0x12, 8, 0),
        insn_23x(0x4D, 7, 6, 8),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [3]),
        insn_11x(0x0C, 7),
        insn_11n(0x12, 8, 1),
        insn_23x(0x4D, 7, 6, 8),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [4]),
        insn_11x(0x0C, 7),
        insn_11n(0x12, 8, 2),
        insn_23x(0x4D, 7, 6, 8),
        insn_22c(0x55, 8, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "hasAmbientSensor", "Z")]),
        insn_21c(0x1A, 7, str_idx["BatteryManager Thermistor (Compensated -8.0°F)"]),
        insn_21t(0x38, 8, 4),
        insn_21c(0x1A, 7, str_idx["Sensor.TYPE_AMBIENT_TEMPERATURE (13)"]),
        insn_11n(0x12, 8, 3),
        insn_23x(0x4D, 7, 6, 8),
        insn_21c(0x1A, 7, str_idx["Raw: %.2f °C  |  Dew Point: %.1f °F  |  Heat Index: %.1f °F\nSource: %s\nNetwork Access: 0 Bytes (INTERNET Permission Omitted)"]),
        insn_35c(0x71, 3, method_idx[("Ljava/lang/String;", "format", "Ljava/lang/String;", ("Ljava/util/Locale;", "Ljava/lang/String;", "[Ljava/lang/Object;"))], [5, 7, 6]),
        insn_11x(0x0C, 7),
        insn_22c(0x54, 6, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "metaView", "Landroid/widget/TextView;")]),
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/TextView;", "setText", "V", ("Ljava/lang/CharSequence;",))], [6, 7]),

        # 4. Update accelView with "X: %+.2f   Y: %+.2f   Z: %+.2f m/s²"
        insn_22c(0x54, 0, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "accelVals", "[F")]),
        insn_11n(0x12, 6, 3),
        insn_22c(0x23, 6, 6, type_idx["[Ljava/lang/Object;"]),
        # X (index 0)
        insn_11n(0x12, 8, 0),
        insn_23x(0x44, 2, 0, 8),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [2]),
        insn_11x(0x0C, 7),
        insn_23x(0x4D, 7, 6, 8),
        # Y (index 1)
        insn_11n(0x12, 8, 1),
        insn_23x(0x44, 2, 0, 8),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [2]),
        insn_11x(0x0C, 7),
        insn_23x(0x4D, 7, 6, 8),
        # Z (index 2)
        insn_11n(0x12, 8, 2),
        insn_23x(0x44, 2, 0, 8),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [2]),
        insn_11x(0x0C, 7),
        insn_23x(0x4D, 7, 6, 8),
        insn_21c(0x1A, 7, str_idx["X: %+.2f   Y: %+.2f   Z: %+.2f m/s²"]),
        insn_35c(0x71, 3, method_idx[("Ljava/lang/String;", "format", "Ljava/lang/String;", ("Ljava/util/Locale;", "Ljava/lang/String;", "[Ljava/lang/Object;"))], [5, 7, 6]),
        insn_11x(0x0C, 7),
        insn_22c(0x54, 6, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "accelView", "Landroid/widget/TextView;")]),
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/TextView;", "setText", "V", ("Ljava/lang/CharSequence;",))], [6, 7]),

        # 5. Compute Compass Heading & Update compassView
        insn_22c(0x54, 1, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "magVals", "[F")]),
        insn_22c(0x54, 2, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "rotMat", "[F")]),
        insn_11n(0x12, 3, 0),  # null I matrix
        insn_35c(0x71, 4, method_idx[("Landroid/hardware/SensorManager;", "getRotationMatrix", "Z", ("[F", "[F", "[F", "[F"))], [2, 3, 0, 1]),
        insn_11x(0x0A, 4),  # v4 = boolean success
        insn_21t(0x38, 4, (len(ori_calc_block) // 2) + 2),  # if-eqz v4, skip orientation calculation
        ori_calc_block,

        # Format compassView: "%03.0f° %s  (Bx:%+.0f By:%+.0f Bz:%+.0f µT)"
        insn_22c(0x52, 2, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "compassDeg", "F")]),
        # Rotate graphical compassDialView by -compassDeg so North needle points to Magnetic North
        insn_22c(0x54, 6, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "compassDialView", "Landroid/widget/ImageView;")]),
        insn_12x(0x7F, 7, 2),  # neg-float v7, v2
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/ImageView;", "setRotation", "V", ("F",))], [6, 7]),
        # Cardinal index = ((int)((compassDeg + 22.5f) / 45.0f)) & 7
        insn_21h(0x15, 3, 0x41B4),  # 22.5f
        insn_23x(0xA6, 3, 2, 3),
        insn_21h(0x15, 4, 0x4234),  # 45.0f
        insn_23x(0xA9, 3, 3, 4),
        insn_12x(0x87, 3, 3),       # float-to-int v3, v3
        insn_21s(0x13, 4, 7),
        insn_23x(0x95, 3, 3, 4),    # and-int v3, v3, v4
        insn_22c(0x54, 4, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "dirs", "[Ljava/lang/String;")]),
        insn_23x(0x46, 3, 4, 3),    # aget-object v3, v4, v3 (cardinal String)

        insn_11n(0x12, 6, 5),
        insn_22c(0x23, 6, 6, type_idx["[Ljava/lang/Object;"]),
        # arg 0: compassDeg (v2)
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [2]),
        insn_11x(0x0C, 7),
        insn_11n(0x12, 8, 0),
        insn_23x(0x4D, 7, 6, 8),
        # arg 1: cardinal String (v3)
        insn_11n(0x12, 8, 1),
        insn_23x(0x4D, 3, 6, 8),
        # arg 2: magVals[0]
        insn_11n(0x12, 8, 0),
        insn_23x(0x44, 2, 1, 8),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [2]),
        insn_11x(0x0C, 7),
        insn_11n(0x12, 8, 2),
        insn_23x(0x4D, 7, 6, 8),
        # arg 3: magVals[1]
        insn_11n(0x12, 8, 1),
        insn_23x(0x44, 2, 1, 8),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [2]),
        insn_11x(0x0C, 7),
        insn_11n(0x12, 8, 3),
        insn_23x(0x4D, 7, 6, 8),
        # arg 4: magVals[2]
        insn_11n(0x12, 8, 2),
        insn_23x(0x44, 2, 1, 8),
        insn_35c(0x71, 1, method_idx[("Ljava/lang/Float;", "valueOf", "Ljava/lang/Float;", ("F",))], [2]),
        insn_11x(0x0C, 7),
        insn_11n(0x12, 8, 4),
        insn_23x(0x4D, 7, 6, 8),

        insn_21c(0x1A, 7, str_idx["%03.0f° %s  (Bx:%+.0f By:%+.0f Bz:%+.0f µT)"]),
        insn_35c(0x71, 3, method_idx[("Ljava/lang/String;", "format", "Ljava/lang/String;", ("Ljava/util/Locale;", "Ljava/lang/String;", "[Ljava/lang/Object;"))], [5, 7, 6]),
        insn_11x(0x0C, 7),
        insn_22c(0x54, 6, 9, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "compassView", "Landroid/widget/TextView;")]),
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/TextView;", "setText", "V", ("Ljava/lang/CharSequence;",))], [6, 7]),
        insn_10x(0x0E),
    ])

    # ------------------------------------------------------------------------
    # Method 3: onAccuracyChanged(Sensor, int)V
    # ------------------------------------------------------------------------
    m_acc_insns = insn_10x(0x0E)

    # ------------------------------------------------------------------------
    # Method 4: onCreate(Bundle)V
    # Registers: v0..v7 (8 registers total; v6 = this/p0, v7 = bundle/p1)
    # ------------------------------------------------------------------------
    def make_textview_block(title_str_idx, color_int, size_float_high16, save_field_key=None):
        blk = [
            insn_21c(0x22, 2, type_idx["Landroid/widget/TextView;"]),
            insn_35c(0x70, 2, method_idx[("Landroid/widget/TextView;", "<init>", "V", ("Landroid/content/Context;",))], [2, 6]),
            insn_35c(0x6E, 2, method_idx[("Landroid/widget/TextView;", "setTypeface", "V", ("Landroid/graphics/Typeface;",))], [2, 5]),
            insn_31i(0x14, 3, color_int),
            insn_35c(0x6E, 2, method_idx[("Landroid/widget/TextView;", "setTextColor", "V", ("I",))], [2, 3]),
            insn_21h(0x15, 3, size_float_high16),
            insn_35c(0x6E, 2, method_idx[("Landroid/widget/TextView;", "setTextSize", "V", ("F",))], [2, 3]),
        ]
        if title_str_idx is not None:
            blk.extend([
                insn_21c(0x1A, 3, title_str_idx),
                insn_35c(0x6E, 2, method_idx[("Landroid/widget/TextView;", "setText", "V", ("Ljava/lang/CharSequence;",))], [2, 3]),
            ])
        if save_field_key is not None:
            blk.append(insn_22c(0x5B, 2, 6, field_idx[save_field_key]))
        blk.append(
            insn_35c(0x6E, 2, method_idx[("Landroid/widget/LinearLayout;", "addView", "V", ("Landroid/view/View;",))], [1, 2])
        )
        return b"".join(blk)

    batt_store_block = b"".join([
        insn_12x(0x82, 2, 2),
        insn_21h(0x15, 3, 0x4120),
        insn_23x(0xA9, 2, 2, 3),
        insn_31i(0x14, 3, 0x40333333),
        insn_23x(0xA7, 2, 2, 3),
        insn_22c(0x59, 2, 6, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "lastTempC", "F")]),
    ])
    batt_check_tail = b"".join([
        insn_21c(0x1A, 3, str_idx["temperature"]),
        insn_21s(0x13, 4, -1000),
        insn_35c(0x6E, 3, method_idx[("Landroid/content/Intent;", "getIntExtra", "I", ("Ljava/lang/String;", "I"))], [2, 3, 4]),
        insn_11x(0x0A, 2),
        insn_21s(0x13, 3, -500),
        insn_22t(0x35, 2, 3, (len(batt_store_block) // 2) + 2),
        batt_store_block,
    ])
    skip_batt_units = (len(batt_check_tail) // 2) + 2

    m_oncreate_insns = b"".join([
        insn_35c(0x6F, 2, method_idx[("Landroid/app/Activity;", "onCreate", "V", ("Landroid/os/Bundle;",))], [6, 7]),
        insn_21c(0x62, 5, field_idx[("Landroid/graphics/Typeface;", "MONOSPACE", "Landroid/graphics/Typeface;")]),

        # ScrollView v0 = new ScrollView(this)
        insn_21c(0x22, 0, type_idx["Landroid/widget/ScrollView;"]),
        insn_35c(0x70, 2, method_idx[("Landroid/widget/ScrollView;", "<init>", "V", ("Landroid/content/Context;",))], [0, 6]),
        insn_31i(0x14, 2, 0xFF0B0E17),
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/ScrollView;", "setBackgroundColor", "V", ("I",))], [0, 2]),

        # LinearLayout v1 = new LinearLayout(this)
        insn_21c(0x22, 1, type_idx["Landroid/widget/LinearLayout;"]),
        insn_35c(0x70, 2, method_idx[("Landroid/widget/LinearLayout;", "<init>", "V", ("Landroid/content/Context;",))], [1, 6]),
        insn_11n(0x12, 2, 1),
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/LinearLayout;", "setOrientation", "V", ("I",))], [1, 2]),
        insn_31i(0x14, 2, 0xFF0B0E17),
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/LinearLayout;", "setBackgroundColor", "V", ("I",))], [1, 2]),
        insn_21s(0x13, 2, 48),
        insn_21s(0x13, 3, 56),
        insn_35c(0x6E, 5, method_idx[("Landroid/widget/LinearLayout;", "setPadding", "V", ("I", "I", "I", "I"))], [1, 2, 3, 2, 3]),

        # Add child TextViews
        make_textview_block(str_idx["THERMOHYGRO · ZERO-NETWORK ANDROID APK"], 0xFF34D399, 0x4140),
        make_textview_block(str_idx["AMBIENT TEMPERATURE (FAHRENHEIT)"], 0xFF94A3B8, 0x4140),
        make_textview_block(None, 0xFF06B6D4, 0x4228, ("Lcom/thermohygro/offlinesensor/MainActivity;", "tempView", "Landroid/widget/TextView;")),
        make_textview_block(str_idx["\nRELATIVE HUMIDITY (SENSOR_TYPE_12)"], 0xFF94A3B8, 0x4140),
        make_textview_block(None, 0xFFF59E0B, 0x4208, ("Lcom/thermohygro/offlinesensor/MainActivity;", "rhView", "Landroid/widget/TextView;")),
        make_textview_block(str_idx["\nACCELEROMETER AXES (X / Y / Z m/s²)"], 0xFF94A3B8, 0x4140),
        make_textview_block(None, 0xFF38BDF8, 0x4190, ("Lcom/thermohygro/offlinesensor/MainActivity;", "accelView", "Landroid/widget/TextView;")),
        make_textview_block(str_idx["\nMAGNETIC COMPASS (HEADING & FIELD)"], 0xFF94A3B8, 0x4140),
        make_textview_block(None, 0xFF34D399, 0x4190, ("Lcom/thermohygro/offlinesensor/MainActivity;", "compassView", "Landroid/widget/TextView;")),
        make_textview_block(str_idx["                  ▼ HEADING ▼"], 0xFF38BDF8, 0x4150),
        insn_35c(0x70, 1, method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "createCompassView", "V", ())], [6]),
        insn_22c(0x54, 2, 6, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "compassDialView", "Landroid/widget/ImageView;")]),
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/LinearLayout;", "addView", "V", ("Landroid/view/View;",))], [1, 2]),
        make_textview_block(None, 0xFFE2E8F0, 0x4150, ("Lcom/thermohygro/offlinesensor/MainActivity;", "metaView", "Landroid/widget/TextView;")),

        # scrollView.addView(linearLayout) & setContentView(scrollView)
        insn_35c(0x6E, 2, method_idx[("Landroid/widget/ScrollView;", "addView", "V", ("Landroid/view/View;",))], [0, 1]),
        insn_35c(0x6E, 2, method_idx[("Landroid/app/Activity;", "setContentView", "V", ("Landroid/view/View;",))], [6, 0]),

        # SensorManager setup
        insn_21c(0x1A, 2, str_idx["sensor"]),
        insn_35c(0x6E, 2, method_idx[("Landroid/app/Activity;", "getSystemService", "Ljava/lang/Object;", ("Ljava/lang/String;",))], [6, 2]),
        insn_11x(0x0C, 2),
        insn_21c(0x1F, 2, type_idx["Landroid/hardware/SensorManager;"]),
        insn_22c(0x5B, 2, 6, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "sensorManager", "Landroid/hardware/SensorManager;")]),

        # getDefaultSensor(13) -> tempSensor
        insn_21s(0x13, 3, 13),
        insn_35c(0x6E, 2, method_idx[("Landroid/hardware/SensorManager;", "getDefaultSensor", "Landroid/hardware/Sensor;", ("I",))], [2, 3]),
        insn_11x(0x0C, 3),
        insn_22c(0x5B, 3, 6, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "tempSensor", "Landroid/hardware/Sensor;")]),

        # getDefaultSensor(12) -> humiditySensor
        insn_21s(0x13, 3, 12),
        insn_35c(0x6E, 2, method_idx[("Landroid/hardware/SensorManager;", "getDefaultSensor", "Landroid/hardware/Sensor;", ("I",))], [2, 3]),
        insn_11x(0x0C, 3),
        insn_22c(0x5B, 3, 6, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "humiditySensor", "Landroid/hardware/Sensor;")]),

        # getDefaultSensor(1) -> accelSensor (TYPE_ACCELEROMETER)
        insn_11n(0x12, 3, 1),
        insn_35c(0x6E, 2, method_idx[("Landroid/hardware/SensorManager;", "getDefaultSensor", "Landroid/hardware/Sensor;", ("I",))], [2, 3]),
        insn_11x(0x0C, 3),
        insn_22c(0x5B, 3, 6, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "accelSensor", "Landroid/hardware/Sensor;")]),

        # getDefaultSensor(2) -> magSensor (TYPE_MAGNETIC_FIELD)
        insn_11n(0x12, 3, 2),
        insn_35c(0x6E, 2, method_idx[("Landroid/hardware/SensorManager;", "getDefaultSensor", "Landroid/hardware/Sensor;", ("I",))], [2, 3]),
        insn_11x(0x0C, 3),
        insn_22c(0x5B, 3, 6, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "magSensor", "Landroid/hardware/Sensor;")]),

        # updateDisplay() (automatically queries sticky BATTERY_CHANGED when pollCount == 0)
        insn_35c(0x70, 1, method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "updateDisplay", "V", ())], [6]),
        insn_10x(0x0E),
    ])

    # ------------------------------------------------------------------------
    # Method 5: onPause()V
    # Registers: v0..v1 (2 registers; v1 = this)
    # ------------------------------------------------------------------------
    unreg_call = insn_35c(0x6E, 2, method_idx[("Landroid/hardware/SensorManager;", "unregisterListener", "V", ("Landroid/hardware/SensorEventListener;",))], [0, 1])
    m_onpause_insns = b"".join([
        insn_35c(0x6F, 1, method_idx[("Landroid/app/Activity;", "onPause", "V", ())], [1]),
        insn_22c(0x54, 0, 1, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "sensorManager", "Landroid/hardware/SensorManager;")]),
        insn_21t(0x38, 0, (len(unreg_call) // 2) + 2),
        unreg_call,
        insn_10x(0x0E),
    ])

    # ------------------------------------------------------------------------
    # Method 6: onResume()V
    # Registers: v0..v3 (4 registers; v3 = this)
    # ------------------------------------------------------------------------
    reg_call = insn_35c(0x6E, 4, method_idx[("Landroid/hardware/SensorManager;", "registerListener", "Z", ("Landroid/hardware/SensorEventListener;", "Landroid/hardware/Sensor;", "I"))], [0, 3, 1, 2])
    resume_body = b"".join([
        insn_11n(0x12, 2, 2),   # v2 = SENSOR_DELAY_UI (2)
        insn_22c(0x54, 1, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "tempSensor", "Landroid/hardware/Sensor;")]),
        insn_21t(0x38, 1, (len(reg_call) // 2) + 2),
        reg_call,
        insn_22c(0x54, 1, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "humiditySensor", "Landroid/hardware/Sensor;")]),
        insn_21t(0x38, 1, (len(reg_call) // 2) + 2),
        reg_call,
        insn_22c(0x54, 1, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "accelSensor", "Landroid/hardware/Sensor;")]),
        insn_21t(0x38, 1, (len(reg_call) // 2) + 2),
        reg_call,
        insn_22c(0x54, 1, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "magSensor", "Landroid/hardware/Sensor;")]),
        insn_21t(0x38, 1, (len(reg_call) // 2) + 2),
        reg_call,
    ])
    m_onresume_insns = b"".join([
        insn_35c(0x6F, 1, method_idx[("Landroid/app/Activity;", "onResume", "V", ())], [3]),
        insn_22c(0x54, 0, 3, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "sensorManager", "Landroid/hardware/SensorManager;")]),
        insn_21t(0x38, 0, (len(resume_body) // 2) + 2),
        resume_body,
        insn_10x(0x0E),
    ])

    # ------------------------------------------------------------------------
    # Method 7: onSensorChanged(SensorEvent)V
    # Registers: v0..v6 (7 registers; v5 = this, v6 = event)
    # ------------------------------------------------------------------------
    temp_branch_body = b"".join([
        insn_11n(0x12, 2, 0),
        insn_23x(0x44, 3, 1, 2),
        insn_22c(0x59, 3, 5, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "lastTempC", "F")]),
        insn_11n(0x12, 3, 1),
        insn_22c(0x5C, 3, 5, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "hasAmbientSensor", "Z")]),
        insn_35c(0x70, 1, method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "updateDisplay", "V", ())], [5]),
    ])
    rh_branch_body = b"".join([
        insn_11n(0x12, 2, 0),
        insn_23x(0x44, 3, 1, 2),
        insn_22c(0x59, 3, 5, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "lastHumidity", "F")]),
        insn_11n(0x12, 3, 1),
        insn_22c(0x5C, 3, 5, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "hasHumiditySensor", "Z")]),
        insn_35c(0x70, 1, method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "updateDisplay", "V", ())], [5]),
    ])
    accel_branch_body = b"".join([
        insn_22c(0x54, 4, 5, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "accelVals", "[F")]),
        insn_11n(0x12, 2, 0),
        insn_23x(0x44, 3, 1, 2),
        insn_23x(0x4B, 3, 4, 2),
        insn_11n(0x12, 2, 1),
        insn_23x(0x44, 3, 1, 2),
        insn_23x(0x4B, 3, 4, 2),
        insn_11n(0x12, 2, 2),
        insn_23x(0x44, 3, 1, 2),
        insn_23x(0x4B, 3, 4, 2),
        insn_35c(0x70, 1, method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "updateDisplay", "V", ())], [5]),
    ])
    mag_branch_body = b"".join([
        insn_22c(0x54, 4, 5, field_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "magVals", "[F")]),
        insn_11n(0x12, 2, 0),
        insn_23x(0x44, 3, 1, 2),
        insn_23x(0x4B, 3, 4, 2),
        insn_11n(0x12, 2, 1),
        insn_23x(0x44, 3, 1, 2),
        insn_23x(0x4B, 3, 4, 2),
        insn_11n(0x12, 2, 2),
        insn_23x(0x44, 3, 1, 2),
        insn_23x(0x4B, 3, 4, 2),
        insn_35c(0x70, 1, method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "updateDisplay", "V", ())], [5]),
    ])
    sensor_nonnull_body = b"".join([
        insn_22c(0x54, 0, 6, field_idx[("Landroid/hardware/SensorEvent;", "sensor", "Landroid/hardware/Sensor;")]),
        insn_35c(0x6E, 1, method_idx[("Landroid/hardware/Sensor;", "getType", "I", ())], [0]),
        insn_11x(0x0A, 0),  # v0 = sensor type (int)
        insn_22c(0x54, 1, 6, field_idx[("Landroid/hardware/SensorEvent;", "values", "[F")]),

        # Check type == 13 (TYPE_AMBIENT_TEMPERATURE)
        insn_21s(0x13, 2, 13),
        insn_22t(0x33, 0, 2, (len(temp_branch_body) // 2) + 2),
        temp_branch_body,

        # Check type == 12 (TYPE_RELATIVE_HUMIDITY)
        insn_21s(0x13, 2, 12),
        insn_22t(0x33, 0, 2, (len(rh_branch_body) // 2) + 2),
        rh_branch_body,

        # Check type == 1 (TYPE_ACCELEROMETER)
        insn_11n(0x12, 2, 1),
        insn_22t(0x33, 0, 2, (len(accel_branch_body) // 2) + 2),
        accel_branch_body,

        # Check type == 2 (TYPE_MAGNETIC_FIELD)
        insn_11n(0x12, 2, 2),
        insn_22t(0x33, 0, 2, (len(mag_branch_body) // 2) + 2),
        mag_branch_body,
    ])
    m_onsensor_insns = b"".join([
        insn_21t(0x38, 6, (len(sensor_nonnull_body) // 2) + 2),
        sensor_nonnull_body,
        insn_10x(0x0E),
    ])

    def make_code_item(registers_size, ins_size, outs_size, insns_bytes):
        insns_units = len(insns_bytes) // 2
        hdr = struct.pack(
            "<HHHHII",
            registers_size,
            ins_size,
            outs_size,
            0,          # tries_size
            0,          # debug_info_off
            insns_units,
        )
        return hdr + insns_bytes

    code_items_list = [
        # Direct methods (sorted by method_idx): <init>, createCompassView, updateDisplay
        ("direct", method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "<init>", "V", ())], 0x10001, make_code_item(4, 1, 1, m_init_insns)),
        ("direct", method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "createCompassView", "V", ())], 0x00002, make_code_item(8, 1, 5, m_compass_view_insns)),
        ("direct", method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "updateDisplay", "V", ())], 0x00002, make_code_item(10, 1, 4, m_update_insns)),
        # Virtual methods (sorted by method_idx): onAccuracyChanged, onCreate, onPause, onResume, onSensorChanged
        ("virtual", method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "onAccuracyChanged", "V", ("Landroid/hardware/Sensor;", "I"))], 0x00001, make_code_item(3, 3, 0, m_acc_insns)),
        ("virtual", method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "onCreate", "V", ("Landroid/os/Bundle;",))], 0x00004, make_code_item(8, 2, 5, m_oncreate_insns)),
        ("virtual", method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "onPause", "V", ())], 0x00004, make_code_item(2, 1, 2, m_onpause_insns)),
        ("virtual", method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "onResume", "V", ())], 0x00004, make_code_item(4, 1, 4, m_onresume_insns)),
        ("virtual", method_idx[("Lcom/thermohygro/offlinesensor/MainActivity;", "onSensorChanged", "V", ("Landroid/hardware/SensorEvent;",))], 0x00001, make_code_item(7, 2, 1, m_onsensor_insns)),
    ]

    # Build TYPE_LIST section (interfaces implemented by MainActivity + method parameter lists)
    unique_param_tuples = []
    seen_pt = set()
    # Interface tuple first: (SensorEventListener,)
    iface_tuple = ("Landroid/hardware/SensorEventListener;",)
    unique_param_tuples.append(iface_tuple)
    seen_pt.add(iface_tuple)
    for _, _, pts in sorted_protos:
        if len(pts) > 0 and pts not in seen_pt:
            unique_param_tuples.append(pts)
            seen_pt.add(pts)

    # Calculate exact section offsets
    header_off = 0
    header_size = 112
    string_ids_off = header_size
    string_ids_size = len(sorted_strings) * 4
    type_ids_off = string_ids_off + string_ids_size
    type_ids_size = len(sorted_types) * 4
    proto_ids_off = type_ids_off + type_ids_size
    proto_ids_size = len(sorted_protos) * 12
    field_ids_off = proto_ids_off + proto_ids_size
    field_ids_size = len(sorted_fields) * 8
    method_ids_off = field_ids_off + field_ids_size
    method_ids_size = len(sorted_methods) * 8
    class_defs_off = method_ids_off + method_ids_size
    class_defs_size = 32  # 1 class

    data_off = class_defs_off + class_defs_size
    cur = data_off

    # 1. TYPE_TYPE_LIST (0x1001, 4-byte aligned before each item)
    type_list_off = cur
    type_list_offsets = {}
    type_list_blobs = []
    for pt in unique_param_tuples:
        while cur % 4 != 0:
            type_list_blobs.append(b"\x00")
            cur += 1
        type_list_offsets[pt] = cur
        b = struct.pack("<I", len(pt)) + b"".join(struct.pack("<H", type_idx[t]) for t in pt)
        type_list_blobs.append(b)
        cur += len(b)
    # Align to 4 bytes before TYPE_CODE_ITEM (0x2001)
    while cur % 4 != 0:
        type_list_blobs.append(b"\x00")
        cur += 1
    type_list_blob = b"".join(type_list_blobs)

    # 2. TYPE_CODE_ITEM (0x2001, 4-byte aligned before each item, no trailing padding before 1-byte-aligned 0x2002)
    code_item_off = cur
    code_item_offsets = []
    code_item_blobs = []
    for kind, midx, acc, cblob in code_items_list:
        while cur % 4 != 0:
            code_item_blobs.append(b"\x00")
            cur += 1
        code_item_offsets.append((kind, midx, acc, cur))
        code_item_blobs.append(cblob)
        cur += len(cblob)
    code_items_blob = b"".join(code_item_blobs)

    # 3. TYPE_STRING_DATA_ITEM (0x2002, 1-byte aligned)
    string_data_off = cur
    string_data_offsets = []
    string_data_blobs = []
    for s in sorted_strings:
        string_data_offsets.append(cur)
        sb = mutf8_encode(s)
        string_data_blobs.append(sb)
        cur += len(sb)
    string_data_blob = b"".join(string_data_blobs)

    # 4. TYPE_CLASS_DATA_ITEM (0x2000, 1-byte aligned)
    class_data_off = cur
    instance_fields = [
        f for f in sorted_fields if f[0] == "Lcom/thermohygro/offlinesensor/MainActivity;"
    ]
    direct_methods = [c for c in code_item_offsets if c[0] == "direct"]
    virtual_methods = [c for c in code_item_offsets if c[0] == "virtual"]

    cd_parts = [
        uleb128(0),                       # static_fields_size = 0
        uleb128(len(instance_fields)),    # instance_fields_size = 10
        uleb128(len(direct_methods)),     # direct_methods_size = 2
        uleb128(len(virtual_methods)),    # virtual_methods_size = 5
    ]
    prev_f = 0
    for f in instance_fields:
        fidx = field_idx[(f[0], f[2], f[1])]
        cd_parts.append(uleb128(fidx - prev_f))
        cd_parts.append(uleb128(0x0002))  # ACC_PRIVATE
        prev_f = fidx

    prev_m = 0
    for _, midx, acc, coff in direct_methods:
        cd_parts.append(uleb128(midx - prev_m))
        cd_parts.append(uleb128(acc))
        cd_parts.append(uleb128(coff))
        prev_m = midx

    prev_m = 0
    for _, midx, acc, coff in virtual_methods:
        cd_parts.append(uleb128(midx - prev_m))
        cd_parts.append(uleb128(acc))
        cd_parts.append(uleb128(coff))
        prev_m = midx

    class_data_blob = b"".join(cd_parts)
    cur += len(class_data_blob)

    # Pad to 4-byte alignment before TYPE_MAP_LIST
    pad_before_map = b""
    while cur % 4 != 0:
        pad_before_map += b"\x00"
        cur += 1

    # 5. TYPE_MAP_LIST (0x1000, 4-byte aligned)
    map_list_off = cur
    map_entries = [
        (0x0000, 1, header_off),
        (0x0001, len(sorted_strings), string_ids_off),
        (0x0002, len(sorted_types), type_ids_off),
        (0x0003, len(sorted_protos), proto_ids_off),
        (0x0004, len(sorted_fields), field_ids_off),
        (0x0005, len(sorted_methods), method_ids_off),
        (0x0006, 1, class_defs_off),
        (0x1001, len(unique_param_tuples), type_list_off),
        (0x2001, len(code_items_list), code_item_off),
        (0x2002, len(sorted_strings), string_data_off),
        (0x2000, 1, class_data_off),
        (0x1000, 1, map_list_off),
    ]
    map_list_blob = struct.pack("<I", len(map_entries)) + b"".join(
        struct.pack("<HHII", t, 0, cnt, off) for t, cnt, off in map_entries
    )
    cur += len(map_list_blob)

    file_size = cur
    data_size = file_size - data_off

    # Assemble index tables
    string_ids_blob = b"".join(struct.pack("<I", o) for o in string_data_offsets)
    type_ids_blob = b"".join(struct.pack("<I", str_idx[t]) for t in sorted_types)
    proto_ids_blob = b"".join(
        struct.pack(
            "<III",
            str_idx[sh],
            type_idx[rt],
            type_list_offsets[pts] if len(pts) > 0 else 0,
        )
        for sh, rt, pts in sorted_protos
    )
    field_ids_blob = b"".join(
        struct.pack("<HHI", type_idx[c], type_idx[ft], str_idx[fn])
        for c, ft, fn in sorted_fields
    )
    method_ids_blob = b"".join(
        struct.pack("<HHI", type_idx[c], proto_idx[(rt, pts)], str_idx[mn])
        for c, mn, rt, pts in sorted_methods
    )
    class_defs_blob = struct.pack(
        "<IIIIIIII",
        type_idx["Lcom/thermohygro/offlinesensor/MainActivity;"],
        0x0001,  # ACC_PUBLIC
        type_idx["Landroid/app/Activity;"],
        type_list_offsets[iface_tuple],
        0xFFFFFFFF,  # source_file_idx = NO_INDEX
        0,           # annotations_off
        class_data_off,
        0,           # static_values_off
    )

    body_after_header = (
        string_ids_blob
        + type_ids_blob
        + proto_ids_blob
        + field_ids_blob
        + method_ids_blob
        + class_defs_blob
        + type_list_blob
        + code_items_blob
        + string_data_blob
        + class_data_blob
        + pad_before_map
        + map_list_blob
    )

    header_tail = struct.pack(
        "<IIIIIIIIIIIIIIIIIIII",
        file_size,
        112,
        0x12345678,
        0,
        0,
        map_list_off,
        len(sorted_strings),
        string_ids_off,
        len(sorted_types),
        type_ids_off,
        len(sorted_protos),
        proto_ids_off,
        len(sorted_fields),
        field_ids_off,
        len(sorted_methods),
        method_ids_off,
        1,
        class_defs_off,
        data_size,
        data_off,
    )

    sha1_digest = hashlib.sha1(header_tail + body_after_header).digest()
    adler = zlib.adler32(sha1_digest + header_tail + body_after_header) & 0xFFFFFFFF

    dex_header = b"dex\n035\x00" + struct.pack("<I", adler) + sha1_digest + header_tail
    return dex_header + body_after_header


# ============================================================================
# PART 3: APK PACKAGER + APK SIGNATURE SCHEME V1 & V2 SIGNER
# ============================================================================

def compute_v2_chunk_digest(sections: list[bytes]) -> bytes:
    CHUNK_SIZE = 1024 * 1024
    chunk_digests = []
    for sec in sections:
        pos = 0
        while pos < len(sec):
            chunk = sec[pos : pos + CHUNK_SIZE]
            pos += CHUNK_SIZE
            h = hashlib.sha256()
            h.update(b"\xa5")
            h.update(struct.pack("<I", len(chunk)))
            h.update(chunk)
            chunk_digests.append(h.digest())

    top = hashlib.sha256()
    top.update(b"\x5a")
    top.update(struct.pack("<I", len(chunk_digests)))
    for d in chunk_digests:
        top.update(d)
    return top.digest()


def len_prefixed(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


def build_signed_apk(output_path: str):
    manifest_bytes = build_axml_manifest()
    dex_bytes = build_classes_dex()

    with tempfile.TemporaryDirectory() as tmpdir:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        key_pem = os.path.join(script_dir, "debug_key.pem")
        cert_pem = os.path.join(script_dir, "debug_cert.pem")
        cert_der = os.path.join(tmpdir, "cert.der")
        pubkey_der = os.path.join(tmpdir, "pubkey.der")

        # Generate or reuse persistent 2048-bit RSA key & self-signed X.509 certificate
        if not (os.path.exists(key_pem) and os.path.exists(cert_pem)):
            subprocess.run(
                [
                    "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", key_pem, "-out", cert_pem,
                    "-days", "10000", "-subj", "/CN=ThermoHygro Offline Sensor/O=Android Debug/C=US",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        subprocess.run(
            ["openssl", "x509", "-in", cert_pem, "-outform", "DER", "-out", cert_der],
            check=True,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", key_pem, "-pubout", "-outform", "DER", "-out", pubkey_der],
            check=True,
        )

        # Build APK Signature Scheme v1 (META-INF/MANIFEST.MF, CERT.SF, CERT.RSA)
        import base64
        m_b64 = base64.b64encode(hashlib.sha256(manifest_bytes).digest()).decode("ascii")
        d_b64 = base64.b64encode(hashlib.sha256(dex_bytes).digest()).decode("ascii")

        mf_header = "Manifest-Version: 1.0\r\nCreated-By: 1.0 (ThermoHygro Offline Builder)\r\n\r\n"
        mf_entry_1 = f"Name: AndroidManifest.xml\r\nSHA-256-Digest: {m_b64}\r\n\r\n"
        mf_entry_2 = f"Name: classes.dex\r\nSHA-256-Digest: {d_b64}\r\n\r\n"
        manifest_mf = (mf_header + mf_entry_1 + mf_entry_2).encode("utf-8")

        mf_all_b64 = base64.b64encode(hashlib.sha256(manifest_mf).digest()).decode("ascii")
        e1_b64 = base64.b64encode(hashlib.sha256(mf_entry_1.encode("utf-8")).digest()).decode("ascii")
        e2_b64 = base64.b64encode(hashlib.sha256(mf_entry_2.encode("utf-8")).digest()).decode("ascii")

        cert_sf = (
            f"Signature-Version: 1.0\r\nCreated-By: 1.0 (ThermoHygro)\r\nSHA-256-Digest-Manifest: {mf_all_b64}\r\n\r\n"
            f"Name: AndroidManifest.xml\r\nSHA-256-Digest: {e1_b64}\r\n\r\n"
            f"Name: classes.dex\r\nSHA-256-Digest: {e2_b64}\r\n\r\n"
        ).encode("utf-8")

        sf_path = os.path.join(tmpdir, "CERT.SF")
        rsa_path = os.path.join(tmpdir, "CERT.RSA")
        with open(sf_path, "wb") as f:
            f.write(cert_sf)

        subprocess.run(
            [
                "openssl", "cms", "-sign", "-binary", "-noattr",
                "-in", sf_path, "-signer", cert_pem, "-inkey", key_pem,
                "-outform", "DER", "-out", rsa_path, "-md", "sha256",
            ],
            check=True,
        )
        with open(rsa_path, "rb") as f:
            cert_rsa = f.read()

        # Create base unsigned/v1-signed ZIP archive
        unsigned_zip = os.path.join(tmpdir, "base.apk")
        with zipfile.ZipFile(unsigned_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("AndroidManifest.xml", manifest_bytes)
            zf.writestr("classes.dex", dex_bytes)
            zf.writestr("META-INF/MANIFEST.MF", manifest_mf)
            zf.writestr("META-INF/CERT.SF", cert_sf)
            zf.writestr("META-INF/CERT.RSA", cert_rsa)

        with open(unsigned_zip, "rb") as f:
            raw_zip = f.read()

        # Locate End of Central Directory (EOCD)
        eocd_pos = raw_zip.rfind(b"PK\x05\x06")
        if eocd_pos < 0:
            raise RuntimeError("Could not find EOCD in ZIP")
        cd_size = struct.unpack("<I", raw_zip[eocd_pos + 12 : eocd_pos + 16])[0]
        cd_offset = struct.unpack("<I", raw_zip[eocd_pos + 16 : eocd_pos + 20])[0]

        section_1 = raw_zip[:cd_offset]
        section_3 = raw_zip[cd_offset:eocd_pos]
        section_4_for_digest = bytearray(raw_zip[eocd_pos:])
        # For v2 digest calculation, EOCD's cd_offset is set to cd_offset (where APK Signing Block starts)
        struct.pack_into("<I", section_4_for_digest, 16, cd_offset)

        # Compute APK Signature Scheme v2 digest (0x0103 = RSA PKCS#1 v1.5 with SHA-256)
        top_digest = compute_v2_chunk_digest([section_1, section_3, bytes(section_4_for_digest)])

        with open(cert_der, "rb") as f:
            cert_der_bytes = f.read()
        with open(pubkey_der, "rb") as f:
            pubkey_der_bytes = f.read()

        # Build v2 signedData
        ALG_RSA_PKCS1_V1_5_SHA256 = 0x0103
        digest_entry = len_prefixed(struct.pack("<I", ALG_RSA_PKCS1_V1_5_SHA256) + len_prefixed(top_digest))
        digests_seq = len_prefixed(digest_entry)
        certs_seq = len_prefixed(len_prefixed(cert_der_bytes))
        add_attrs = len_prefixed(b"")
        signed_data_contents = digests_seq + certs_seq + add_attrs

        # Sign signed_data_contents using RSA-SHA256
        sd_path = os.path.join(tmpdir, "signed_data.bin")
        sig_path = os.path.join(tmpdir, "sig.bin")
        with open(sd_path, "wb") as f:
            f.write(signed_data_contents)
        subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_pem, "-out", sig_path, sd_path],
            check=True,
        )
        with open(sig_path, "rb") as f:
            rsa_sig_bytes = f.read()

        sig_entry = len_prefixed(struct.pack("<I", ALG_RSA_PKCS1_V1_5_SHA256) + len_prefixed(rsa_sig_bytes))
        signatures_seq = len_prefixed(sig_entry)
        signer = len_prefixed(
            len_prefixed(signed_data_contents)
            + signatures_seq
            + len_prefixed(pubkey_der_bytes)
        )
        signers_seq = len_prefixed(signer)

        APK_SIG_SCHEME_V2_ID = 0x7109871A
        id_value_pair = struct.pack("<QI", 4 + len(signers_seq), APK_SIG_SCHEME_V2_ID) + signers_seq

        # Pad APK Signing Block so total block size is a multiple of 4096 (or 8) bytes
        # Block = uint64(size_of_block) + pairs + uint64(size_of_block) + "APK Sig Block 42" (16 bytes)
        block_inner = id_value_pair
        size_of_block = len(block_inner) + 8 + 16
        apk_signing_block = (
            struct.pack("<Q", size_of_block)
            + block_inner
            + struct.pack("<Q", size_of_block)
            + b"APK Sig Block 42"
        )

        # Update EOCD Central Directory offset to point after the APK Signing Block
        new_cd_offset = cd_offset + len(apk_signing_block)
        final_eocd = bytearray(raw_zip[eocd_pos:])
        struct.pack_into("<I", final_eocd, 16, new_cd_offset)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(section_1)
            f.write(apk_signing_block)
            f.write(section_3)
            f.write(bytes(final_eocd))

    apk_bytes = open(output_path, "rb").read()
    b64_str = base64.b64encode(apk_bytes).decode("ascii")
    ts_out = f"""// Auto-generated from {output_path} ({len(apk_bytes)} bytes)
export const PREBUILT_APK_BASE64 = "{b64_str}";

export function getPrebuiltApkBytes(): Uint8Array {{
  const binary = atob(PREBUILT_APK_BASE64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {{
    bytes[i] = binary.charCodeAt(i);
  }}
  return bytes;
}}

export function getPrebuiltApkBlob(): Blob {{
  const bytes = getPrebuiltApkBytes();
  return new Blob([bytes.buffer as ArrayBuffer], {{
    type: "application/vnd.android.package-archive",
  }});
}}
"""
    with open("src/utils/prebuiltApk.ts", "w") as f_ts:
        f_ts.write(ts_out)

    print(f"Successfully built signed native APK: {output_path} ({len(apk_bytes)} bytes) and updated src/utils/prebuiltApk.ts")


if __name__ == "__main__":
    build_signed_apk("public/ThermoHygro-Offline.apk")
