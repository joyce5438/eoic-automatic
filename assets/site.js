(() => {
  const normalizeTerms = value => value.normalize('NFKC').toLowerCase().trim().split(/\s+/).filter(Boolean);
  const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const includesAll = (text, terms) => terms.every(term => text.normalize('NFKC').toLowerCase().includes(term));
  const markText = (text, terms) => {
    if (!terms.length) return escapeHTML(text);
    const pattern = new RegExp(terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).sort((a,b) => b.length-a.length).join('|'), 'giu');
    let output = '', last = 0;
    for (const match of text.matchAll(pattern)) { output += escapeHTML(text.slice(last, match.index)) + '<mark>' + escapeHTML(match[0]) + '</mark>'; last = match.index + match[0].length; }
    return output + escapeHTML(text.slice(last));
  };
  const makeSnippet = (text, terms, radius = 40) => { const normalized = text.normalize('NFKC').toLowerCase(); const positions = terms.map(term => normalized.indexOf(term)).filter(pos => pos >= 0); const center = positions.length ? Math.min(...positions) : 0; const start = Math.max(0, center - radius), end = Math.min(text.length, center + Math.max(...terms.map(t => t.length), 1) + radius); return (start ? '…' : '') + markText(text.slice(start, end), terms) + (end < text.length ? '…' : ''); };
  const dateGroupState = hiddenStates => { const visible = hiddenStates.filter(hidden => !hidden).length; return { visible, hidden: visible === 0 }; };
  const highlightText = (text, terms) => ({ original: text, html: markText(text, terms) });
  const clearHighlightedText = result => result.original;
  if (typeof module !== 'undefined') module.exports = { dateGroupState, normalizeTerms, includesAll, makeSnippet, markText, highlightText, clearHighlightedText };
  if (typeof document === 'undefined') return;
  const drawer = document.querySelector('.site-sidebar'), drawerButton = document.querySelector('[data-drawer-open]'), drawerMask = document.querySelector('.drawer-mask');
  const closeDrawer = () => { if (!drawer) return; drawer.classList.remove('is-open'); document.body.classList.remove('drawer-open'); drawerButton.setAttribute('aria-expanded', 'false'); drawerMask.hidden = true; drawerButton.focus(); };
  const openDrawer = () => { drawer.classList.add('is-open'); document.body.classList.add('drawer-open'); drawerButton.setAttribute('aria-expanded', 'true'); drawerMask.hidden = false; (drawer.querySelector('input,button,a') || drawer).focus(); };
  document.addEventListener('click', event => { if (event.target.closest('[data-drawer-open]')) openDrawer(); if (event.target.closest('[data-drawer-close]')) closeDrawer(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && drawer?.classList.contains('is-open')) closeDrawer(); });
  document.querySelector('.side-report-link[aria-current="page"]')?.scrollIntoView({block:'center'});

  const cards = [...document.querySelectorAll('.report-card')];
  if (cards.length) {
    const input = document.querySelector('#search'), activeBox = document.querySelector('#active-tags'), count = document.querySelector('#result-count'), empty = document.querySelector('#empty'), clear = document.querySelector('#clear-all');
    const indexByFile = new Map((window.EOIC_INDEX || []).map(item => [item.url, item])); let tags = new Set(), date = '', timer;
    const allTagButtons = () => [...document.querySelectorAll('[data-tag]')];
    const viewSwitch = document.querySelector('.view-switch');
    const reportList = document.querySelector('#report-list');
    const matrixView = document.querySelector('#matrix-view');
    let currentView = 'timeline';

    const setView = view => {
      currentView = view;
      document.querySelectorAll('.view-tab').forEach(b => {
        const active = b.dataset.view === view;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      if (reportList) reportList.hidden = view !== 'timeline';
      if (matrixView) matrixView.hidden = view !== 'matrix';
      writeHash();
    };

    viewSwitch?.addEventListener('click', e => {
      const tab = e.target.closest('.view-tab');
      if (tab) setView(tab.dataset.view);
    });

    const writeHash = () => {
      const p = new URLSearchParams();
      tags.forEach(t => p.append('tag', t));
      if (input.value.trim()) p.set('q', input.value.trim());
      if (date) p.set('date', date);
      if (currentView !== 'timeline') p.set('view', currentView);
      history.replaceState(null, '', p.toString() ? '#' + p.toString() : location.pathname);
    };

    const apply = () => {
      const terms = normalizeTerms(input.value), selectedByGroup = {}; let shown = 0, fullHits = 0;
      tags.forEach(t => { const button = allTagButtons().find(b => b.dataset.tag === t); if (button) (selectedByGroup[button.dataset.group] ||= []).push(t); });
      cards.forEach(card => {
        const item = indexByFile.get(`reports/${card.dataset.reportFile}`), cardMatch = includesAll(card.dataset.search, terms), matchingSections = terms.length && item ? item.sections.filter(section => includesAll(section.title + ' ' + section.text, terms)) : [];
        const textOK = !terms.length || cardMatch || matchingSections.length > 0, cardGroups = JSON.parse(card.dataset.tagGroups);
        const tagOK = Object.entries(selectedByGroup).every(([group, selected]) => selected.some(t => (cardGroups[group] || []).includes(t)));
        const ok = textOK && (!date || card.dataset.date === date) && tagOK; card.hidden = !ok; if (ok) shown++;
        const hitBox = card.querySelector('.search-hits'); hitBox.hidden = !ok || !matchingSections.length || cardMatch;
        if (!hitBox.hidden) { fullHits += matchingSections.length; hitBox.innerHTML = '<strong>命中段落</strong>' + matchingSections.slice(0, 2).map(section => `<a href="reports/${encodeURIComponent(card.dataset.reportFile)}?q=${encodeURIComponent(input.value.trim())}#${encodeURIComponent(section.id)}"><b>${escapeHTML(section.title)}</b><span>${makeSnippet(section.text, terms)}</span></a>`).join(''); } else hitBox.textContent = '';
      });

      // Synchronize matrix pills
      const matrixPills = [...document.querySelectorAll('.matrix-pill')];
      if (matrixPills.length) {
        matrixPills.forEach(pill => {
          const file = pill.dataset.reportFile;
          const card = cards.find(c => c.dataset.reportFile === file);
          const isVisible = card ? !card.hidden : true;
          pill.classList.toggle('is-dimmed', !isVisible);
        });
        document.querySelectorAll('.matrix-quadrant').forEach(q => {
          const totalInQ = q.querySelectorAll('.matrix-pill').length;
          const visibleInQ = q.querySelectorAll('.matrix-pill:not(.is-dimmed)').length;
          const cntSpan = q.querySelector('.q-count');
          if (cntSpan) cntSpan.textContent = (terms.length || tags.size || date) ? `${visibleInQ}/${totalInQ} 份` : `${totalInQ} 份`;
        });
      }

      document.querySelectorAll('.date-group').forEach(g => { const state = dateGroupState([...g.querySelectorAll('.report-card')].map(card => card.hidden)); g.hidden = state.hidden; const groupCount = g.querySelector('header span'); if (groupCount) groupCount.textContent = `${state.visible} 份`; });
      document.querySelectorAll('.side-report-link').forEach(link => { link.hidden = cards.find(card => card.dataset.reportFile === link.dataset.reportFile)?.hidden ?? false; });
      document.querySelectorAll('.side-report-group').forEach(group => { group.hidden = !group.querySelector('.side-report-link:not([hidden])'); });
      allTagButtons().forEach(b => b.classList.toggle('active', tags.has(b.dataset.tag))); activeBox.innerHTML = [...tags].map(t => `<button class="tag active" data-remove="${escapeHTML(t)}">${escapeHTML(t)} ×</button>`).join('');
      count.textContent = terms.length ? `找到 ${shown} 份（全文命中 ${fullHits} 處）` : `找到 ${shown} 份`; empty.hidden = shown !== 0; clear.hidden = !terms.length && !date && !tags.size; writeHash();
    };

    const reset = () => { tags.clear(); date = ''; input.value = ''; document.querySelectorAll('.date-filter').forEach(b => b.classList.toggle('active', !b.dataset.date)); apply(); };
    document.addEventListener('click', e => { const tag = e.target.closest('[data-tag]'); if (tag) { const t = tag.dataset.tag; tags.has(t) ? tags.delete(t) : tags.add(t); apply(); } const remove = e.target.closest('[data-remove]'); if (remove) { tags.delete(remove.dataset.remove); apply(); } const df = e.target.closest('.date-filter'); if (df) { date = df.dataset.date; document.querySelectorAll('.date-filter').forEach(b => b.classList.toggle('active', b === df)); apply(); } if (e.target.closest('#clear-all') || e.target.closest('#empty button')) reset(); if (e.target.closest('[data-focus-search]')) input.focus(); });
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(apply, 150); });

    const initial = new URLSearchParams(location.hash.slice(1));
    initial.getAll('tag').forEach(t => tags.add(t));
    input.value = initial.get('q') || '';
    date = initial.get('date') || '';
    const initView = initial.get('view');
    if (initView === 'matrix') setView('matrix');
    document.querySelectorAll('.date-filter').forEach(b => b.classList.toggle('active', b.dataset.date === date));
    apply();

    document.addEventListener('keydown', e => { if (e.key === '/' && document.activeElement !== input) { e.preventDefault(); input.focus(); } if (e.key === 'Escape') reset(); });
    if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) { const reveal = new IntersectionObserver(entries => entries.forEach(entry => { if (entry.isIntersecting) { entry.target.classList.add('is-visible'); reveal.unobserve(entry.target); } })); cards.forEach((card, index) => { card.style.setProperty('--delay', `${(index % 8) * 40}ms`); reveal.observe(card); }); } else cards.forEach(card => card.classList.add('is-visible'));
  }

  const prose = document.querySelector('.prose');
  if (prose) {
    // 1. Table tools: Copy as Markdown & Export CSV
    const tables = prose.querySelectorAll('.table-scroll table');
    tables.forEach(table => {
      const scrollBox = table.closest('.table-scroll');
      if (!scrollBox || scrollBox.previousElementSibling?.classList.contains('table-tools')) return;
      const tools = document.createElement('div');
      tools.className = 'table-tools';
      tools.innerHTML = `
        <span class="table-tools-badge">📊 數據表格</span>
        <div class="table-tools-btns">
          <button type="button" class="btn-table-action" data-action="copy-md">📋 複製 Markdown</button>
          <button type="button" class="btn-table-action" data-action="dl-csv">📥 下載 CSV</button>
        </div>
      `;
      scrollBox.parentElement.insertBefore(tools, scrollBox);

      tools.querySelector('[data-action="copy-md"]').addEventListener('click', function() {
        const rows = [...table.querySelectorAll('tr')].map(tr =>
          [...tr.querySelectorAll('th, td')].map(cell => cell.innerText.trim().replace(/\|/g, '\\|').replace(/\s+/g, ' '))
        );
        if (rows.length < 2) return;
        const header = '| ' + rows[0].join(' | ') + ' |';
        const sep = '| ' + rows[0].map(() => '---').join(' | ') + ' |';
        const body = rows.slice(1).map(r => '| ' + r.join(' | ') + ' |').join('\n');
        const md = `${header}\n${sep}\n${body}`;
        navigator.clipboard.writeText(md).then(() => {
          this.textContent = '✓ 已複製！';
          this.classList.add('copied');
          setTimeout(() => {
            this.textContent = '📋 複製 Markdown';
            this.classList.remove('copied');
          }, 1800);
        }).catch(() => {
          prompt('請手動複製以下 Markdown：', md);
        });
      });

      tools.querySelector('[data-action="dl-csv"]').addEventListener('click', function() {
        const rows = [...table.querySelectorAll('tr')].map(tr =>
          [...tr.querySelectorAll('th, td')].map(cell => {
            const val = cell.innerText.trim().replace(/"/g, '""');
            return `"${val}"`;
          }).join(',')
        );
        const csv = '\uFEFF' + rows.join('\r\n');
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const ticker = document.querySelector('.breadcrumb-current')?.innerText?.trim() || document.querySelector('.eyebrow')?.innerText?.trim() || 'EOIC';
        a.href = url;
        a.download = `${ticker}_EOIC_指標數據.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      });
    });

    const reportForm = document.querySelector('.side-search');
    reportForm.addEventListener('submit', event => { event.preventDefault(); const value = reportForm.querySelector('input').value.trim(); location.href = '../index.html' + (value ? '#q=' + encodeURIComponent(value) : ''); });
    const progress = document.querySelector('.reading-progress'); addEventListener('scroll', () => { const max = document.documentElement.scrollHeight - innerHeight; progress.style.transform = `scaleX(${max > 0 ? scrollY / max : 0})`; }, {passive:true});
    const query = new URLSearchParams(location.search).get('q') || '', terms = normalizeTerms(query), originals = [], toolbar = document.querySelector('#hit-toolbar'); let hits = [], current = -1;
    if (terms.length) { const walker = document.createTreeWalker(prose, NodeFilter.SHOW_TEXT, {acceptNode: node => node.parentElement.closest('mark,script,style') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT}), nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(node => { if (!terms.some(term => node.data.normalize('NFKC').toLowerCase().includes(term))) return; const holder = document.createElement('span'); holder.innerHTML = markText(node.data, terms).replaceAll('<mark>', '<mark class="hit">'); originals.push({holder, node: node.cloneNode()}); node.replaceWith(holder); });
      hits = [...prose.querySelectorAll('mark.hit')]; toolbar.hidden = !hits.length; toolbar.querySelector('span').textContent = `找到 ${hits.length} 處`; const go = delta => { if (!hits.length) return; current = (current + delta + hits.length) % hits.length; hits.forEach((hit, i) => hit.classList.toggle('current', i === current)); hits[current].scrollIntoView({behavior:'smooth', block:'center'}); };
      toolbar.querySelector('[data-hit-prev]').addEventListener('click', () => go(-1)); toolbar.querySelector('[data-hit-next]').addEventListener('click', () => go(1)); if (hits.length) setTimeout(() => go(1), 80); toolbar.querySelector('[data-hit-clear]').addEventListener('click', () => { originals.forEach(item => item.holder.replaceWith(item.node)); toolbar.hidden = true; history.replaceState(null, '', location.pathname + location.hash); });
    }
  }
  const links = [...document.querySelectorAll('.toc a')]; if (links.length && 'IntersectionObserver' in window) { const observer = new IntersectionObserver(entries => entries.forEach(entry => { if (entry.isIntersecting) links.forEach(a => a.classList.toggle('active', a.hash === '#' + entry.target.id)); }), {rootMargin:'-15% 0px -70%'}); document.querySelectorAll('.prose h2[id]').forEach(h => observer.observe(h)); }
})();
