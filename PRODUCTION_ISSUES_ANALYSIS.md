# Production Issues Analysis & Fix Plan

## Date: October 27, 2025

## Critical Issues Identified

### Issue 1: spaCy Model Missing in Production ✅ PARTIALLY FIXED
**Symptom:**
```
WARNING:root:Could not initialize spaCy: [E050] Can't find model 'en_core_web_sm'
```

**Root Cause:**
- Dockerfile installs spaCy library but doesn't download the language model
- Production Docker image missing: `python -m spacy download en_core_web_sm`

**Fix Applied:**
- Added `RUN python -m spacy download en_core_web_sm` to Dockerfile (line 16)
- **STATUS**: Code updated, but Cloud Build using cached Dockerfile
- **ACTION NEEDED**: Force rebuild or wait for cache invalidation

---

### Issue 2: 100% Order Download Failure Rate ⚠️ INVESTIGATION IN PROGRESS
**Symptom:**
```
WARNING:root:❌ Case WP/10598/2024 - FAILED after 50 sequences: 
No matching order found after 50 attempts. 50 downloads failed.
```

**Local Testing Results:**
```bash
✅ Local Test: Successfully downloaded PDF from Bombay HC API
- URL: https://bombayhighcourt.nic.in/generatenewauth.php
- Status: 200 OK
- Content-Type: application/pdf
- Size: 107,924 bytes
```

**Root Cause Hypothesis:**
1. **Network/Firewall**: Cloud Run may be blocked by Bombay HC
2. **IP Blocking**: Google Cloud IPs might be blacklisted
3. **Missing User-Agent**: Bot detection blocking requests

**Fixes Applied:**
1. ✅ Added browser-like User-Agent header to prevent bot detection
2. ✅ Enhanced logging to capture:
   - HTTP status codes
   - Response Content-Type
   - Response body preview (first 500 chars)
   - Specific exception types (Timeout, ConnectionError)

**Enhanced Logging Example:**
```python
logging.warning(
    f"⚠️ Sequence {sequence_number} returned non-PDF: "
    f"Status={response.status_code}, "
    f"Content-Type={content_type}, "
    f"Response preview: {response_preview}"
)
```

---

## Files Modified

### 1. billingonaire_backend/Dockerfile
```dockerfile
# Line 16 - Download spaCy language model
RUN python -m spacy download en_core_web_sm
```

### 2. billingonaire_backend/AutoOrderManager.py
**Changes (lines 835-889):**
- Added User-Agent header to mimic browser
- Enhanced logging with HTTP status, content-type, response preview
- Separated exception handling (Timeout, ConnectionError, RequestException)
- Added emoji indicators (✅, ⚠️, 🔴) for log visibility

---

## Deployment Status

### Latest Deployment: Revision 00101
- **Deployed**: October 26, 2025, 18:42 UTC
- **spaCy Model**: ❌ Still missing (using cached Dockerfile)
- **Enhanced Logging**: ❌ Not deployed yet
- **User-Agent Fix**: ❌ Not deployed yet

### Why Deployment Failed
Cloud Build cached old Dockerfile despite:
- `gcloud run deploy --source .` (should always rebuild)
- Dockerfile correctly updated locally
- No .gcloudignore exclusions

**Build Evidence:**
```
Step 5/9: RUN pip install --no-cache-dir -r requirements.txt
 (spaCy installed here: spacy-3.7.2)
Step 6/9: COPY . .
 (Missing: Step for spaCy model download!)
```

---

## Next Steps

### Immediate Actions
1. **Force Docker Rebuild**
   - Option A: Add timestamp comment to Dockerfile (DONE)
   - Option B: Use cloudbuild.yaml with `--no-cache` flag
   - Option C: Clear Cloud Build cache manually

2. **Deploy to Production**
   ```bash
   cd billingonaire_backend
   gcloud run deploy billingonaire-backend \
     --source . \
     --region=asia-south1 \
     --project=billingonaire
   ```

3. **Verify spaCy Model**
   - Check logs for "Could not initialize spaCy" warning
   - Should disappear after successful deployment

4. **Test Order Download**
   - Trigger order processing for a test case
   - Review enhanced logs to see actual HTTP response:
     - If getting HTML → IP blocking by Bombay HC
     - If timeout → Network egress issue
     - If 403/401 → Authentication/authorization issue

### If Order Downloads Still Fail

**Scenario A: IP Blocking**
```
Response: <html>Access Denied</html>
```
**Solution**: 
- Configure Cloud Run with static IP via Cloud NAT
- Request Bombay HC to whitelist IP

**Scenario B: Network Egress**
```
Error: Connection error/timeout
```
**Solution**:
- Check Cloud Run VPC connector configuration
- Ensure Cloud NAT configured if using VPC connector

**Scenario C: Bot Detection**
```
Response: Captcha or JavaScript challenge
```
**Solution**:
- Already added User-Agent header
- May need additional headers (Referer, Accept, etc.)
- Consider using proxy service

---

## Testing Checklist

After successful deployment:

- [ ] Verify spaCy loads without errors
- [ ] Trigger order processing for test case
- [ ] Check enhanced logs for HTTP response details
- [ ] Identify specific failure reason
- [ ] Apply targeted fix based on logs
- [ ] Retest order download functionality
- [ ] Verify analytics dashboard shows correct data

---

## Technical Notes

### Local vs Production Discrepancy
- **Local**: Order download works perfectly
- **Production**: 100% failure rate
- **Implication**: Environment-specific issue (network/IP/firewall)

### spaCy Model Size
- Model: en_core_web_sm
- Size: ~12 MB
- Download time: ~5-10 seconds during build
- No impact on runtime performance

### Order Download Logic
- Tries sequences 1-50 for each case
- Each sequence = different PDF filename variant
- Uses Bombay HC API with base64-encoded parameters
- Authenticates with timestamp passphrase

---

**Document Created**: October 27, 2025, 01:20 UTC  
**Status**: Awaiting successful deployment with fixes
