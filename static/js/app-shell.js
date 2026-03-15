document.addEventListener('DOMContentLoaded', () => {
    const body = document.body;
    const sidebar = document.getElementById('appSidebar');
    const sidebarRailToggle = document.getElementById('sidebarRailToggle');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');

    if (!sidebar) {
        return;
    }

    const desktopQuery = window.matchMedia('(min-width: 992px)');
    const sidebarStateKey = 'omniSidebarExpanded';

    const closeSidebar = () => body.classList.remove('sidebar-open');
    const openSidebar = () => body.classList.add('sidebar-open');

    const getSavedExpanded = () => {
        try {
            return localStorage.getItem(sidebarStateKey) === '1';
        } catch (error) {
            return false;
        }
    };

    const setSidebarExpanded = (expanded, options = {}) => {
        const { persist = true } = options;
        body.classList.toggle('sidebar-expanded', expanded);

        if (sidebarRailToggle) {
            sidebarRailToggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
            sidebarRailToggle.setAttribute('aria-label', expanded ? 'Collapse sidebar' : 'Expand sidebar');
        }

        if (persist) {
            try {
                localStorage.setItem(sidebarStateKey, expanded ? '1' : '0');
            } catch (error) {
            }
        }
    };

    const syncForViewport = () => {
        if (desktopQuery.matches) {
            closeSidebar();
            setSidebarExpanded(getSavedExpanded(), { persist: false });
        } else {
            body.classList.remove('sidebar-expanded');
            closeSidebar();
        }
    };

    syncForViewport();

    if (sidebarRailToggle) {
        sidebarRailToggle.addEventListener('click', () => {
            if (desktopQuery.matches) {
                setSidebarExpanded(!body.classList.contains('sidebar-expanded'));
                return;
            }

            if (body.classList.contains('sidebar-open')) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });
    }

    if (sidebarBackdrop) {
        sidebarBackdrop.addEventListener('click', closeSidebar);
    }

    sidebar.querySelectorAll('[data-nav-link]').forEach((link) => {
        const href = link.getAttribute('href') || '';
        const isRoot = href === '/';
        const matches = isRoot
            ? window.location.pathname === '/'
            : window.location.pathname.startsWith(href);

        if (matches) {
            link.classList.add('active');
        }

        link.addEventListener('click', () => {
            if (!desktopQuery.matches) {
                closeSidebar();
            }
        });
    });

    desktopQuery.addEventListener('change', syncForViewport);

    requestAnimationFrame(() => {
        body.classList.remove('app-shell-no-transition');
    });
});
