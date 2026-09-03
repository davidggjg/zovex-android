import React, {useEffect, useState, useCallback} from 'react';
import {
  View, Text, Image, ScrollView, StyleSheet, Modal, ActivityIndicator,
} from 'react-native';
import TvFocusable from './TvFocusable';
import {fetchChannelSchedule, splitNowNext, channelSlug} from '../api/epg';
import {
  remindersSupported, reminderId, listReminders, addReminder, removeReminder,
  canNotify, requestNotificationPermission,
} from '../api/reminders';

// ── דף ערוץ שידור חי ─────────────────────────────────────────────────────────
// עד עכשיו לחיצה על ערוץ קפצה ישר לנגן, בלי לומר מה בכלל משודר. כאן אותו
// מבנה שיש לסרט: תמונה, שם, מה משודר עכשיו, כפתור צפייה, ומתחת לוח השידורים
// של הערוץ הזה בלבד.
//
// לא לכל ערוץ יש לוח — ערוצי VOD וסרטים רצופים אין להם לוח לינארי מטבעם —
// ובמקרה כזה מוצג הדף בלי החלק התחתון במקום הודעה מיותרת. כל עוד הלוח נטען
// מוצג סימון טעינה: בלעדיו "עדיין לא הגיע" נראה בדיוק כמו "אין".

const fmt = ep =>
  new Date(ep * 1000).toLocaleTimeString('he-IL', {hour: '2-digit', minute: '2-digit'});

export default function LiveChannelModal({channel, onPlay, onClose}) {
  const [programs, setPrograms] = useState(null);   // null = טוען
  const [, tick] = useState(0);

  useEffect(() => {
    let alive = true;
    setPrograms(null);
    fetchChannelSchedule(channel)
      .then(p => { if (alive) setPrograms(p); })
      .catch(() => { if (alive) setPrograms([]); });
    return () => { alive = false; };
  }, [channel]);

  // מרענן את החלוקה ל"עכשיו/הבא" בלי למשוך שוב מהרשת
  useEffect(() => {
    const id = setInterval(() => tick(x => x + 1), 60000);
    return () => clearInterval(id);
  }, []);

  // אילו תוכניות כבר יש להן תזכורת. האזעקה עצמה חיה במערכת ואי אפשר לשאול
  // אותה מה קיים, ולכן הרשימה נשמרת מקומית — רק כדי שהכפתור יידע להראות
  // "יזכיר" כשחוזרים לאותו ערוץ.
  const [reminded, setReminded] = useState({});
  useEffect(() => {
    let alive = true;
    listReminders().then(m => { if (alive) setReminded(m); });
    return () => { alive = false; };
  }, [channel]);

  const play = useCallback(() => onPlay(channel), [onPlay, channel]);

  const toggleRemind = useCallback(async program => {
    const slug = channelSlug(channel);
    const id = reminderId(slug, program);
    if (reminded[id]) {
      await removeReminder(slug, program);
      setReminded(m => { const n = {...m}; delete n[id]; return n; });
      return;
    }
    // אם ההתראות כבויות, בקשה אחת — אחרת התזכורת תיקבע ולא תופיע לעולם.
    if (!(await canNotify())) requestNotificationPermission();
    if (await addReminder(slug, channel.title || channel.name || '', program)) {
      setReminded(m => ({...m, [id]: program.start}));
    }
  }, [channel, reminded]);

  if (!channel) return null;
  const title = channel.title || channel.name || 'שידור חי';
  const {current, upcoming} = splitNowNext(programs || []);

  return (
    <Modal transparent animationType="fade" visible onRequestClose={onClose}>
      <View style={s.overlay}>
        <TvFocusable style={s.closeBtn} onPress={onClose}>
          <Text style={s.closeTxt}>✕</Text>
        </TvFocusable>

        <ScrollView showsVerticalScrollIndicator={false} bounces={false}>
          {channel.thumbnail_url ? (
            <Image source={{uri: channel.thumbnail_url}} style={s.thumb} />
          ) : (
            <View style={s.noThumb} />
          )}

          <View style={s.body}>
            <Text style={s.title} numberOfLines={2}>{title}</Text>

            <View style={s.liveTag}>
              <View style={s.liveDot} />
              <Text style={s.liveTxt}>שידור חי</Text>
            </View>

            {!!current && (
              <View style={s.nowBox}>
                <Text style={s.nowLabel}>עכשיו משודר</Text>
                <Text style={s.nowTitle}>{current.title || '—'}</Text>
                <Text style={s.nowTime}>{fmt(current.start)} – {fmt(current.end)}</Text>
                {!!current.desc && <Text style={s.nowDesc}>{current.desc}</Text>}
              </View>
            )}

            <TvFocusable style={s.playBtn} onPress={play} hasFocus>
              <Text style={s.playTxt}>▶ צפה בשידור החי</Text>
            </TvFocusable>

            {programs === null ? (
              <View style={s.loading}>
                <ActivityIndicator color="#e50914" />
                <Text style={s.loadingTxt}>טוען לוח שידורים…</Text>
              </View>
            ) : upcoming.length > 0 ? (
              <View style={s.sched}>
                <Text style={s.schedHead}>לוח שידורים</Text>
                {upcoming.slice(0, 40).map((p, i) => {
                  const isNow = current && p.start === current.start;
                  const rid = reminderId(channelSlug(channel), p);
                  const isSet = !!reminded[rid];
                  return (
                    <View key={`${p.start}_${i}`} style={[s.row, isNow && s.rowNow]}>
                      <Text style={[s.rowTime, isNow && s.rowTimeNow]}>{fmt(p.start)}</Text>
                      <View style={s.rowBody}>
                        <Text style={[s.rowTitle, isNow && s.rowTitleNow]} numberOfLines={1}>
                          {p.title || '—'}
                        </Text>
                        {!!p.desc && <Text style={s.rowDesc} numberOfLines={1}>{p.desc}</Text>}
                      </View>
                      {isNow ? (
                        <Text style={s.rowLive}>● עכשיו</Text>
                      ) : remindersSupported ? (
                        <TvFocusable
                          style={[s.remindBtn, isSet && s.remindBtnOn]}
                          onPress={() => toggleRemind(p)}>
                          <Text style={[s.remindTxt, isSet && s.remindTxtOn]}>
                            {isSet ? '🔔 יזכיר' : 'הזכר לי'}
                          </Text>
                        </TvFocusable>
                      ) : null}
                    </View>
                  );
                })}
              </View>
            ) : null}
          </View>
        </ScrollView>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  overlay: {...StyleSheet.absoluteFillObject, backgroundColor: '#0a0a0a'},
  closeBtn: {
    position: 'absolute', top: 14, right: 14, zIndex: 10,
    backgroundColor: 'rgba(0,0,0,0.65)', borderRadius: 20,
    width: 38, height: 38, justifyContent: 'center', alignItems: 'center',
  },
  closeTxt: {color: '#fff', fontSize: 14, fontWeight: '700'},
  thumb: {width: '100%', height: 260, resizeMode: 'cover'},
  noThumb: {width: '100%', height: 160, backgroundColor: '#1c1c1e'},
  body: {padding: 18},
  title: {color: '#fff', fontSize: 20, fontWeight: '800', textAlign: 'right', marginBottom: 8},
  liveTag: {
    flexDirection: 'row-reverse', alignItems: 'center', alignSelf: 'flex-end',
    backgroundColor: '#e50914', borderRadius: 20, paddingHorizontal: 12,
    paddingVertical: 4, marginBottom: 14, gap: 6,
  },
  liveDot: {width: 7, height: 7, borderRadius: 4, backgroundColor: '#fff'},
  liveTxt: {color: '#fff', fontSize: 12, fontWeight: '700'},
  nowBox: {marginBottom: 16},
  nowLabel: {color: '#ddd', fontSize: 13, fontWeight: '700', textAlign: 'right', marginBottom: 4},
  nowTitle: {color: '#fff', fontSize: 16, fontWeight: '800', textAlign: 'right'},
  nowTime: {color: '#e50914', fontSize: 13, textAlign: 'right', marginTop: 2},
  nowDesc: {color: '#bbb', fontSize: 13, lineHeight: 20, textAlign: 'right', marginTop: 6},
  playBtn: {backgroundColor: '#e50914', borderRadius: 12, paddingVertical: 14, alignItems: 'center'},
  playTxt: {color: '#fff', fontSize: 16, fontWeight: '800'},
  loading: {flexDirection: 'row-reverse', alignItems: 'center', gap: 8, marginTop: 22},
  loadingTxt: {color: '#888', fontSize: 13},
  sched: {marginTop: 24},
  schedHead: {color: '#fff', fontSize: 14, fontWeight: '900', textAlign: 'right', marginBottom: 10},
  row: {
    flexDirection: 'row-reverse', alignItems: 'center', gap: 12,
    backgroundColor: '#1a1a1a', borderRadius: 12, padding: 10, marginBottom: 8,
    borderWidth: 1, borderColor: '#2a2a2a',
  },
  rowNow: {backgroundColor: 'rgba(229,9,20,0.12)', borderColor: '#e50914'},
  rowTime: {color: '#888', fontSize: 14, fontWeight: '800', width: 46, textAlign: 'center'},
  rowTimeNow: {color: '#e50914'},
  rowBody: {flex: 1},
  rowTitle: {color: '#fff', fontSize: 14, fontWeight: '700', textAlign: 'right'},
  rowTitleNow: {fontWeight: '800'},
  rowDesc: {color: '#888', fontSize: 12, textAlign: 'right', marginTop: 2},
  rowLive: {color: '#e50914', fontSize: 12, fontWeight: '800'},
  remindBtn: {
    borderWidth: 1, borderColor: '#444', borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 6,
  },
  remindBtnOn: {backgroundColor: '#e50914', borderColor: '#e50914'},
  remindTxt: {color: '#bbb', fontSize: 12, fontWeight: '700'},
  remindTxtOn: {color: '#fff'},
});
