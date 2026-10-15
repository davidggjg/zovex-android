// אייקוני סרגל הניווט התחתון והסרגל העליון.
//
// למה PNG ולא אימוג'י: האימוג'י (🏠 🔍 ❤️ 👤) מצויר בגופן של היצרן, בצבעים
// ובעומק שונים בכל מכשיר — וזה בדיוק מה ש\"נראה כמו מדבקות\". כאן לבן עם
// אלפא, ולכן tintColor נותן אייקון חד וחד-גוני כמו באפליקציות סטרימינג.
// אין react-native-svg בפרויקט, ולכן אותה שיטה כמו ב-playerIcons.js —
// בלי תלות נייטיבית חדשה ובלי סיכון לבנייה. 96px מכסה xxhdpi ב-32dp.
// *_ON = גרסה מלאה למצב פעיל (כמו בנטפליקס), השאר קו דק.

const png = s => ({uri: 'data:image/png;base64,' + s});

export const NAV_HOME = png(
  'iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAYAAADimHc4AAAFEElEQVR42u2dvascVRjGn3d2vZCr1+TGKrewUgTBIhBNYaMohohY' +
  'prAUJI2F+Q8UwUILizR+/gF2lhaCFoFgAmpQEewU0SbmZiWgZnfmsbjv0cMys/O9c87M+8Aws7uzM2ff55z3d+bMnHsBk8lkMplM' +
  'proiKSTFIjFM4Gfe6xnJxCKzneAn3vYuyRN5n5n6Cf5M1wckPyT5C8mbJD8leVY/m1uk+gn+XNePauDXtSR5wUtJxoYegv+k1niS' +
  'vEsy02Wpa5K8aFzoAbYkX9FAk2Sa0wIy7/331tOWqWG+1+13c4LMAhNWuv0ZyX3jQruUs0/yE6/WZ6wm11K+JnnaTGjW03mY5DUv' +
  '39eVM+EWyXMG5/qw/WMtkHlKvZSTJ/8zg3MD2FYN7qqiSQbnjmDrUtIXJN/3TMgMzv3C1g/kxyTv1e9fqtgaDM4tYOu3iNdzTLyg' +
  'wC3jhsG5AWxdrf6T5MvrQSN5j64fJ/lTTX5MB84NYev2+Y3kE37AC0w9SfJKzR7U+OHcErbXSJ4qy9meuXOSHxicu4PtXtXaSTLx' +
  'UtNrk4dzh7BNaqa6ZPJw7hq2Dc4/TTj3CdsWlWAacN4GbFukwXHDeZuwbVC2ccN5CNg2TI3jg/PQsJ0snEOC7eTgHCJsJwPnkGE7' +
  'ejjHANvRwjk22I4GztpMo4Rt9HBeexo5StgOCOdZ69yo64PYYTsAnM+2Yp2bfULyFMmfKzbFoGG7JTivvH2ebVwBvWb4kR7w77HA' +
  'dgtwdgb9SHKndhy8prdH8nfvMfDRwHZLcM68mMyaGHCS5KGX34vSTpSw7QjOWUlKfqaNAftefz/LOUEaO2xbwvkSyb8KeoTuvafa' +
  'GnArxwC3fUjy2FSCXwDnLwuY4Ax4elN82vZQCGBXDcumYoCI0Atq2uZYXXQRM1egqUlEUgAytAEmM8AMMJkBcSrIi6a+hjBC7CzM' +
  'Awx8or2LXi6i1IjMDMgJvtbQlOQugB1XcTu4VgEAishi7VxmgB8QkgcA3gDwHID7Ogi+rxXJqwDeEpGvSCYhtIR5IGkHOph3FcCD' +
  'PZ7uRQDPkzwvIp+TnPWV7mLqBSWaDt7U4P+jaaOP5a5Wusskd0IYPkkCSD2pjqa+oEHa0dTTx+KC/giA05r2ZlNvAS4VzjvO+WU6' +
  'NvkLMa2BCYDbAH7Qt7MNvZk6S9ExEgALAN+XnG86vSA1YlW2W5fZD8AqlKYfisoCfAfAUvfjhmO4Wn5/yTHFDKimTAP6EoArul2W' +
  'No4D+AbACTUk2KczYrqBvhCRw4q9q9WGVmIGNC2rXrRtug3oUlA0j8XEZAAV1iwaxyHpgB7NLVK7H2AGmAEmM8AMMJkBZoDJDDAD' +
  'TGaAGWDaoroYC3L/y0saDsEM9b/Agih3FwYsdXCs6QBYCgADDKAFUe62BgiAB1pOzBtiCDmYcs9bnBw4uvP0LY7uUEnD2uS+t6ev' +
  'Zz0HPqhyd9ECjkfIvmDK3QUD2HHt3JaCKPc8osBJ4MdrdJ6kQi0hwrjBndas3VGUO9cA75nJBYDr6uKy4Af2sfiFJ4CbAG6UzUeO' +
  'tdz5Vej/meBnvFnfackfaupK2drM81e1LLOxlVtKfoybOHEOwDsAHtOPFi27cGVdu319/SuAt0Xkcp0JFTGVW6rUKBHJtGadAbAL' +
  '4Dv0+1DrQziaIXNdRO40mVIUa7mLfsxgz9C3OXcM5ZYaBxQP2n0/0v3fedrWoFjLbTKZTCaTqWf9C/PpToQkBNJCAAAAAElFTkSu' +
  'QmCC');
