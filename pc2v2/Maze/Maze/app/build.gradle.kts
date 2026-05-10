plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.maze"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.maze"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
}

dependencies {

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    implementation("com.github.PhilJay:MPAndroidChart:v3.1.0")
    implementation (libs.androidx.appcompat.v161)
    implementation ("com.google.android.material:material:1.12.0") // Versão atualizada do Material Design)
    implementation ("androidx.constraintlayout:constraintlayout:2.1.4")
    // Adicione estas:
    implementation ("com.squareup.okhttp3:okhttp:4.12.0") // Ou a versão mais recente
    implementation ("com.google.code.gson:gson:2.10.1") // Ou a versão mais recente
    implementation ("com.github.PhilJay:MPAndroidChart:v3.1.0") // Ou a versão mais recente

    implementation ("com.github.PhilJay:MPAndroidChart:v3.1.0") // Última versão pode varia
}
