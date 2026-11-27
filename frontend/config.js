// API base URL. Empty string = same origin (the FastAPI app also serves this UI on port 8000,
// which is what you want locally and in GitHub Codespaces). Never put Supabase keys here.
// Only set a full URL if you host the UI somewhere else, e.g. "https://my-api.onrender.com".
window.API_URL = window.API_URL || "";
