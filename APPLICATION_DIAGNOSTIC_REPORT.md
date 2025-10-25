# Application Health Check and Diagnostic Report
**Date**: October 25, 2025  
**Issue Reported**: "Failed to load user profile" - User profile loading not working correctly  
**Status**: 🔍 **INVESTIGATION IN PROGRESS**

---

## 1. Services Status

### ✅ Backend API Server (FastAPI)
```
Status: RUNNING
URL: http://0.0.0.0:8000
Process ID: 66413
Documentation: http://localhost:8000/docs
```

**Verification**:
```bash
$ curl -I http://localhost:8000/docs
HTTP/1.1 200 OK
server: uvicorn
content-type: text/html; charset=utf-8
```

✅ **Backend is running and accessible**

### ✅ Frontend Development Server (Vite/React)
```
Status: RUNNING
URL: http://localhost:5000
Port: 5000 (configured in vite.config.js)
Proxy: /api -> http://localhost:8000
```

✅ **Frontend is running and accessible**

---

## 2. User Profile Loading Flow

### Architecture Overview

```
User Browser
    ↓
Frontend (React) - UserProfile.jsx
    ↓ (Firebase Auth Token)
GET /api/user/profile
    ↓ (Proxied to backend)
Backend API (FastAPI) - main.py:621
    ↓ (Requires Firebase JWT)
get_user_with_profile() dependency
    ↓
get_current_user() - Verify Firebase Token
    ↓
require_active_user() - Check if user is active
    ↓
UserManager.get_user_profile(uid)
    ↓
Firestore Database
```

### Critical Dependencies

1. **Firebase Authentication**
   - User must be authenticated with Firebase
   - Valid JWT token required in Authorization header
   
2. **Firestore Database**
   - User profile stored in collection: `users`
   - Document ID: User's Firebase UID

3. **Backend Authentication Middleware**
   - File: `main.py` lines 183-201
   - Validates Firebase ID token
   - Extracts user UID from token

4. **User Profile Retrieval**
   - File: `UserManager.py` lines 134-192
   - Fetches profile from Firestore
   - Handles missing profiles (returns default)

---

## 3. Potential Failure Points

### 🔴 Issue #1: Firebase Authentication Failure

**Symptoms**:
- "Failed to load user profile" error
- 401 Unauthorized responses

**Possible Causes**:
1. User not logged in (no Firebase auth token)
2. Expired Firebase token
3. Invalid token format
4. Firebase project misconfiguration

**Code Location**:
```javascript
// Frontend: billingonaire-ui/src/UserProfile.jsx:38-50
const loadUserProfile = async () => {
  try {
    const profileData = await authenticatedFetchJSON('/user/profile');
    setProfile(profileData);
    // ...
  } catch (error) {
    console.error('Error loading profile:', error);
    setError('Failed to load user profile');  // ← This error message
  }
};
```

```python
# Backend: billingonaire_backend/main.py:621
@app.get("/user/profile", tags=["User Management"])
async def get_user_profile(current_user_with_profile=Depends(get_user_with_profile)):
    """Get current user's profile"""
    return current_user_with_profile["profile"]
```

### 🔴 Issue #2: Missing or Inactive User Profile

**Symptoms**:
- "Account is disabled" error
- Profile data not found

**Possible Causes**:
1. User profile not created in Firestore
2. User marked as `is_active: false`
3. Firestore connection error

**Code Location**:
```python
# billingonaire_backend/main.py:204-215
def require_active_user(current_user: dict = Depends(get_current_user)):
    """Dependency to require active user account"""
    uid = current_user.get("uid")
    profile = get_user_manager().get_user_profile(uid)

    if not profile.get("is_active", True):
        raise HTTPException(
            status_code=403, detail="Account is disabled. Contact administrator."
        )

    return {**current_user, "profile": profile}
```

### 🔴 Issue #3: Firestore Connection Error

**Symptoms**:
- 500 Internal Server Error
- Firebase Admin SDK errors in logs

**Possible Causes**:
1. Firebase credentials not configured
2. Firestore database not initialized
3. Network connectivity issues

**Code Location**:
```python
# billingonaire_backend/UserManager.py:134-192
def get_user_profile(self, uid: str) -> Dict:
    """Get user profile by UID"""
    try:
        user_ref = self.db.collection(self.users_collection).document(uid)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            # Return default profile for backward compatibility
            firebase_user = auth.get_user(uid)
            # ...
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve user profile: {str(e)}"
        )
```

### 🔴 Issue #4: CORS or Proxy Configuration

**Symptoms**:
- Network errors in browser console
- Failed to fetch errors

**Possible Causes**:
1. CORS not configured on backend
2. Vite proxy misconfigured
3. Port mismatch

**Configuration**:
```javascript
// billingonaire-ui/vite.config.js
server: {
  host: '0.0.0.0',
  port: 5000,
  proxy: {
    '/api': {
      target: 'http://localhost:8000',  // ← Must match backend port
      changeOrigin: true,
      secure: false,
      rewrite: (path) => path.replace(/^\/api/, '')
    }
  }
}
```

---

## 4. Diagnostic Steps

### Step 1: Check User Authentication State

**Frontend Console Test**:
```javascript
// Open browser console on http://localhost:5000
import { auth } from './lib/firebase';
console.log('Current user:', auth.currentUser);

// If null, user is not logged in
// If object, check: auth.currentUser.uid, auth.currentUser.email
```

### Step 2: Test API Endpoint Manually

**With Authentication Token**:
```bash
# Get Firebase ID token (from browser console)
auth.currentUser.getIdToken().then(token => console.log(token));

# Test API with token
curl -H "Authorization: Bearer YOUR_TOKEN_HERE" \
     http://localhost:8000/user/profile
```

**Expected Success Response**:
```json
{
  "uid": "abc123...",
  "email": "user@example.com",
  "role": "user",
  "full_name": "John Doe",
  "is_active": true,
  "created_at": "2025-10-25T10:00:00",
  "updated_at": "2025-10-25T12:00:00"
}
```

**Expected Error Responses**:
```json
// 401: No/invalid token
{"detail": "Missing or invalid authentication token"}

// 401: Expired token
{"detail": "Invalid authentication token"}

// 403: Inactive account
{"detail": "Account is disabled. Contact administrator."}

// 500: Server error
{"detail": "Failed to retrieve user profile: ..."}
```

### Step 3: Check Backend Logs

**Terminal Output**:
```bash
# In the terminal running uvicorn, check for errors like:
ERROR:root:Token verification failed: ...
ERROR:root:Failed to initialize Firebase: ...
```

### Step 4: Verify Firestore Data

**Check if user profile exists**:
```python
# In Python console or test script
from firebase_admin import firestore
db = firestore.client()
users_ref = db.collection('users')
user_doc = users_ref.document('USER_UID_HERE').get()
if user_doc.exists:
    print(user_doc.to_dict())
else:
    print("Profile does not exist")
```

### Step 5: Test Frontend API Helper

**Check authenticatedFetchJSON function**:
```javascript
// billingonaire-ui/src/lib/api.js
export async function authenticatedFetchJSON(endpoint, options = {}) {
  const user = auth.currentUser;
  if (!user) {
    throw new Error('No authenticated user');  // ← Check this error
  }

  const token = await user.getIdToken();
  // ...
}
```

---

## 5. Common Issues and Solutions

### Issue: "No authenticated user" Error

**Problem**: User not logged in to Firebase

**Solution**:
1. Navigate to login page
2. Sign in with valid credentials
3. Verify auth state in console: `auth.currentUser`

### Issue: 401 Unauthorized

**Problem**: Invalid or expired Firebase token

**Solution**:
1. Refresh the page (gets new token)
2. Log out and log back in
3. Clear browser cache and cookies

### Issue: Profile Not Found (404/500)

**Problem**: User profile not created in Firestore

**Solution**:
```python
# Create profile for first-time user
from UserManager import UserManager
um = UserManager()
um.create_user_profile(
    uid="USER_UID",
    email="user@example.com",
    role="user",
    full_name="User Name"
)
```

### Issue: "Account is disabled"

**Problem**: User marked inactive in Firestore

**Solution**:
```python
# Admin must reactivate account
um.update_user_profile(uid="USER_UID", updates={"is_active": True})
```

---

## 6. Testing Checklist

### ✅ Prerequisites
- [ ] Backend server running on port 8000
- [ ] Frontend server running on port 5000
- [ ] Firebase project configured
- [ ] Firestore database initialized
- [ ] User account created in Firebase Auth

### ✅ Authentication Tests
- [ ] User can access login page
- [ ] User can log in with valid credentials
- [ ] Firebase auth state updates correctly
- [ ] Auth token is present after login
- [ ] Token includes required claims (uid, email)

### ✅ API Tests
- [ ] GET /user/profile returns 401 without token
- [ ] GET /user/profile returns 200 with valid token
- [ ] Profile data structure is correct
- [ ] POST /user/profile creates/updates profile
- [ ] Error messages are informative

### ✅ Frontend Tests
- [ ] UserProfile component loads without errors
- [ ] Loading state displays correctly
- [ ] Profile data renders after load
- [ ] Error message displays on failure
- [ ] Update profile form works correctly

---

## 7. Current Investigation Status

### Services Running ✅
- Backend API: ✅ Running on port 8000
- Frontend: ✅ Running on port 5000

### Next Steps
1. ⏳ Open frontend in browser (http://localhost:5000)
2. ⏳ Attempt login with Firebase credentials
3. ⏳ Navigate to User Profile page
4. ⏳ Check browser console for errors
5. ⏳ Check backend logs for authentication errors
6. ⏳ Verify Firestore connection and data

---

## 8. Browser Testing Instructions

### Step 1: Open Application
```
URL: http://localhost:5000
```

### Step 2: Open Browser Developer Tools
```
Chrome/Edge: F12 or Ctrl+Shift+I
Firefox: F12 or Ctrl+Shift+I
Safari: Cmd+Option+I
```

### Step 3: Check Console Tab
Look for errors related to:
- Firebase authentication
- API fetch failures
- CORS errors
- Network errors

### Step 4: Check Network Tab
Filter for:
- `/api/user/profile` requests
- Check status code (200, 401, 403, 500)
- Check request headers (Authorization: Bearer ...)
- Check response body

### Step 5: Test Authentication
In console, run:
```javascript
// Check if user is logged in
import { auth } from './src/lib/firebase';
console.log('User:', auth.currentUser);

// Get auth token
if (auth.currentUser) {
  auth.currentUser.getIdToken().then(token => {
    console.log('Token:', token);
  });
}
```

---

## 9. Expected Behavior

### Normal Flow (Success)

1. **User navigates to app** → Sees login page
2. **User enters credentials** → Firebase authentication
3. **Login successful** → Redirect to dashboard
4. **Token generated** → Stored in Firebase auth
5. **UserProfile.jsx loads** → Calls `loadUserProfile()`
6. **API call made** → GET /api/user/profile with Bearer token
7. **Backend validates token** → Extracts UID
8. **Backend fetches profile** → From Firestore
9. **Profile returned** → Status 200 with JSON data
10. **Frontend updates** → Displays profile information

### Error Flow (Failure)

1. **User navigates to app** → Sees login page
2. **User not authenticated** OR **Token expired**
3. **UserProfile.jsx loads** → Calls `loadUserProfile()`
4. **API call fails** → Missing/invalid token
5. **Error caught** → "Failed to load user profile"
6. **Error displayed** → User sees error message

---

## 10. Recommended Fixes

Based on the code review, here are potential fixes if issues are found:

### Fix #1: Add Better Error Messages

**Update UserProfile.jsx**:
```javascript
const loadUserProfile = async () => {
  try {
    const user = auth.currentUser;
    if (!user) {
      setError('Please log in to view your profile');
      return;
    }
    
    const profileData = await authenticatedFetchJSON('/user/profile');
    setProfile(profileData);
    // ...
  } catch (error) {
    console.error('Error loading profile:', error);
    if (error.message.includes('401')) {
      setError('Session expired. Please log in again.');
    } else if (error.message.includes('403')) {
      setError('Your account has been disabled. Contact support.');
    } else {
      setError(`Failed to load user profile: ${error.message}`);
    }
  }
};
```

### Fix #2: Add Token Refresh Logic

**Update api.js**:
```javascript
export async function authenticatedFetchJSON(endpoint, options = {}) {
  const user = auth.currentUser;
  if (!user) {
    throw new Error('No authenticated user');
  }

  try {
    // Force token refresh if needed
    const token = await user.getIdToken(true); // true = force refresh
    // ...
  } catch (tokenError) {
    console.error('Token refresh failed:', tokenError);
    throw new Error('Authentication failed. Please log in again.');
  }
}
```

### Fix #3: Add Retry Logic

**Update UserProfile.jsx**:
```javascript
const loadUserProfile = async (retryCount = 0) => {
  try {
    const profileData = await authenticatedFetchJSON('/user/profile');
    setProfile(profileData);
    setError(''); // Clear any previous errors
  } catch (error) {
    if (retryCount < 2 && error.message.includes('401')) {
      // Retry once if token might be expired
      await new Promise(resolve => setTimeout(resolve, 1000));
      return loadUserProfile(retryCount + 1);
    }
    console.error('Error loading profile:', error);
    setError('Failed to load user profile');
  }
};
```

---

## 11. Monitoring and Debugging

### Enable Verbose Logging

**Backend** (`main.py`):
```python
# Already enabled:
logging.info(f"Attempting to verify ID token for authentication")
logging.info(f"Token verified successfully for user: {decoded_token.get('uid')}")
logging.error(f"Token verification failed: {str(e)}")
```

**Frontend** (Add to `UserProfile.jsx`):
```javascript
const loadUserProfile = async () => {
  console.log('🔍 Loading user profile...');
  console.log('📧 Current user:', auth.currentUser?.email);
  
  try {
    console.log('📡 Fetching from /user/profile...');
    const profileData = await authenticatedFetchJSON('/user/profile');
    console.log('✅ Profile loaded:', profileData);
    setProfile(profileData);
  } catch (error) {
    console.error('❌ Error loading profile:', error);
    console.error('Error details:', {
      message: error.message,
      stack: error.stack
    });
    setError('Failed to load user profile');
  }
};
```

---

## 12. Summary

### Status: 🔍 READY FOR MANUAL TESTING

**Services**:
- ✅ Backend running on http://localhost:8000
- ✅ Frontend running on http://localhost:5000
- ✅ Proxy configured (/api → backend)

**Next Actions**:
1. Open browser to http://localhost:5000
2. Log in with Firebase credentials
3. Navigate to User Profile page
4. Observe behavior and errors
5. Report findings for further investigation

**Likely Issues**:
1. User not authenticated (most common)
2. Firebase token expired
3. User profile not created in Firestore
4. Firestore connection error

**Required Information for Further Diagnosis**:
- Browser console errors
- Network tab showing /api/user/profile request/response
- Backend terminal logs
- Firebase Auth status (logged in/out)

---

**Last Updated**: October 25, 2025  
**Diagnostic Status**: Services running, awaiting manual testing results
