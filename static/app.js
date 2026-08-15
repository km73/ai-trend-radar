/* ===================================================================
   全球AI热点雷达 — Frontend SPA (DESIGN·TANG system)
   FULLSTACK MODE: calls FastAPI backend for data + refresh.
   =================================================================== */

const REDUCE = matchMedia('(prefers-reduced-motion: reduce)').matches;

let allArticles = [];
let currentFilter = { category: 'all', tag: 'all', sort: 'hot', q: '' };

const grid = document.getElementById('grid');
const searchInput = document.getElementById('searchInput');
const resultCount = document.getElementById('resultCount');
const refreshBtn = document.getElementById('refreshBtn');
const toast = document.getElementById('toast');
const themeToggle = document.getElementById('themeToggle');
const statTotal = document.getElementById('statTotal');
const statNews = document.getElementById('statNews');
const statCommentary = document.getElementById('statCommentary');
const statSocial = document.getElementById('statSocial');
const statVideo = document.getElementById('statVideo');
const statTranslated = document.getElementById('statTranslated');
const statRefresh = document.getElementById('statRefresh');

// ===== THEME =====
themeToggle.addEventListener('click', () => {
  const html = document.documentElement;
  html.setAttribute('data-theme', html.getAttribute('data-theme') === 'light' ? '' : 'light');
});

// ===== CHIPS =====
function setupChips(containerId, dataAttr, onSelect) {
  const container = document.getElementById(containerId);
  const chips = container.querySelectorAll('.chip');
  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      chips.forEach(c => { c.classList.remove('active'); c.setAttribute('aria-pressed', 'false'); });
      chip.classList.add('active'); chip.setAttribute('aria-pressed', 'true');
      onSelect(chip.dataset[dataAttr]);
      loadAndRender();
    });
    chip.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); chip.click(); } });
  });
}
setupChips('tagChips', 'tag', v => currentFilter.tag = v);
setupChips('catChips', 'cat', v => currentFilter.category = v);
setupChips('sortChips', 'sort', v => currentFilter.sort = v);

// ===== SEARCH =====
let searchTimer = null;
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { currentFilter.q = searchInput.value.trim(); loadAndRender(); }, 300);
});

// ===== BACKEND API CALLS =====
async function fetchArticles() {
  const params = new URLSearchParams({
    category: currentFilter.category, tag: currentFilter.tag,
    q: currentFilter.q, sort: currentFilter.sort, limit: 200, offset: 0
  });
  try {
    const resp = await fetch(`/api/articles?${params}`);
    const data = await resp.json();
    allArticles = data.articles || [];
    return data;
  } catch (e) { console.error('[Radar] API fetch failed:', e); return null; }
}

async function fetchStats() {
  try {
    const resp = await fetch('/api/stats');
    return await resp.json();
  } catch (e) { console.error('[Radar] stats failed:', e); return null; }
}

// ===== FADE-THROUGH =====
function fadeSwap(el, renderFn) {
  if (REDUCE) { renderFn(); return; }
  el.style.transition = 'opacity .14s var(--ease-standard), transform .14s var(--ease-standard)';
  el.style.opacity = '0'; el.style.transform = 'translateY(-6px)';
  setTimeout(() => {
    renderFn();
    requestAnimationFrame(() => {
      el.style.transition = 'opacity .28s var(--spring-gentle), transform .28s var(--spring-gentle)';
      el.style.opacity = '1'; el.style.transform = 'translateY(0)';
    });
  }, 140);
}

// ===== RENDER =====
function renderCards(articles) {
  grid.innerHTML = '';
  if (!articles.length) {
    grid.innerHTML = '<div class="t-body-l" style="padding:var(--s7);text-align:center;color:var(--fg-mute);">无匹配结果。尝试调整过滤条件或搜索关键词。</div>';
    return;
  }
  resultCount.textContent = `显示 ${articles.length} 条 · 按${currentFilter.sort === 'hot' ? '热度' : currentFilter.sort === 'time' ? '时间' : '浏览量'}排序`;

  articles.forEach((art, i) => {
    const card = document.createElement('div');
    card.className = `card level-${art.level} state`;
    card.setAttribute('data-index', i);

    const tagsHtml = (art.tags || '').split(';').map(t => {
      t = t.trim(); let cls = '';
      if (t === 'HR') cls = ' tag-hr'; else if (t === 'HR服务') cls = ' tag-hrs';
      return `<span class="tag${cls}">${t}</span>`;
    }).join('');

    const hotPct = art.hot_percent ? `${art.hot_percent}%` : 'N/A';
    let timeDisplay = '';
    if (art.time_published) {
      try { const d = new Date(art.time_published); timeDisplay = d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }); }
      catch (e) { timeDisplay = art.time_published.slice(0, 10); }
    }

    // 英文原文（若有翻译则展示原英文，便于溯源）
    const origTitleHtml = art.original_title && art.original_title !== art.title
      ? `<div class="extra-row"><span class="extra-label t-label-m">原文</span><span class="extra-text t-body-s" style="font-family:var(--mono);color:var(--fg-mute);">${escapeHtml(art.original_title)}</span></div>` : '';
    const origSummaryHtml = art.original_summary && art.original_summary !== art.summary
      ? `<div class="extra-row"><span class="extra-label t-label-m">原摘</span><span class="extra-text t-body-s" style="font-family:var(--mono);color:var(--fg-mute);">${escapeHtml(art.original_summary)}</span></div>` : '';

    card.innerHTML = `
      <div class="card-head"><div class="card-title t-title-m"><a href="${art.url}" target="_blank" rel="noopener noreferrer">${escapeHtml(art.title)}</a></div><span class="hot-badge level-${art.level} t-label-l">${art.level_emoji || ''} ${hotPct}</span></div>
      <div class="card-meta"><span class="card-source">${art.source || 'N/A'}</span><span>${timeDisplay}</span><span>${formatNum(art.views)}</span><span>${formatNum(art.engagement)}</span></div>
      <div class="card-tags">${tagsHtml}</div>
      <div class="card-summary t-body-m">${escapeHtml(art.summary || '')}</div>
      <span class="expand-hint"></span>
      <div class="card-extra"><div class="extra-row"><span class="extra-label t-label-m">WHY</span><span class="extra-text t-body-m">${escapeHtml(art.why_hot || 'N/A')}</span></div><div class="extra-row"><span class="extra-label t-label-m">TAKE</span><span class="extra-text t-body-m">${escapeHtml(art.takeaway || 'N/A')}</span></div><div class="extra-row"><span class="extra-label t-label-m">KW</span><span class="extra-text t-body-s">${escapeHtml(art.keywords || 'N/A')}</span></div>${origTitleHtml}${origSummaryHtml}</div>
    `;
    card.addEventListener('click', (e) => { if (e.target.tagName === 'A') return; card.classList.toggle('expanded'); });
    grid.appendChild(card);
  });

  if (!REDUCE) {
    const cards = grid.querySelectorAll('.card');
    cards.forEach((c, i) => {
      c.style.opacity = '0'; c.style.transform = 'translateY(8px)';
      setTimeout(() => {
        c.style.transition = `opacity var(--dur-3) var(--spring-gentle), transform var(--dur-3) var(--spring-gentle)`;
        c.style.transitionDelay = `${i * 50}ms`;
        c.style.opacity = '1'; c.style.transform = 'translateY(0)';
        setTimeout(() => { c.style.transitionDelay = '0ms'; }, 400 + i * 50);
      }, 50);
    });
  }
}

function formatNum(n) {
  if (!n || n === 0) return '0';
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(0) + 'K';
  return n.toString();
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function updateStats(stats) {
  if (!stats) return;
  statTotal.textContent = stats.total || '0';
  const cats = stats.by_category || {};
  statNews.textContent = cats.news || '0';
  statCommentary.textContent = cats.commentary || '0';
  statSocial.textContent = cats.social || '0';
  statVideo.textContent = cats.video || '0';
  statTranslated.textContent = stats.translated || '0';
  if (stats.last_refresh) {
    try { const d = new Date(stats.last_refresh); statRefresh.textContent = d.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
    catch (e) { statRefresh.textContent = stats.last_refresh.slice(0, 16); }
  }
}

async function loadAndRender() {
  const data = await fetchArticles();
  if (data) fadeSwap(grid, () => renderCards(allArticles));
}

// ===== REFRESH (calls backend /api/refresh to trigger live scraping) =====
refreshBtn.addEventListener('click', async () => {
  refreshBtn.disabled = true;
  showToast('正在从全球数据源抓取最新AI热点...');
  try {
    const resp = await fetch('/api/refresh', { method: 'POST' });
    const data = await resp.json();
    const trMsg = data.translated ? `，自动翻译 ${data.translated} 篇` : '';
    showToast(`刷新完成！新增 ${data.new_articles || 0} 条${trMsg}，总计 ${data.total_now || 0} 条`);
    const stats = await fetchStats();
    updateStats(stats);
    await loadAndRender();
  } catch (e) { showToast('刷新失败，请稍后再试'); }
  finally { refreshBtn.disabled = false; }
});

function showToast(msg) {
  toast.textContent = msg; toast.classList.add('show');
  setTimeout(() => { toast.classList.remove('show'); }, 3000);
}

// ===== BOOT =====
(async () => {
  const stats = await fetchStats();
  updateStats(stats);
  await loadAndRender();
})();
