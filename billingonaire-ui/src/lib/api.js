import { auth } from './firebase.js';

// Use environment variable for API URL, fallback to /api for development proxy
const API_BASE_URL = import.meta.env.VITE_API_URL || "/api";

// Helper to build API URLs
export const getApiUrl = (path) => {
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  if (API_BASE_URL.startsWith('http')) {
    return `${API_BASE_URL}${cleanPath}`;
  }
  return `${API_BASE_URL}${cleanPath}`;
};

// Helper function to make authenticated API calls
export const authenticatedFetch = async (url, options = {}) => {
  try {
    const user = auth.currentUser;
    console.log('🔐 authenticatedFetch: Current user:', user ? user.email : 'NOT LOGGED IN');

    if (!user) {
      console.error('❌ authenticatedFetch: No authenticated user found');
      throw new Error('User not authenticated');
    }

    // Get the Firebase ID token
    console.log('🎫 authenticatedFetch: Getting Firebase ID token...');
    const idToken = await user.getIdToken();
    console.log('✅ authenticatedFetch: Token obtained (length:', idToken?.length, ')');

    // Set up headers with authentication
    const headers = {
      'Authorization': `Bearer ${idToken}`,
      ...options.headers
    };

    // Only set Content-Type for non-FormData requests
    if (!(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }

    // Make the API call - use API_BASE_URL prefix with Vite proxy
    const fullUrl = `${API_BASE_URL}${url}`;
    console.log('📡 authenticatedFetch: Making request to:', fullUrl);
    console.log('📡 authenticatedFetch: Method:', options.method || 'GET');

    const response = await fetch(fullUrl, {
      ...options,
      headers
    });

    console.log('📥 authenticatedFetch: Response status:', response.status, response.statusText);

    if (!response.ok) {
      const errorText = await response.text();
      console.error('❌ authenticatedFetch: API error response:', errorText);
      throw new Error(`API call failed: ${response.status} ${response.statusText}`);
    }

    console.log('✅ authenticatedFetch: Request successful');
    return response;
  } catch (error) {
    console.error('❌ authenticatedFetch: Exception caught:', error);
    throw error;
  }
};

// Helper function to make authenticated API calls and return JSON
export const authenticatedFetchJSON = async (url, options = {}) => {
  const response = await authenticatedFetch(url, options);
  return response.json();
};
