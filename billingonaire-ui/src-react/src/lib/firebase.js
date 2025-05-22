// Firebase configuration for React app
import { initializeApp } from 'firebase/app';
import { getAuth } from 'firebase/auth';

const firebaseConfig = {
  apiKey: "AIzaSyDPv9Tp-we4lIF81BIfyN3-p3yh2o52fAE",
  authDomain: "billingonaire.firebaseapp.com",
  projectId: "billingonaire",
  storageBucket: "billingonaire.appspot.com",
  messagingSenderId: "819125105651",
  appId: "1:819125105651:web:53cfe0b3564110bd335886",
  measurementId: "G-1KD3K4H7KV"
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
