document.addEventListener("submit", function (e) {
    const form = e.target;
    const msg = form.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) {
        e.preventDefault();
    }
});