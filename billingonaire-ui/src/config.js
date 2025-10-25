// Use production Cloud Run URL when deployed, local proxy for development
export const API_BASE_URL = import.meta.env.PROD 
  ? "https://billingonaire-backend-819125105651.asia-south1.run.app"
  : "/api";