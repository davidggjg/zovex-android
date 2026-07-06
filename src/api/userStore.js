import AsyncStorage from '@react-native-async-storage/async-storage';

let _userId = null;

export const getUserId = () => _userId;
export const setUserId = id => {
  _userId = id;
};

export async function initUserId() {
  try {
    let id = await AsyncStorage.getItem('zovex_user_id');
    if (!id) {
      id = 'u_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
      await AsyncStorage.setItem('zovex_user_id', id);
    }
    _userId = id;
  } catch (_) {
    _userId = 'u_' + Math.random().toString(36).slice(2);
  }
}
