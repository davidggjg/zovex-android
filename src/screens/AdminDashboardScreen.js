import React from 'react';
import {View, Text, TouchableOpacity, StyleSheet} from 'react-native';
import {WebView} from 'react-native-webview';

// Inline the docs/admin.html so it works offline and needs no server
const ADMIN_HTML = `<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>ZOVEX Admin</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0a0a0a;
    color: #f5f5f7;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }
  .card {
    background: #1c1c1e;
    border-radius: 20px;
    padding: 32px;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  }
  h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; text-align: center; }
  .sub { font-size: 13px; color: #6e6e73; text-align: center; margin-bottom: 28px; }
  label { display: block; font-size: 12px; color: #6e6e73; font-weight: 700; margin-bottom: 6px; margin-top: 16px; }
  input, textarea {
    width: 100%; background: #2c2c2e; border: 1.5px solid #3a3a3c; border-radius: 12px;
    padding: 12px 14px; font-size: 15px; color: #f5f5f7; font-family: inherit;
    outline: none; transition: border-color 0.2s; resize: none;
  }
  input:focus, textarea:focus { border-color: #e50914; }
  .btn {
    width: 100%; margin-top: 22px; padding: 14px; background: #e50914; color: #fff;
    border: none; border-radius: 14px; font-size: 16px; font-weight: 700;
    cursor: pointer; font-family: inherit; transition: background 0.2s, opacity 0.2s;
  }
  .btn:hover { background: #c0070f; }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .status { margin-top: 16px; padding: 12px 16px; border-radius: 12px; font-size: 14px; text-align: center; display: none; }
  .status.ok  { background: #1a3a1a; color: #34c759; display: block; }
  .status.err { background: #3a1a1a; color: #ff453a; display: block; }
  .divider { border: none; border-top: 1px solid #2c2c2e; margin: 24px 0; }
  .token-row { display: flex; gap: 8px; }
  .token-row input { flex: 1; }
  .save-btn {
    background: #2c2c2e; border: 1.5px solid #3a3a3c; border-radius: 12px;
    color: #f5f5f7; font-size: 13px; font-weight: 700; padding: 0 14px;
    cursor: pointer; font-family: inherit; white-space: nowrap;
  }
</style>
</head>
<body>
<div class="card" id="mainCard">
  <h1>📱 שליחת התראה</h1>
  <p class="sub">שולח לכל משתמשי אפליקציית ZOVEX</p>

  <label>GitHub Token (נשמר מקומית)</label>
  <div class="token-row">
    <input type="password" id="ghToken" placeholder="ghp_..." />
    <button class="save-btn" onclick="saveToken()">שמור</button>
  </div>

  <hr class="divider" />

  <label>כותרת ההתראה</label>
  <input type="text" id="notifTitle" placeholder="לדוגמה: עדכון חדש!" maxlength="100" />

  <label>תוכן ההתראה</label>
  <textarea id="notifBody" rows="3" placeholder="כתוב כאן את ההודעה שתישלח..." maxlength="300"></textarea>

  <button class="btn" id="sendBtn" onclick="sendNotif()">📤 שלח לכולם</button>
  <div class="status" id="mainStatus"></div>
</div>

<script>
  const REPO = 'davidggjg/zovex-android';
  const WORKFLOW = 'send-notification.yml';

  window.onload = function() {
    var saved = localStorage.getItem('zovex_gh_token');
    if (saved) document.getElementById('ghToken').value = saved;
  };

  function saveToken() {
    var t = document.getElementById('ghToken').value.trim();
    if (t) { localStorage.setItem('zovex_gh_token', t); alert('נשמר!'); }
  }

  async function sendNotif() {
    var token = document.getElementById('ghToken').value.trim();
    var title = document.getElementById('notifTitle').value.trim();
    var body  = document.getElementById('notifBody').value.trim();
    var status = document.getElementById('mainStatus');
    var btn    = document.getElementById('sendBtn');

    if (!token) { showStatus(status, '❌ הכנס GitHub Token קודם', 'err'); return; }
    if (!title)  { showStatus(status, '❌ חסרה כותרת', 'err'); return; }
    if (!body)   { showStatus(status, '❌ חסר תוכן', 'err'); return; }

    btn.disabled = true;
    btn.textContent = 'שולח...';
    showStatus(status, '', '');

    try {
      var res = await fetch(
        'https://api.github.com/repos/' + REPO + '/actions/workflows/' + WORKFLOW + '/dispatches',
        {
          method: 'POST',
          headers: {
            'Authorization': 'token ' + token,
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ ref: 'main', inputs: { title: title, body: body } }),
        }
      );
      if (res.status === 204) {
        showStatus(status, '✅ ההתראה נשלחה! (תגיע תוך ~30 שניות)', 'ok');
        document.getElementById('notifTitle').value = '';
        document.getElementById('notifBody').value = '';
      } else {
        var data = await res.json().catch(function(){ return {}; });
        showStatus(status, '❌ שגיאה: ' + (data.message || res.status), 'err');
      }
    } catch(e) {
      showStatus(status, '❌ שגיאת רשת', 'err');
    } finally {
      btn.disabled = false;
      btn.textContent = '📤 שלח לכולם';
    }
  }

  function showStatus(el, msg, type) {
    el.textContent = msg;
    el.className = 'status' + (type ? ' ' + type : '');
  }
</script>
</body>
</html>`;

export default function AdminDashboardScreen({navigation}) {
  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backTxt}>✕</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>פאנל ניהול</Text>
        <View style={{width: 36}} />
      </View>
      <WebView
        source={{html: ADMIN_HTML}}
        javaScriptEnabled
        domStorageEnabled
        startInLoadingState
        style={styles.webview}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1a1a1a',
  },
  headerTitle: {color: '#fff', fontSize: 16, fontWeight: '700'},
  backBtn: {padding: 4},
  backTxt: {color: '#aaa', fontSize: 20},
  webview: {flex: 1, backgroundColor: '#0a0a0a'},
});
