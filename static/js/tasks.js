document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('runtimeSearch');
    const noResultsRow = document.getElementById('runtimeNoResultsRow');
    const rows = Array.from(document.querySelectorAll('tr[data-task-row]'));
    const filterInputs = Array.from(document.querySelectorAll('.column-filter'));

    const getSelectedSet = (filterName) => {
        return new Set(
            filterInputs
                .filter((input) => input.dataset.filter === filterName && input.checked)
                .map((input) => input.value)
        );
    };

    const dateMatches = (dateValue, dueFilters) => {
        if (dueFilters.size === 0) {
            return true;
        }
        if (!dateValue) {
            return false;
        }

        const dueDate = new Date(`${dateValue}T00:00:00`);
        if (Number.isNaN(dueDate.getTime())) {
            return false;
        }

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        const inSevenDays = new Date(today);
        inSevenDays.setDate(inSevenDays.getDate() + 7);

        const checks = {
            overdue: dueDate < today,
            today: dueDate.getTime() === today.getTime(),
            next7: dueDate > today && dueDate <= inSevenDays
        };

        for (const key of dueFilters) {
            if (checks[key]) {
                return true;
            }
        }
        return false;
    };

    const applyRuntimeFilters = () => {
        const query = (searchInput ? searchInput.value : '').trim().toLowerCase();
        const priorityFilters = getSelectedSet('priority');
        const statusFilters = getSelectedSet('status');
        const categoryFilters = getSelectedSet('category');
        const tagFilters = getSelectedSet('tag');
        const dueFilters = getSelectedSet('due');

        let visibleCount = 0;
        rows.forEach((row) => {
            const rowSearch = row.dataset.search || '';
            const rowPriority = row.dataset.priority || '';
            const rowStatus = row.dataset.status || '';
            const rowCategory = row.dataset.category || '';
            const rowDueDate = row.dataset.dueDate || '';
            const rowTags = (row.dataset.tags || '').split('|').filter(Boolean);

            const searchPass = !query || rowSearch.includes(query);
            const priorityPass = priorityFilters.size === 0 || priorityFilters.has(rowPriority);
            const statusPass = statusFilters.size === 0 || statusFilters.has(rowStatus);
            const categoryPass = categoryFilters.size === 0 || categoryFilters.has(rowCategory);
            const tagPass = tagFilters.size === 0 || rowTags.some((tag) => tagFilters.has(tag));
            const duePass = dateMatches(rowDueDate, dueFilters);

            const show = searchPass && priorityPass && statusPass && categoryPass && tagPass && duePass;
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

    const applyProjectCategoryLock = (projectSelect, categorySelect) => {
        if (!projectSelect || !categorySelect) {
            return;
        }

        const form = projectSelect.closest('form');
        if (!form) {
            return;
        }

        let hiddenCategoryInput = form.querySelector('input[type="hidden"].locked-category-id');
        if (!hiddenCategoryInput) {
            hiddenCategoryInput = document.createElement('input');
            hiddenCategoryInput.type = 'hidden';
            hiddenCategoryInput.className = 'locked-category-id';
            form.appendChild(hiddenCategoryInput);
        }

        const sync = () => {
            const selectedProjectOption = projectSelect.options[projectSelect.selectedIndex];
            const projectCategoryId = selectedProjectOption ? selectedProjectOption.getAttribute('data-category-id') : null;

            if (projectSelect.value && projectCategoryId) {
                categorySelect.value = projectCategoryId;
                categorySelect.disabled = true;
                categorySelect.removeAttribute('name');

                hiddenCategoryInput.name = 'category_id';
                hiddenCategoryInput.value = projectCategoryId;
            } else {
                categorySelect.disabled = false;
                categorySelect.setAttribute('name', 'category_id');

                hiddenCategoryInput.name = '';
                hiddenCategoryInput.value = '';
            }
        };

        projectSelect.addEventListener('change', sync);
        sync();
    };

    applyProjectCategoryLock(
        document.getElementById('project_id'),
        document.getElementById('category_id')
    );

    applyProjectCategoryLock(
        document.getElementById('routine_project_id'),
        document.getElementById('routine_category_id')
    );

    document.querySelectorAll('[id^="editTaskModal"]').forEach((modal) => {
        const taskId = modal.id.replace('editTaskModal', '');
        const projectSelect = document.getElementById(`project_id${taskId}`);
        const categorySelect = document.getElementById(`category_id${taskId}`);
        applyProjectCategoryLock(projectSelect, categorySelect);
    });

    document.querySelectorAll('[id^="editRoutineModal"]').forEach((modal) => {
        const taskId = modal.id.replace('editRoutineModal', '');
        const projectSelect = document.getElementById(`routine_project_id${taskId}`);
        const categorySelect = document.getElementById(`routine_category_id${taskId}`);
        applyProjectCategoryLock(projectSelect, categorySelect);
    });
});
