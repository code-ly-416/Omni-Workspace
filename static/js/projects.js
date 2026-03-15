document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('projectRuntimeSearch');
    const noResultsRow = document.getElementById('projectRuntimeNoResultsRow');
    const rows = Array.from(document.querySelectorAll('tr[data-project-row]'));
    const filterInputs = Array.from(document.querySelectorAll('.project-column-filter'));

    const getSelectedSet = (filterName) => {
        return new Set(
            filterInputs
                .filter((input) => input.dataset.filter === filterName && input.checked)
                .map((input) => input.value)
        );
    };

    const applyRuntimeFilters = () => {
        const query = (searchInput ? searchInput.value : '').trim().toLowerCase();
        const categoryFilters = getSelectedSet('category');
        const courseFilters = getSelectedSet('course');
        const statusFilters = getSelectedSet('status');

        let visibleCount = 0;
        rows.forEach((row) => {
            const rowSearch = row.dataset.search || '';
            const rowCategory = row.dataset.category || '';
            const rowCourse = row.dataset.course || '-';
            const rowStatus = row.dataset.status || '';

            const searchPass = !query || rowSearch.includes(query);
            const categoryPass = categoryFilters.size === 0 || categoryFilters.has(rowCategory);
            const coursePass = courseFilters.size === 0 || courseFilters.has(rowCourse);
            const statusPass = statusFilters.size === 0 || statusFilters.has(rowStatus);

            const show = searchPass && categoryPass && coursePass && statusPass;
            row.style.display = show ? '' : 'none';
            if (show) {
                visibleCount += 1;
            }
        });

        if (noResultsRow) {
            noResultsRow.style.display = visibleCount === 0 ? '' : 'none';
        }
    };

    let filterFrame = null;
    const scheduleRuntimeFilters = () => {
        if (filterFrame !== null) {
            cancelAnimationFrame(filterFrame);
        }
        filterFrame = requestAnimationFrame(() => {
            filterFrame = null;
            applyRuntimeFilters();
        });
    };

    if (searchInput) {
        ['input', 'keyup', 'search', 'paste', 'change', 'compositionend'].forEach((eventName) => {
            searchInput.addEventListener(eventName, scheduleRuntimeFilters);
        });
    }

    filterInputs.forEach((input) => {
        input.addEventListener('change', scheduleRuntimeFilters);
    });

    applyRuntimeFilters();
});
