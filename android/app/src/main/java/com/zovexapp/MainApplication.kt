package com.zovexapp

import android.app.Application
import com.facebook.react.PackageList
import com.facebook.react.ReactApplication
import com.facebook.react.ReactHost
import com.facebook.react.ReactNativeHost
import com.facebook.react.ReactPackage
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.load
import com.facebook.react.defaults.DefaultReactHost.getDefaultReactHost
import com.facebook.react.defaults.DefaultReactNativeHost
import com.facebook.soloader.SoLoader
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability

class MainApplication : Application(), ReactApplication {

    // האם Google Play Services זמין במכשיר. הבדיקה עצמה (GoogleApiAvailability)
    // עובדת גם כשאין GMS — זה בדיוק ה-API שנועד לבדוק אם GMS מותקן — ולכן היא
    // בטוחה לקריאה גם על טלפוני Qin / טלוויזיות בלי GMS.
    fun hasPlayServices(): Boolean = try {
        GoogleApiAvailability.getInstance()
            .isGooglePlayServicesAvailable(this) == ConnectionResult.SUCCESS
    } catch (_: Throwable) {
        false
    }

    override val reactNativeHost: ReactNativeHost =
        object : DefaultReactNativeHost(this) {
            override fun getPackages(): List<ReactPackage> {
                val packages = PackageList(this).packages.toMutableList()
                // במכשירים בלי Google Play Services (Qin F22/F21 Pro, חלק
                // מהטלוויזיות) חבילת Google Cast מאתחלת CastContext דרך GMS, ועצם
                // האתחול זורק חריגה מקורית שמקריסה את האפליקציה בעלייה — עוד לפני
                // שקוד ה-JS בכלל רץ. מסירים אותה כשאין GMS (ל-Cast אין ערך בלי GMS
                // ממילא); האפליקציה עולה תקין ורק כפתור השידור נעלם.
                if (!this@MainApplication.hasPlayServices()) {
                    packages.removeAll {
                        it.javaClass.name.contains("googlecast", ignoreCase = true)
                    }
                }
                packages.add(PipPackage())
                return packages
            }
            override fun getJSMainModuleName(): String = "index"
            override fun getUseDeveloperSupport(): Boolean = BuildConfig.DEBUG
            override val isNewArchEnabled: Boolean = BuildConfig.IS_NEW_ARCHITECTURE_ENABLED
            override val isHermesEnabled: Boolean = BuildConfig.IS_HERMES_ENABLED
        }

    override val reactHost: ReactHost
        get() = getDefaultReactHost(applicationContext, reactNativeHost)

    override fun onCreate() {
        super.onCreate()
        SoLoader.init(this, false)
        if (BuildConfig.IS_NEW_ARCHITECTURE_ENABLED) load()
    }
}
