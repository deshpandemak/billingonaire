// Quick API testing script to diagnose issues
const http = require('http');

async function testAPI(path, method = 'GET', body = null) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: 'localhost',
      port: 8000,
      path: path,
      method: method,
      headers: {
        'Content-Type': 'application/json',
      }
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        console.log(`\n=== ${method} ${path} ===`);
        console.log(`Status: ${res.statusCode}`);
        console.log(`Response: ${data}`);
        resolve({ status: res.statusCode, data: data });
      });
    });

    req.on('error', (e) => {
      console.error(`Error: ${e.message}`);
      reject(e);
    });

    if (body) {
      req.write(JSON.stringify(body));
    }
    req.end();
  });
}

async function runTests() {
  console.log('Testing Billingonaire APIs...\n');

  // Test 1: Check if backend is running
  await testAPI('/');

  // Test 2: Check admin AGP names endpoint (will fail without auth, but we can see the response)
  await testAPI('/admin/agp-names');

  // Test 3: Check a sample analyze endpoint (will fail without auth and valid case_id)
  await testAPI('/auto-orders/analyze-case/test123', 'POST');

  console.log('\n=== Tests Complete ===');
}

runTests().catch(console.error);
