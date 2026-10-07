package com.thermohygro.offlinesensor

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.BatteryManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import java.util.Locale
import kotlin.math.ln

/**
 * Zero-Network Android Thermometer (°F), Relative Humidity (% RH), Barometer (hPa / inHg),
 * 3-Axis Accelerometer (X/Y/Z m/s²), and Magnetic Compass (0°–360° Heading & µT).
 * Reads hardware sensors directly from SensorManager.
 */
class MainActivity : ComponentActivity(), SensorEventListener {

    private lateinit var sensorManager: SensorManager
    private var ambientTempSensor: Sensor? = null
    private var relativeHumiditySensor: Sensor? = null
    private var pressureSensor: Sensor? = null
    private var accelerometerSensor: Sensor? = null
    private var magnetometerSensor: Sensor? = null

    // Calibration offsets configured in ThermoHygro Bench
    private val calibrationTempOffsetC = 0.00f
    private val calibrationRhOffset = 0.00f

    // Reactive state holders for Compose UI
    private var rawCelsius by mutableStateOf<Float?>(null)
    private var relativeHumidity by mutableStateOf<Float?>(null)
    private var rawPressureHpa by mutableStateOf<Float?>(null)
    private var usingBatteryFallback by mutableStateOf(false)
    private var accelX by mutableStateOf(0.0f)
    private var accelY by mutableStateOf(0.0f)
    private var accelZ by mutableStateOf(9.81f)
    private var magX by mutableStateOf(0.0f)
    private var magY by mutableStateOf(25.0f)
    private var magZ by mutableStateOf(-40.0f)
    private var compassHeadingDeg by mutableStateOf(0.0f)
    private var sensorAccuracy by mutableStateOf(SensorManager.SENSOR_STATUS_ACCURACY_HIGH)

    private val gravityReading = FloatArray(3)
    private val geomagneticReading = FloatArray(3)
    private val rotationMatrix = FloatArray(9)
    private val orientationAngles = FloatArray(3)

    // Fallback BatteryManager thermistor receiver for phones without MEMS ambient thermometer
    private val batteryThermalReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (ambientTempSensor == null && intent != null) {
                val tenthsOfDegreeC = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
                if (tenthsOfDegreeC != Int.MIN_VALUE) {
                    // Compensate for internal battery/PMIC chassis heat dissipation (-4.4444 °C / -8.0 °F)
                    rawCelsius = (tenthsOfDegreeC / 10.0f) - 4.4444447f
                    usingBatteryFallback = true
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        sensorManager = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        ambientTempSensor = sensorManager.getDefaultSensor(Sensor.TYPE_AMBIENT_TEMPERATURE)
        relativeHumiditySensor = sensorManager.getDefaultSensor(Sensor.TYPE_RELATIVE_HUMIDITY)
        pressureSensor = sensorManager.getDefaultSensor(Sensor.TYPE_PRESSURE)
        accelerometerSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        magnetometerSensor = sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)

        setContent {
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = Color(0xFF0B0E17)
                ) {
                    ThermoHygroScreen(
                        rawTempC = rawCelsius,
                        rawRh = relativeHumidity,
                        pressureHpa = rawPressureHpa,
                        tempOffsetC = calibrationTempOffsetC,
                        rhOffset = calibrationRhOffset,
                        accelX = accelX,
                        accelY = accelY,
                        accelZ = accelZ,
                        magX = magX,
                        magY = magY,
                        magZ = magZ,
                        compassHeadingDeg = compassHeadingDeg,
                        hasHardwareTemp = ambientTempSensor != null,
                        hasHardwareHumidity = relativeHumiditySensor != null,
                        hasHardwareBarometer = pressureSensor != null,
                        usingBatteryFallback = usingBatteryFallback,
                        accuracy = sensorAccuracy
                    )
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        ambientTempSensor?.let { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        } ?: run {
            ContextCompat.registerReceiver(
                this,
                batteryThermalReceiver,
                IntentFilter(Intent.ACTION_BATTERY_CHANGED),
                ContextCompat.RECEIVER_EXPORTED
            )
        }

        relativeHumiditySensor?.let { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }

        pressureSensor?.let { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }

        accelerometerSensor?.let { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }

        magnetometerSensor?.let { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }
    }

    override fun onPause() {
        super.onPause()
        sensorManager.unregisterListener(this)
        if (ambientTempSensor == null) {
            try {
                unregisterReceiver(batteryThermalReceiver)
            } catch (_: IllegalArgumentException) {}
        }
    }

    override fun onSensorChanged(event: SensorEvent?) {
        event ?: return
        when (event.sensor.type) {
            Sensor.TYPE_AMBIENT_TEMPERATURE -> {
                rawCelsius = event.values[0]
                usingBatteryFallback = false
            }
            Sensor.TYPE_RELATIVE_HUMIDITY -> {
                relativeHumidity = event.values[0]
            }
            Sensor.TYPE_PRESSURE -> {
                rawPressureHpa = event.values[0]
            }
            Sensor.TYPE_ACCELEROMETER -> {
                System.arraycopy(event.values, 0, gravityReading, 0, 3)
                accelX = event.values[0]
                accelY = event.values[1]
                accelZ = event.values[2]
                updateCompassHeading()
            }
            Sensor.TYPE_MAGNETIC_FIELD -> {
                System.arraycopy(event.values, 0, geomagneticReading, 0, 3)
                magX = event.values[0]
                magY = event.values[1]
                magZ = event.values[2]
                updateCompassHeading()
            }
        }
    }

    private fun updateCompassHeading() {
        if (SensorManager.getRotationMatrix(rotationMatrix, null, gravityReading, geomagneticReading)) {
            SensorManager.getOrientation(rotationMatrix, orientationAngles)
            var degrees = Math.toDegrees(orientationAngles[0].toDouble()).toFloat()
            if (degrees < 0f) degrees += 360f
            compassHeadingDeg = degrees
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        sensorAccuracy = accuracy
    }
}

fun celsiusToFahrenheit(celsius: Float): Float = (celsius * 9.0f / 5.0f) + 32.0f

fun hpaToInHg(hpa: Float): Float = hpa * 0.0295300f

fun calculateAltitudeFeet(pressureHpa: Float): Float {
    val meters = SensorManager.getAltitude(SensorManager.PRESSURE_STANDARD_ATMOSPHERE, pressureHpa)
    return meters * 3.28084f
}

fun cardinalDirection(deg: Float): String {
    val dirs = arrayOf("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    val idx = ((deg + 22.5f) / 45.0f).toInt() and 7
    return dirs[idx]
}

fun calculateDewPointFahrenheit(tempC: Float, rhPercent: Float): Float {
    val clampedRh = rhPercent.coerceIn(1.0f, 100.0f)
    val a = 17.625f
    val b = 243.04f
    val alpha = ln(clampedRh / 100.0f) + (a * tempC) / (b + tempC)
    val dewPointC = (b * alpha) / (a - alpha)
    return celsiusToFahrenheit(dewPointC)
}

fun calculateHeatIndexFahrenheit(tempF: Float, rh: Float): Float {
    val simple = 0.5f * (tempF + 61.0f + ((tempF - 68.0f) * 1.2f) + (rh * 0.094f))
    if ((simple + tempF) / 2.0f < 80.0f) return simple
    return (-42.379 + 2.04901523 * tempF + 10.14333127 * rh
            - 0.22475541 * tempF * rh - 0.00683783 * tempF * tempF
            - 0.05481717 * rh * rh + 0.00122874 * tempF * tempF * rh
            + 0.00085282 * tempF * rh * rh - 0.00000199 * tempF * tempF * rh * rh).toFloat()
}

@Composable
fun ThermoHygroScreen(
    rawTempC: Float?,
    rawRh: Float?,
    pressureHpa: Float?,
    tempOffsetC: Float,
    rhOffset: Float,
    accelX: Float,
    accelY: Float,
    accelZ: Float,
    magX: Float,
    magY: Float,
    magZ: Float,
    compassHeadingDeg: Float,
    hasHardwareTemp: Boolean,
    hasHardwareHumidity: Boolean,
    hasHardwareBarometer: Boolean,
    usingBatteryFallback: Boolean,
    accuracy: Int
) {
    val calibratedC = rawTempC?.plus(tempOffsetC)
    val tempFahrenheit = calibratedC?.let { celsiusToFahrenheit(it) }
    val calibratedRh = rawRh?.plus(rhOffset)?.coerceIn(0f, 100f)

    val dewPointF = if (calibratedC != null && calibratedRh != null) {
        calculateDewPointFahrenheit(calibratedC, calibratedRh)
    } else null

    val heatIndexF = if (tempFahrenheit != null && calibratedRh != null) {
        calculateHeatIndexFahrenheit(tempFahrenheit, calibratedRh)
    } else null

    val accuracyLabel = when (accuracy) {
        SensorManager.SENSOR_STATUS_ACCURACY_HIGH -> "HIGH"
        SensorManager.SENSOR_STATUS_ACCURACY_MEDIUM -> "MEDIUM"
        SensorManager.SENSOR_STATUS_ACCURACY_LOW -> "LOW"
        SensorManager.SENSOR_STATUS_UNRELIABLE -> "UNRELIABLE"
        else -> "UNCALIBRATED"
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "THERMOHYGRO · ZERO-NETWORK ANDROID APK",
                color = Color(0xFF34D399),
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace
            )
            Text(
                text = "ACC: $accuracyLabel",
                color = Color(0xFF94A3B8),
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace
            )
        }

        // Primary Fahrenheit Card
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color(0xFF111827))
                .border(1.dp, Color(0xFF1E293B))
                .padding(20.dp)
        ) {
            val tempSourceLabel = when {
                hasHardwareTemp -> "AMBIENT TEMPERATURE (FAHRENHEIT)"
                usingBatteryFallback -> "BATTERY THERMISTOR (COMPENSATED)"
                else -> "TEMPERATURE SENSOR UNAVAILABLE"
            }
            Text(
                text = tempSourceLabel,
                color = Color(0xFF94A3B8),
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = tempFahrenheit?.let { String.format(Locale.US, "%.2f °F", it) } ?: "--.-- °F",
                color = Color(0xFF38BDF8),
                fontSize = 42.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace
            )
        }

        // Relative Humidity Card
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color(0xFF111827))
                .border(1.dp, Color(0xFF1E293B))
                .padding(20.dp)
        ) {
            val rhSourceLabel = if (hasHardwareHumidity) {
                "RELATIVE HUMIDITY (SENSOR_TYPE_12)"
            } else {
                "HUMIDITY SENSOR UNAVAILABLE"
            }
            Text(
                text = rhSourceLabel,
                color = Color(0xFF94A3B8),
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = calibratedRh?.let { String.format(Locale.US, "%.1f %% RH", it) } ?: "--.- % RH",
                color = Color(0xFFFBBF24),
                fontSize = 34.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace
            )

            if (dewPointF != null || heatIndexF != null) {
                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = "Dew Point: " + (dewPointF?.let { String.format(Locale.US, "%.1f °F", it) } ?: "--"),
                        color = Color(0xFF94A3B8),
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace
                    )
                    Text(
                        text = "Heat Index: " + (heatIndexF?.let { String.format(Locale.US, "%.1f °F", it) } ?: "--"),
                        color = Color(0xFF94A3B8),
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace
                    )
                }
            }
        }

        // Atmospheric Barometer Card
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color(0xFF111827))
                .border(1.dp, Color(0xFF1E293B))
                .padding(20.dp)
        ) {
            val barometerSourceLabel = if (hasHardwareBarometer) {
                "ATMOSPHERIC BAROMETER (SENSOR_TYPE_6)"
            } else {
                "BAROMETER SENSOR UNAVAILABLE"
            }
            Text(
                text = barometerSourceLabel,
                color = Color(0xFF94A3B8),
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = pressureHpa?.let { String.format(Locale.US, "%.1f hPa", it) } ?: "----.- hPa",
                color = Color(0xFFF43F5E),
                fontSize = 34.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace
            )

            if (pressureHpa != null) {
                Spacer(modifier = Modifier.height(8.dp))
                val inHg = hpaToInHg(pressureHpa)
                val altFt = calculateAltitudeFeet(pressureHpa)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = String.format(Locale.US, "%.2f inHg", inHg),
                        color = Color(0xFF94A3B8),
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace
                    )
                    Text(
                        text = String.format(Locale.US, "Est. Alt: %,.0f ft", altFt),
                        color = Color(0xFF94A3B8),
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace
                    )
                }
            }
        }

        // 3-Axis Accelerometer Card
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color(0xFF111827))
                .border(1.dp, Color(0xFF1E293B))
                .padding(20.dp)
        ) {
            Text(
                text = "ACCELEROMETER AXES (X / Y / Z m/s²)",
                color = Color(0xFF94A3B8),
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = String.format(Locale.US, "X: %+.2f   Y: %+.2f   Z: %+.2f m/s²", accelX, accelY, accelZ),
                color = Color(0xFFA78BFA),
                fontSize = 19.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace
            )
        }

        // Magnetic Compass Card with Graphic Compass Dial
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color(0xFF111827))
                .border(1.dp, Color(0xFF1E293B))
                .padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = "MAGNETIC COMPASS (HEADING & FIELD)",
                color = Color(0xFF94A3B8),
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = String.format(
                    Locale.US,
                    "%03.0f° %s  (Bx:%+.0f By:%+.0f Bz:%+.0f µT)",
                    compassHeadingDeg,
                    cardinalDirection(compassHeadingDeg),
                    magX,
                    magY,
                    magZ
                ),
                color = Color(0xFF34D399),
                fontSize = 19.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = "▼ HEADING ▼",
                color = Color(0xFF38BDF8),
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace
            )
            Spacer(modifier = Modifier.height(6.dp))
            GraphicCompassDial(headingDeg = compassHeadingDeg)
        }
    }
}

@Composable
fun GraphicCompassDial(headingDeg: Float) {
    Canvas(modifier = Modifier.size(210.dp)) {
        val cx = size.width / 2f
        val cy = size.height / 2f
        val outerR = size.minDimension * 0.46f

        // Outer & inner dial rings
        drawCircle(color = Color(0xFF0B0E17), radius = outerR, center = Offset(cx, cy))
        drawCircle(color = Color(0xFF334155), radius = outerR, center = Offset(cx, cy), style = Stroke(width = 4f))
        drawCircle(color = Color(0xFF1E293B), radius = outerR * 0.72f, center = Offset(cx, cy), style = Stroke(width = 2f))
        drawCircle(color = Color(0xFF1E293B), radius = outerR * 0.35f, center = Offset(cx, cy), style = Stroke(width = 2f))

        // Rotate compass rose and North/South needle by -headingDeg so North points to Magnetic North
        rotate(degrees = -headingDeg, pivot = Offset(cx, cy)) {
            val northPath = Path().apply {
                moveTo(cx, cy - outerR * 0.78f)
                lineTo(cx - 18f, cy)
                lineTo(cx + 18f, cy)
                close()
            }
            drawPath(path = northPath, color = Color(0xFF10B981))

            val southPath = Path().apply {
                moveTo(cx, cy + outerR * 0.78f)
                lineTo(cx - 16f, cy)
                lineTo(cx + 16f, cy)
                close()
            }
            drawPath(path = southPath, color = Color(0xFF64748B))
        }

        // Center pivot cap
        drawCircle(color = Color(0xFFF8FAFC), radius = 14f, center = Offset(cx, cy))
        drawCircle(color = Color(0xFF06B6D4), radius = 6f, center = Offset(cx, cy))
    }
}

