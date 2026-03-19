/**
 * ============================================================
 * CineMatch - UI Utilities (static/js/ui.js)
 * ============================================================
 *
 * Reusable UI components used across all pages:
 *   Toast      → success/error/info notifications
 *   Skeleton   → shimmer loading placeholders
 *   MovieCard  → renders a movie card from API data
 *   StarRating → interactive 1–10 star widget
 *   Carousel   → horizontal scroll with arrow controls
 *   Modal      → rating/review popup
 * ============================================================
 */

// ── TOAST NOTIFICATIONS ──────────────────────────────────────
const Toast = {
  _container: null,

  _getContainer() {
    if (!this._container) {
      this._container = document.createElement('div');
      this._container.className = 'toast-container';
      document.body.appendChild(this._container);
    }
    return this._container;
  },

  show(message, type = 'info', duration = 3500) {
    const icons = { success: '✓', error: '✕', info: '◆' };
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.innerHTML = `<span style="color:${type === 'success' ? '#2ecc71' : type === 'error' ? '#e74c3c' : '#f5a623'}">${icons[type]}</span> ${message}`;

    const container = this._getContainer();
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.animation = 'slideIn 0.3s reverse both';
      setTimeout(() => toast.remove(), 300);
    }, duration);

    return toast;
  },

  success(msg) { return this.show(msg, 'success'); },
  error(msg)   { return this.show(msg, 'error'); },
  info(msg)    { return this.show(msg, 'info'); },
};

// ── SKELETON LOADER ───────────────────────────────────────────
const Skeleton = {
  movieCard(count = 6) {
    return Array.from({ length: count }, () => `
      <div class="movie-card">
        <div class="skeleton skeleton-poster"></div>
      </div>
    `).join('');
  },

  recCard(count = 4) {
    return Array.from({ length: count }, () => `
      <div class="rec-card" style="height:100px">
        <div class="skeleton" style="width:67px;height:100px;min-width:67px"></div>
        <div style="padding:12px;flex:1;display:flex;flex-direction:column;gap:8px">
          <div class="skeleton" style="height:14px;width:70%"></div>
          <div class="skeleton" style="height:11px;width:50%"></div>
          <div class="skeleton" style="height:11px;width:40%"></div>
        </div>
      </div>
    `).join('');
  }
};

// ── MOVIE CARD RENDERER ───────────────────────────────────────
/**
 * Generates the HTML for a movie card from API data.
 *
 * @param {Object} movie  - Movie object from API
 * @param {Object} opts   - Options
 *   opts.userRating      - Current user's rating (if any)
 *   opts.inWatchlist     - Whether in user's watchlist
 *   opts.recId           - Recommendation ID (for click tracking)
 *   opts.reasonText      - Reason text from recommendation
 *   opts.showReason      - Show reason chip on card
 */
function MovieCard(movie, opts = {}) {
  // const posterUrl = movie.poster_url || movie.poster_path
  //   ? `https://image.tmdb.org/t/p/w342${movie.poster_path || ''}`
  //   : 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 240"%3E%3Crect fill="%2321212f" width="160" height="240"/%3E%3Ctext fill="%235a5768" font-size="40" x="80" y="130" text-anchor="middle"%3E🎬%3C/text%3E%3C/svg%3E';

  const finalPosterUrl = movie.poster_url && movie.poster_url.startsWith('http')
    ? movie.poster_url
    : `https://via.placeholder.com/342x513/1a1a2e/f5a623?text=${encodeURIComponent((movie.title||'??').substring(0,2).toUpperCase())}`;

  // const finalPosterUrl = movie.poster_url || posterUrl;
  const genres = (movie.genres || []).slice(0, 2);
  const rating = movie.vote_average ? movie.vote_average.toFixed(1) : '–';
  const year = movie.release_year || '';
  const inWatchlist = opts.inWatchlist || movie.in_watchlist;

  const card = document.createElement('div');
  card.className = 'movie-card animate-fade-up';
  card.dataset.movieId = movie.id;
  if (opts.recId) card.dataset.recId = opts.recId;

  card.innerHTML = `
    <img class="movie-card__poster"
         src="${finalPosterUrl}"
         alt="${escHtml(movie.title)}"
         loading="lazy"
         onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 160 240%22%3E%3Crect fill=%22%2321212f%22 width=%22160%22 height=%22240%22/%3E%3Ctext fill=%22%235a5768%22 font-size=%2240%22 x=%2280%22 y=%22130%22 text-anchor=%22middle%22%3E🎬%3C/text%3E%3C/svg%3E'">

    <div class="movie-card__overlay">
      ${opts.showReason && opts.reasonText ? `
        <div style="font-size:10px;color:var(--amber);margin-bottom:6px;display:flex;align-items:center;gap:4px;">
          <span>✦</span> ${escHtml(opts.reasonText)}
        </div>` : ''}

      <div class="movie-card__genres">
        ${genres.map(g => `<span class="movie-card__genre-tag">${escHtml(g.name || g)}</span>`).join('')}
      </div>

      <div class="movie-card__title">${escHtml(movie.title)}</div>

      <div class="movie-card__meta">
        <span class="movie-card__rating">★ ${rating}</span>
        ${year ? `<span>·</span><span>${year}</span>` : ''}
        ${movie.runtime ? `<span>·</span><span>${movie.runtime}m</span>` : ''}
      </div>

      <div class="movie-card__actions">
        <a href="/movies/${movie.slug || movie.id}/"
           class="movie-card__action-btn"
           onclick="trackClick(event, ${movie.id}, ${opts.recId || 'null'})">
          Details
        </a>
        <button class="movie-card__action-btn"
                onclick="quickRate(event, ${movie.id}, '${escHtml(movie.title)}')">
          Rate
        </button>
        <button class="movie-card__action-btn movie-card__watchlist-btn ${inWatchlist ? 'active' : ''}"
                onclick="toggleWatchlist(event, ${movie.id}, this)"
                title="${inWatchlist ? 'Remove from watchlist' : 'Add to watchlist'}">
          ${inWatchlist ? '♥' : '♡'}
        </button>
      </div>
    </div>
  `;

  return card;
}

// ── CAROUSEL INITIALIZER ──────────────────────────────────────
function initCarousel(container) {
  const track = container.querySelector('.carousel__track');
  const leftBtn = container.querySelector('.carousel__arrow--left');
  const rightBtn = container.querySelector('.carousel__arrow--right');

  if (!track) return;

  const scroll = (dir) => {
    const cardWidth = track.querySelector('.movie-card')?.offsetWidth || 200;
    const scrollBy = (cardWidth + 16) * 3; // scroll 3 cards
    track.scrollBy({ left: dir * scrollBy, behavior: 'smooth' });
  };

  if (leftBtn)  leftBtn.addEventListener('click', () => scroll(-1));
  if (rightBtn) rightBtn.addEventListener('click', () => scroll(1));

  // Hide arrows at extremes
  const update = () => {
    if (leftBtn)  leftBtn.style.opacity = track.scrollLeft > 10 ? '1' : '0.3';
    if (rightBtn) rightBtn.style.opacity =
      track.scrollLeft < track.scrollWidth - track.clientWidth - 10 ? '1' : '0.3';
  };

  track.addEventListener('scroll', update, { passive: true });
  update();
}

// ── STAR RATING WIDGET ────────────────────────────────────────
function StarRatingWidget(container, opts = {}) {
  const { initialRating = 0, onRate, max = 10, halfStars = true } = opts;
  let current = initialRating;

  function render(hovered = null) {
    const display = hovered ?? current;
    container.innerHTML = '';
    container.className = 'star-rating';

    for (let i = 1; i <= max; i++) {
      const star = document.createElement('span');
      star.className = 'star';
      star.textContent = '★';

      if (i <= display) star.classList.add('active');
      else if (halfStars && i - 0.5 <= display) star.classList.add('half');

      star.addEventListener('mouseover', () => render(i));
      star.addEventListener('mouseout', () => render(null));
      star.addEventListener('click', () => {
        current = i;
        render();
        if (onRate) onRate(i);
      });

      container.appendChild(star);
    }

    // Score display
    if (display > 0) {
      const score = document.createElement('span');
      score.style.cssText = 'margin-left:8px;font-size:18px;font-weight:700;color:var(--amber);font-family:var(--font-display)';
      score.textContent = display.toFixed(0) + '/10';
      container.appendChild(score);
    }
  }

  render();
  return { getValue: () => current };
}

// ── RATING MODAL ──────────────────────────────────────────────
function openRatingModal(movieId, movieTitle, existingRating = null) {
  // Remove any existing modal
  document.querySelector('.cm-modal-overlay')?.remove();

  let selectedRating = existingRating || 0;

  const overlay = document.createElement('div');
  overlay.className = 'cm-modal-overlay';
  overlay.style.cssText = `
    position:fixed;inset:0;z-index:8000;
    background:rgba(5,5,8,0.85);backdrop-filter:blur(8px);
    display:flex;align-items:center;justify-content:center;
    animation:fadeIn 0.2s ease;
  `;

  overlay.innerHTML = `
    <div class="cm-modal" style="
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:var(--radius-xl);
      padding:32px;
      width:90%;max-width:480px;
      animation:fadeUp 0.3s var(--ease-out-expo);
    ">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px">
        <div>
          <div class="label" style="margin-bottom:6px">Rate this film</div>
          <h2 style="font-family:var(--font-display);font-size:28px;letter-spacing:0.04em;color:var(--text-primary)">${escHtml(movieTitle)}</h2>
        </div>
        <button id="cm-modal-close" style="background:none;border:none;color:var(--text-muted);font-size:24px;cursor:pointer;padding:4px;line-height:1">✕</button>
      </div>

      <div id="cm-star-container" style="margin-bottom:24px;justify-content:center;display:flex"></div>

      <div class="form-group">
        <label class="form-label">Your review (optional)</label>
        <textarea id="cm-review-input"
          class="form-input"
          rows="3"
          placeholder="What did you think? What made it memorable?"
          style="resize:vertical">${''}</textarea>
      </div>

      <div style="display:flex;gap:12px;margin-top:8px">
        <button id="cm-rate-submit" class="btn btn-primary" style="flex:1">
          Save Rating
        </button>
        ${existingRating ? `<button id="cm-rate-delete" class="btn btn-ghost" style="color:var(--crimson);border-color:rgba(192,57,43,0.3)">Remove</button>` : ''}
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  // Init star widget
  const starContainer = overlay.querySelector('#cm-star-container');
  const widget = StarRatingWidget(starContainer, {
    initialRating: existingRating || 0,
    max: 10,
    onRate: (val) => { selectedRating = val; }
  });

  // Close handlers
  overlay.querySelector('#cm-modal-close').addEventListener('click', () => overlay.remove());
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

  // Submit
  overlay.querySelector('#cm-rate-submit').addEventListener('click', async () => {
    const rating = widget.getValue();
    if (!rating) { Toast.error('Please select a rating.'); return; }

    const review = overlay.querySelector('#cm-review-input').value;
    const btn = overlay.querySelector('#cm-rate-submit');
    btn.textContent = 'Saving…';
    btn.disabled = true;

    try {
      await API.movies.rate(movieId, rating, review);
      Toast.success(`Rated ${escHtml(movieTitle)}: ${rating}/10`);
      overlay.remove();
      // Refresh page recommendations if on dashboard
      if (window.loadDashboard) window.loadDashboard();
    } catch (err) {
      Toast.error(err.message || 'Could not save rating.');
      btn.textContent = 'Save Rating';
      btn.disabled = false;
    }
  });

  // Delete rating
  overlay.querySelector('#cm-rate-delete')?.addEventListener('click', async () => {
    try {
      await API.movies.deleteRating(movieId);
      Toast.info('Rating removed.');
      overlay.remove();
    } catch {
      Toast.error('Could not remove rating.');
    }
  });
}

// ── GLOBAL INTERACTION HANDLERS ───────────────────────────────
// These are attached globally so movie cards (rendered via JS)
// can trigger them without needing their own event listeners.

window.quickRate = function(e, movieId, movieTitle) {
  e.preventDefault();
  e.stopPropagation();
  if (!API.auth.isLoggedIn()) {
    window.location.href = '/auth/login/';
    return;
  }
  openRatingModal(movieId, movieTitle);
};

window.toggleWatchlist = async function(e, movieId, btn) {
  e.preventDefault();
  e.stopPropagation();
  if (!API.auth.isLoggedIn()) {
    window.location.href = '/auth/login/';
    return;
  }

  const isActive = btn.classList.contains('active');
  btn.disabled = true;

  try {
    if (isActive) {
      await API.watchlist.remove(movieId);
      btn.classList.remove('active');
      btn.textContent = '♡';
      Toast.info('Removed from watchlist');
    } else {
      await API.watchlist.add(movieId);
      btn.classList.add('active');
      btn.textContent = '♥';
      Toast.success('Added to watchlist');
    }
  } catch (err) {
    Toast.error(err.data?.non_field_errors?.[0] || 'Could not update watchlist.');
  } finally {
    btn.disabled = false;
  }
};

window.trackClick = function(e, movieId, recId) {
  // Don't prevent default — let the link navigate
  if (recId) API.recs.markClicked(recId).catch(() => {});
  API.movies.recordView(movieId).catch(() => {});
};

// ── HELPERS ───────────────────────────────────────────────────
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Navbar scroll effect
document.addEventListener('DOMContentLoaded', () => {
  const navbar = document.querySelector('.navbar');
  if (navbar) {
    window.addEventListener('scroll', () => {
      navbar.classList.toggle('scrolled', window.scrollY > 20);
    }, { passive: true });
  }

  // Init all carousels on page
  document.querySelectorAll('.carousel').forEach(initCarousel);
});

// Export
window.Toast = Toast;
window.Skeleton = Skeleton;
window.MovieCard = MovieCard;
window.StarRatingWidget = StarRatingWidget;
window.openRatingModal = openRatingModal;
window.initCarousel = initCarousel;
window.escHtml = escHtml;