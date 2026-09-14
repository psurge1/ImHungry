import React from 'react';
import ReactDOM from 'react-dom/client';
import { Amplify } from 'aws-amplify';
import { cognitoUserPoolsTokenProvider } from 'aws-amplify/auth/cognito';
import { CookieStorage } from 'aws-amplify/utils';
import { Authenticator } from '@aws-amplify/ui-react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '@aws-amplify/ui-react/styles.css';
import './style.css';
import { config } from './config';
import App from './App';

Amplify.configure({Auth: {Cognito: {userPoolId: config.userPoolId, userPoolClientId: config.userPoolClientId, loginWith: {email: true}}}});
cognitoUserPoolsTokenProvider.setKeyValueStorage(new CookieStorage({path: '/', sameSite: 'strict', secure: location.protocol === 'https:', expires: 1}));
const client = new QueryClient({defaultOptions: {queries: {retry: false, staleTime: 15000}, mutations: {retry: false}}});
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><QueryClientProvider client={client}>
    <header className="brand"><span className="logo">ih</span><div><strong>ImHungry</strong><small>Food, habits, and a little help.</small></div></header>
    <Authenticator loginMechanisms={['email']} signUpAttributes={['email']}>
      {({signOut, user}) => <App key={user?.userId} onSignOut={() => { client.clear(); signOut?.(); }} />}
    </Authenticator>
  </QueryClientProvider></React.StrictMode>
);
