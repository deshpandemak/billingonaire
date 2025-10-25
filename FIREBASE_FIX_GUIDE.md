# RESOLVED: User Profile Loading Issue - Firebase Configuration
**Date**: October 25, 2025  
**Issue**: "Failed to load user profile"  
**Root Cause**: Firebase Admin SDK not properly configured  
**Status**: 🎯 **FIX IDENTIFIED - READY TO IMPLEMENT**

---

## 🔴 Actual Error from Backend Logs

```
ERROR:root:Token verification failed: A project ID is required to access the auth service.
    1. Use a service account credential, or
    2. set the project ID explicitly via Firebase App options, or
    3. set the project ID via the GOOGLE_CLOUD_PROJECT environment variable.

INFO: 127.0.0.1:40796 - "GET /user/profile HTTP/1.1" 401 Unauthorized
{"detail":"Invalid authentication token"}
```

This confirms Firebase Admin SDK cannot verify authentication tokens because it's not properly initialized.

---

## ✅ QUICK FIX (Choose ONE Option)

### Option 1: Set Project ID Environment Variable (Fastest)

```bash
export GOOGLE_CLOUD_PROJECT=billingonaire
export FIREBASE_PROJECT_ID=billingonaire
```

Then restart backend:
```bash
pkill -f "uvicorn.*main:app"
python3 -m uvicorn billingonaire_backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**This might work** for basic operations but **won't fully work** for token verification without proper service account credentials.

### Option 2: Get Firebase Service Account Key (Recommended)

#### Step 1: Download Key
1. Go to https://console.firebase.google.com/
2. Select **billingonaire** project
3. Click ⚙️ (Settings) → **Project Settings**
4. Go to **Service Accounts** tab
5. Click **Generate New Private Key**
6. Click **Generate Key** → Downloads JSON file

#### Step 2: Set Environment Variable
```bash
# Read the downloaded JSON file content
export GCLOUD_SERVICE_ACCOUNT_KEY='paste-json-content-here'

# Example format (DO NOT use this, get your own key):
export GCLOUD_SERVICE_ACCOUNT_KEY='{"type":"service_account","project_id":"billingonaire","private_key_id":"abc123...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"firebase-adminsdk-xyz@billingonaire.iam.gserviceaccount.com",...}'
```

#### Step 3: Restart Backend
```bash
# Stop current backend
pkill -f "uvicorn.*main:app"

# Start with credentials available
python3 -m uvicorn billingonaire_backend.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Step 4: Verify
You should see in logs:
```
✅ Firebase Admin SDK initialized with service account key
```

### Option 3: Use Service Account File (Alternative)

#### Save key to file:
```bash
# Save downloaded JSON to file
cat > /workspaces/billingonaire/billingonaire_backend/firebase-key.json << 'EOF'
{
  "type": "service_account",
  "project_id": "billingonaire",
  ... rest of JSON ...
}
EOF
```

#### Modify backend code:
Add to `main.py` in `ensure_firebase()` function after line 104:

```python
def ensure_firebase():
    global _firebase_initialized, _firebase_init_error
    if not _firebase_initialized:
        if not firebase_admin._apps:
            import json
            import os.path

            gcloud_key = os.environ.get("GCLOUD_SERVICE_ACCOUNT_KEY")
            if gcloud_key:
                # Existing code...
            else:
                # NEW: Try to load from file
                key_file = os.path.join(
                    os.path.dirname(__file__),
                    "firebase-key.json"
                )
                if os.path.exists(key_file):
                    cred = credentials.Certificate(key_file)
                    firebase_admin.initialize_app(cred)
                    logging.info("✅ Firebase initialized from file")
                else:
                    # Existing ADC code...
```

Then restart backend.

---

## 🧪 Test After Fix

### 1. Check Backend Logs
After restarting, you should see ONE of these (no errors):
```
✅ Firebase Admin SDK initialized with service account key
✅ Firebase Admin SDK initialized with Application Default Credentials  
✅ Firebase initialized from file
```

### 2. Test API Endpoint
```bash
# Should return 401 but WITHOUT the "project ID is required" error
curl -H "Authorization: Bearer fake-token" http://localhost:8000/user/profile

# Expected output:
# {"detail":"Invalid authentication token"}
# NOT: "A project ID is required..."
```

### 3. Test with Real User
1. Open http://localhost:5000
2. Log in with Firebase credentials
3. Open browser console and get token:
   ```javascript
   auth.currentUser.getIdToken().then(t => console.log(t))
   ```
4. Test API:
   ```bash
   TOKEN="paste-from-console"
   curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/user/profile
   ```
5. Should return user profile JSON ✅

### 4. Test Frontend
1. Open http://localhost:5000
2. Log in
3. Navigate to User Profile
4. Should load without "Failed to load user profile" error ✅

---

## 📝 Make Fix Permanent

### Create .env file
```bash
cat > /workspaces/billingonaire/billingonaire_backend/.env << 'EOF'
GCLOUD_SERVICE_ACCOUNT_KEY='your-json-here'
GOOGLE_CLOUD_PROJECT=billingonaire
EOF
```

### Load .env in startup script
Modify backend startup or add to `.bashrc`:

```bash
# In ~/.bashrc or startup script
if [ -f "/workspaces/billingonaire/billingonaire_backend/.env" ]; then
    export $(cat /workspaces/billingonaire/billingonaire_backend/.env | grep -v '^#' | xargs)
fi
```

### Or use python-dotenv
```bash
pip install python-dotenv
```

Then in `main.py` add at top:
```python
from dotenv import load_dotenv
load_dotenv()  # Loads .env file
```

---

## 🎯 Summary

**Issue**: Firebase Admin SDK cannot verify authentication tokens

**Actual Error**: 
```
Token verification failed: A project ID is required to access the auth service
```

**Cause**: No service account credentials or project ID configured

**Solution**: Set `GCLOUD_SERVICE_ACCOUNT_KEY` environment variable with Firebase service account JSON

**Steps**:
1. Download Firebase service account key from console
2. Set as environment variable
3. Restart backend
4. Test application

**Status**: ⏳ Awaiting service account key configuration

---

## 🔒 Security Notes

**DO NOT**:
- ❌ Commit service account key to git
- ❌ Share key publicly
- ❌ Hardcode key in source code
- ❌ Log key contents

**DO**:
- ✅ Store in environment variable
- ✅ Use .env file (add to .gitignore)
- ✅ Rotate keys if compromised
- ✅ Use different keys for dev/prod

---

**Last Updated**: October 25, 2025  
**Error Confirmed**: ✅ Yes - "A project ID is required to access the auth service"  
**Fix Available**: ✅ Yes - Set Firebase credentials  
**Ready to Implement**: ✅ Yes - Awaiting credentials
