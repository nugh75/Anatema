// JavaScript principale perAnatema

document.addEventListener('DOMContentLoaded', function() {
    // Inizializzazione tooltips Bootstrap
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    const tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Inizializzazione popovers Bootstrap
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    const popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });

    applyAutoContrast();

    // Auto-hide alerts dopo 5 secondi
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        if (!alert.querySelector('.btn-close')) {
            setTimeout(() => {
                alert.style.opacity = '0';
                setTimeout(() => alert.remove(), 300);
            }, 5000);
        }
    });

    // Conferma eliminazione
    const deleteButtons = document.querySelectorAll('[data-confirm-delete]');
    deleteButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            const message = this.dataset.confirmDelete || 'Sei sicuro di voler eliminare questo elemento?';
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });

    // Auto-resize textarea
    const textareas = document.querySelectorAll('textarea[data-auto-resize]');
    textareas.forEach(textarea => {
        textarea.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = this.scrollHeight + 'px';
        });
        // Trigger iniziale
        textarea.dispatchEvent(new Event('input'));
    });

    // Search functionality
    const searchInputs = document.querySelectorAll('[data-search-target]');
    searchInputs.forEach(input => {
        input.addEventListener('input', function() {
            const searchTerm = this.value.toLowerCase();
            const targetSelector = this.dataset.searchTarget;
            const targets = document.querySelectorAll(targetSelector);
            
            targets.forEach(target => {
                const text = target.textContent.toLowerCase();
                const shouldShow = text.includes(searchTerm);
                target.style.display = shouldShow ? '' : 'none';
            });
        });
    });

    // File upload drag and drop
    const fileUploadAreas = document.querySelectorAll('.file-upload-area');
    fileUploadAreas.forEach(area => {
        const fileInput = area.querySelector('input[type="file"]');
        
        if (fileInput) {
            area.addEventListener('dragover', function(e) {
                e.preventDefault();
                this.classList.add('dragover');
            });

            area.addEventListener('dragleave', function(e) {
                e.preventDefault();
                this.classList.remove('dragover');
            });

            area.addEventListener('drop', function(e) {
                e.preventDefault();
                this.classList.remove('dragover');
                
                const files = e.dataTransfer.files;
                if (files.length > 0) {
                    fileInput.files = files;
                    // Trigger change event
                    fileInput.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });

            area.addEventListener('click', function() {
                fileInput.click();
            });

            fileInput.addEventListener('change', function() {
                if (this.files.length > 0) {
                    const fileName = this.files[0].name;
                    const fileNameDisplay = area.querySelector('.file-name-display');
                    if (fileNameDisplay) {
                        fileNameDisplay.textContent = fileName;
                    }
                }
            });
        }
    });

    // Copy to clipboard functionality
    const copyButtons = document.querySelectorAll('[data-copy-text]');
    copyButtons.forEach(button => {
        button.addEventListener('click', function() {
            const textToCopy = this.dataset.copyText;
            navigator.clipboard.writeText(textToCopy).then(() => {
                showToast('Testo copiato negli appunti!', 'success');
            }).catch(() => {
                showToast('Errore durante la copia', 'error');
            });
        });
    });

    // Toggle visibility
    const toggleButtons = document.querySelectorAll('[data-toggle-target]');
    toggleButtons.forEach(button => {
        button.addEventListener('click', function() {
            const targetSelector = this.dataset.toggleTarget;
            const target = document.querySelector(targetSelector);
            if (target) {
                target.style.display = target.style.display === 'none' ? '' : 'none';
                
                // Update button text/icon if needed
                const showText = this.dataset.showText;
                const hideText = this.dataset.hideText;
                if (showText && hideText) {
                    const isHidden = target.style.display === 'none';
                    this.textContent = isHidden ? showText : hideText;
                }
            }
        });
    });

    // Progress bar animation
    const progressBars = document.querySelectorAll('.progress-bar[data-animate]');
    progressBars.forEach(bar => {
        const targetWidth = bar.style.width || bar.getAttribute('aria-valuenow') + '%';
        bar.style.width = '0%';
        setTimeout(() => {
            bar.style.transition = 'width 1s ease-in-out';
            bar.style.width = targetWidth;
        }, 100);
    });

    // Form validation enhancement
    const forms = document.querySelectorAll('form[data-validate]');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();
                
                // Focus on first invalid field
                const firstInvalid = form.querySelector(':invalid');
                if (firstInvalid) {
                    firstInvalid.focus();
                }
            }
            form.classList.add('was-validated');
        });
    });

    // Real-time character counter
    const textInputsWithCounter = document.querySelectorAll('[data-max-length]');
    textInputsWithCounter.forEach(input => {
        const maxLength = parseInt(input.dataset.maxLength);
        const counter = document.createElement('small');
        counter.className = 'form-text text-muted character-counter';
        input.parentNode.appendChild(counter);
        
        function updateCounter() {
            const remaining = maxLength - input.value.length;
            counter.textContent = `${input.value.length}/${maxLength} caratteri`;
            
            if (remaining < 10) {
                counter.className = 'form-text text-warning character-counter';
            } else if (remaining < 0) {
                counter.className = 'form-text text-danger character-counter';
            } else {
                counter.className = 'form-text text-muted character-counter';
            }
        }
        
        input.addEventListener('input', updateCounter);
        updateCounter(); // Initial call
    });

    // Smooth scroll for anchor links
    const anchorLinks = document.querySelectorAll('a[href^="#"]');
    anchorLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            const targetId = this.getAttribute('href').substring(1);
            const targetElement = document.getElementById(targetId);
            
            if (targetElement) {
                e.preventDefault();
                targetElement.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    // Auto-save functionality (for future implementation)
    const autoSaveForms = document.querySelectorAll('[data-auto-save]');
    autoSaveForms.forEach(form => {
        let saveTimeout;
        const inputs = form.querySelectorAll('input, textarea, select');
        
        inputs.forEach(input => {
            input.addEventListener('input', function() {
                clearTimeout(saveTimeout);
                saveTimeout = setTimeout(() => {
                    // Auto-save logic here
                    console.log('Auto-saving form data...');
                }, 2000);
            });
        });
    });

    // AI labeling assistant initialization
    // Sets up AI status, enables buttons, and binds generate/review actions
    const generateBtn = document.getElementById('generate-ai-labels');
    const reAnnotateBtn = document.getElementById('re-annotate-ai-labels');
    const reviewBtn = document.getElementById('review-ai-labels');
    const statusBadge = document.getElementById('ai-config-status');
    const pendingCountElem = document.getElementById('pending-count');
    const aiCountElem = document.getElementById('ai-annotations-count');
    
    if (generateBtn && generateBtn.dataset.customAiHandler !== 'true') {
        const fileId = generateBtn.dataset.fileId;
        const progressDiv = document.getElementById('ai-progress');
        const progressBar = progressDiv ? progressDiv.querySelector('.progress-bar') : null;
        const progressText = document.getElementById('ai-progress-text');

        // Load current AI configuration
        window.AnalisiMU.apiRequest(`/ai/config/current`).then(data => {
            if (data.success) {
                const cfg = data.config;
                statusBadge.textContent = `${cfg.provider.toUpperCase()} (${cfg.model})`;
                statusBadge.className = 'badge bg-success';
                generateBtn.disabled = false;
                if (reAnnotateBtn) reAnnotateBtn.disabled = false;
            } else {
                statusBadge.textContent = data.message || 'Nessuna configurazione AI attiva';
                statusBadge.className = 'badge bg-danger';
            }
        }).catch(() => {
            statusBadge.textContent = 'Errore caricamento';
            statusBadge.className = 'badge bg-danger';
        });

        // Refresh AI annotations status
        function refreshStatus() {
            window.AnalisiMU.apiRequest(`/ai/status/${fileId}`).then(data => {
                if (data.success && data.ai_stats) {
                    if (pendingCountElem) pendingCountElem.textContent = data.ai_stats.pending;
                    if (aiCountElem) aiCountElem.textContent = data.ai_stats.total;
                    
                    if (reviewBtn) {
                        reviewBtn.disabled = data.ai_stats.pending <= 0;
                        if (data.ai_stats.pending > 0) {
                            reviewBtn.classList.add('btn-warning');
                            reviewBtn.classList.remove('btn-outline-info');
                        } else {
                            reviewBtn.classList.remove('btn-warning');
                            reviewBtn.classList.add('btn-outline-info');
                        }
                    }
                }
            });
        }
        refreshStatus();

        // Auto refresh every 30 seconds
        setInterval(refreshStatus, 30000);

        // Generate AI labels with enhanced UI
        generateBtn.addEventListener('click', function() {
            if (!confirm('Vuoi generare etichette AI per tutte le risposte non ancora annotate?')) {
                return;
            }
            // Raccogli parametri UI
            const templateId = document.getElementById('ai-template-select')?.value || 1;
            const mode = document.getElementById('ai-mode-select')?.value || 'new';
            const categoriesSelect = document.getElementById('ai-categories-select');
            let selectedCategories = [];
            if (categoriesSelect) {
                selectedCategories = Array.from(categoriesSelect.selectedOptions).map(opt => opt.value);
            }
            // Aggiorna UI
            this.disabled = true;
            this.innerHTML = '<i class="bi bi-hourglass-split"></i> Generando...';
            if (progressDiv && progressBar && progressText) {
                progressDiv.style.display = 'block';
                progressBar.style.width = '0%';
                progressText.textContent = 'Inizializzazione...';
                let progressValue = 0;
                const progressInterval = setInterval(() => {
                    progressValue += Math.random() * 10;
                    if (progressValue > 85) progressValue = 85;
                    progressBar.style.width = progressValue + '%';
                    progressText.textContent = `Elaborazione in corso... ${Math.round(progressValue)}%`;
                }, 800);
                window.AnalisiMU.apiRequest(`/ai/generate/${fileId}`, { 
                    method: 'POST',
                    body: JSON.stringify({ 
                        batch_size: 50,
                        template_id: templateId,
                        mode: mode,
                        selected_categories: selectedCategories
                    })
                })
                .then(res => {
                    clearInterval(progressInterval);
                    progressBar.style.width = '100%';
                    progressText.textContent = 'Completato!';
                    setTimeout(() => {
                        progressDiv.style.display = 'none';
                        generateBtn.innerHTML = '<i class="bi bi-magic"></i> Genera Etichette AI';
                        generateBtn.disabled = false;
                        window.AnalisiMU.showToast(`Generazione completata!\n\nProcessate: ${res.total_processed} risposte\nAnnotazioni create: ${res.annotations_count}`, 'success', 5000);
                        refreshStatus();
                    }, 1000);
                })
                .catch(() => {
                    clearInterval(progressInterval);
                    progressDiv.style.display = 'none';
                    generateBtn.innerHTML = '<i class="bi bi-magic"></i> Genera Etichette AI';
                    generateBtn.disabled = false;
                    window.AnalisiMU.showToast('Errore generazione etichette', 'error');
                });
            } else {
                window.AnalisiMU.apiRequest(`/ai/generate/${fileId}`, { 
                    method: 'POST',
                    body: JSON.stringify({ 
                        batch_size: 50,
                        template_id: templateId,
                        mode: mode,
                        selected_categories: selectedCategories
                    })
                })
                .then(res => {
                    window.AnalisiMU.showToast(res.message || 'Generazione completata', 'success');
                    refreshStatus();
                })
                .catch(() => {
                    window.AnalisiMU.showToast('Errore generazione etichette', 'error');
                })
                .finally(() => {
                    this.innerHTML = '<i class="bi bi-magic"></i> Genera Etichette AI';
                    this.disabled = false;
                });
            }
        });

        // Re-annotate AI labels (new functionality)
        if (reAnnotateBtn) {
            reAnnotateBtn.addEventListener('click', function() {
                if (!confirm('⚠️ ATTENZIONE: Questa operazione ri-etichetterà TUTTE le celle del file (anche quelle già annotate).\n\nTutte le annotazioni AI esistenti verranno rimosse e ricreate con le etichette correnti del sistema.\n\nVuoi continuare?')) {
                    return;
                }
                
                // Update UI
                this.disabled = true;
                this.innerHTML = '<i class="bi bi-hourglass-split"></i> Ri-etichettando...';
                
                if (progressDiv && progressBar && progressText) {
                    progressDiv.style.display = 'block';
                    progressBar.style.width = '0%';
                    progressText.textContent = 'Ri-etichettatura in corso...';
                }
                
                window.AnalisiMU.apiRequest(`/ai/generate/${fileId}`, { 
                    method: 'POST',
                    body: JSON.stringify({ 
                        batch_size: 10,  // Batch più piccoli per ri-etichettatura
                        re_annotate: true 
                    })
                })
                .then(res => {
                    if (progressDiv && progressBar && progressText) {
                        progressBar.style.width = '100%';
                        progressText.textContent = 'Ri-etichettatura completata!';
                        
                        setTimeout(() => {
                            progressDiv.style.display = 'none';
                        }, 2000);
                    }
                    
                    window.AnalisiMU.showToast(`Ri-etichettatura completata!\n\nProcessate: ${res.total_processed} celle\nNuove annotazioni: ${res.annotations_count}`, 'success', 7000);
                    refreshStatus();
                })
                .catch(() => {
                    window.AnalisiMU.showToast('Errore durante la ri-etichettatura', 'error');
                })
                .finally(() => {
                    this.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Ri-etichetta Tutto';
                    this.disabled = false;
                    if (progressDiv) progressDiv.style.display = 'none';
                });
            });
        }

        // Review AI labels
        if (reviewBtn) {
            reviewBtn.addEventListener('click', function() {
                window.location.href = `/ai/review/file/${fileId}`;
            });
        }
    }
});

// Utility functions

/**
 * Mostra un toast notification
 */
function showToast(message, type = 'info', duration = 3000) {
    const toastContainer = getOrCreateToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type === 'error' ? 'danger' : type} border-0`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast, {
        autohide: true,
        delay: duration
    });
    
    bsToast.show();
    
    // Remove element after hiding
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

/**
 * Ottiene o crea il container per i toast
 */
function getOrCreateToastContainer() {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
    }
    return container;
}

/**
 * Mostra un loading spinner
 */
function showLoading(target = document.body) {
    target.classList.add('loading');
}

/**
 * Nasconde il loading spinner
 */
function hideLoading(target = document.body) {
    target.classList.remove('loading');
}

/**
 * Debounce function per limitare la frequenza di chiamate
 */
function debounce(func, wait, immediate) {
    let timeout;
    return function executedFunction() {
        const context = this;
        const args = arguments;
        const later = function() {
            timeout = null;
            if (!immediate) func.apply(context, args);
        };
        const callNow = immediate && !timeout;
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
        if (callNow) func.apply(context, args);
    };
}

/**
 * Formatta una data in formato locale
 */
function formatDate(date, options = {}) {
    const defaultOptions = {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    };
    
    const finalOptions = { ...defaultOptions, ...options };
    return new Intl.DateTimeFormat('it-IT', finalOptions).format(new Date(date));
}

/**
 * Parsing di un colore CSS rgb/rgba
 */
function parseRgbColor(color) {
    const match = color && color.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/i);
    if (!match) {
        return null;
    }

    return {
        r: parseInt(match[1], 10),
        g: parseInt(match[2], 10),
        b: parseInt(match[3], 10),
        a: match[4] === undefined ? 1 : parseFloat(match[4])
    };
}

/**
 * Luminanza relativa per valutare il contrasto
 */
function getRelativeLuminance({ r, g, b }) {
    const normalize = (value) => {
        const channel = value / 255;
        return channel <= 0.03928
            ? channel / 12.92
            : Math.pow((channel + 0.055) / 1.055, 2.4);
    };

    const red = normalize(r);
    const green = normalize(g);
    const blue = normalize(b);

    return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/**
 * Applica testo scuro a badge/etichette con sfondo dinamico troppo chiaro
 */
function applyAutoContrast(root = document) {
    const elements = root.querySelectorAll(
        '.label-display, .label-badge, .badge[style*="background-color"], .badge[style*="background:"]'
    );

    elements.forEach((element) => {
        const background = window.getComputedStyle(element).backgroundColor;
        const parsed = parseRgbColor(background);

        if (!parsed || parsed.a === 0) {
            element.classList.remove('has-light-background');
            return;
        }

        const isLight = getRelativeLuminance(parsed) >= 0.6;
        element.classList.toggle('has-light-background', isLight);
    });
}

/**
 * Ottiene il token CSRF
 */
function getCSRFToken() {
    const metaTag = document.querySelector('meta[name=csrf-token]');
    if (metaTag) {
        return metaTag.getAttribute('content');
    }
    
    const hiddenInput = document.querySelector('input[name="csrf_token"]');
    if (hiddenInput) {
        return hiddenInput.value;
    }
    
    return null;
}

/**
 * Wrapper per fetch con handling degli errori
 */
async function apiRequest(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        }
    };
    
    const finalOptions = {
        ...defaultOptions,
        ...options,
        headers: {
            ...defaultOptions.headers,
            ...options.headers
        }
    };
    
    try {
        const response = await fetch(url, finalOptions);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('API request failed:', error);
        throw error;
    }
}

// Esporta le funzioni globalmente
window.AnalisiMU = {
    showToast,
    showLoading,
    hideLoading,
    applyAutoContrast,
    debounce,
    formatDate,
    getCSRFToken,
    apiRequest
};
