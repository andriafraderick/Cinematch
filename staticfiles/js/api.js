/**
 * ============================================================
 * CineMatch - JavaScript API Client (static/js/api.js)
 * ============================================================
 *
 * This module handles ALL communication between the browser
 * and the Django REST API at /api/v1/.
 *
 * ARCHITECTURE:
 *   CineMatchAPI   → low-level fetch wrapper (auth headers, token refresh)
 *     ├── auth     → register, login, logout, me, onboarding
 *     ├── movies   → list, detail, search, trending, rate, watchlist
 *     └── recs     → get recommendations, refresh, mark clicked
 *
 * TOKEN MANAGEMENT:
 *   Tokens stored in localStorage (client-side only).
 *   On 401 → auto-refreshes access token using refresh token.
 *   On refresh failure → redirects to login.
 *
 *   Keys: cm_access_token, cm_refresh_token
 *
 * USAGE:
 *   const data = await API.movies.list({ genre: 28, min_rating: 7 });
 *   const recs = await API.recs.get();
 *   await API.movies.rate(movieId, 8.5, "Great film!");
 * ============================================================
 */

const API_BASE = '/api/v1';

// ── TOKEN STORAGE ────────────────────────────────────────────
const TokenStore = {
  get access()  { return localStorage.getItem('cm_access_token'); },
  get refresh() { return localStorage.getItem('cm_refresh_token'); },
  set(access, refresh) {
    if (access)  localStorage.setItem('cm_access_token', access);
    if (refresh) localStorage.setItem('cm_refresh_token', refresh);
  },
  clear() {
    localStorage.removeItem('cm_access_token');
    localStorage.removeItem('cm_refresh_token');
    localStorage.removeItem('cm_user');
  },
  saveUser(user) { localStorage.setItem('cm_user', JSON.stringify(user)); },
  getUser() {
    try { return JSON.parse(localStorage.getItem('cm_user')); }
    catch { return null; }
  }
};

// ── CORE FETCH WRAPPER ───────────────────────────────────────
let _isRefreshing = false;

async function request(endpoint, {
  method = 'GET',
  data = null,
  auth = true,
  retry = true,
} = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (auth && TokenStore.access) {
    headers['Authorization'] = `Bearer ${TokenStore.access}`;
  }

  const config = { method, headers };
  if (data && method !== 'GET') config.body = JSON.stringify(data);

  // Build URL with query params for GET
  let url = `${API_BASE}${endpoint}`;
  if (data && method === 'GET') {
    const params = new URLSearchParams(
      Object.fromEntries(Object.entries(data).filter(([_, v]) => v != null && v !== ''))
    );
    if (params.toString()) url += `?${params}`;
  }

  const response = await fetch(url, config);

  // Handle 401 — try token refresh once
  if (response.status === 401 && retry && !_isRefreshing) {
    _isRefreshing = true;
    const refreshed = await _refreshToken();
    _isRefreshing = false;

    if (refreshed) {
      return request(endpoint, { method, data, auth, retry: false });
    } else {
      TokenStore.clear();
      window.location.href = '/auth/login/?next=' + encodeURIComponent(window.location.pathname);
      return null;
    }
  }

  // Return null for 204 No Content
  if (response.status === 204) return null;

  const json = await response.json().catch(() => null);
  if (!response.ok) {
    const err = new Error(json?.detail || json?.error || `HTTP ${response.status}`);
    err.status = response.status;
    err.data = json;
    throw err;
  }
  return json;
}

async function _refreshToken() {
  if (!TokenStore.refresh) return false;
  try {
    const res = await fetch(`${API_BASE}/auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: TokenStore.refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    if (data.access) { TokenStore.set(data.access, null); return true; }
    return false;
  } catch { return false; }
}

// ── PUBLIC API OBJECT ────────────────────────────────────────
const API = {

  // ── AUTH ──────────────────────────────────────────────────
  auth: {
    async register(email, username, password, passwordConfirm, fullName = '') {
      const data = await request('/auth/register/', {
        method: 'POST', auth: false,
        data: { email, username, password, password_confirm: passwordConfirm, full_name: fullName }
      });
      if (data?.access) {
        TokenStore.set(data.access, data.refresh);
        TokenStore.saveUser(data.user);
      }
      return data;
    },

    async login(email, password) {
      const data = await request('/auth/login/', {
        method: 'POST', auth: false,
        data: { email, password }
      });
      if (data?.access) {
        TokenStore.set(data.access, data.refresh);
        TokenStore.saveUser(data.user);
      }
      return data;
    },

    async logout() {
      try {
        await request('/auth/logout/', {
          method: 'POST',
          data: { refresh: TokenStore.refresh }
        });
      } catch {}
      TokenStore.clear();
      window.location.href = '/auth/login/';
    },

    async me() {
      return request('/auth/me/');
    },

    async onboarding(genreIds, streamingServices = []) {
      return request('/auth/onboarding/', {
        method: 'POST',
        data: { genre_ids: genreIds, streaming_services: streamingServices }
      });
    },

    async updateProfile(updates) {
      return request('/auth/profile/', {
        method: 'PATCH', data: updates
      });
    },

    isLoggedIn() { return !!TokenStore.access; },
    getUser()   { return TokenStore.getUser(); },
  },

  // ── MOVIES ────────────────────────────────────────────────
  movies: {
    async list(params = {}) {
      return request('/movies/', { method: 'GET', data: params });
    },

    async get(id) {
      return request(`/movies/${id}/`);
    },

    async search(query, params = {}) {
      return request('/movies/', { method: 'GET', data: { search: query, ...params } });
    },

    async trending() {
      return request('/movies/trending/');
    },

    async topRated() {
      return request('/movies/top-rated/');
    },

    async byGenre(slug, page = 1) {
      return request(`/movies/genre/${slug}/?page=${page}`);
    },

    async similar(movieId) {
      return request(`/movies/${movieId}/similar/`);
    },

    async rate(movieId, score, review = '') {
      return request(`/movies/${movieId}/rate/`, {
        method: 'POST', data: { score, review }
      });
    },

    async deleteRating(movieId) {
      return request(`/movies/${movieId}/rate/`, { method: 'DELETE' });
    },

    async recordView(movieId) {
      return request(`/movies/${movieId}/viewed/`, { method: 'POST' }).catch(() => {});
    },
  },

  // ── GENRES ────────────────────────────────────────────────
  genres: {
    async list() {
      return request('/genres/', { auth: false });
    }
  },

  // ── WATCHLIST ─────────────────────────────────────────────
  watchlist: {
    async list() {
      return request('/watchlist/');
    },

    async add(movieId) {
      return request('/watchlist/', {
        method: 'POST', data: { movie_id: movieId }
      });
    },

    async remove(movieId) {
      return request(`/watchlist/movie/${movieId}/`, { method: 'DELETE' });
    },

    async toggle(movieId, currentlyIn) {
      if (currentlyIn) return this.remove(movieId);
      return this.add(movieId);
    }
  },

  // ── WATCHED ───────────────────────────────────────────────
  watched: {
    async list() {
      return request('/watched/');
    },

    async add(movieId, source = '', rewatched = false) {
      return request('/watched/', {
        method: 'POST', data: { movie_id: movieId, source, rewatched }
      });
    }
  },

  // ── RATINGS ───────────────────────────────────────────────
  ratings: {
    async list() { return request('/ratings/'); }
  },

  // ── RECOMMENDATIONS ───────────────────────────────────────
  recs: {
    async get() {
      return request('/recommendations/');
    },

    async refresh() {
      return request('/recommendations/refresh/', { method: 'POST' });
    },

    async markClicked(recId) {
      return request(`/recommendations/${recId}/clicked/`, { method: 'POST' }).catch(() => {});
    }
  },

  // ── DASHBOARD ─────────────────────────────────────────────
  dashboard: {
    async get() {
      return request('/dashboard/');
    }
  }
};

// Export for use in templates
window.API = API;
window.TokenStore = TokenStore;