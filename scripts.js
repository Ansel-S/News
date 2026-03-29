/**
 * AllStar Terminal — Main Script
 * Handles: data fetching, card rendering, reader mode modal, live clock.
 * Zero external dependencies. Zero trackers.
 */

'use strict';

/* ─────────────────────────────────────────────
   Constants & State
───────────────────────────────────────────── */
const DATA_URL    = './data.json';
const POLL_MS     = 4 * 60 * 60 * 1000;   // 4 hours — matches Actions schedule

const state = {
  articles: [],
  lastFetched: null,
  activeCard: null,
};

/* ─────────────────────────────────────────────
   DOM Refs  (populated after DOMContentLoaded)
───────────────────────────────────────────── */
let dom = {};

/* ─────────────────────────────────────────────
   Utility Helpers
───────────────────────────────────────────── */

/**
 * Relative time string: "3 min ago", "2 h ago", "Jan 5"
 */
function relativeTime(isoString) {
  const now   = Date.now();
  const past  = new Date(isoString).getTime();
  const delta = Math.max(0, now - past);
  const sec   = Math.floor(delta / 1000);
  const min   = Math.floor(sec  / 60);
  const hr    = Math.floor(min  / 60);
  const day   = Math.floor(hr   / 24);

  if (sec < 60)  return 'Just now';
  if (min < 60)  return `${min}m ago`;
  if (hr  < 24)  return `${hr}h ago`;
  if (day <  7)  return `${day}d ago`;

  return new Date(isoString).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric',
  });
}

/**
 * Format ISO string to readable date for modal.
 */
function fullDate(isoString) {
  return new Date(isoString).toLocaleString('en-US', {
    weekday: 'long', year: 'numeric',
    month:   'long', day: 'numeric',
    hour:    '2-digit', minute: '2-digit',
    timeZoneName: 'short',
  });
}

/**
 * Escape a string for safe insertion as text.
 */
function esc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

/**
 * Minimal sanitizer: drops scripts/iframes/event-handlers from HTML.
 * The heavy cleaning is done in Python; this is a client-side safety net.
 */
function sanitizeHTML(html) {
  const tpl = document.createElement('template');
  tpl.innerHTML = html;

  const forbidden = ['script', 'iframe', 'object', 'embed', 'form', 'input', 'button'];
  forbidden.forEach(tag => {
    tpl.content.querySelectorAll(tag).forEach(el => el.remove());
  });

  // Strip on* attributes
  tpl.content.querySelectorAll('*').forEach(el => {
    [...el.attributes].forEach(attr => {
      if (/^on/i.test(attr.name) || /^javascript:/i.test(attr.value)) {
        el.removeAttribute(attr.name);
      }
    });
    // Open external links in new tab safely
    if (el.tagName === 'A') {
      el.setAttribute('target', '_blank');
      el.setAttribute('rel',    'noopener noreferrer');
    }
  });

  return tpl.innerHTML;
}

/* ─────────────────────────────────────────────
   Live Clock
───────────────────────────────────────────── */
function startClock() {
  const tickEl = dom.clockTime;
  const dateEl = dom.clockDate;
  if (!tickEl) return;

  function tick() {
    const now = new Date();
    tickEl.textContent = now.toLocaleTimeString('en-US', {
      hour:   '2-digit',
      minute: '2-digit',
      hour12: false,
    });
    dateEl.textContent = now.toLocaleDateString('en-US', {
      weekday: 'long',
      month:   'short',
      day:     'numeric',
    });
  }

  tick();
  setInterval(tick, 1000);
}

/* ─────────────────────────────────────────────
   Status Bar
───────────────────────────────────────────── */
function setStatus(type, text) {
  const dot  = dom.statusDot;
  const label = dom.statusLabel;
  if (!dot || !label) return;

  dot.className = 'status-dot';
  if (type === 'loading') dot.classList.add('loading');
  if (type === 'error')   dot.classList.add('error');

  label.textContent = text;
}

/* ─────────────────────────────────────────────
   Skeleton Loaders
───────────────────────────────────────────── */
function renderSkeletons(container, count = 3) {
  container.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const card = document.createElement('article');
    card.className = 'skeleton-card';
    card.innerHTML = `
      <div class="skeleton-line w-40"  style="height:9px;margin-bottom:12px"></div>
      <div class="skeleton-line w-80 h-16" style="margin-bottom:6px"></div>
      <div class="skeleton-line w-60 h-12"></div>
    `;
    container.appendChild(card);
  }
}

function showSkeletons() {
  ['pulse', 'facts', 'geek'].forEach(col => {
    const list = document.querySelector(`.col-${col} .feed-list`);
    if (list) renderSkeletons(list);
  });
}

/* ─────────────────────────────────────────────
   Card Rendering
───────────────────────────────────────────── */
function buildCard(article, column) {
  const card = document.createElement('article');
  card.className = 'news-card';
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  card.setAttribute('aria-label', `Read: ${article.title}`);

  // Tag-based accent
  const safeTag = (article.source_tag || '').replace(/\s+/g, '-').toLowerCase();
  if (article.source_tag) card.classList.add(`tag-${safeTag}`);

  // Thumbnail
  const imageHTML = article.image
    ? `<img class="card-image" src="${esc(article.image)}" alt="" loading="lazy" onerror="this.style.display='none'">`
    : '';

  // External link (stops propagation so it doesn't open reader)
  const extLink = `
    <a class="card-ext-link"
       href="${esc(article.link)}"
       target="_blank"
       rel="noopener noreferrer"
       title="Open original"
       aria-label="Open original article"
       onclick="event.stopPropagation()">
      <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M5 2H2a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1V7"/>
        <path d="M8 1h3v3"/>
        <path d="M11 1 5.5 6.5"/>
      </svg>
    </a>`;

  card.innerHTML = `
    ${imageHTML}
    <div class="card-meta">
      <span class="card-source-icon" aria-hidden="true">${esc(article.source_icon)}</span>
      <span class="card-source-name">${esc(article.source_label)}</span>
      <span class="card-tag">${esc(article.source_tag)}</span>
      <time class="card-time" datetime="${esc(article.published)}">${relativeTime(article.published)}</time>
    </div>
    <h2 class="card-title">${esc(article.title)}</h2>
    ${article.summary ? `<p class="card-summary">${esc(article.summary)}</p>` : ''}
    <footer class="card-footer">
      <span class="card-read-hint">
        <svg viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path d="M1 5h8M6 2l3 3-3 3"/>
        </svg>
        Reader
      </span>
      ${extLink}
    </footer>
  `;

  // Open reader on click / Enter key
  card.addEventListener('click', () => openReader(article));
  card.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openReader(article);
    }
  });

  return card;
}

/* ─────────────────────────────────────────────
   Column Rendering
───────────────────────────────────────────── */
function renderColumns(articles) {
  const columns = {
    pulse: articles.filter(a => a.column === 'pulse'),
    facts: articles.filter(a => a.column === 'facts'),
    geek:  articles.filter(a => a.column === 'geek'),
  };

  ['pulse', 'facts', 'geek'].forEach(col => {
    const list    = document.querySelector(`.col-${col} .feed-list`);
    const counter = document.querySelector(`.col-${col} .col-count`);
    if (!list) return;

    list.innerHTML = '';

    const items = columns[col];
    if (!items.length) {
      list.innerHTML = `<p style="color:var(--text-tertiary);font-size:12px;padding:8px 4px;">No articles loaded.</p>`;
    } else {
      items.forEach(article => list.appendChild(buildCard(article, col)));
    }

    if (counter) counter.textContent = items.length;
  });
}

/* ─────────────────────────────────────────────
   Data Fetching
───────────────────────────────────────────── */
async function fetchData(showSkeleton = true) {
  if (showSkeleton) showSkeletons();
  setStatus('loading', 'Updating…');
  dom.refreshBtn?.classList.add('spinning');

  try {
    const res  = await fetch(`${DATA_URL}?t=${Date.now()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    state.articles   = data.articles || [];
    state.lastFetched = data.generated_at;

    renderColumns(state.articles);

    const ts = new Date(state.lastFetched);
    setStatus('live', `Updated ${relativeTime(state.lastFetched)}`);

  } catch (err) {
    console.error('[AllStar] Fetch error:', err);
    setStatus('error', 'Fetch failed');

    if (!state.articles.length) {
      // Show error state in grid if no cached data
      const grid = document.querySelector('.terminal-grid');
      if (grid) {
        ['pulse','facts','geek'].forEach(col => {
          const list = document.querySelector(`.col-${col} .feed-list`);
          if (list) {
            list.innerHTML = `
              <div class="error-state" style="text-align:center;padding:32px 12px">
                <div style="font-size:32px;margin-bottom:8px">⚠️</div>
                <p style="font-size:12px;color:var(--text-secondary)">
                  Could not load feed data.<br>
                  Make sure <code>data.json</code> exists<br>and the GitHub Action has run.
                </p>
              </div>`;
          }
        });
      }
    }
  } finally {
    dom.refreshBtn?.classList.remove('spinning');
  }
}

/* ─────────────────────────────────────────────
   Reader Mode Modal
───────────────────────────────────────────── */
function openReader(article) {
  state.activeCard = article;

  const body = article.body_html
    ? sanitizeHTML(article.body_html)
    : null;

  const contentHTML = body
    ? `<div class="reader-content">${body}</div>`
    : `<div class="reader-empty">
         <div class="empty-icon">📄</div>
         <p>No full content was fetched for this article.<br>
            The RSS feed may only provide a summary.</p>
       </div>`;

  dom.modalTitle.textContent    = article.title;
  dom.modalSourceIcon.textContent = article.source_icon;
  dom.modalSourceName.textContent = article.source_label;
  dom.modalTag.textContent      = article.source_tag;
  dom.modalDate.textContent     = fullDate(article.published);
  dom.modalLink.href            = article.link;
  dom.modalLink.textContent     = 'Open original ↗';
  dom.modalBody.innerHTML       = contentHTML;
  dom.modalBody.scrollTop       = 0;

  dom.backdrop.classList.add('open');
  document.body.style.overflow = 'hidden';
  dom.modalClose.focus();

  // Trap focus inside modal
  trapFocus(dom.modalPanel);
}

function closeReader() {
  dom.backdrop.classList.remove('open');
  document.body.style.overflow = '';
  state.activeCard = null;
  releaseFocus();
}

/* Minimal focus trap */
let _prevFocus = null;
function trapFocus(el) {
  _prevFocus = document.activeElement;
  const focusable = el.querySelectorAll(
    'a, button, [tabindex]:not([tabindex="-1"])'
  );
  if (!focusable.length) return;

  const first = focusable[0];
  const last  = focusable[focusable.length - 1];

  el._focusTrapHandler = e => {
    if (e.key !== 'Tab') return;
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
      if (document.activeElement === last)  { e.preventDefault(); first.focus(); }
    }
  };
  el.addEventListener('keydown', el._focusTrapHandler);
}

function releaseFocus() {
  const el = dom.modalPanel;
  if (el?._focusTrapHandler) {
    el.removeEventListener('keydown', el._focusTrapHandler);
    delete el._focusTrapHandler;
  }
  _prevFocus?.focus();
}

/* ─────────────────────────────────────────────
   Event Wiring
───────────────────────────────────────────── */
function wireEvents() {
  // Close modal
  dom.modalClose.addEventListener('click', closeReader);
  dom.backdrop.addEventListener('click', e => {
    if (e.target === dom.backdrop) closeReader();
  });

  // ESC key
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && state.activeCard) closeReader();
  });

  // Manual refresh
  dom.refreshBtn?.addEventListener('click', () => {
    if (!dom.refreshBtn.classList.contains('spinning')) fetchData(false);
  });
}

/* ─────────────────────────────────────────────
   Auto-Poll
───────────────────────────────────────────── */
function startAutoPoll() {
  setInterval(() => fetchData(false), POLL_MS);
}

/* ─────────────────────────────────────────────
   Init
───────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  dom = {
    clockTime:      document.getElementById('clock-time'),
    clockDate:      document.getElementById('clock-date'),
    statusDot:      document.getElementById('status-dot'),
    statusLabel:    document.getElementById('status-label'),
    refreshBtn:     document.getElementById('btn-refresh'),
    backdrop:       document.getElementById('modal-backdrop'),
    modalPanel:     document.getElementById('modal-panel'),
    modalClose:     document.getElementById('modal-close'),
    modalTitle:     document.getElementById('modal-title'),
    modalSourceIcon:document.getElementById('modal-source-icon'),
    modalSourceName:document.getElementById('modal-source-name'),
    modalTag:       document.getElementById('modal-tag'),
    modalDate:      document.getElementById('modal-date'),
    modalLink:      document.getElementById('modal-link'),
    modalBody:      document.getElementById('modal-body'),
  };

  startClock();
  wireEvents();
  fetchData();
  startAutoPoll();
});
