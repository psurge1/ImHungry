export const config = {
  apiUrl: import.meta.env.VITE_API_URL || 'https://kud8sdryy0.execute-api.us-west-2.amazonaws.com/dev',
  userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID || 'us-west-2_pvA4Z82k5',
  userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID || '2cm2uoqc3e5nc9lmaisqejqg9r',
};
