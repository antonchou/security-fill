const SecurityFill = (() => {
  const toastEl = () => document.getElementById('toast');

  function toast(msg, ms = 3000) {
    const el = toastEl();
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('show'), ms);
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      credentials: 'same-origin',
      ...options,
    });
    const ct = res.headers.get('content-type') || '';
    let data = null;
    if (ct.includes('application/json')) {
      data = await res.json();
    } else {
      data = await res.text();
    }
    if (!res.ok) {
      const detail = (data && data.detail) || data || res.statusText;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  }

  async function login(email, password) {
    return api('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
  }

  async function register(email, password, name = '') {
    return api('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, name }),
    });
  }

  async function logout() {
    await api('/api/auth/logout', { method: 'POST' });
    location.href = '/';
  }

  function confChip(c) {
    if (c >= 0.7) return `<span class="chip high">置信度 ${(c * 100).toFixed(0)}%</span>`;
    if (c >= 0.4) return `<span class="chip mid">置信度 ${(c * 100).toFixed(0)}%</span>`;
    return `<span class="chip low">置信度 ${(c * 100).toFixed(0)}%</span>`;
  }

  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Logout button on all pages
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('btn-logout');
    if (btn) btn.addEventListener('click', () => logout().catch(e => toast(e.message)));
  });

  async function loadHome() {
    const kbForm = document.getElementById('kb-form');
    const qnForm = document.getElementById('qn-form');
    if (!kbForm) return;

    try {
      const me = await api('/api/auth/me');
      const u = me.usage;
      const line = document.getElementById('usage-line');
      if (line && u) {
        line.textContent =
          `${me.email} · ${u.plan.toUpperCase()} · 文档 ${u.usage.docs}/${u.limits.max_docs}` +
          ` · 本月问卷 ${u.usage.questionnaires_this_month}/${u.limits.max_questionnaires_per_month}` +
          ` · 答案库 ${u.usage.library_items}/${u.limits.max_answer_library}`;
      }
      const pb = document.getElementById('plan-badge');
      if (pb) pb.textContent = (me.plan || 'free').toUpperCase();
    } catch (e) {
      if (String(e.message).includes('Not authenticated') || String(e.message).includes('401')) {
        location.href = '/login';
        return;
      }
    }

    async function refreshKb() {
      const docs = await api('/api/knowledge');
      const box = document.getElementById('kb-list');
      if (!docs.length) {
        box.innerHTML = '<div class="empty">暂无文档 — 可上传 samples/sample_security_policy.txt</div>';
        return;
      }
      box.innerHTML = docs.map(d => `
        <div class="list-item">
          <div>
            <strong>${escapeHtml(d.title)}</strong>
            <span>${escapeHtml(d.source_type)} · ${d.chunk_count} chunks</span>
          </div>
          <button class="btn btn-danger btn-sm" data-del-kb="${d.id}">删除</button>
        </div>
      `).join('');
      box.querySelectorAll('[data-del-kb]').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm('删除该知识库文档？')) return;
          await api(`/api/knowledge/${btn.dataset.delKb}`, { method: 'DELETE' });
          toast('已删除');
          refreshKb();
        });
      });
    }

    async function refreshQn() {
      const items = await api('/api/questionnaires');
      const box = document.getElementById('qn-list');
      if (!items.length) {
        box.innerHTML = '<div class="empty">暂无问卷</div>';
        return;
      }
      box.innerHTML = items.map(q => `
        <div class="list-item">
          <div>
            <strong><a href="/q/${q.id}">${escapeHtml(q.name)}</a></strong>
            <span>${q.question_count} 题 · 已答 ${q.answered_count} · ${escapeHtml(q.status)}</span>
          </div>
          <div class="actions">
            <a class="btn btn-secondary btn-sm" href="/q/${q.id}">打开</a>
            <button class="btn btn-danger btn-sm" data-del-qn="${q.id}">删除</button>
          </div>
        </div>
      `).join('');
      box.querySelectorAll('[data-del-qn]').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm('删除该问卷？')) return;
          await api(`/api/questionnaires/${btn.dataset.delQn}`, { method: 'DELETE' });
          toast('已删除');
          refreshQn();
        });
      });
    }

    kbForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const file = document.getElementById('kb-file').files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      fd.append('title', document.getElementById('kb-title').value);
      fd.append('source_type', document.getElementById('kb-type').value);
      try {
        kbForm.querySelector('button').disabled = true;
        const r = await api('/api/knowledge', { method: 'POST', body: fd });
        toast(`已入库：${r.title}（${r.chunk_count} chunks）`);
        kbForm.reset();
        await refreshKb();
      } catch (err) {
        toast(err.message);
      } finally {
        kbForm.querySelector('button').disabled = false;
      }
    });

    qnForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const file = document.getElementById('qn-file').files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      fd.append('name', document.getElementById('qn-name').value);
      try {
        qnForm.querySelector('button').disabled = true;
        const r = await api('/api/questionnaires', { method: 'POST', body: fd });
        toast(`问卷已上传：${r.question_count} 题`);
        window.location.href = `/q/${r.id}`;
      } catch (err) {
        toast(err.message);
        qnForm.querySelector('button').disabled = false;
      }
    });

    await Promise.all([refreshKb(), refreshQn()]);
  }

  let reviewState = { qnId: null, filter: 'all', data: null };

  async function loadReview(qnId) {
    reviewState.qnId = qnId;
    document.getElementById('btn-export-xlsx').href = `/api/questionnaires/${qnId}/export?format=xlsx`;
    document.getElementById('btn-export-csv').href = `/api/questionnaires/${qnId}/export?format=csv`;

    document.getElementById('btn-generate').addEventListener('click', async () => {
      const btn = document.getElementById('btn-generate');
      btn.disabled = true;
      btn.textContent = '生成中…';
      try {
        await api(`/api/questionnaires/${qnId}/generate`, { method: 'POST' });
        toast('答案草稿已生成');
        await refreshReview();
      } catch (err) {
        toast(err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = '一键生成全部答案';
      }
    });

    document.querySelectorAll('.filters [data-filter]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.filters [data-filter]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        reviewState.filter = btn.dataset.filter;
        renderQuestions();
      });
    });

    await refreshReview();
  }

  async function refreshReview() {
    const data = await api(`/api/questionnaires/${reviewState.qnId}`);
    reviewState.data = data;
    document.getElementById('qn-title').textContent = data.name;
    document.getElementById('qn-sub').textContent = `状态：${data.status} · ${data.question_count} 题`;
    const low = data.questions.filter(q => (q.confidence || 0) < 0.4).length;
    const reviewed = data.questions.filter(q => q.status === 'reviewed').length;
    const fromLib = data.questions.filter(q => q.from_library).length;
    document.getElementById('stats').innerHTML = `
      <div class="stat">已答 <b>${data.answered_count}</b> / ${data.question_count}</div>
      <div class="stat">低置信度 <b>${low}</b></div>
      <div class="stat">答案库命中 <b>${fromLib}</b></div>
      <div class="stat">已审阅 <b>${reviewed}</b></div>
    `;
    renderQuestions();
  }

  function renderQuestions() {
    const box = document.getElementById('questions');
    let qs = reviewState.data.questions.slice();
    const f = reviewState.filter;
    if (f === 'low') qs = qs.filter(q => (q.confidence || 0) < 0.4);
    if (f === 'library') qs = qs.filter(q => q.from_library);
    if (f === 'pending') qs = qs.filter(q => q.status === 'pending' || q.status === 'drafted');
    if (f === 'reviewed') qs = qs.filter(q => q.status === 'reviewed');

    if (!qs.length) {
      box.innerHTML = '<div class="empty">没有匹配的问题。可先点击「一键生成全部答案」。</div>';
      return;
    }

    box.innerHTML = qs.map(q => {
      const sources = (q.sources || []).slice(0, 3).map(s => `
        <details>
          <summary>${escapeHtml(s.title || 'source')} · score ${s.score ?? '-'}</summary>
          <div style="margin-top:0.35rem;white-space:pre-wrap">${escapeHtml((s.excerpt || '').slice(0, 500))}</div>
        </details>
      `).join('');
      return `
        <article class="q-card" data-qid="${q.id}">
          <div class="q-meta">
            <span class="chip">#${q.row_number}</span>
            ${q.section ? `<span class="chip">${escapeHtml(q.section)}</span>` : ''}
            <span class="chip">${escapeHtml(q.status)}</span>
            ${q.from_library ? '<span class="chip high">答案库</span>' : ''}
            ${confChip(q.confidence || 0)}
          </div>
          <p class="q-text">${escapeHtml(q.question_text)}</p>
          <label>答案草稿</label>
          <textarea data-answer>${escapeHtml(q.answer_text || '')}</textarea>
          <label style="margin-top:0.55rem">备注</label>
          <input type="text" data-notes value="${escapeHtml(q.notes || '')}" placeholder="可选：需法务确认…" />
          <div class="actions">
            <button class="btn btn-secondary btn-sm" data-action="regen">重新生成</button>
            <button class="btn btn-secondary btn-sm" data-action="save">保存</button>
            <button class="btn btn-primary btn-sm" data-action="review">审阅并入库</button>
            <button class="btn btn-secondary btn-sm" data-action="skip">跳过</button>
          </div>
          <div class="sources">${sources || '<em>无引用来源</em>'}</div>
        </article>
      `;
    }).join('');

    box.querySelectorAll('.q-card').forEach(card => {
      const id = card.dataset.qid;
      card.querySelector('[data-action="save"]').addEventListener('click', async () => {
        await api(`/api/questions/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            answer_text: card.querySelector('[data-answer]').value,
            notes: card.querySelector('[data-notes]').value,
          }),
        });
        toast('已保存');
      });
      card.querySelector('[data-action="review"]').addEventListener('click', async () => {
        await api(`/api/questions/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            answer_text: card.querySelector('[data-answer]').value,
            notes: card.querySelector('[data-notes]').value,
            status: 'reviewed',
            save_to_library: true,
          }),
        });
        toast('已审阅并写入答案库');
        await refreshReview();
      });
      card.querySelector('[data-action="skip"]').addEventListener('click', async () => {
        await api(`/api/questions/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'skipped' }),
        });
        toast('已跳过');
        await refreshReview();
      });
      card.querySelector('[data-action="regen"]').addEventListener('click', async () => {
        toast('重新生成中…');
        await api(`/api/questions/${id}/generate`, { method: 'POST' });
        await refreshReview();
        toast('已更新该题答案');
      });
    });
  }

  async function loadLibrary() {
    const form = document.getElementById('lib-form');
    if (!form) return;

    async function refresh() {
      const items = await api('/api/library');
      const box = document.getElementById('lib-list');
      if (!items.length) {
        box.innerHTML = '<div class="card empty">答案库为空。在审阅页点击「审阅并入库」即可积累。</div>';
        return;
      }
      box.innerHTML = items.map(it => `
        <div class="card" style="margin-bottom:0.75rem">
          <div class="q-meta">
            <span class="chip">使用 ${it.times_used} 次</span>
            ${it.section ? `<span class="chip">${escapeHtml(it.section)}</span>` : ''}
          </div>
          <p class="q-text"><strong>Q:</strong> ${escapeHtml(it.question_text)}</p>
          <p class="sub" style="white-space:pre-wrap"><strong>A:</strong> ${escapeHtml(it.answer_text)}</p>
          <button class="btn btn-danger btn-sm" data-del="${it.id}">删除</button>
        </div>
      `).join('');
      box.querySelectorAll('[data-del]').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm('删除该答案？')) return;
          await api(`/api/library/${btn.dataset.del}`, { method: 'DELETE' });
          toast('已删除');
          refresh();
        });
      });
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await api('/api/library', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question_text: document.getElementById('lib-q').value,
            answer_text: document.getElementById('lib-a').value,
            section: document.getElementById('lib-s').value,
          }),
        });
        toast('已保存');
        form.reset();
        await refresh();
      } catch (err) {
        toast(err.message);
      }
    });

    await refresh();
  }

  return {
    api, toast, login, register, logout,
    loadHome, loadReview, loadLibrary,
  };
})();
