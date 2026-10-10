/*
 * Etiquetas Zebra (patch 9).
 *
 * Impressão direta usa o Zebra Browser Print, o programa gratuito da Zebra que
 * fica rodando no computador da loja e recebe ZPL do navegador:
 *   GET  http://127.0.0.1:9100/default?type=printer   -> impressora padrão
 *   GET  http://127.0.0.1:9100/available              -> impressoras encontradas
 *   POST http://127.0.0.1:9100/write  {device, data}  -> envia o ZPL
 * A porta https://127.0.0.1:9101 é a alternativa com HTTPS.
 */
(function () {
  'use strict';

  var BASES = ['http://127.0.0.1:9100/', 'https://127.0.0.1:9101/'];
  var cached = null;

  function timeout(ms) {
    if (window.AbortSignal && AbortSignal.timeout) return AbortSignal.timeout(ms);
    return undefined;
  }

  function findPrinter() {
    if (cached) return Promise.resolve(cached);
    var i = 0;
    function next() {
      if (i >= BASES.length) return Promise.resolve(null);
      var base = BASES[i++];
      return fetch(base + 'default?type=printer', { signal: timeout(2500) })
        .then(function (r) { return r.ok ? r.text() : ''; })
        .then(function (txt) {
          var dev = null;
          try { dev = txt ? JSON.parse(txt) : null; } catch (e) { dev = null; }
          if (dev && dev.name) { cached = { base: base, device: dev }; return cached; }
          // Agente encontrado mas sem impressora padrão: tenta a lista.
          return fetch(base + 'available', { signal: timeout(2500) })
            .then(function (r) { return r.ok ? r.json() : {}; })
            .then(function (all) {
              var list = (all && all.printer) || [];
              if (list.length) { cached = { base: base, device: list[0] }; return cached; }
              return { base: base, device: null };
            });
        })
        .catch(function () { return next(); });
    }
    return next();
  }

  function sendZpl(zpl) {
    return findPrinter().then(function (p) {
      if (!p) throw new Error('agent');
      if (!p.device) throw new Error('noprinter');
      return fetch(p.base + 'write', {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
        body: JSON.stringify({ device: p.device, data: zpl })
      }).then(function (r) {
        if (!r.ok) throw new Error('write');
        return p.device;
      });
    });
  }

  function errorText(err) {
    var code = err && err.message;
    if (code === 'agent') return 'Não encontrei o Zebra Browser Print neste computador. Use "Imprimir pelo navegador" ou veja "Como ligar a Zebra".';
    if (code === 'noprinter') return 'O Zebra Browser Print está aberto, mas sem impressora padrão. Abra o programa e escolha a Zebra.';
    return 'A Zebra não aceitou a impressão. Confira se ela está ligada e com etiqueta.';
  }

  function csrf() {
    var el = document.querySelector('input[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  function warningsFrom(resp) {
    try { return JSON.parse(resp.headers.get('X-Label-Warnings') || '[]'); } catch (e) { return []; }
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function icons() { if (window.lucide) window.lucide.createIcons(); }

  function toast(box, kind, text) {
    if (!box) return;
    var cls = {
      ok: 'border-emerald-200 bg-emerald-50 text-emerald-800',
      warn: 'border-amber-200 bg-amber-50 text-amber-900',
      err: 'border-rose-200 bg-rose-50 text-rose-800',
      info: 'border-slate-200 bg-slate-50 text-slate-700'
    }[kind];
    box.className = 'rounded-md border px-3 py-2 text-sm ' + cls;
    box.textContent = text;
    box.hidden = false;
  }

  function printerChip(chip) {
    if (!chip) return;
    chip.className = 'pf-badge-gray';
    chip.textContent = 'Procurando a Zebra…';
    findPrinter().then(function (p) {
      chip.textContent = '';
      chip.appendChild(el('span', 'pf-dot'));
      if (p && p.device) {
        chip.className = 'pf-badge-green';
        chip.appendChild(document.createTextNode('Zebra pronta: ' + p.device.name));
      } else if (p) {
        chip.className = 'pf-badge-amber';
        chip.appendChild(document.createTextNode('Browser Print sem impressora'));
      } else {
        chip.className = 'pf-badge-gray';
        chip.appendChild(document.createTextNode('Zebra não conectada'));
      }
    });
  }

  function postForm(action, fields, target) {
    var f = document.createElement('form');
    f.method = 'post';
    f.action = action;
    if (target) f.target = target;
    fields.push(['csrfmiddlewaretoken', csrf()]);
    fields.forEach(function (kv) {
      var i = document.createElement('input');
      i.type = 'hidden'; i.name = kv[0]; i.value = kv[1];
      f.appendChild(i);
    });
    document.body.appendChild(f);
    f.submit();
    f.remove();
  }

  function fetchZpl(action, fields) {
    var body = new URLSearchParams();
    fields.forEach(function (kv) { body.append(kv[0], kv[1]); });
    return fetch(action, {
      method: 'POST', body: body, credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) {
      return r.text().then(function (t) {
        if (!r.ok) throw new Error('server:' + t);
        return { zpl: t, warnings: warningsFrom(r), count: r.headers.get('X-Label-Count') };
      });
    });
  }

  function serverError(err) {
    var m = (err && err.message) || '';
    return m.indexOf('server:') === 0 ? m.slice(7) : null;
  }

  // ---------------------------------------------------------------- fila
  function initQueue(root) {
    var urls = {
      search: root.dataset.searchUrl, nfe: root.dataset.nfeUrl,
      preview: root.dataset.previewUrl, generate: root.dataset.generateUrl
    };
    var columns = parseInt(root.dataset.columns, 10) || 1;
    var max = parseInt(root.dataset.max, 10) || 2000;
    var STORE = 'stockpro.labels.queue.' + String(root.dataset.tenantId || 'unknown') + '.' + String(root.dataset.userId || 'unknown');
    var items = [];
    var selected = null;

    var initial = [];
    try { initial = JSON.parse(document.getElementById('labels-initial').textContent) || []; } catch (e) { initial = []; }
    if (initial.length) {
      items = initial;
    } else {
      try { items = JSON.parse(localStorage.getItem(STORE) || '[]') || []; } catch (e) { items = []; }
    }

    var tbody = root.querySelector('[data-queue-body]');
    var empty = root.querySelector('[data-queue-empty]');
    var total = root.querySelector('[data-total]');
    var rowsInfo = root.querySelector('[data-rows]');
    var previewBox = root.querySelector('[data-preview]');
    var previewCaption = root.querySelector('[data-preview-caption]');
    var warnBox = root.querySelector('[data-warnings]');
    var msg = root.querySelector('[data-message]');
    var buttons = root.querySelectorAll('[data-needs-items]');

    function save() { try { localStorage.setItem(STORE, JSON.stringify(items)); } catch (e) { /* sem storage */ } }

    function totalCount() { return items.reduce(function (s, it) { return s + (parseInt(it.qty, 10) || 0); }, 0); }

    function codeBadge(it) {
      if (it.code === 'EAN13') return el('span', 'pf-badge-green', 'EAN-13');
      if (it.code === 'EAN8') return el('span', 'pf-badge-green', 'EAN-8');
      if (it.code === 'CODE128') return el('span', 'pf-badge-indigo', it.code_value === it.sku ? 'Code 128 · SKU' : 'Code 128');
      return el('span', 'pf-badge-amber', 'Sem código');
    }

    function money(v) {
      if (!v) return '—';
      var n = Number(v);
      return 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function render() {
      tbody.textContent = '';
      empty.hidden = items.length > 0;
      items.forEach(function (it, idx) {
        var tr = el('tr', 'cursor-pointer hover:bg-slate-50' + (selected === it.id ? ' bg-indigo-50/60' : ''));
        tr.addEventListener('click', function (ev) {
          if (ev.target.closest('input,button')) return;
          selected = it.id; render(); refreshPreview();
        });
        var td1 = el('td');
        var name = el('div', 'font-medium text-slate-900', it.name);
        td1.appendChild(name);
        var sub = el('div', 'text-xs text-slate-500');
        sub.textContent = [it.variant, it.sku].filter(Boolean).join(' · ');
        td1.appendChild(sub);
        var td2 = el('td', 'hidden sm:table-cell'); td2.appendChild(codeBadge(it));
        var td3 = el('td', 'hidden md:table-cell whitespace-nowrap text-right tabular-nums text-slate-700', money(it.price));
        var td4 = el('td', 'text-right');
        var wrap = el('div', 'inline-flex items-center rounded-md border border-slate-300 bg-white');
        var minus = el('button', 'px-2 py-1.5 text-slate-500 hover:text-slate-900', '−');
        minus.type = 'button'; minus.setAttribute('aria-label', 'Diminuir');
        var input = el('input', 'w-14 border-0 bg-transparent p-1 text-center text-sm tabular-nums focus:ring-0');
        input.type = 'number'; input.min = '1'; input.max = String(max); input.value = it.qty;
        input.setAttribute('aria-label', 'Quantidade de etiquetas de ' + it.name);
        var plus = el('button', 'px-2 py-1.5 text-slate-500 hover:text-slate-900', '+');
        plus.type = 'button'; plus.setAttribute('aria-label', 'Aumentar');
        minus.addEventListener('click', function () { it.qty = Math.max(1, (parseInt(it.qty, 10) || 1) - 1); changed(); });
        plus.addEventListener('click', function () { it.qty = (parseInt(it.qty, 10) || 0) + 1; changed(); });
        input.addEventListener('change', function () { it.qty = Math.max(1, parseInt(input.value, 10) || 1); changed(); });
        wrap.appendChild(minus); wrap.appendChild(input); wrap.appendChild(plus);
        td4.appendChild(wrap);
        var td5 = el('td', 'text-right');
        var rm = el('button', 'rounded p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600');
        rm.type = 'button'; rm.setAttribute('aria-label', 'Tirar da lista');
        rm.appendChild(el('i')).setAttribute('data-lucide', 'x');
        rm.querySelector('i').className = 'h-4 w-4';
        rm.addEventListener('click', function () {
          items.splice(idx, 1);
          if (selected === it.id) selected = null;
          changed(true);
        });
        td5.appendChild(rm);
        [td1, td2, td3, td4, td5].forEach(function (td) { tr.appendChild(td); });
        tbody.appendChild(tr);
      });
      var n = totalCount();
      total.textContent = n.toLocaleString('pt-BR');
      var rows = Math.ceil(n / columns);
      rowsInfo.textContent = columns > 1 ? rows.toLocaleString('pt-BR') + ' linha' + (rows === 1 ? '' : 's') + ' do rolo' : '';
      buttons.forEach(function (b) { b.disabled = n === 0 || n > max; });
      if (n > max) toast(msg, 'warn', 'Máximo de ' + max + ' etiquetas por impressão. Divida em partes.');
      icons();
    }

    var pvTimer = null;
    function refreshPreview() {
      clearTimeout(pvTimer);
      pvTimer = setTimeout(function () {
        var ids = [];
        if (selected) ids.push(selected);
        items.forEach(function (it) { if (ids.length < columns && ids.indexOf(it.id) === -1) ids.push(it.id); });
        var url = urls.preview + (ids.length ? '?v=' + ids.join(',') : '');
        fetch(url, { credentials: 'same-origin' }).then(function (r) {
          var w = warningsFrom(r);
          return r.text().then(function (svg) {
            previewBox.innerHTML = svg;
            previewCaption.textContent = ids.length ? 'Prévia com os produtos da lista' : 'Exemplo: adicione produtos para ver a etiqueta deles';
            warnBox.textContent = '';
            w.forEach(function (t) { warnBox.appendChild(el('li', '', t)); });
            warnBox.hidden = !w.length;
          });
        }).catch(function () { /* mantém a prévia anterior */ });
      }, 150);
    }

    function changed(structure) { save(); render(); if (structure !== false) refreshPreview(); }

    function add(it, qty) {
      var found = items.find(function (x) { return x.id === it.id; });
      if (found) { found.qty = (parseInt(found.qty, 10) || 0) + (qty || 1); }
      else { it.qty = qty || it.qty || 1; items.push(it); }
      selected = it.id;
      changed(true);
    }

    // Busca
    var search = root.querySelector('[data-search]');
    var results = root.querySelector('[data-results]');
    var sTimer = null;
    function closeResults() { results.hidden = true; results.textContent = ''; }
    search.addEventListener('input', function () {
      clearTimeout(sTimer);
      var q = search.value.trim();
      if (q.length < 2) { closeResults(); return; }
      sTimer = setTimeout(function () {
        fetch(urls.search + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            results.textContent = '';
            var list = data.results || [];
            if (!list.length) {
              results.appendChild(el('li', 'px-3 py-3 text-sm text-slate-500', 'Nada encontrado para "' + q + '".'));
            }
            list.forEach(function (it) {
              var li = el('li');
              var b = el('button', 'flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-slate-50 focus:bg-slate-50 focus:outline-none');
              b.type = 'button';
              var left = el('span', 'min-w-0');
              left.appendChild(el('span', 'block truncate text-sm font-medium text-slate-900', it.name + (it.variant ? ' · ' + it.variant : '')));
              left.appendChild(el('span', 'block truncate text-xs text-slate-500', (it.sku || '') + (it.barcode ? ' · ' + it.barcode : '') + ' · estoque ' + it.stock.toLocaleString('pt-BR')));
              b.appendChild(left);
              b.appendChild(el('span', 'shrink-0 text-xs font-medium text-indigo-600', 'Adicionar'));
              b.addEventListener('click', function () { add(it, 1); search.value = ''; closeResults(); search.focus(); });
              li.appendChild(b);
              results.appendChild(li);
            });
            results.hidden = false;
          });
      }, 200);
    });
    search.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') closeResults();
      if (ev.key === 'Enter') {
        ev.preventDefault();
        // Leitor de código de barras: digita o código e dá Enter.
        var first = results.querySelector('button');
        if (first && !results.hidden) { first.click(); return; }
        var q = search.value.trim();
        if (q.length >= 2) {
          fetch(urls.search + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              var list = data.results || [];
              if (list.length === 1) { add(list[0], 1); search.value = ''; closeResults(); }
            });
        }
      }
    });
    document.addEventListener('click', function (ev) { if (!ev.target.closest('[data-search-wrap]')) closeResults(); });

    // NF-e
    var nfeSel = root.querySelector('[data-nfe]');
    var nfeBtn = root.querySelector('[data-nfe-load]');
    if (nfeSel && nfeBtn) {
      nfeBtn.addEventListener('click', function () {
        if (!nfeSel.value) return;
        fetch(urls.nfe.replace('00000000-0000-0000-0000-000000000000', nfeSel.value), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            (data.results || []).forEach(function (it) { add(it, it.qty); });
            toast(msg, 'ok', (data.results || []).length + ' produto(s) da ' + data.source + ' na lista, com a quantidade que entrou.');
          });
      });
    }

    root.querySelector('[data-clear]').addEventListener('click', function () {
      items = []; selected = null; changed(true); msg.hidden = true;
    });

    function fields() {
      return items.map(function (it) { return ['q_' + it.id, String(parseInt(it.qty, 10) || 0)]; });
    }

    root.querySelector('[data-print-zebra]').addEventListener('click', function () {
      var btn = this;
      btn.disabled = true;
      toast(msg, 'info', 'Gerando ' + totalCount() + ' etiqueta(s)…');
      fetchZpl(urls.generate, fields().concat([['formato', 'zpl']]))
        .then(function (res) {
          return sendZpl(res.zpl).then(function (dev) {
            toast(msg, 'ok', res.count + ' etiqueta(s) enviada(s) para ' + dev.name + '.');
          });
        })
        .catch(function (err) { toast(msg, 'err', serverError(err) || errorText(err)); printerChip(root.querySelector('[data-printer]')); })
        .finally(function () { btn.disabled = false; });
    });
    root.querySelector('[data-print-browser]').addEventListener('click', function () {
      postForm(urls.generate, fields().concat([['formato', 'html']]), '_blank');
    });
    root.querySelector('[data-download]').addEventListener('click', function () {
      postForm(urls.generate, fields().concat([['formato', 'zpl'], ['download', '1']]));
    });

    printerChip(root.querySelector('[data-printer]'));
    render();
    refreshPreview();
  }

  // ---------------------------------------------------------- modelo
  function initSettings(root) {
    var form = root.querySelector('form[data-label-form]');
    var box = root.querySelector('[data-preview]');
    var warnBox = root.querySelector('[data-warnings]');
    var msg = root.querySelector('[data-message]');
    var url = root.dataset.previewUrl;
    var generate = root.dataset.generateUrl;
    var timer = null;

    function params() {
      var p = new URLSearchParams(new FormData(form));
      p.delete('csrfmiddlewaretoken');
      p.set('live', '1');
      return p;
    }
    function refresh() {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var test = root.querySelector('[data-show-test]');
        var p = params();
        if (test && test.checked) p.set('test', '1');
        fetch(url + '?' + p.toString(), { credentials: 'same-origin' }).then(function (r) {
          var w = warningsFrom(r);
          return r.text().then(function (svg) {
            box.innerHTML = svg;
            warnBox.textContent = '';
            w.forEach(function (t) { warnBox.appendChild(el('li', '', t)); });
            warnBox.hidden = !w.length;
          });
        });
      }, 200);
    }
    form.addEventListener('input', refresh);
    form.addEventListener('change', refresh);
    var t = root.querySelector('[data-show-test]');
    if (t) t.addEventListener('change', refresh);

    root.querySelectorAll('[data-preset]').forEach(function (b) {
      b.addEventListener('click', function () {
        form.querySelector('[name=width_mm]').value = b.dataset.w;
        form.querySelector('[name=height_mm]').value = b.dataset.h;
        form.querySelector('[name=columns]').value = b.dataset.cols;
        form.querySelector('[name=column_gap_mm]').value = b.dataset.gap;
        refresh();
      });
    });

    var dirty = false;
    form.addEventListener('input', function () { dirty = true; });
    function needSaved() {
      if (dirty) { toast(msg, 'warn', 'Salve o modelo antes de imprimir o teste.'); return true; }
      return false;
    }
    var zt = root.querySelector('[data-test-zebra]');
    if (zt) zt.addEventListener('click', function () {
      if (needSaved()) return;
      fetchZpl(generate, [['teste', '1'], ['formato', 'zpl']])
        .then(function (res) { return sendZpl(res.zpl); })
        .then(function (dev) { toast(msg, 'ok', 'Etiqueta de teste enviada para ' + dev.name + '. A moldura deve ficar 1 mm para dentro em todos os lados.'); })
        .catch(function (err) { toast(msg, 'err', serverError(err) || errorText(err)); });
    });
    var bt = root.querySelector('[data-test-browser]');
    if (bt) bt.addEventListener('click', function () {
      if (needSaved()) return;
      postForm(generate, [['teste', '1'], ['formato', 'html']], '_blank');
    });
    var cal = root.querySelector('[data-calibrate]');
    if (cal) cal.addEventListener('click', function () {
      sendZpl('~JC')
        .then(function (dev) { toast(msg, 'ok', dev.name + ' vai puxar algumas etiquetas para medir o tamanho. Isso é normal.'); })
        .catch(function (err) { toast(msg, 'err', errorText(err)); });
    });
    printerChip(root.querySelector('[data-printer]'));
    refresh();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var q = document.querySelector('[data-labels-queue]');
    if (q) initQueue(q);
    var s = document.querySelector('[data-labels-settings]');
    if (s) initSettings(s);
  });
})();
