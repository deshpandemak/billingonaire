import { auth } from './firebase.js';

const API_BASE_URL = "/api";

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
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${idToken}`,
      ...options.headers
    };

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