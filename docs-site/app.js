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

// Curated section labels keep top navigation focused on useful destinations.
const PAGE_NAV_ITEMS = {
  readme: [
    ['Why MARM Memory', 'Why MARM'],
    ['Performance & Scaling Benchmarks', 'Performance'],
    ['Quick Start for MCP (HTTP & STDIO)', 'Quick Start'],
    ['Complete MCP Tool Suite (14 Tools)', 'Tools'],
    ['Using MARM: Talk, Don\'t Call Tools', 'Using MARM'],
    ['Knowledge Graphs: Code & Concepts', 'Knowledge Graphs'],
    ['MARM Dashboard', 'Dashboard'],
    ['Architecture & Internals', 'Architecture'],
    ['Troubleshooting', 'Troubleshooting'],
    ['Contributing', 'Contributing'],
  ],
  faq: [
    ['General', 'General'],
    ['Setup & Installation', 'Setup'],
    ['Tools & Capabilities', 'Tools'],
    ['Multi-Agent & Swarm', 'Multi-Agent'],
    ['Memory, Search & Maintenance', 'Memory & Search'],
  ],
  roadmap: [
    ['Strategic Direction', 'Direction'],
    ['Current Foundation', 'Foundation'],
    ['MCP Server Roadmap', 'MCP Server'],
    ['Dashboard Roadmap', 'Dashboard'],
    ['Shared Technical Priorities', 'Priorities'],
    ['Long-Term Possibilities', 'Long-Term'],
  ],
  'install-docker': [
    ['Quick Start (2 Minutes)', 'Quick Start'],
    ['Installation Options', 'Install Options'],
    ['Client Connections', 'Client Setup'],
    ['Management Commands', 'Commands'],
    ['Verification & Testing', 'Verify'],
    ['Troubleshooting', 'Troubleshooting'],
    ['Configuration', 'Configuration'],
  ],
  'install-windows': [
    ['Quick Start (5 Minutes)', 'Quick Start'],
    ['System Requirements', 'Requirements'],
    ['Installation Options', 'Install Options'],
    ['Client Connections', 'Client Setup'],
    ['Verification & Testing', 'Verify'],
    ['Troubleshooting', 'Troubleshooting'],
    ['Configuration', 'Configuration'],
  ],
  'install-linux': [
    ['Quick Start (5 Minutes)', 'Quick Start'],
    ['System Requirements', 'Requirements'],
    ['Installation Options', 'Install Options'],
    ['Distribution-Specific Setup', 'Distributions'],
    ['Client Connections', 'Client Setup'],
    ['Verification & Testing', 'Verify'],
    ['Troubleshooting', 'Troubleshooting'],
  ],
  'install-platforms': [
    ['Overview: Connecting MARM to Apps & Platforms', 'Overview'],
    ['Part 1: Base Application Integration', 'Base Apps'],
    ['Part 2: Developer Integration', 'Developer Apps'],
    ['Platform Comparison Summary', 'Comparison'],
    ['Best Practices', 'Best Practices'],
  ],
  contributing: [
    ['Getting Started', 'Getting Started'],
    ['Development', 'Development'],
    ['Adding or Changing MCP Tools', 'MCP Tools'],
    ['Testing', 'Testing'],
    ['Documentation', 'Documentation'],
    ['Submitting Changes', 'Submitting Changes'],
  ],
  contributors: [
    ['Core Maintainers', 'Maintainers'],
    ['Code Contributors', 'Contributors'],
    ['Security Acknowledgments', 'Security'],
  ],
};

// ── Marked: custom heading renderer for stable anchor IDs ────────
const renderer = new marked.Renderer();

renderer.heading = function (text, level) {
  const plain = DOMPurify.sanitize(text, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
  const id = plain
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/[\s_]+/g, '-')
    .replace(/-{2,}/g, '-');
  return `<h${level} id="${id}">${text}</h${level}>\n`;
};

marked.setOptions({ renderer, gfm: true, breaks: false });

function sanitizeRenderedHtml(html) {
  if (typeof DOMPurify === 'undefined') {
    throw new Error('The documentation sanitizer did not load.');
  }
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}

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

// ── Current-page navigation ────────────────────────────────────────
const pageNavInner = document.getElementById('page-nav-inner');
const pageNavToggle = document.getElementById('page-nav-toggle');
const pageNavFlyout = document.getElementById('page-nav-flyout');
const pageNavClose = document.getElementById('page-nav-close');

function normalizeHeading(value) {
  return value
    .replace(/[^\w\s&:()/.-]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function setPageNavOpen(open) {
  const shouldOpen = open && !pageNavToggle.disabled;
  pageNavFlyout.classList.toggle('open', shouldOpen);
  pageNavFlyout.setAttribute('aria-hidden', String(!shouldOpen));
  pageNavToggle.setAttribute('aria-expanded', String(shouldOpen));
}

function buildPageNav(container, docId) {
  pageNavInner.innerHTML = '';
  const configuredItems = PAGE_NAV_ITEMS[docId];
  const headings = configuredItems
    ? configuredItems.map(([heading, label]) => {
      const target = [...container.querySelectorAll('h2, h3')]
        .find(element => normalizeHeading(element.textContent) === normalizeHeading(heading));
      return target ? { target, label } : null;
    }).filter(Boolean)
    : [...container.querySelectorAll('h2')]
      .filter(heading => !['Table of Contents', 'Related Docs'].includes(heading.textContent.trim()))
      .map(target => ({ target, label: target.textContent.trim() }));

  if (!headings.length) {
    const em = document.createElement('p');
    em.className = 'page-nav-empty';
    em.textContent = 'This document does not have section navigation.';
    pageNavInner.appendChild(em);
    pageNavToggle.disabled = true;
    setPageNavOpen(false);
    return;
  }

  pageNavToggle.disabled = false;

  headings.forEach(({ target, label }) => {
    const a = document.createElement('a');
    a.href = `#${target.id}`;
    a.className = 'page-nav-link';
    a.textContent = label;
    a.addEventListener('click', e => {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setPageNavOpen(false);
    });
    pageNavInner.appendChild(a);
  });
}

function applyTableOfContents(container) {
  const heading = [...container.querySelectorAll('h2')]
    .find(element => normalizeHeading(element.textContent) === 'table of contents');
  const list = heading?.nextElementSibling;
  if (list?.tagName === 'UL') list.classList.add('table-of-contents-grid');
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
  pageNavInner.innerHTML = '';
  contentEl.innerHTML = `<div class="loading-state">
    <div class="loading-spinner"></div>
    <span>Loading ${doc.label}...</span>
  </div>`;

  try {
    const markdown = await fetchMarkdown(doc.path);
    let html = marked.parse(markdown);
    html = processAlerts(html);
    html = sanitizeRenderedHtml(html);

    contentEl.innerHTML = html;
    contentEl.classList.add('loaded');

    // Reset scroll position
    window.scrollTo({ top: 0, behavior: 'instant' });

    applyCodeBlocks(contentEl);
    applyTableOfContents(contentEl);
    buildPageNav(contentEl, doc.id);

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
    buildPageNav(contentEl, doc.id);
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
  setPageNavOpen(false);
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

pageNavToggle.addEventListener('click', () => {
  setPageNavOpen(!pageNavFlyout.classList.contains('open'));
});

pageNavClose.addEventListener('click', () => setPageNavOpen(false));

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

overlay.addEventListener('click', () => {
  closeSidebar();
  setPageNavOpen(false);
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeSidebar();
    setPageNavOpen(false);
  }
});

// ── Boot ──────────────────────────────────────────────────────────
loadDoc(docFromHash());
