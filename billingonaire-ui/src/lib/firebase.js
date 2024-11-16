import { initializeApp } from 'firebase/app';
import { getAuth, onAuthStateChanged } from 'firebase/auth';
import { getFirestore, doc, getDoc } from 'firebase/firestore';

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
const auth = getAuth(app);
const db = getFirestore(app);

const getUserRole = (user) => {
  return new Promise((resolve, reject) => {
    onAuthStateChanged(auth, async (user) => {
      if (user) {
        try {
          const userDoc = await getDoc(doc(db, "roles", user.uid));
          if (userDoc.exists()) {
            resolve(userDoc.data().role);
          } else {
            resolve(null);
          }
        } catch (error) {
          reject(error);
        }
      } else {
        resolve(null);
      }
    });
  });
};

export { app, auth, getUserRole };
