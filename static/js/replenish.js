/* Tela Repor e pedido ao fornecedor (patch 9). */
(function () {
  'use strict';
  function brl(n) { return 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-autosubmit]').forEach(function (s) {
      s.addEventListener('change', function () { s.form.submit(); });
    });

    document.querySelectorAll('[data-order-form]').forEach(function (form) {
      function recalc() {
        var total = 0;
        form.querySelectorAll('input[data-cost]').forEach(function (inp) {
          var line = (parseFloat(inp.value) || 0) * (parseFloat(inp.dataset.cost) || 0);
          total += line;
          var cell = inp.closest('tr').querySelector('[data-line-total]');
          if (cell) cell.textContent = brl(line);
        });
        var t = form.querySelector('[data-group-total]');
        if (t) t.textContent = brl(total);
      }
      form.addEventListener('input', recalc);
    });

    var copy = document.querySelector('[data-copy]');
    if (copy) {
      copy.addEventListener('click', function () {
        var src = document.getElementById(copy.dataset.copy);
        var done = function () { copy.textContent = 'Copiado'; setTimeout(function () { copy.textContent = 'Copiar texto'; }, 1800); };
        if (navigator.clipboard) navigator.clipboard.writeText(src.value).then(done);
        else { src.select(); document.execCommand('copy'); done(); }
      });
    }
    var pr = document.querySelector('[data-print]');
    if (pr) pr.addEventListener('click', function () { window.print(); });
  });
})();
