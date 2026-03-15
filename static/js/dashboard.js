document.addEventListener('DOMContentLoaded', () => {
    const calendarEventsNode = document.getElementById('dashboardCalendarEvents');
    if (!calendarEventsNode) {
        return;
    }

    let calendarEvents = [];
    if (calendarEventsNode.textContent) {
        try {
            calendarEvents = JSON.parse(calendarEventsNode.textContent);
        } catch (error) {
            calendarEvents = [];
        }
    }

    const monthLabel = document.getElementById('calendarMonthLabel');
    const miniMonthLabel = document.getElementById('calendarMiniMonthLabel');
    const calendarGrid = document.getElementById('dashboardCalendarGrid');
    const miniCalendarGrid = document.getElementById('dashboardMiniCalendarGrid');
    const prevMonthBtn = document.getElementById('calendarPrevMonth');
    const nextMonthBtn = document.getElementById('calendarNextMonth');
    const miniPrevMonthBtn = document.getElementById('calendarMiniPrevMonth');
    const miniNextMonthBtn = document.getElementById('calendarMiniNextMonth');
    const todayBtn = document.getElementById('calendarTodayBtn');
    const searchInput = document.getElementById('dashboardEventSearch');
    const viewButtons = Array.from(document.querySelectorAll('[data-calendar-view]'));
    const weekdaysRow = document.querySelector('.dashboard-month-weekdays');
    const selectedDayLabel = document.getElementById('selectedDayLabel');
    const selectedDayTasks = document.getElementById('selectedDayTasks');

    const eventsByDate = calendarEvents.reduce((accumulator, eventItem) => {
        if (!accumulator[eventItem.due_date]) {
            accumulator[eventItem.due_date] = [];
        }
        accumulator[eventItem.due_date].push(eventItem);
        return accumulator;
    }, {});

    const today = new Date();
    const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

    let activeDate = todayIso;
    let visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    let viewMode = 'month';
    let searchQuery = '';

    const formatIso = (dateObj) => {
        return `${dateObj.getFullYear()}-${String(dateObj.getMonth() + 1).padStart(2, '0')}-${String(dateObj.getDate()).padStart(2, '0')}`;
    };

    const getPriorityClass = (priority) => {
        const normalized = (priority || '').toLowerCase();
        if (normalized === 'high') {
            return 'priority-high';
        }
        if (normalized === 'medium') {
            return 'priority-medium';
        }
        return 'priority-low';
    };

    const normalizeDate = (dateObj) => {
        return new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate());
    };

    const getActiveDateObject = () => {
        return new Date(`${activeDate}T00:00:00`);
    };

    const getWeekStart = (dateObj) => {
        const normalized = normalizeDate(dateObj);
        const offset = normalized.getDay();
        normalized.setDate(normalized.getDate() - offset);
        return normalized;
    };

    const eventMatchesSearch = (task) => {
        if (!searchQuery) {
            return true;
        }

        const haystack = [
            task.title,
            task.project_name,
            task.priority,
            task.status,
            (task.tags || []).map((tag) => tag.label).join(' ')
        ].join(' ').toLowerCase();

        return haystack.includes(searchQuery);
    };

    const getEventsForDate = (dateIso) => {
        const events = eventsByDate[dateIso] || [];
        return events.filter((task) => eventMatchesSearch(task));
    };

    const renderSelectedDayTasks = () => {
        const dayEvents = getEventsForDate(activeDate);
        const readableDate = new Date(`${activeDate}T00:00:00`).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
            year: 'numeric'
        });
        selectedDayLabel.textContent = readableDate;

        if (!dayEvents.length) {
            selectedDayTasks.innerHTML = '<div class="text-muted small">No tasks for this day.</div>';
            return;
        }

        selectedDayTasks.innerHTML = dayEvents.map((task) => {
            const priorityClass = getPriorityClass(task.priority);
            const projectInfo = task.project_name ? `<div class="small text-muted">${task.project_name}</div>` : '';
            return `
                <a href="/tasks" class="dashboard-selected-task ${priorityClass}">
                    <div class="dashboard-selected-task-title">${task.title}</div>
                    <div class="dashboard-selected-task-meta">${task.priority || 'Priority N/A'}</div>
                    ${projectInfo}
                </a>
            `;
        }).join('');
    };

    const createMainDayCell = (dateObj, isCurrentMonth) => {
        const dayIso = formatIso(dateObj);
        const dayEvents = getEventsForDate(dayIso);
        const isActive = dayIso === activeDate;
        const isToday = dayIso === todayIso;

        const cell = document.createElement('button');
        cell.type = 'button';
        cell.className = `dashboard-day-cell${isCurrentMonth ? '' : ' outside'}${isActive ? ' active' : ''}${isToday ? ' today' : ''}`;
        cell.setAttribute('data-date', dayIso);

        const eventSnippets = dayEvents.slice(0, 2).map((task) => {
            const priorityClass = getPriorityClass(task.priority);
            return `<div class="dashboard-day-event ${priorityClass}">${task.title}</div>`;
        }).join('');

        const moreCount = dayEvents.length > 2 ? `<div class="dashboard-day-more">+${dayEvents.length - 2} more</div>` : '';

        cell.innerHTML = `
            <div class="dashboard-day-number-wrap">
                <span class="dashboard-day-number">${dateObj.getDate()}</span>
            </div>
            <div class="dashboard-day-events">
                ${eventSnippets}
                ${moreCount}
            </div>
        `;

        cell.addEventListener('click', () => {
            activeDate = dayIso;
            renderCalendar();
            renderMiniCalendar();
            renderSelectedDayTasks();
        });

        return cell;
    };

    const createMiniDayCell = (dateObj, isCurrentMonth) => {
        const dayIso = formatIso(dateObj);
        const hasEvents = getEventsForDate(dayIso).length > 0;
        const isActive = dayIso === activeDate;
        const isToday = dayIso === todayIso;

        const cell = document.createElement('button');
        cell.type = 'button';
        cell.className = `dashboard-mini-day${isCurrentMonth ? '' : ' outside'}${isActive ? ' active' : ''}${isToday ? ' today' : ''}`;
        cell.setAttribute('data-date', dayIso);
        cell.innerHTML = `<span>${dateObj.getDate()}</span>${hasEvents ? '<i></i>' : ''}`;

        cell.addEventListener('click', () => {
            activeDate = dayIso;
            visibleMonth = new Date(dateObj.getFullYear(), dateObj.getMonth(), 1);
            renderCalendar();
            renderMiniCalendar();
            renderSelectedDayTasks();
        });

        return cell;
    };

    const renderCalendar = () => {
        if (!calendarGrid || !monthLabel) {
            return;
        }

        const activeDateObj = getActiveDateObject();

        if (viewMode === 'day') {
            monthLabel.textContent = activeDateObj.toLocaleDateString(undefined, {
                month: 'long',
                day: 'numeric',
                year: 'numeric'
            });
            calendarGrid.className = 'dashboard-month-grid day-view';
            if (weekdaysRow) {
                weekdaysRow.style.display = 'none';
            }

            const dayEvents = getEventsForDate(activeDate);
            const dayItems = dayEvents.length
                ? dayEvents.map((task) => {
                    const priorityClass = getPriorityClass(task.priority);
                    const projectInfo = task.project_name ? `<div class="small text-muted">${task.project_name}</div>` : '';
                    return `
                        <a href="/tasks" class="dashboard-selected-task ${priorityClass}">
                            <div class="dashboard-selected-task-title">${task.title}</div>
                            <div class="dashboard-selected-task-meta">${task.priority || 'Priority N/A'}</div>
                            ${projectInfo}
                        </a>
                    `;
                }).join('')
                : '<div class="text-muted small">No tasks for this day.</div>';

            calendarGrid.innerHTML = `<div class="dashboard-day-focus">${dayItems}</div>`;
            return;
        }

        if (viewMode === 'week') {
            const start = getWeekStart(activeDateObj);
            const end = new Date(start);
            end.setDate(start.getDate() + 6);

            monthLabel.textContent = `${start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} - ${end.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`;
            calendarGrid.className = 'dashboard-month-grid week-view';
            if (weekdaysRow) {
                weekdaysRow.style.display = '';
            }

            calendarGrid.innerHTML = '';
            for (let index = 0; index < 7; index += 1) {
                const dayDate = new Date(start);
                dayDate.setDate(start.getDate() + index);
                calendarGrid.appendChild(createMainDayCell(dayDate, true));
            }
            return;
        }

        const year = visibleMonth.getFullYear();
        const month = visibleMonth.getMonth();
        const firstDay = new Date(year, month, 1);
        const startDay = new Date(year, month, 1 - firstDay.getDay());

        monthLabel.textContent = firstDay.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
        calendarGrid.className = 'dashboard-month-grid';
        if (weekdaysRow) {
            weekdaysRow.style.display = '';
        }
        calendarGrid.innerHTML = '';

        for (let index = 0; index < 42; index += 1) {
            const dayDate = new Date(startDay);
            dayDate.setDate(startDay.getDate() + index);
            const isCurrentMonth = dayDate.getMonth() === month;
            calendarGrid.appendChild(createMainDayCell(dayDate, isCurrentMonth));
        }
    };

    const renderMiniCalendar = () => {
        if (!miniCalendarGrid || !miniMonthLabel) {
            return;
        }

        const year = visibleMonth.getFullYear();
        const month = visibleMonth.getMonth();
        const firstDay = new Date(year, month, 1);
        const startDay = new Date(year, month, 1 - firstDay.getDay());

        miniMonthLabel.textContent = firstDay.toLocaleDateString(undefined, { month: 'long' });
        miniCalendarGrid.innerHTML = '';

        for (let index = 0; index < 42; index += 1) {
            const dayDate = new Date(startDay);
            dayDate.setDate(startDay.getDate() + index);
            const isCurrentMonth = dayDate.getMonth() === month;
            miniCalendarGrid.appendChild(createMiniDayCell(dayDate, isCurrentMonth));
        }
    };

    if (prevMonthBtn) {
        prevMonthBtn.addEventListener('click', () => {
            if (viewMode === 'month') {
                visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1);
            } else if (viewMode === 'week') {
                const current = getActiveDateObject();
                current.setDate(current.getDate() - 7);
                activeDate = formatIso(current);
                visibleMonth = new Date(current.getFullYear(), current.getMonth(), 1);
            } else {
                const current = getActiveDateObject();
                current.setDate(current.getDate() - 1);
                activeDate = formatIso(current);
                visibleMonth = new Date(current.getFullYear(), current.getMonth(), 1);
            }
            renderCalendar();
            renderMiniCalendar();
            renderSelectedDayTasks();
        });
    }

    if (nextMonthBtn) {
        nextMonthBtn.addEventListener('click', () => {
            if (viewMode === 'month') {
                visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1);
            } else if (viewMode === 'week') {
                const current = getActiveDateObject();
                current.setDate(current.getDate() + 7);
                activeDate = formatIso(current);
                visibleMonth = new Date(current.getFullYear(), current.getMonth(), 1);
            } else {
                const current = getActiveDateObject();
                current.setDate(current.getDate() + 1);
                activeDate = formatIso(current);
                visibleMonth = new Date(current.getFullYear(), current.getMonth(), 1);
            }
            renderCalendar();
            renderMiniCalendar();
            renderSelectedDayTasks();
        });
    }

    if (miniPrevMonthBtn) {
        miniPrevMonthBtn.addEventListener('click', () => {
            visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1);
            renderCalendar();
            renderMiniCalendar();
        });
    }

    if (miniNextMonthBtn) {
        miniNextMonthBtn.addEventListener('click', () => {
            visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1);
            renderCalendar();
            renderMiniCalendar();
        });
    }

    if (todayBtn) {
        todayBtn.addEventListener('click', () => {
            visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1);
            activeDate = todayIso;
            renderCalendar();
            renderMiniCalendar();
            renderSelectedDayTasks();
        });
    }

    if (searchInput) {
        searchInput.addEventListener('input', () => {
            searchQuery = searchInput.value.trim().toLowerCase();
            renderCalendar();
            renderMiniCalendar();
            renderSelectedDayTasks();
        });
    }

    viewButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const nextView = button.getAttribute('data-calendar-view');
            if (!nextView || nextView === viewMode) {
                return;
            }

            viewMode = nextView;
            viewButtons.forEach((candidate) => {
                candidate.classList.toggle('active', candidate === button);
            });

            renderCalendar();
            renderMiniCalendar();
            renderSelectedDayTasks();
        });
    });

    renderCalendar();
    renderMiniCalendar();
    renderSelectedDayTasks();

    const params = new URLSearchParams(window.location.search);
    if (params.has('open_project')) {
        const cleanUrl = `${window.location.pathname}`;
        window.history.replaceState({}, '', cleanUrl);
    }
});
