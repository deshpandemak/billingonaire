# Billingonaire React UI - Build & Firebase Deployment Guide

This guide explains how to build the React UI and deploy it to Firebase Hosting.

## Prerequisites
- Node.js (v18 or later recommended)
- npm (comes with Node.js)
- Firebase CLI (`npm install -g firebase-tools`)
- Access to your Firebase project (see `firebase.js` for config)

## 1. Install Dependencies

```
cd src-react
npm install
```

## 2. Build the React App

This will generate a production-ready build in the `dist` folder:

```
npm run build
```

## 3. Configure Firebase Hosting

If you haven't already, initialize Firebase Hosting in the project root:

```
cd ../..
firebase login
firebase init hosting
```
- When prompted, select your Firebase project.
- Set the public directory to: `billingonaire-ui/src-react/dist`
- Configure as a single-page app: **Yes**
- Do **not** overwrite `index.html` if prompted.

## 4. Deploy to Firebase Hosting

From the project root:

```
cd billingonaire-ui/src-react
npm run build
cd ../..
firebase deploy --only hosting
```

## 5. Access Your Deployed App

After deployment, Firebase CLI will provide a hosting URL. Open it in your browser to view your live React app.

---

## Notes
- Make sure your Firebase config in `src/lib/firebase.js` matches your Firebase project.
- For production, consider using environment variables for sensitive config.
- You can update and redeploy at any time by repeating steps 2 and 4.
