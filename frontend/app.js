'use strict';

// ---------------------------------------------------------------------------
// タブ切り替え
// ---------------------------------------------------------------------------
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.tab;
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${target}`).classList.add('active');
    if (target === 'context') loadContext();
  });
});

// ---------------------------------------------------------------------------
// レビュー実行
// ---------------------------------------------------------------------------
let reviewAbortController = null;
let reviewResultText = '';

async function startReview() {
  const docType = document.getElementById('doc-type').value;
  const docContent = document.getElementById('doc-content').value.trim();

  if (!docContent) {
    alert('ドキュメント本文を入力してください。');
    return;
  }

  // UI: ローディング状態へ
  const btn = document.getElementById('btn-review');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-color:#fff4;border-top-color:#fff"></div> レビュー中...';

  document.getElementById('result-status').classList.remove('hidden');
  document.getElementById('status-text').textContent = 'Claude が分析中です...';

  const resultEl = document.getElementById('result-content');
  resultEl.innerHTML = '';
  reviewResultText = '';

  document.getElementById('btn-copy').disabled = true;
  document.getElementById('btn-clear').disabled = true;

  reviewAbortController = new AbortController();

  try {
    const resp = await fetch('/api/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: reviewAbortController.signal,
      body: JSON.stringify({ doc_type: docType, doc_content: docContent }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: 'サーバーエラー' }));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }

    // ストリーミング読み取り
    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let rawText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      rawText += chunk;
      reviewResultText = rawText;
      resultEl.innerHTML = renderMarkdown(rawText);
      resultEl.scrollTop = resultEl.scrollHeight;
    }

  } catch (err) {
    if (err.name === 'AbortError') {
      reviewResultText += '\n\n*(レビューを中断しました)*';
    } else {
      reviewResultText += `\n\n**エラー**: ${err.message}`;
    }
    resultEl.innerHTML = renderMarkdown(reviewResultText);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">▶</span> レビュー開始';
    document.getElementById('result-status').classList.add('hidden');
    document.getElementById('btn-copy').disabled = false;
    document.getElementById('btn-clear').disabled = false;
    reviewAbortController = null;
  }
}

// ---------------------------------------------------------------------------
// 結果操作
// ---------------------------------------------------------------------------
function copyResult() {
  if (!reviewResultText) return;
  navigator.clipboard.writeText(reviewResultText)
    .then(() => { showTemporaryMessage('btn-copy', '✅ コピー完了', 2000); })
    .catch(() => { showTemporaryMessage('btn-copy', '❌ 失敗', 2000); });
}

function clearResult() {
  reviewResultText = '';
  document.getElementById('result-content').innerHTML = `
    <div class="result-placeholder">
      <div class="placeholder-icon">📄</div>
      <p>ドキュメントを入力して「レビュー開始」を押すと、</p>
      <p>AI による自動レビューが表示されます。</p>
    </div>`;
  document.getElementById('btn-copy').disabled = true;
  document.getElementById('btn-clear').disabled = true;
}

function showTemporaryMessage(btnId, msg, ms) {
  const btn = document.getElementById(btnId);
  const original = btn.textContent;
  btn.textContent = msg;
  setTimeout(() => { btn.textContent = original; }, ms);
}

// ---------------------------------------------------------------------------
// プロジェクトコンテキスト
// ---------------------------------------------------------------------------
async function loadContext() {
  try {
    const resp = await fetch('/api/context');
    if (!resp.ok) return;
    const data = await resp.json();
    document.getElementById('ctx-overview').value  = data.project_overview  || '';
    document.getElementById('ctx-rules').value     = data.project_rules     || '';
    document.getElementById('ctx-issues').value    = data.recent_issues     || '';
    document.getElementById('ctx-checklist').value = data.custom_checklist  || '';
  } catch (_) { /* フォールバック: 何もしない */ }
}

async function saveContext() {
  const payload = {
    project_overview:  document.getElementById('ctx-overview').value,
    project_rules:     document.getElementById('ctx-rules').value,
    recent_issues:     document.getElementById('ctx-issues').value,
    custom_checklist:  document.getElementById('ctx-checklist').value,
  };

  const statusEl = document.getElementById('save-status');
  statusEl.className = 'save-status';

  try {
    const resp = await fetch('/api/context', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error('保存失敗');
    statusEl.textContent = '✅ 保存しました';
    statusEl.className = 'save-status ok visible';
  } catch (err) {
    statusEl.textContent = '❌ 保存に失敗しました';
    statusEl.className = 'save-status err visible';
  }
  setTimeout(() => statusEl.classList.remove('visible'), 3000);
}

// ---------------------------------------------------------------------------
// 簡易 Markdown レンダラー
// ---------------------------------------------------------------------------
function renderMarkdown(text) {
  // XSS対策: HTMLエスケープ後に変換
  const esc = s => s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  let html = esc(text);

  // コードブロック（```）
  html = html.replace(/```[\s\S]*?```/g, m => {
    const code = m.slice(3, -3).replace(/^[a-z]+\n/, '');
    return `<pre><code>${code}</code></pre>`;
  });

  // インラインコード
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // 見出し
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // 水平線
  html = html.replace(/^---$/gm, '<hr>');

  // 太字・斜体
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // 評価グレードに色付け
  html = html.replace(/\bA:問題なし\b/g, '<span class="grade-A">A:問題なし</span>');
  html = html.replace(/\bB:軽微な指摘\b/g, '<span class="grade-B">B:軽微な指摘</span>');
  html = html.replace(/\bC:要修正\b/g, '<span class="grade-C">C:要修正</span>');
  html = html.replace(/\bD:重大な問題\b/g, '<span class="grade-D">D:重大な問題</span>');

  // 引用ブロック
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

  // リスト（-・*で始まる行）
  html = html.replace(/^(\s*)[-*] (.+)$/gm, (_, indent, item) => {
    const depth = Math.floor(indent.length / 2);
    return `<li style="margin-left:${depth * 16}px">• ${item}</li>`;
  });

  // 番号付きリスト
  html = html.replace(/^(\d+)\. (.+)$/gm, (_, num, item) => {
    return `<li style="list-style:decimal;margin-left:20px">${item}</li>`;
  });

  // 段落（空行区切り）
  html = html
    .split(/\n{2,}/)
    .map(block => {
      if (/^<(h[1-6]|li|ul|ol|blockquote|pre|hr)/.test(block.trim())) return block;
      return `<p>${block.replace(/\n/g, '<br>')}</p>`;
    })
    .join('\n');

  return html;
}

// ---------------------------------------------------------------------------
// 初期化
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  // コンテキストタブが開かれたとき自動ロード（既に設定している場合）
  document.querySelector('[data-tab="context"]').addEventListener('click', loadContext);
});
