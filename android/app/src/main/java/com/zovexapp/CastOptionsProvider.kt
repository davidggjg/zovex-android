package com.zovexapp

import android.content.Context
import com.google.android.gms.cast.framework.CastOptions
import com.google.android.gms.cast.framework.OptionsProvider
import com.google.android.gms.cast.framework.SessionProvider

// נדרש על ידי react-native-google-cast. Default Media Receiver (CC1AD845)
// מנגן קישורי mp4/HLS ישירים — בדיוק מה שהשרת שלנו מגיש.
class CastOptionsProvider : OptionsProvider {
    override fun getCastOptions(context: Context): CastOptions =
        CastOptions.Builder()
            .setReceiverApplicationId("CC1AD845")
            .build()

    override fun getAdditionalSessionProviders(context: Context): List<SessionProvider>? = null
}
