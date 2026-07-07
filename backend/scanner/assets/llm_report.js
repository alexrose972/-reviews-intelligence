function initScoreBars(scope) {
  const root = scope || document;
  root.querySelectorAll('.score-bar-fill[data-bar-width]').forEach((el) => {
    const w = el.getAttribute('data-bar-width');
    if (w != null && w !== '') el.style.width = w + '%';
  });
}

function setActiveModelForCompany(companyIdx, modelName) {
  const panel = document.getElementById('panel-co-' + companyIdx);
  if (!panel) return;
  panel.querySelectorAll('[data-model-tab]').forEach((btn) => {
    const m = btn.getAttribute('data-model-tab');
    btn.setAttribute('aria-selected', m === modelName ? 'true' : 'false');
  });
  panel.querySelectorAll('[data-model-panel]').forEach((mp) => {
    const m = mp.getAttribute('data-model-panel');
    mp.classList.toggle('is-active', m === modelName);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initScoreBars(document);

  document.querySelectorAll('[data-main-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const name = btn.getAttribute('data-main-tab');
      document.querySelectorAll('[data-main-tab]').forEach((b) => {
        const sel = b.getAttribute('data-main-tab') === name;
        b.setAttribute('aria-selected', sel ? 'true' : 'false');
      });
      const reportPanel = document.getElementById('panel-main-report');
      const metricsPanel = document.getElementById('panel-main-metrics');
      if (name === 'report') {
        reportPanel.classList.add('is-active');
        reportPanel.removeAttribute('hidden');
        metricsPanel.classList.remove('is-active');
        metricsPanel.setAttribute('hidden', '');
      } else {
        metricsPanel.classList.add('is-active');
        metricsPanel.removeAttribute('hidden');
        reportPanel.classList.remove('is-active');
        reportPanel.setAttribute('hidden', '');
      }
    });
  });

  document.querySelectorAll('[data-company-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = btn.getAttribute('data-company-tab');
      document.querySelectorAll('[data-company-tab]').forEach((b) => {
        b.setAttribute('aria-selected', b.getAttribute('data-company-tab') === idx ? 'true' : 'false');
      });
      document.querySelectorAll('.company-panel').forEach((panel) => {
        const match = panel.id === 'panel-co-' + idx;
        panel.classList.toggle('is-active', match);
        if (match) panel.removeAttribute('hidden');
        else panel.setAttribute('hidden', '');
      });
      const activePanel = document.getElementById('panel-co-' + idx);
      if (activePanel) {
        initScoreBars(activePanel);
        const def = activePanel.getAttribute('data-default-model') || 'chatgpt';
        const firstBtn = activePanel.querySelector('[data-model-tab="' + def + '"]')
          || activePanel.querySelector('[data-model-tab]');
        if (firstBtn) {
          const m = firstBtn.getAttribute('data-model-tab');
          if (m) setActiveModelForCompany(idx, m);
        }
      }
    });
  });

  document.querySelectorAll('[data-model-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = btn.getAttribute('data-company-idx');
      const m = btn.getAttribute('data-model-tab');
      if (idx != null && m) setActiveModelForCompany(idx, m);
    });
  });

  document.querySelectorAll('.company-panel.is-active').forEach((panel) => {
    const idx = panel.id.replace('panel-co-', '');
    const def = panel.getAttribute('data-default-model') || 'chatgpt';
    const firstBtn = panel.querySelector('[data-model-tab="' + def + '"]')
      || panel.querySelector('[data-model-tab]');
    if (firstBtn) {
      const m = firstBtn.getAttribute('data-model-tab');
      if (m) setActiveModelForCompany(idx, m);
    }
  });
});