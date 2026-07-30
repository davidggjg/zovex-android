package com.zovexapp

import android.content.Context
import com.google.android.gms.cast.framework.CastOptions
import com.google.android.gms.cast.framework.OptionsProvider
import com.google.android.gms.cast.framework.SessionProvider

// נדרש על ידי react-native-google-cast. משתמש ב-Default Media Receiver של גוגל
// (CC1AD845) — מנגן קישורי mp4/HLS ישירים, בדיוק מה שהשרת שלנו מגיש.
class CastOptionsProvider : OptionsProvider {
    override fun getCastOptions(context: Context): CastOptions {
        return CastOptions.Builder()
            .setReceiverApplicationId("CC1AD845")
            .build()
    }
    override fun getAdditionalSessionProviders(context: Context): MutableList<SessionProvider>? = null
}
