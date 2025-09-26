import { auth } from './firebase.js';

// Use production cloud function URL when deployed, local proxy for development
const API_BASE_URL = import.meta.env.PROD 
  ? "https://asia-south1-billingonaire.cloudfunctions.net/billingonaire-backend"
  : "/api";

// Helper function to make authenticated API calls
export const authenticatedFetch = async (url, options = {}) => {
  try {
    const user = auth.currentUser;
    if (!user) {
      throw new Error('User not authenticated');
    }

    // Get the Firebase ID token
    const idToken = await user.getIdToken();
    
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
    const response = await fetch(`${API_BASE_URL}${url}`, {
      ...options,
      headers
    });

    if (!response.ok) {
      throw new Error(`API call failed: ${response.status} ${response.statusText}`);
    }

    return response;
  } catch (error) {
    console.error('API call failed:', error);
    throw error;
  }
};

// Helper function to make authenticated API calls and return JSON
export const authenticatedFetchJSON = async (url, options = {}) => {
  const response = await authenticatedFetch(url, options);
  return response.json();
};