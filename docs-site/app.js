'use strict';

/* ============================================================
   MARM Documentation — app.js
   Routing, markdown rendering, top nav, mobile, copy buttons.
   ============================================================ */

// ── Doc registry ─────────────────────────────────────────────────
const DOCS = [
  { id: 'readme',            path: './README.md',                 label: 'Readme' },
  { id: 'faq',               path: './docs/FAQ.md',               label: 'FAQ' },
  { id: 'protocol',          path: './docs/PROTOCOL.md',          label: 'MCP Protocol' },
  { id: 'roadmap',           path: './docs/ROADMAP.md',           label: 'Roadmap' },
  { id: 'install-docker',    path: './docs/INSTALL-DOCKER.md',    label: 'Docker Install' },
  { id: 'install-windows',   path: './docs/INSTALL-WINDOWS.md',   label: 'Windows Install' },
  { id: 'install-linux',     path: './docs/INSTALL-LINUX.md',     label: 'Linux Install' },
  { id: 'install-platforms', path: './docs/INSTALL-PLATFORMS.md', label: 'Other Platforms' },
  { id: 'contributing',      path: './CONTRIBUTING.md',           label: 'Contributing' },
  { id: 'changelog',         path: './CHANGELOG.md',              label: 'Changelog' },
  { id: 'contributors',      path: './CONTRIBUTORS.md',           label: 'Contributors' },
];

// ── Marked: custom heading renderer for stable anchor IDs ────────
const renderer = new marked.Renderer();

renderer.heading = function (text, level) {
  const plain = text.replace(/<[^>]+>/g, '');
  const id = plain
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/[\s_]+/g, '-')
    .replace(/-{2,}/g, '-');
  return `<h${level} id="${id}">${text}</h${level}>\n`;
};

marked.setOptions({ renderer, gfm: true, breaks: false });

// ── GitHub-style alert post-processor ────────────────────────────
const ALERT_TYPES = {
  NOTE:      { icon: 'ℹ',  label: 'Note' },
  TIP:       { icon: '◈',  label: 'Tip' },
  IMPORTANT: { icon: '⚡', label: 'Important' },
  WARNING:   { icon: '⚠',  label: 'Warning' },
  CAUTION:   { icon: '🔥', label: 'Caution' },
};

function processAlerts(html) {
  return html.replace(
    /<blockquote>\s*<p>\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*([\s\S]*?)<\/p>\s*<\/blockquote>/gi,
    (_, type, body) => {
      const t = type.toUpperCase();
      const { icon, label } = ALERT_TYPES[t] || { icon: 'ℹ', label: type };
      return `<div class="gh-alert gh-alert-${t.toLowerCase()}" role="note">
  <div class="gh-alert-header"><span aria-hidden="true">${icon}</span>${label}</div>
  <div class="gh-alert-body">${body.trim()}</div>
</div>`;
    }
  );
}

// ── Syntax highlight + copy buttons ──────────────────────────────
function applyCodeBlocks(container) {
  container.querySelectorAll('pre code').forEach(el => {
    try { hljs.highlightElement(el); } catch (_) {}
  });

  container.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector('.code-copy-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'code-copy-btn';
    btn.textContent = 'copy';
    btn.setAttribute('aria-label', 'Copy code');
    btn.addEventListener('click', async () => {
      const code = pre.querySelector('code');
      if (!code) return;
      try {
        await navigator.clipboard.writeText(code.innerText);
        btn.textContent = 'copied!';
        btn.classList.add('copied');
        setTimeout(() => {
          btn.textContent = 'copy';
          btn.classList.remove('copied');
        }, 2000);
      } catch (_) {}
    });
    pre.appendChild(btn);
  });
}

// ── Top quick-nav ─────────────────────────────────────────────────
const topnavInner = document.getElementById('topnav-inner');

function buildTopNav(container) {
  topnavInner.innerHTML = '';
  const headings = container.querySelectorAll('h2');

  if (!headings.length) {
    const em = document.createElement('span');
    em.className = 'topnav-empty';
    topnavInner.appendChild(em);
    return;
  }

  headings.forEach(h => {
    const a = document.createElement('a');
    a.href = `#${h.id}`;
    a.className = 'topnav-link';
    a.textContent = h.textContent.trim();
    a.addEventListener('click', e => {
      e.preventDefault();
      h.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    topnavInner.appendChild(a);
  });
}

// ── Markdown fetch cache ──────────────────────────────────────────
const cache = new Map();

async function fetchMarkdown(path) {
  if (cache.has(path)) return cache.get(path);
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Could not load ${path} (HTTP ${res.status})`);
  const text = await res.text();
  cache.set(path, text);
  return text;
}

// ── Sidebar active state ──────────────────────────────────────────
function setActiveNav(id) {
  document.querySelectorAll('.nav-item[data-doc]').forEach(el => {
    el.classList.toggle('active', el.dataset.doc === id);
  });
}

// ── Load a document ───────────────────────────────────────────────
const contentEl = document.getElementById('content');

async function loadDoc(id) {
  const doc = DOCS.find(d => d.id === id) || DOCS[0];

  setActiveNav(doc.id);
  contentEl.classList.remove('loaded');
  topnavInner.innerHTML = '';
  contentEl.innerHTML = `<div class="loading-state">
    <div class="loading-spinner"></div>
    <span>Loading ${doc.label}...</span>
  </div>`;

  try {
    const markdown = await fetchMarkdown(doc.path);
    let html = marked.parse(markdown);
    html = processAlerts(html);

    contentEl.innerHTML = html;
    contentEl.classList.add('loaded');

    // Reset scroll position
    window.scrollTo({ top: 0, behavior: 'instant' });

    applyCodeBlocks(contentEl);
    buildTopNav(contentEl);

    // Page title from first h1
    const h1 = contentEl.querySelector('h1');
    document.title = h1
      ? `${h1.textContent.replace(/[◈⬡◎▣◇⌂?]/g, '').trim()} — MARM Docs`
      : 'MARM Memory — Documentation';

  } catch (err) {
    contentEl.innerHTML = `<div class="error-state">
      <p class="error-title">◈ Failed to load document</p>
      <p>${err.message}</p>
    </div>`;
    buildTopNav(contentEl);
  }
}

// ── Hash router ───────────────────────────────────────────────────
function docFromHash() {
  const raw = location.hash.replace('#', '');
  return DOCS.find(d => d.id === raw)?.id ?? 'readme';
}

function navigate(id) {
  if (location.hash !== `#${id}`) {
    history.pushState(null, '', `#${id}`);
  }
  loadDoc(id);
  closeSidebar();
}

window.addEventListener('popstate', () => loadDoc(docFromHash()));

// ── Sidebar nav clicks ────────────────────────────────────────────
document.querySelectorAll('.nav-item[data-doc]').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    navigate(link.dataset.doc);
  });
});

// ── Mobile sidebar ────────────────────────────────────────────────
const menuToggle   = document.getElementById('menu-toggle');
const sidebar      = document.getElementById('sidebar');
const overlay      = document.getElementById('mobile-overlay');

function openSidebar() {
  sidebar.classList.add('open');
  overlay.classList.add('open');
  menuToggle.classList.add('open');
  menuToggle.setAttribute('aria-expanded', 'true');
}

function closeSidebar() {
  sidebar.classList.remove('open');
  overlay.classList.remove('open');
  menuToggle.classList.remove('open');
  menuToggle.setAttribute('aria-expanded', 'false');
}

menuToggle.addEventListener('click', () => {
  sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
});

overlay.addEventListener('click', closeSidebar);

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeSidebar();
});

// ── Boot ──────────────────────────────────────────────────────────
loadDoc(docFromHash());
