(() => {
    const viewer = document.querySelector('.media-viewer');
    const image = viewer.querySelector('.viewer-image img');
    const title = viewer.querySelector('#viewer-title');
    const download = viewer.querySelector('.viewer-download');
    const close = viewer.querySelector('.viewer-close');
    let opener = null;
    let previousOverflow = '';

    if (typeof viewer.showModal === 'function') {
        document.querySelectorAll('[data-preview]').forEach(link => {
            link.addEventListener('click', event => {
                if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
                event.preventDefault();
                opener = link;
                title.textContent = link.dataset.title;
                image.src = link.href;
                image.alt = link.querySelector('img').alt;
                download.href = link.href;
                download.download = 'HIDMaestro-' + link.dataset.filename;
                viewer.classList.toggle('is-brand', link.classList.contains('brand-preview'));
                viewer.classList.toggle('viewer-dark', link.dataset.background === 'dark');
                previousOverflow = document.body.style.overflow;
                document.body.style.overflow = 'hidden';
                viewer.showModal();
                close.focus();
            });
        });
        close.addEventListener('click', () => viewer.close());
        viewer.addEventListener('click', event => {
            if (event.target !== viewer) return;
            const bounds = viewer.getBoundingClientRect();
            if (event.clientX < bounds.left || event.clientX > bounds.right ||
                event.clientY < bounds.top || event.clientY > bounds.bottom) viewer.close();
        });
        viewer.addEventListener('close', () => {
            document.body.style.overflow = previousOverflow;
            image.removeAttribute('src');
            if (opener) opener.focus({ preventScroll: true });
        });
    }

    const copy = document.querySelector('.copy-button');
    const status = document.querySelector('.copy-status');
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        copy.hidden = false;
        copy.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(document.querySelector('#product-description').textContent.trim());
                status.textContent = 'Description copied.';
            } catch {
                status.textContent = 'Select the description to copy it, or download the fact sheet.';
            }
        });
    }
})();
