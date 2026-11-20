plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.thermohygro.offlinesensor"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.thermohygro.offlinesensor"
        minSdk = 24
        targetSdk = 37
        versionCode = 1
        versionName = "1.0.0-airgap"
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    // Strictly UI & AndroidX Core — Zero networking or telemetry SDKs
    implementation(kotlin("stdlib"))
    implementation(platform("androidx.compose:compose-bom:2026.09.00"))
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
}