import React from 'react';
import {StatusBar} from 'react-native';
import {NavigationContainer} from '@react-navigation/native';
import {createNativeStackNavigator} from '@react-navigation/native-stack';
import {SafeAreaProvider} from 'react-native-safe-area-context';

import HomeScreen from './screens/HomeScreen';
import SeriesScreen from './screens/SeriesScreen';
import PlayerScreen from './screens/PlayerScreen';

const Stack = createNativeStackNavigator();

export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar barStyle="light-content" backgroundColor="#000" />
      <NavigationContainer>
        <Stack.Navigator
          screenOptions={{
            headerStyle: {backgroundColor: '#0a0a0a'},
            headerTintColor: '#fff',
            headerTitleStyle: {fontWeight: 'bold'},
            animation: 'slide_from_right',
          }}>
          <Stack.Screen
            name="Home"
            component={HomeScreen}
            options={{title: 'ZOVEX'}}
          />
          <Stack.Screen
            name="Series"
            component={SeriesScreen}
            options={({route}) => ({title: route.params?.seriesName || 'סדרה'})}
          />
          <Stack.Screen
            name="Player"
            component={PlayerScreen}
            options={{
              title: '',
              headerTransparent: true,
            }}
          />
        </Stack.Navigator>
      </NavigationContainer>
    </SafeAreaProvider>
  );
}
