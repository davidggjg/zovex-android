import React from 'react';
import {View, StyleSheet} from 'react-native';
import {WebView} from 'react-native-webview';

// ── שכבת זוהר צבעונית מאחורי כל התוכן, זהה לאתר ─────────────────────────────
// אותה תבנית בדיוק כמו zovex/src/components/home/AmbientGlow.jsx: הרקע היה
// #0a0a0a שטוח, וזה מה שגורם למסך להיראות "פשוט" גם כשהתוכן עצמו עשיר.
// אין בפרויקט הזה שום ספריית blur/gradient (בדקתי package.json) - הוספת אחת
// דורשת linking נייטיבי שאי אפשר לבדוק מקומית לפני שדוחפים, ואם זה שובר את
// android/, אין APK בכלל עד שמתקנים. WebView כבר קיימת ועובדת (הפתיח
// משתמש בה), אז זה נבנה באותה שיטה בטוחה - HTML/CSS רגיל, בלי תלות חדשה.
// pointerEvents="none" כדי שלא יחסום מגע לתוכן שמעליו.
const GLOW_HTML = `<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>
*{margin:0;padding:0}
html,body{width:100%;height:100%;overflow:hidden;background:transparent}
#bg{position:fixed;inset:0;overflow:hidden;
  background:linear-gradient(170deg,#101018 0%,#0b0b10 40%,#08080b 100%)}
.blob{position:absolute;border-radius:50%;filter:blur(60px);will-change:transform}
@keyframes zvDrift{
  0%{transform:translate3d(0,0,0) scale(1)}
  50%{transform:translate3d(3%,-2%,0) scale(1.12)}
  100%{transform:translate3d(0,0,0) scale(1)}
}
#dark{position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(8,8,11,.26) 0%,rgba(8,8,11,.42) 45%,rgba(8,8,11,.58) 100%)}
</style></head><body>
<div id="bg">
  <div class="blob" style="top:-18%;left:-14%;width:82vmax;height:82vmax;
    background:radial-gradient(circle at 50% 50%,hsla(352,72%,48%,.6) 0%,hsla(352,72%,34%,0) 68%);
    animation:zvDrift 26s ease-in-out infinite"></div>
  <div class="blob" style="top:22%;left:44%;width:74vmax;height:74vmax;
    background:radial-gradient(circle at 50% 50%,hsla(30,72%,48%,.48) 0%,hsla(30,72%,34%,0) 68%);
    animation:zvDrift 34s ease-in-out -8s infinite"></div>
  <div class="blob" style="top:62%;left:-6%;width:78vmax;height:78vmax;
    background:radial-gradient(circle at 50% 50%,hsla(312,72%,48%,.42) 0%,hsla(312,72%,34%,0) 68%);
    animation:zvDrift 30s ease-in-out -16s infinite"></div>
  <div id="dark"></div>
</div>
</body></html>`;

export default function AmbientGlow() {
  return (
    <View style={StyleSheet.absoluteFillObject} pointerEvents="none">
      <WebView
        source={{html: GLOW_HTML}}
        style={styles.web}
        scrollEnabled={false}
        overScrollMode="never"
        androidLayerType="hardware"
        pointerEvents="none"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  web: {flex: 1, backgroundColor: 'transparent'},
});
