export const logger = {
  info: (message) => {
    console.log(`INFO: ${message}`);
  },
  warn: (message) => {
    console.warn(`WARN: ${message}`);
  },
  error: (message, error = null) => {
    console.error(`ERROR: ${message}`);
    if (error) {
      console.error(error);
    }
  }
};