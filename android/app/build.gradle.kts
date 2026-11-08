plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "io.github.valerianarch.homelabhub"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "io.github.valerianarch.homelabhub"
        minSdk = 26
        targetSdk = 37
        versionCode = 2
        versionName = "0.1.1"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    // Release signing: the key comes from environment variables (set by the GitHub
    // "Android release" workflow from repository secrets). It is never stored in the repo.
    // Without these variables (local builds), release builds are signed with your debug key so you
    // can install and test them on your own phone. Official releases always use the real key.
    val keystorePath = providers.environmentVariable("HUB_KEYSTORE_PATH").orNull
    signingConfigs {
        create("release") {
            if (keystorePath != null) {
                storeFile = file(keystorePath)
                storePassword = providers.environmentVariable("HUB_KEYSTORE_PASSWORD").orNull
                keyAlias = providers.environmentVariable("HUB_KEY_ALIAS").orNull
                keyPassword = providers.environmentVariable("HUB_KEY_PASSWORD").orNull
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (keystorePath != null) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
            // R8 optimization is OFF for now: v0.1.0 (optimized) crashed on launch while the
            // identical debug build worked. Re-enable only after a crash log shows what R8 removed
            // and the right keep rules are in src/main/keepRules/.
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.material)
    implementation(libs.zxing.android.embedded) // QR scanner; no Google Play Services needed
    testImplementation(libs.junit)
    testImplementation(libs.org.json) // Android's built-in org.json isn't available in local unit tests
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)
}