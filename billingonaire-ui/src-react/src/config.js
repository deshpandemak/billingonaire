export const API_BASE_URL =
  window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : window.location.hostname.endsWith("github.dev") || window.location.hostname.endsWith("githubpreview.dev")
      ? `https://${window.location.hostname.replace(/^([^.]+)\.github(dev|preview)\.dev$/, "$1-8000.app.github.dev")}`
      : "https://asia-south1-billingonaire.cloudfunctions.net/billingonaire-backend";