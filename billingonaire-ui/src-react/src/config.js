export const API_BASE_URL =
  window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : "https://asia-south1-billingonaire.cloudfunctions.net/billingonaire-backend";