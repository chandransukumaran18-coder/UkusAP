// Single place to point the frontend at your backend.
// Automatically uses localhost when you open the pages locally, and the
// deployed Railway backend when the site is served from anywhere else.
const API_BASE = (location.hostname === "127.0.0.1" || location.hostname === "localhost")
  ? "http://127.0.0.1:8000"
  : "https://ukusap-production.up.railway.app";
