import React, {useEffect, useRef, useMemo} from 'react';
import {View, StyleSheet, StatusBar, NativeModules} from 'react-native';
import {WebView} from 'react-native-webview';
import {saveProgress, saveHistory, loadProgress} from '../api/movies';

const {PipModule} = NativeModules;

const TG_PROXY = 'https://telegram-bot-8528.onrender.com';

// Maps channel names → numeric IDs (same as CustomVideoPlayer.jsx)
const TG_CHANNELS = {zove8: '7282626428', ZOVE8: '7282626428'};

function buildSrc(movie, startTime = 0) {
  const vid = (movie.video_id || movie.video_url || '').trim();
  const type = movie.type || 'direct';
  const t = Math.max(0, Math.floor(startTime || 0));
  if (!vid) return null;
  // Decrypted offline downloads are served from a local file:// path - play
  // it directly as a native video, skip every remote-service pattern below.
  if (vid.startsWith('file://')) return vid;
  if (vid.includes('kaltura.com')) return vid;
  const kalturaMatch = vid.match(/^(\d+)\/(\d+)\/([a-zA-Z0-9_]+)$/);
  if (type === 'kaltura' || kalturaMatch) {
    const parts = vid.split('/');
    if (parts.length >= 3)
      return `https://cdnapisec.kaltura.com/p/${parts[0]}/embedPlaykitJs/uiconf_id/${parts[1]}?iframeembed=true&entry_id=${parts[2]}`;
    return null;
  }
  if (type === 'youtube' || vid.includes('youtube.com') || vid.includes('youtu.be')) {
    const m = vid.match(/(?:v=|youtu\.be\/)([^&/?]+)/);
    const base = `https://www.youtube.com/embed/${m ? m[1] : vid}?autoplay=1`;
    return t > 0 ? `${base}&start=${t}` : base;
  }
  if (type === 'drive' || vid.includes('drive.google.com')) {
    const m = vid.match(/\/d\/([^/?]+)/);
    return `https://drive.google.com/file/d/${m ? m[1] : vid}/preview`;
  }
  if (type === 'vimeo' || vid.includes('vimeo.com')) {
    const m = vid.match(/vimeo\.com\/(\d+)/);
    const base = `https://player.vimeo.com/video/${m ? m[1] : vid}?autoplay=1`;
    return t > 0 ? `${base}#t=${t}s` : base;
  }
  if (type === 'dailymotion' || vid.includes('dailymotion.com')) {
    const m = vid.match(/(?:video\/|dai\.ly\/)([a-zA-Z0-9]+)/);
    return `https://www.dailymotion.com/embed/video/${m ? m[1] : vid}?autoplay=1`;
  }
  if (type === 'streamable' || vid.includes('streamable.com')) {
    const m = vid.match(/streamable\.com\/([a-zA-Z0-9]+)/);
    return `https://streamable.com/e/${m ? m[1] : vid}?autoplay=1`;
  }
  if (type === 'rumble' || vid.includes('rumble.com')) {
    const m = vid.match(/(?:embed\/|video\/)([a-zA-Z0-9]+)/);
    return `https://rumble.com/embed/${m ? m[1] : vid}/`;
  }
  if (type === 'archive' || vid.includes('archive.org')) {
    const m = vid.match(/archive\.org\/(?:embed|details)\/([^/?]+)/);
    return `https://archive.org/embed/${m ? m[1] : vid}`;
  }
  if (type === 'kan' || vid.includes('kan.org.il'))
    return `https://www.kan.org.il/General/Embed.aspx?id=${vid}`;
  if (type === 'okru' || vid.includes('ok.ru')) {
    const m = vid.match(/ok\.ru\/video\/(\d+)/);
    return `https://ok.ru/videoembed/${m ? m[1] : vid}`;
  }
  if (type === 'telegram' || vid.includes('t.me')) {
    if (vid.startsWith('http') && !vid.includes('t.me')) return vid;
    const tgId = vid.replace(/^https?:\/\/t\.me\//, '');
    const parts = tgId.split('/').filter(Boolean);
    const chanRaw = parts[0] || '';
    const msgId = parts[parts.length - 1];
    if (/^\d+$/.test(chanRaw) && msgId) return `${TG_PROXY}/stream/${chanRaw}/${msgId}`;
    const numericId = TG_CHANNELS[chanRaw] || TG_CHANNELS[chanRaw.toLowerCase()];
    if (numericId && msgId) return `${TG_PROXY}/stream/${numericId}/${msgId}`;
    return `https://t.me/${tgId}?embed=1&mode=tme`;
  }
  if (type === 'jellyfin') {
    const server = (movie.jellyfin_server || '').replace(/\/$/, '');
    const apiKey = movie.jellyfin_api_key || '';
    return server && vid ? `${server}/web/index.html#!/video?id=${vid}&api_key=${apiKey}` : null;
  }
  return vid.startsWith('http') ? vid : null;
}

function isHlsUrl(src) {
  return src?.includes('.m3u8') || src?.includes('Manifest.ism');
}

function isIframeUrl(src, type) {
  if (!src) return false;
  const iframeTypes = ['youtube', 'drive', 'vimeo', 'dailymotion', 'streamable', 'rumble', 'archive', 'kan', 'okru', 'kaltura', 'jellyfin'];
  if (iframeTypes.includes(type)) return true;
  return ['youtube.com', 'youtu.be', 'drive.google.com', 'vimeo.com', 'dailymotion.com',
    'streamable.com', 'rumble.com', 'archive.org', 'kan.org.il', 'ok.ru', 't.me', 'kaltura.com']
    .some(d => src.includes(d));
}

function buildPlayerHtml(movie, src, startTime, isLive, hasNext) {
  const movieJson = JSON.stringify(movie).replace(/</g, '\\u003c').replace(/>/g, '\\u003e');
  const hls = isHlsUrl(src);
  const iframe = isIframeUrl(src, movie.type || 'direct');
  const episodeLabel = movie.episode_title
    ? `פרק ${movie.episode_number} - ${movie.episode_title}`
    : movie.episode_number ? `פרק ${movie.episode_number}` : '';

  if (iframe) {
    return `<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>*{margin:0;padding:0;box-sizing:border-box}body{background:#000;display:flex;flex-direction:column;height:100vh;overflow:hidden}
.bar{flex-shrink:0;height:56px;background:rgba(0,0,0,.85);display:flex;align-items:center;padding:0 14px;direction:rtl;gap:12px}
.x{background:none;border:none;color:#fff;font-size:22px;cursor:pointer;padding:8px;line-height:1;flex-shrink:0}
.ttl{flex:1;text-align:center;color:#fff;font:700 14px/1.3 Arial;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ep{color:rgba(255,255,255,.6);font-size:11px;font-family:Arial}
iframe{flex:1;border:none;width:100%;min-height:0}
</style></head><body>
<div class="bar">
  <button class="x" onclick="postMsg({type:'close'})">✕</button>
  <div style="flex:1;text-align:center">
    <div class="ttl">${(movie.title || '').replace(/</g, '&lt;')}</div>
    ${episodeLabel ? `<div class="ep">${episodeLabel}</div>` : ''}
  </div>
  <div style="width:36px"></div>
</div>
<iframe src="${src}" allowfullscreen allow="autoplay;encrypted-media;picture-in-picture;fullscreen"></iframe>
<script>
function postMsg(m){try{window.ReactNativeWebView&&window.ReactNativeWebView.postMessage(JSON.stringify(m));}catch{}}
</script>
</body></html>`;
  }

  // Native video — HLS via Shaka Player (→ HLS.js fallback → native), or direct MP4/stream
  return `<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeInOut{0%{opacity:0;transform:translateY(-50%) scale(.7)}25%{opacity:1;transform:translateY(-50%) scale(1.1)}70%{opacity:1}100%{opacity:0}}
@keyframes resumeFade{0%{opacity:0;transform:translateX(-50%) translateY(-8px)}15%{opacity:1;transform:translateX(-50%) translateY(0)}80%{opacity:1}100%{opacity:0}}
@keyframes liveDot{0%,100%{box-shadow:0 0 0 0 rgba(229,9,20,.6)}50%{box-shadow:0 0 0 6px rgba(229,9,20,0)}}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:100%;height:100%;background:#000;overflow:hidden}
#wrap{position:relative;width:100vw;height:100vh;background:#000;overflow:hidden}
video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000}
#loader{position:absolute;inset:0;z-index:5;background:#000;display:flex;align-items:center;justify-content:center}
.spin{width:44px;height:44px;border:4px solid rgba(255,255,255,.2);border-top:4px solid #e91e8c;border-radius:50%;animation:spin 1s linear infinite}
#overlay{position:absolute;inset:0;z-index:10}
#topbar{position:absolute;top:0;left:0;right:0;z-index:30;padding:14px 16px 40px;
  background:linear-gradient(to bottom,rgba(0,0,0,.82) 0%,transparent 100%);
  display:flex;align-items:flex-start;justify-content:space-between;direction:rtl;
  opacity:1;transition:opacity .3s}
.xbtn{background:none;border:none;color:#fff;cursor:pointer;padding:4px;line-height:1;
  display:flex;align-items:center;justify-content:center;-webkit-tap-highlight-color:transparent;outline:none;font-size:26px}
#ttl{flex:1;text-align:center;padding-top:2px}
#ttl .main{color:#fff;font:700 15px/1.3 Arial;text-shadow:0 1px 6px rgba(0,0,0,.9)}
#ttl .sub{color:rgba(255,255,255,.7);font:12px Arial;margin-top:2px}
#viewersbadge{position:absolute;top:68px;left:14px;z-index:25;background:rgba(0,0,0,.62);
  backdrop-filter:blur(6px);border-radius:20px;padding:6px 12px;
  display:none;align-items:center;gap:6px;color:#fff;font:700 12px Arial;pointer-events:none}
#viewersbadge .vdot{width:7px;height:7px;border-radius:50%;background:#e50914;display:inline-block;animation:liveDot 1.5s ease-in-out infinite}
#bottombar{position:absolute;bottom:0;left:0;right:0;z-index:30;padding:40px 20px 20px;
  background:linear-gradient(to top,rgba(0,0,0,.55) 0%,transparent 100%);
  transition:opacity .3s;opacity:1;direction:ltr}
#progwrap{width:100%;padding:8px 0;margin-bottom:12px;cursor:pointer;touch-action:none}
#progtrack{position:relative;height:3px;background:rgba(255,255,255,.25);border-radius:3px}
#progfill{position:absolute;top:0;left:0;height:100%;width:0%;background:#e91e8c;border-radius:3px}
#progdot{position:absolute;top:50%;left:0%;transform:translate(-50%,-50%);width:13px;height:13px;border-radius:50%;background:#e91e8c;box-shadow:0 0 6px rgba(233,30,140,.7)}
.brow{display:flex;align-items:center;justify-content:space-between}
.bleft{display:flex;align-items:center;gap:16px}
.bright{display:flex;align-items:center;gap:8px}
.ibtn{background:none;border:none;color:#fff;width:42px;height:42px;border-radius:50%;cursor:pointer;
  display:flex;align-items:center;justify-content:center;-webkit-tap-highlight-color:transparent;font-size:20px}
#timestr{color:rgba(255,255,255,.75);font:12px Arial;white-space:nowrap}
.livedot{display:inline-flex;align-items:center;gap:6px;color:#fff;font:900 12px Arial}
.livedot span{width:8px;height:8px;border-radius:50%;background:#e50914;display:inline-block;animation:liveDot 1.5s ease-in-out infinite}
#ctrls{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  display:flex;align-items:center;gap:32px;z-index:20;transition:opacity .3s}
.cbtn{background:none;border:none;color:#fff;width:58px;height:58px;border-radius:50%;cursor:pointer;
  display:flex;align-items:center;justify-content:center;position:relative;-webkit-tap-highlight-color:transparent;outline:none}
.cbtn .num{position:absolute;top:54%;left:50%;transform:translate(-50%,-50%);font:900 10px Arial;color:#fff}
#skipanim{position:absolute;top:40%;z-index:20;animation:fadeInOut .7s ease forwards;display:none}
.skipbox{background:rgba(0,0,0,.55);backdrop-filter:blur(8px);border-radius:18px;padding:14px 22px;
  display:flex;flex-direction:column;align-items:center;gap:4px;border:1px solid rgba(255,255,255,.18)}
.skipbox span{font:700 13px Arial;color:#fff}
#nextcard{display:none;position:absolute;bottom:88px;right:16px;z-index:40;
  background:rgba(10,10,10,.92);border:1px solid rgba(255,255,255,.18);border-radius:14px;
  padding:14px 18px;direction:rtl;min-width:180px}
#nextcard .nclbl{color:rgba(255,255,255,.55);font:11px Arial;margin-bottom:4px}
#nextcard .nctitle{color:#fff;font:700 13px/1.3 Arial}
#nextcard .ncbtn{display:block;margin-top:10px;background:#e91e8c;border:none;color:#fff;
  padding:8px 0;border-radius:8px;font:700 13px Arial;cursor:pointer;width:100%;text-align:center}
#resumetoast{display:none;position:absolute;top:70px;left:50%;transform:translateX(-50%);z-index:50;
  background:rgba(0,0,0,.72);border-radius:20px;padding:8px 18px;color:#fff;font:600 13px Arial;
  white-space:nowrap;pointer-events:none;border:1px solid rgba(255,255,255,.15)}
</style>
</head><body>
<div id="wrap">
  <div id="loader"><div class="spin"></div></div>
  <div id="overlay">
    <div id="topbar">
      <button class="xbtn" id="closebtn">✕</button>
      <div id="ttl">
        <div class="main">${(movie.title || '').replace(/</g, '&lt;')}</div>
        ${episodeLabel ? `<div class="sub">${episodeLabel.replace(/</g, '&lt;')}</div>` : ''}
      </div>
      <button class="xbtn" id="sharebtn" style="font-size:18px">⤴</button>
    </div>
    ${isLive ? '<div id="viewersbadge"><span class="vdot"></span><span id="viewercount"></span></div>' : ''}
    <div id="ctrls">
      ${isLive ? '' : `<button class="cbtn" id="skipback">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 .49-3.51"></path></svg>
        <span class="num">10</span></button>`}
      <button class="cbtn" style="width:58px;height:58px" id="playbtn">
        <svg id="pauseIcon" width="28" height="28" viewBox="0 0 28 28" fill="white"><rect x="3" y="3" width="8" height="22" rx="2"/><rect x="17" y="3" width="8" height="22" rx="2"/></svg>
        <svg id="playIcon" width="28" height="28" viewBox="0 0 28 28" fill="white" style="display:none"><polygon points="5,2 26,14 5,26"/></svg>
      </button>
      ${isLive ? '' : `<button class="cbtn" id="skipfwd">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-.49-3.51"></path></svg>
        <span class="num">10</span></button>`}
    </div>
    <div id="bottombar">
      ${isLive ? '' : `<div id="progwrap"><div id="progtrack"><div id="progfill"></div><div id="progdot"></div></div></div>`}
      <div class="brow">
        <div class="bleft">
          <button class="ibtn" id="mutebtn"></button>
          ${isLive
            ? '<div class="livedot"><span></span>LIVE</div>'
            : '<div id="timestr">0:00 / 0:00</div>'}
        </div>
        <div class="bright">
          <button class="ibtn" id="pipbtn" style="display:none"></button>
          <button class="ibtn" id="fsbtn"></button>
        </div>
      </div>
    </div>
    <div id="skipanim"><div class="skipbox"><span id="skipicon"></span><span id="skiptext"></span></div></div>
    ${hasNext ? `<div id="nextcard"><div class="nclbl">הפרק הבא</div><div class="nctitle" id="nexttitle"></div><button class="ncbtn" onclick="goNextEp()">המשך לפרק הבא ▶</button></div>` : ''}
    <div id="resumetoast"></div>
  </div>
</div>
<script>
(function(){
var MOVIE = ${movieJson};
var START = ${Math.max(0, Math.floor(startTime || 0))};
var IS_LIVE = ${isLive ? 'true' : 'false'};
var SRC = ${JSON.stringify(src)};
var IS_HLS = ${hls ? 'true' : 'false'};
var BACKEND_URL = 'https://davidhzhdhd-my-telegram-bot.hf.space';
var STREAM_BACKEND_URL = 'https://maco11.onrender.com';

function postMsg(m){try{window.ReactNativeWebView&&window.ReactNativeWebView.postMessage(JSON.stringify(m));}catch{}}

// ── MediaSession (lock-screen controls) ──────────────────────
function setupMediaSession(videoEl){
  if(!('mediaSession' in navigator))return;
  var art=MOVIE.poster_url?[{src:MOVIE.poster_url,sizes:'512x512',type:'image/jpeg'}]:[];
  try{navigator.mediaSession.metadata=new MediaMetadata({title:MOVIE.title||'ZOVEX',artist:MOVIE.year?String(MOVIE.year):'',artwork:art});}catch{}
  var seek=function(s){try{videoEl.currentTime=Math.max(0,videoEl.currentTime+s);}catch{}};
  var safe=function(a,h){try{navigator.mediaSession.setActionHandler(a,h);}catch{}};
  safe('play',function(){videoEl.play().catch(function(){});});
  safe('pause',function(){videoEl.pause();});
  safe('seekbackward',function(d){seek(-((d&&d.seekOffset)||10));});
  safe('seekforward',function(d){seek((d&&d.seekOffset)||10);});
  safe('stop',function(){videoEl.pause();videoEl.currentTime=0;});
  try{navigator.mediaSession.playbackState='playing';}catch{}
}
function clearMediaSession(){
  if(!('mediaSession' in navigator))return;
  try{navigator.mediaSession.metadata=null;}catch{}
  ['play','pause','seekbackward','seekforward','stop'].forEach(function(a){
    try{navigator.mediaSession.setActionHandler(a,null);}catch{}
  });
  try{navigator.mediaSession.playbackState='none';}catch{}
}

// ── Live viewer count heartbeat ───────────────────────────────
if(IS_LIVE&&MOVIE.id){
  var _vid=(function(){try{var id=localStorage.getItem('zovex_viewer_id');if(!id){id='v_'+Math.random().toString(36).slice(2)+Date.now().toString(36);try{localStorage.setItem('zovex_viewer_id',id);}catch{}}return id;}catch{return 'v_'+Math.random().toString(36).slice(2);}})();
  var _hbUrl=BACKEND_URL+'/api/live/'+encodeURIComponent(String(MOVIE.id))+'/heartbeat';
  var _lbUrl=BACKEND_URL+'/api/live/'+encodeURIComponent(String(MOVIE.id))+'/leave';
  var _hb=function(){
    fetch(_hbUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({viewer_id:_vid})})
    .then(function(r){return r.ok?r.json():null;}).then(function(d){
      if(d&&typeof d.viewers==='number'){
        var badge=document.getElementById('viewersbadge');
        var cnt=document.getElementById('viewercount');
        if(badge&&cnt){cnt.textContent=d.viewers.toLocaleString('he-IL')+' צופים עכשיו';badge.style.display='flex';}
      }
    }).catch(function(){});
  };
  _hb();setInterval(_hb,15000);
  var _leave=function(){try{var b=JSON.stringify({viewer_id:_vid});if(navigator.sendBeacon){navigator.sendBeacon(_lbUrl,b);}else{fetch(_lbUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:b,keepalive:true}).catch(function(){});}}catch{}};
  window.addEventListener('beforeunload',_leave);
}

// ── HLS auto-refresh every 25 min (updates stream URL without page reload) ──
var _refreshTimer=null;
var _currentSrc=[SRC];
function _startRefresh(shakaPl){
  if(_refreshTimer)clearInterval(_refreshTimer);
  _refreshTimer=setInterval(function(){
    fetch(STREAM_BACKEND_URL+'/api/refresh-stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_src:_currentSrc[0]})})
    .then(function(r){return r.ok?r.json():null;}).then(function(d){
      if(!d)return;
      var ns=d.hls_url||d.url;
      if(!ns||ns===_currentSrc[0])return;
      _currentSrc[0]=ns;
      if(shakaPl){try{shakaPl.load(ns).catch(function(){});}catch{}}
    }).catch(function(){});
  },25*60*1000);
}

var HAS_NEXT=${hasNext ? 'true' : 'false'};
var vid=null, dragging=false, hideTimer=null, ctrlsVisible=true, isFullscreen=false, nextShown=false;

var overlay=document.getElementById('overlay');
var loader=document.getElementById('loader');
var ctrls=document.getElementById('ctrls');
var topbar=document.getElementById('topbar');
var bottombar=document.getElementById('bottombar');
var progwrap=document.getElementById('progwrap');
var progfill=document.getElementById('progfill');
var progdot=document.getElementById('progdot');
var timestr=document.getElementById('timestr');
var playIcon=document.getElementById('playIcon');
var pauseIcon=document.getElementById('pauseIcon');
var skipanim=document.getElementById('skipanim');
var NEAR_END=60, NEAR_RATIO=0.95;

function fmt(s){if(!s||isNaN(s)||!isFinite(s))return'0:00';var m=Math.floor(s/60);return m+':'+(Math.floor(s%60)+'').padStart(2,'0');}
function usableDur(v){if(!v)return 0;if(Number.isFinite(v.duration)&&v.duration>0)return v.duration;try{if(v.seekable&&v.seekable.length>0){var e=v.seekable.end(v.seekable.length-1);if(Number.isFinite(e)&&e>0)return e;}}catch{}return 0;}

function onProgress(){
  var dur=usableDur(vid);
  if(!dur||!Number.isFinite(dur))return;
  var finished=(dur-vid.currentTime)<=NEAR_END||(vid.currentTime/dur)>=NEAR_RATIO;
  postMsg({type:'progress',position:finished?0:Math.floor(vid.currentTime),duration:Math.floor(dur)});
}

setInterval(function(){if(vid&&!vid.paused&&!vid.ended)onProgress();},5000);

function updateUI(){
  if(!vid)return;
  var dur=usableDur(vid);
  var ct=vid.currentTime;
  if(!IS_LIVE&&progfill&&dur>0){var pct=(ct/dur)*100;progfill.style.width=pct+'%';if(progdot)progdot.style.left=pct+'%';}
  if(!IS_LIVE&&timestr)timestr.textContent=fmt(ct)+' / '+fmt(dur);
  playIcon.style.display=vid.paused?'block':'none';
  pauseIcon.style.display=vid.paused?'none':'block';
  renderMuteIcon(vid.muted);
  checkNextEp();
}

function showCtrls(){
  ctrlsVisible=true;
  overlay.style.opacity=1;topbar.style.opacity=1;bottombar.style.opacity=1;ctrls.style.opacity=1;
  overlay.style.pointerEvents='auto';topbar.style.pointerEvents='auto';bottombar.style.pointerEvents='auto';ctrls.style.pointerEvents='auto';
  clearTimeout(hideTimer);
  hideTimer=setTimeout(function(){
    ctrlsVisible=false;
    [topbar,bottombar,ctrls].forEach(function(el){el.style.opacity=0;el.style.pointerEvents='none';});
  },3500);
}

function toggleCtrls(){if(ctrlsVisible){clearTimeout(hideTimer);[topbar,bottombar,ctrls].forEach(function(el){el.style.opacity=0;el.style.pointerEvents='none';});ctrlsVisible=false;}else{showCtrls();}}
function checkNextEp(){
  if(!HAS_NEXT||nextShown||!vid||IS_LIVE)return;
  var dur=usableDur(vid);if(!dur||dur<30)return;
  if(dur-vid.currentTime<=300&&vid.currentTime>0){
    nextShown=true;
    var card=document.getElementById('nextcard');
    if(card)card.style.display='block';
    showCtrls();
  }
}
function goNextEp(){postMsg({type:'next_episode'});}

overlay.addEventListener('click',function(e){if(e.target===overlay)toggleCtrls();});
showCtrls();

function togglePlay(){if(!vid)return;vid.paused?vid.play():vid.pause();}
function toggleMute(){
  if(!vid)return;
  vid.muted=!vid.muted;
  updateUI();
}
function renderMuteIcon(muted){
  var btn=document.getElementById('mutebtn');
  if(!btn)return;
  if(muted){
    btn.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="1" y1="1" x2="23" y2="23"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/><path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg>';
  } else {
    btn.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>';
  }
}

function goFullscreen(){
  isFullscreen=!isFullscreen;
  postMsg({type:'fullscreen',enter:isFullscreen});
  renderFsIcon(isFullscreen);
}
function renderFsIcon(fs){
  var btn=document.getElementById('fsbtn');
  if(!btn)return;
  if(fs){
    btn.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"/></svg>';
  } else {
    btn.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>';
  }
}

// ── PiP button ────────────────────────────────────────────────
var pipbtn=document.getElementById('pipbtn');
if(pipbtn&&document.pictureInPictureEnabled){
  pipbtn.style.display='flex';
  pipbtn.innerHTML='<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2"/><rect x="12" y="12" width="8" height="6" rx="1"/></svg>';
  pipbtn.addEventListener('click',function(){
    if(!vid)return;
    try{if(document.pictureInPictureElement){document.exitPictureInPicture().catch(function(){});}
    else{vid.requestPictureInPicture().catch(function(){});}}catch{}
  });
}

function skip(s){
  if(!vid)return;
  vid.currentTime=Math.max(0,vid.currentTime+s);
  var anim=document.getElementById('skipanim');
  var icon=document.getElementById('skipicon');
  var txt=document.getElementById('skiptext');
  if(s>0){anim.style.right='6%';anim.style.left='';icon.textContent='▶▶';txt.textContent='+10 שניות';}
  else{anim.style.left='6%';anim.style.right='';icon.textContent='◀◀';txt.textContent='-10 שניות';}
  anim.style.display='block';
  anim.style.animation='none';anim.offsetHeight;anim.style.animation='fadeInOut .7s ease forwards';
  setTimeout(function(){anim.style.display='none';},700);
}
function doShare(){try{navigator.share&&navigator.share({title:MOVIE.title||'ZOVEX'});}catch{}}

var playbtn=document.getElementById('playbtn');
var skipbackbtn=document.getElementById('skipback');
var skipfwdbtn=document.getElementById('skipfwd');
var sharebtn=document.getElementById('sharebtn');
var closebtn=document.getElementById('closebtn');
if(playbtn)playbtn.addEventListener('click',togglePlay);
if(skipbackbtn)skipbackbtn.addEventListener('click',function(){skip(-10);});
if(skipfwdbtn)skipfwdbtn.addEventListener('click',function(){skip(10);});
if(sharebtn)sharebtn.addEventListener('click',doShare);
if(closebtn)closebtn.addEventListener('click',function(){postMsg({type:'close'});});
document.getElementById('mutebtn').addEventListener('click',toggleMute);
document.getElementById('fsbtn').addEventListener('click',goFullscreen);

// ── Seek bar ──────────────────────────────────────────────────
function doSeek(e){
  if(!vid||!progwrap)return;
  var dur=usableDur(vid);if(!dur)return;
  var rect=progwrap.getBoundingClientRect();
  var x=(e.clientX!=null?e.clientX:(e.touches&&e.touches[0]?e.touches[0].clientX:0))-rect.left;
  var ratio=Math.max(0,Math.min(1,x/rect.width));
  vid.currentTime=ratio*dur;updateUI();
}
if(progwrap){
  progwrap.addEventListener('mousedown',function(e){dragging=true;doSeek(e);});
  document.addEventListener('mousemove',function(e){if(dragging)doSeek(e);});
  document.addEventListener('mouseup',function(){dragging=false;});
  progwrap.addEventListener('touchstart',function(e){e.preventDefault();dragging=true;doSeek(e);},{passive:false,capture:true});
  progwrap.addEventListener('touchmove',function(e){if(dragging){e.preventDefault();doSeek(e);}},{passive:false});
  progwrap.addEventListener('touchend',function(){dragging=false;});
}

function initVideo(el){
  vid=el;
  function showResume(t){
    var rt=document.getElementById('resumetoast');if(!rt)return;
    var m=Math.floor(t/60);var s=Math.floor(t%60);
    rt.textContent='ממשיך מ-'+m+':'+(s<10?'0'+s:s);
    rt.style.display='block';rt.style.animation='none';rt.offsetHeight;
    rt.style.animation='resumeFade 3s ease forwards';
    setTimeout(function(){rt.style.display='none';},3000);
  }
  window._seekTo=function(t){
    if(!vid)return;
    var doShow=function(){if(t>5)showResume(t);};
    if(vid.readyState>=1){try{vid.currentTime=t;}catch{}doShow();}
    else{vid.addEventListener('loadedmetadata',function(){try{vid.currentTime=t;}catch{}doShow();},{once:true});}
  };
  renderMuteIcon(false);
  renderFsIcon(false);
  updateUI();
  vid.addEventListener('timeupdate',updateUI);
  vid.addEventListener('loadedmetadata',updateUI);
  vid.addEventListener('durationchange',updateUI);
  vid.addEventListener('play',function(){updateUI();postMsg({type:'video_playing',value:true});});
  vid.addEventListener('pause',function(){updateUI();postMsg({type:'video_playing',value:false});});
  vid.addEventListener('ended',function(){onProgress();postMsg({type:'video_playing',value:false});clearMediaSession();});
  vid.addEventListener('waiting',function(){loader.style.display='flex';});
  vid.addEventListener('playing',function(){loader.style.display='none';showCtrls();setupMediaSession(vid);});
  vid.addEventListener('canplay',function(){loader.style.display='none';});
}

function tryLoadScript(url,onOk,onFail){
  var s=document.createElement('script');s.src=url;
  s.onload=onOk;s.onerror=onFail;
  document.head.appendChild(s);
}

if(IS_HLS){
  // ── Shaka Player (primary) ────────────────────────────────
  function startWithShaka(){
    var v=document.createElement('video');
    v.setAttribute('playsinline','');v.setAttribute('autoplay','');
    v.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000';
    document.getElementById('wrap').insertBefore(v,loader);
    initVideo(v);
    window.shaka.polyfill.installAll();
    var player=new window.shaka.Player();
    player.attach(v).then(function(){
      return player.load(SRC);
    }).then(function(){
      if(START>1){try{v.currentTime=START;}catch{}}
      v.play().catch(function(){});
      loader.style.display='none';
      _startRefresh(player);
    }).catch(function(){
      // Shaka failed — fall through to HLS.js
      player.destroy().catch(function(){});
      v.parentNode&&v.parentNode.removeChild(v);
      vid=null;
      startWithHlsJs();
    });
  }

  // ── HLS.js (fallback) ────────────────────────────────────
  function startWithHlsJs(){
    var v=document.createElement('video');
    v.setAttribute('playsinline','');v.setAttribute('autoplay','');
    v.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000';
    document.getElementById('wrap').insertBefore(v,loader);
    initVideo(v);
    if(window.Hls&&Hls.isSupported()){
      var hls=new Hls({maxBufferLength:30,enableWorker:false});
      hls.loadSource(SRC);hls.attachMedia(v);
      hls.on(Hls.Events.MANIFEST_PARSED,function(){
        if(START>1){try{v.currentTime=START;}catch{}}
        v.play().catch(function(){});loader.style.display='none';
        _startRefresh(null);
      });
      hls.on(Hls.Events.ERROR,function(ev,d){if(d.fatal)loader.style.display='none';});
    } else if(v.canPlayType('application/vnd.apple.mpegurl')){
      v.src=SRC;
      v.addEventListener('loadedmetadata',function(){
        if(START>1){try{v.currentTime=START;}catch{}}
        v.play().catch(function(){});loader.style.display='none';
      });
    } else {
      loader.style.display='none';
    }
  }

  // Try Shaka first; if it fails to load, fall back to HLS.js
  tryLoadScript(
    'https://cdnjs.cloudflare.com/ajax/libs/shaka-player/4.7.11/shaka-player.compiled.js',
    startWithShaka,
    function(){
      tryLoadScript(
        'https://cdnjs.cloudflare.com/ajax/libs/hls.js/1.4.12/hls.min.js',
        startWithHlsJs,
        function(){
          tryLoadScript(
            'https://cdn.jsdelivr.net/npm/hls.js@1.4.12/dist/hls.min.js',
            startWithHlsJs,
            function(){
              var v=document.createElement('video');
              v.setAttribute('playsinline','');v.setAttribute('autoplay','');
              v.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000';
              v.src=SRC;
              document.getElementById('wrap').insertBefore(v,loader);
              initVideo(v);
              v.addEventListener('loadedmetadata',function(){
                if(START>1){try{v.currentTime=START;}catch{}}
                v.play().catch(function(){});loader.style.display='none';
              });
              v.addEventListener('error',function(){loader.style.display='none';});
            }
          );
        }
      );
    }
  );
} else {
  // ── Direct video (MP4, stream, telegram proxy, etc.) ─────
  var v=document.createElement('video');
  v.setAttribute('playsinline','');v.setAttribute('autoplay','');
  v.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000';
  v.src=SRC;
  document.getElementById('wrap').insertBefore(v,loader);
  initVideo(v);
  v.addEventListener('loadedmetadata',function(){
    if(START>1){try{v.currentTime=START;}catch{}}
    v.play().catch(function(){});loader.style.display='none';
  });
  v.addEventListener('error',function(){loader.style.display='none';});
}
window.addEventListener('beforeunload',function(){clearMediaSession();if(_refreshTimer)clearInterval(_refreshTimer);});
})();
</script>
</body></html>`;
}

export default function PlayerScreen({route, navigation}) {
  const {movie, startTime = 0, userId = null, seriesEpisodes = null, onLeaveCleanup = null} = route.params;
  const progressRef = useRef({position: startTime, duration: 0});
  const seriesEpisodesRef = useRef(seriesEpisodes);
  const isLive = !!movie.is_live;
  const webViewRef = useRef(null);
  const nextEpIdx = seriesEpisodes ? seriesEpisodes.findIndex(e => e.id === movie.id) : -1;
  const hasNext = nextEpIdx >= 0 && nextEpIdx < (seriesEpisodes?.length ?? 0) - 1;

  const {src, html, isIframe} = useMemo(() => {
    const s = buildSrc(movie, isLive ? 0 : startTime);
    if (!s) return {src: null, html: null, isIframe: false};
    const iframe = isIframeUrl(s, movie.type || 'direct');
    return {
      src: s,
      html: buildPlayerHtml(movie, s, isLive ? 0 : startTime, isLive, hasNext),
      isIframe: iframe,
    };
  }, [movie, startTime, isLive, hasNext]);

  useEffect(() => {
    if (userId) saveHistory(movie.id, movie.title, movie.thumbnail_url, userId);
    return () => {
      StatusBar.setHidden(false, 'fade');
      PipModule?.setFullscreen(false);
      PipModule?.setLandscape(false);
      PipModule?.setVideoPlaying(false);
      if (!userId) return;
      const {position, duration} = progressRef.current;
      if (position > 5 && duration > 0)
        saveProgress(movie.id, position, duration, userId);
    };
  }, [movie.id, movie.title, movie.thumbnail_url, userId]);

  // Offline-download playback decrypts to a short-lived temp file before
  // navigating here (see HomeScreen's playDownloadedItem) - delete it once
  // this screen unmounts, whether the user backs out or plays something else.
  useEffect(() => {
    return () => {
      onLeaveCleanup?.();
    };
  }, [onLeaveCleanup]);

  // Load saved progress in background and seek once the video is ready
  useEffect(() => {
    if (!userId || startTime > 0 || isLive) return;
    loadProgress(movie.id, userId).then(pos => {
      if (pos > 5 && webViewRef.current) {
        progressRef.current.position = pos;
        webViewRef.current.injectJavaScript(
          `window._seekTo&&window._seekTo(${Math.floor(pos)});true;`,
        );
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onMessage = event => {
    try {
      const m = JSON.parse(event.nativeEvent.data);
      if (m.type === 'close') {
        navigation.goBack();
      } else if (m.type === 'fullscreen') {
        StatusBar.setHidden(m.enter, 'fade');
        PipModule?.setFullscreen(!!m.enter);
        PipModule?.setLandscape(!!m.enter);
      } else if (m.type === 'video_playing') {
        PipModule?.setVideoPlaying(!!m.value);
      } else if (m.type === 'next_episode') {
        const eps = seriesEpisodesRef.current;
        if (!eps) return;
        const idx = eps.findIndex(e => e.id === movie.id);
        const next = idx >= 0 && idx < eps.length - 1 ? eps[idx + 1] : null;
        if (next) navigation.replace('Player', {movie: next, startTime: 0, userId, seriesEpisodes: eps});
      } else if (m.type === 'progress' && userId) {
        progressRef.current = {position: m.position, duration: m.duration};
        saveProgress(movie.id, m.position, m.duration, userId);
      }
    } catch (_) {}
  };

  if (!src) {
    return (
      <View style={styles.error}>
        <View style={styles.errorBox}>
          <View style={styles.errorClose} />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <WebView
        ref={webViewRef}
        source={{html}}
        style={styles.player}
        allowsInlineMediaPlayback
        mediaPlaybackRequiresUserAction={false}
        allowsFullscreenVideo
        javaScriptEnabled
        domStorageEnabled
        allowFileAccess
        allowFileAccessFromFileURLs
        allowUniversalAccessFromFileURLs
        startInLoadingState={false}
        onMessage={onMessage}
        onMessageForMainFrameOnly={false}
        injectedJavaScriptForMainFrameOnly={false}
        injectedJavaScriptBeforeContentLoadedForMainFrameOnly={false}
        mixedContentMode="always"
        originWhitelist={['*']}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#000'},
  player: {flex: 1, backgroundColor: '#000'},
  error: {flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#000'},
  errorBox: {width: 60, height: 60, borderRadius: 30, backgroundColor: '#1a1a1a', justifyContent: 'center', alignItems: 'center'},
  errorClose: {width: 24, height: 3, backgroundColor: '#555', borderRadius: 2},
});
