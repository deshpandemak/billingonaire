// Use production cloud function URL when deployed, local proxy for development
export const API_BASE_URL = import.meta.env.PROD 
  ? "https://asia-south1-billingonaire.cloudfunctions.net/billingonaire-backend"
  : "/api";