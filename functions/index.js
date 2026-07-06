const functions = require('firebase-functions');
const admin = require('firebase-admin');

admin.initializeApp();

// HTTP function called from the website admin panel to broadcast a push notification
// to all app users who are subscribed to the 'allUsers' FCM topic.
//
// The 'secret' field guards against unauthorized use — it is the same string
// used in the admin panel UI, so keep it in sync if changed here.
exports.sendNotification = functions.https.onRequest(async (req, res) => {
  res.set('Access-Control-Allow-Origin', '*');
  res.set('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.set('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.status(204).send('');
    return;
  }

  if (req.method !== 'POST') {
    res.status(405).json({error: 'Method not allowed'});
    return;
  }

  const {title, body, secret} = req.body || {};

  if (secret !== 'ZovexAdmin2026') {
    res.status(401).json({error: 'Unauthorized'});
    return;
  }

  if (!title || !body) {
    res.status(400).json({error: 'title and body are required'});
    return;
  }

  try {
    await admin.messaging().send({
      notification: {title, body},
      android: {
        priority: 'high',
        notification: {sound: 'default', channelId: 'default'},
      },
      topic: 'allUsers',
    });
    res.json({success: true});
  } catch (e) {
    res.status(500).json({error: e.message});
  }
});
