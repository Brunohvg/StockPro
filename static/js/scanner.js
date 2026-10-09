/*
 * Leitor de código de barras da tela "Nova movimentação" (desktop/tablet).
 * Usa html5-qrcode (static/vendor). Ao ler um código, preenche o campo de
 * produto (SKU/EAN) e fecha a câmera. Se não houver câmera ou permissão,
 * avisa e deixa digitar normalmente.
 */
(function () {
    class StockScanner {
        constructor(inputId, buttonId, containerId, readerId) {
            this.input = document.getElementById(inputId);
            this.button = document.getElementById(buttonId);
            this.container = document.getElementById(containerId);
            this.readerId = readerId || 'reader';
            this.scanner = null;
            this.starting = null;
            this.closing = false;
            if (this.button) {
                this.button.addEventListener('click', () => this.startScanning());
            }
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.scanner) this.stopScanning();
            });
        }

        startScanning() {
            if (this.scanner || this.closing) return;
            if (typeof Html5Qrcode === 'undefined') {
                alert('Leitor de código indisponível. Digite o SKU ou EAN.');
                return;
            }
            this.container.classList.remove('hidden');
            this.scanner = new Html5Qrcode(this.readerId);
            this.starting = this.scanner.start(
                { facingMode: 'environment' },
                { fps: 10, qrbox: { width: 250, height: 150 } },
                (code) => this.onCode(code),
                () => {}  // quadro sem código: normal, ignora
            ).catch((err) => {
                alert('Não foi possível abrir a câmera (' + (err && err.message ? err.message : err) + '). Digite o código.');
                this.stopScanning();
            });
        }

        onCode(code) {
            if (this.closing || !this.input) return;
            this.input.value = String(code).trim();
            this.input.dispatchEvent(new Event('input', { bubbles: true }));
            this.input.dispatchEvent(new Event('change', { bubbles: true }));
            this.stopScanning();
            this.input.focus();
        }

        async stopScanning() {
            if (this.closing) return;
            this.closing = true;
            const current = this.scanner;
            this.container.classList.add('hidden');
            try {
                if (current) {
                    if (this.starting) await this.starting.catch(() => {});
                    if (current.isScanning) await current.stop();
                    current.clear();
                }
            } catch (e) {
                /* câmera já fechada */
            } finally {
                this.scanner = null;
                this.starting = null;
                this.closing = false;
            }
        }
    }
    window.StockScanner = StockScanner;
})();
