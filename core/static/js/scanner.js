// Basic Barcode Scanner using html5-qrcode library
// In production, you would fetch this from a CDN or bundle it.
// Here we assume the library is loaded in the template.

class StockScanner {
    constructor(inputId, startButtonId, resultContainerId) {
        this.inputId = inputId;
        this.html5QrcodeScanner = null;
        this.startButton = document.getElementById(startButtonId);
        this.resultContainer = document.getElementById(resultContainerId);

        if(this.startButton) {
            this.startButton.addEventListener('click', () => this.startScanning());
        }
    }

    startScanning() {
        // Show modal or container
        this.resultContainer.classList.remove('hidden');

        this.html5QrcodeScanner = new Html5QrcodeScanner(
            "reader", { fps: 10, qrbox: 250 }
        );

        this.html5QrcodeScanner.render(
            (decodedText, decodedResult) => this.onScanSuccess(decodedText, decodedResult),
            (errorMessage) => this.onScanFailure(errorMessage)
        );
    }

    onScanSuccess(decodedText, decodedResult) {
        // Handle on success condition with the decoded message.
        console.log(`Scan result ${decodedText}`, decodedResult);

        // Fill the input
        const input = document.getElementById(this.inputId);
        if(input) {
            // Check if input is a select (Select2 or native)
            // Ideally we search for the SKU in the select options
            input.value = decodedText; // Simple set for now

            // Trigger change event for HTMX or other listeners
            input.dispatchEvent(new Event('change'));
        }

        // Close scanner
        this.stopScanning();
    }

    onScanFailure(error) {
        // handle scan failure, usually better to ignore and keep scanning.
        // console.warn(`Code scan error = ${error}`);
    }

    stopScanning() {
        if(this.html5QrcodeScanner) {
            this.html5QrcodeScanner.clear().then(() => {
                this.resultContainer.classList.add('hidden');
            }).catch(error => {
                console.error("Failed to clear html5QrcodeScanner. ", error);
            });
        }
    }
}
