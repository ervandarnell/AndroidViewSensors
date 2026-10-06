plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.thermohygro.offlinesensor"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.thermohygro.offlinesensor"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0-airgap"
    }

    buildFeatures {
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // Strictly UI & AndroidX Core — Zero networking or telemetry SDKs
    implementation(platform("androidx.compose:compose-bom:2024.06.00"))
    implementation("androidx.activity:activity-compose:1.9.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
}