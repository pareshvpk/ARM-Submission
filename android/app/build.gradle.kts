import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("keystore.properties")
if (keystorePropertiesFile.isFile) {
    FileInputStream(keystorePropertiesFile).use { keystoreProperties.load(it) }
}

fun signingValue(envName: String, propertyName: String): String? =
    System.getenv(envName)?.takeIf { it.isNotBlank() }
        ?: keystoreProperties.getProperty(propertyName)?.takeIf { it.isNotBlank() }

val releaseStoreFile = signingValue("RELEASE_STORE_FILE", "storeFile")
val releaseStorePassword = signingValue("RELEASE_STORE_PASSWORD", "storePassword")
val releaseKeyAlias = signingValue("RELEASE_KEY_ALIAS", "keyAlias")
val releaseKeyPassword = signingValue("RELEASE_KEY_PASSWORD", "keyPassword")
val hasReleaseSigning = releaseStoreFile != null &&
    releaseStorePassword != null &&
    releaseKeyAlias != null &&
    releaseKeyPassword != null

// DT-9: prefer the Armv8.0 build produced by deploy/android/build_executorch_aar.sh.
// The stock Maven AAR contains inline Armv8.1 LSE atomics and SIGILLs on
// Armv8.0 phones (Galaxy M31, Exynos 9611).
val localExecuTorchAar = file("libs/executorch-android-1.5.1-armv8.aar")
val useLocalExecuTorch = localExecuTorchAar.isFile
logger.lifecycle(
    if (useLocalExecuTorch) {
        "ExecuTorch: using local AAR ${localExecuTorchAar}"
    } else {
        "ExecuTorch: using Maven artifact org.pytorch:executorch-android:1.5.1"
    }
)

android {
    namespace = "org.ps3.sentinel"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.ps3.sentinel"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        buildConfigField("boolean", "EXECUTORCH_ARMV8_BASELINE", useLocalExecuTorch.toString())

        ndk {
            abiFilters.add("arm64-v8a")
        }
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(releaseStoreFile!!)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            isDebuggable = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        debug {
            applicationIdSuffix = ""
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
        buildConfig = true
    }

    sourceSets {
        getByName("main") {
            // sentinel/data is the single source of truth for trusted_domains.txt and rules.json.
            assets.srcDir("../../sentinel/data")
            assets.srcDir("src/main/model_hashes")
        }
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    if (useLocalExecuTorch) {
        implementation(files(localExecuTorchAar))
    } else {
        implementation("org.pytorch:executorch-android:1.5.1")
    }
    implementation("com.facebook.soloader:soloader:0.10.5")
    implementation("com.facebook.fbjni:fbjni:0.7.0")

    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
