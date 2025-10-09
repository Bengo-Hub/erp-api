// BengoBox ERP Admin - Custom JavaScript Enhancements

document.addEventListener('DOMContentLoaded', function() {
    
    // Initialize tooltips
    initializeTooltips();
    
    // Initialize smooth scrolling
    initializeSmoothScrolling();
    
    // Initialize table enhancements
    initializeTableEnhancements();
    
    // Initialize form enhancements
    initializeFormEnhancements();
    
    // Initialize sidebar enhancements
    initializeSidebarEnhancements();
    
    // Initialize loading states
    initializeLoadingStates();
    
    // Initialize search enhancements
    initializeSearchEnhancements();
    
    // Initialize responsive behavior
    initializeResponsiveBehavior();
    
    // Initialize collapsible cards
    initializeCollapsibleCards();
    
    // Initialize dropdown fixes
    initializeDropdownFixes();
    
    // Initialize top navigation
    initializeTopNavigation();
});

// Tooltip initialization
function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

// Smooth scrolling for anchor links
function initializeSmoothScrolling() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

// Table enhancements
function initializeTableEnhancements() {
    const tables = document.querySelectorAll('.table');
    
    tables.forEach(table => {
        // Add hover effects
        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(row => {
            row.addEventListener('mouseenter', function() {
                this.style.transform = 'scale(1.01)';
                this.style.transition = 'transform 0.2s ease';
            });
            
            row.addEventListener('mouseleave', function() {
                this.style.transform = 'scale(1)';
            });
        });
        
        // Add click to select functionality
        rows.forEach(row => {
            row.addEventListener('click', function() {
                // Remove selection from other rows
                rows.forEach(r => r.classList.remove('table-active'));
                // Add selection to current row
                this.classList.add('table-active');
            });
        });
    });
}

// Form enhancements
function initializeFormEnhancements() {
    // Add floating labels effect
    const formControls = document.querySelectorAll('.form-control');
    
    formControls.forEach(control => {
        // Add focus effects
        control.addEventListener('focus', function() {
            this.parentElement.classList.add('focused');
        });
        
        control.addEventListener('blur', function() {
            if (!this.value) {
                this.parentElement.classList.remove('focused');
            }
        });
        
        // Add character counter for textareas
        if (control.tagName === 'TEXTAREA') {
            const counter = document.createElement('small');
            counter.className = 'form-text text-muted character-counter';
            counter.textContent = `${control.value.length} characters`;
            control.parentElement.appendChild(counter);
            
            control.addEventListener('input', function() {
                counter.textContent = `${this.value.length} characters`;
            });
        }
    });
    
    // Form validation enhancement
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const requiredFields = form.querySelectorAll('[required]');
            let isValid = true;
            
            requiredFields.forEach(field => {
                if (!field.value.trim()) {
                    isValid = false;
                    field.classList.add('is-invalid');
                    
                    // Add error message
                    if (!field.nextElementSibling || !field.nextElementSibling.classList.contains('invalid-feedback')) {
                        const errorDiv = document.createElement('div');
                        errorDiv.className = 'invalid-feedback';
                        errorDiv.textContent = 'This field is required.';
                        field.parentElement.appendChild(errorDiv);
                    }
                } else {
                    field.classList.remove('is-invalid');
                    const errorDiv = field.parentElement.querySelector('.invalid-feedback');
                    if (errorDiv) {
                        errorDiv.remove();
                    }
                }
            });
            
            if (!isValid) {
                e.preventDefault();
                showNotification('Please fill in all required fields.', 'warning');
            }
        });
    });
}

// Sidebar enhancements
function initializeSidebarEnhancements() {
    const sidebar = document.querySelector('.main-sidebar');
    const sidebarToggle = document.querySelector('.sidebar-toggle');
    
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function() {
            sidebar.classList.toggle('sidebar-collapsed');
            
            // Save state to localStorage
            localStorage.setItem('sidebar-collapsed', sidebar.classList.contains('sidebar-collapsed'));
        });
    }
    
    // Restore sidebar state
    const sidebarCollapsed = localStorage.getItem('sidebar-collapsed') === 'true';
    if (sidebarCollapsed && sidebar) {
        sidebar.classList.add('sidebar-collapsed');
    }
    
    // Add active state to current page
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-sidebar .nav-link');
    
    navLinks.forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });
    
    // Fix sidebar menu text visibility
    const sidebarLinks = document.querySelectorAll('.nav-sidebar .nav-link');
    sidebarLinks.forEach(link => {
        // Ensure text is visible
        const textElements = link.querySelectorAll('span, a');
        textElements.forEach(element => {
            element.style.display = 'inline-block';
            element.style.visibility = 'visible';
            element.style.opacity = '1';
        });
    });
}

// Loading states
function initializeLoadingStates() {
    // Add loading spinner to buttons on form submission
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function() {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                const originalText = submitBtn.innerHTML;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Loading...';
                submitBtn.disabled = true;
                
                // Reset after a delay (in case of errors)
                setTimeout(() => {
                    submitBtn.innerHTML = originalText;
                    submitBtn.disabled = false;
                }, 5000);
            }
        });
    });
    
    // Add loading state to delete buttons
    const deleteButtons = document.querySelectorAll('.btn-delete, .btn-danger');
    deleteButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            if (!confirm('Are you sure you want to delete this item?')) {
                e.preventDefault();
                return;
            }
            
            const originalText = this.innerHTML;
            this.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deleting...';
            this.disabled = true;
        });
    });
}

// Search enhancements
function initializeSearchEnhancements() {
    const searchInputs = document.querySelectorAll('input[type="search"], .search-box');
    
    searchInputs.forEach(input => {
        // Add search icon
        const searchIcon = document.createElement('i');
        searchIcon.className = 'fas fa-search search-icon';
        searchIcon.style.position = 'absolute';
        searchIcon.style.left = '10px';
        searchIcon.style.top = '50%';
        searchIcon.style.transform = 'translateY(-50%)';
        searchIcon.style.color = '#6b7280';
        
        input.parentElement.style.position = 'relative';
        input.style.paddingLeft = '35px';
        input.parentElement.appendChild(searchIcon);
        
        // Add clear button
        const clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.className = 'btn btn-sm btn-outline-secondary clear-search';
        clearBtn.innerHTML = '<i class="fas fa-times"></i>';
        clearBtn.style.position = 'absolute';
        clearBtn.style.right = '5px';
        clearBtn.style.top = '50%';
        clearBtn.style.transform = 'translateY(-50%)';
        clearBtn.style.display = 'none';
        
        input.parentElement.appendChild(clearBtn);
        
        // Show/hide clear button
        input.addEventListener('input', function() {
            clearBtn.style.display = this.value ? 'block' : 'none';
        });
        
        // Clear search
        clearBtn.addEventListener('click', function() {
            input.value = '';
            input.focus();
            clearBtn.style.display = 'none';
            input.dispatchEvent(new Event('input'));
        });
    });
}

// Responsive behavior
function initializeResponsiveBehavior() {
    // Handle mobile menu toggle
    const mobileMenuToggle = document.querySelector('.navbar-toggler');
    const sidebar = document.querySelector('.main-sidebar');
    
    if (mobileMenuToggle && sidebar) {
        mobileMenuToggle.addEventListener('click', function() {
            sidebar.classList.toggle('show');
        });
        
        // Close sidebar when clicking outside
        document.addEventListener('click', function(e) {
            if (!sidebar.contains(e.target) && !mobileMenuToggle.contains(e.target)) {
                sidebar.classList.remove('show');
            }
        });
    }
    
    // Handle window resize
    window.addEventListener('resize', function() {
        if (window.innerWidth > 768) {
            sidebar.classList.remove('show');
        }
    });
}

// Top navigation enhancements
function initializeTopNavigation() {
    const navbar = document.querySelector('.main-header .navbar');
    const navbarNav = document.querySelector('.main-header .navbar-nav');
    
    if (!navbar || !navbarNav) return;
    
    // Create mobile toggle button if it doesn't exist
    let mobileToggle = navbar.querySelector('.navbar-toggler');
    if (!mobileToggle) {
        mobileToggle = document.createElement('button');
        mobileToggle.className = 'navbar-toggler d-md-none';
        mobileToggle.innerHTML = '<i class="fas fa-bars"></i>';
        mobileToggle.setAttribute('type', 'button');
        mobileToggle.setAttribute('aria-label', 'Toggle navigation');
        
        // Insert toggle button before navbar nav
        navbar.insertBefore(mobileToggle, navbarNav);
    }
    
    // Handle mobile toggle
    mobileToggle.addEventListener('click', function() {
        navbarNav.classList.toggle('show');
        
        // Change icon
        const icon = this.querySelector('i');
        if (navbarNav.classList.contains('show')) {
            icon.className = 'fas fa-times';
        } else {
            icon.className = 'fas fa-bars';
        }
    });
    
    // Close mobile menu when clicking outside
    document.addEventListener('click', function(e) {
        if (!navbar.contains(e.target)) {
            navbarNav.classList.remove('show');
            const icon = mobileToggle.querySelector('i');
            icon.className = 'fas fa-bars';
        }
    });
    
    // Handle window resize for mobile menu
    window.addEventListener('resize', function() {
        if (window.innerWidth > 768) {
            navbarNav.classList.remove('show');
            const icon = mobileToggle.querySelector('i');
            icon.className = 'fas fa-bars';
        }
    });
    
    // Add active state to current navigation item
    const currentPath = window.location.pathname;
    const navLinks = navbarNav.querySelectorAll('.nav-link');
    
    navLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (href && (href === currentPath || currentPath.startsWith(href))) {
            link.classList.add('active');
        }
    });
    
    // Improve dropdown positioning
    const dropdowns = navbarNav.querySelectorAll('.dropdown');
    dropdowns.forEach(dropdown => {
        const dropdownMenu = dropdown.querySelector('.dropdown-menu');
        if (dropdownMenu) {
            // Ensure dropdown doesn't go off-screen
            dropdown.addEventListener('mouseenter', function() {
                const rect = dropdownMenu.getBoundingClientRect();
                const windowWidth = window.innerWidth;
                
                if (rect.right > windowWidth) {
                    dropdownMenu.style.left = 'auto';
                    dropdownMenu.style.right = '0';
                }
            });
        }
    });
}

// Collapsible cards functionality
function initializeCollapsibleCards() {
    const cards = document.querySelectorAll('.card');
    
    cards.forEach(card => {
        const header = card.querySelector('.card-header');
        const body = card.querySelector('.card-body');
        
        if (header && body) {
            // Add collapsible class
            card.classList.add('collapsible');
            
            // Add collapse icon if not present
            if (!header.querySelector('.collapse-icon')) {
                const icon = document.createElement('i');
                icon.className = 'collapse-icon fas fa-chevron-down';
                header.appendChild(icon);
            }
            
            // Add click handler
            header.addEventListener('click', function() {
                card.classList.toggle('collapsed');
                
                // Save state to localStorage
                const cardId = card.id || card.className;
                localStorage.setItem(`card-${cardId}-collapsed`, card.classList.contains('collapsed'));
            });
            
            // Restore collapsed state
            const cardId = card.id || card.className;
            const isCollapsed = localStorage.getItem(`card-${cardId}-collapsed`) === 'true';
            if (isCollapsed) {
                card.classList.add('collapsed');
            }
        }
    });
}

// Dropdown fixes
function initializeDropdownFixes() {
    // Fix Bootstrap dropdowns
    const dropdownToggles = document.querySelectorAll('[data-bs-toggle="dropdown"]');
    
    dropdownToggles.forEach(toggle => {
        toggle.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            const dropdownMenu = this.nextElementSibling;
            if (dropdownMenu && dropdownMenu.classList.contains('dropdown-menu')) {
                // Close other dropdowns
                document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
                    if (menu !== dropdownMenu) {
                        menu.classList.remove('show');
                    }
                });
                
                // Toggle current dropdown
                dropdownMenu.classList.toggle('show');
            }
        });
    });
    
    // Close dropdowns when clicking outside
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.dropdown')) {
            document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
                menu.classList.remove('show');
            });
        }
    });
    
    // Fix user menu dropdown
    const userMenuToggle = document.querySelector('.nav-item.dropdown .nav-link');
    if (userMenuToggle) {
        userMenuToggle.addEventListener('click', function(e) {
            e.preventDefault();
            const dropdownMenu = this.nextElementSibling;
            if (dropdownMenu) {
                dropdownMenu.classList.toggle('show');
            }
        });
    }
}

// Notification system
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show notification-toast`;
    notification.style.position = 'fixed';
    notification.style.top = '20px';
    notification.style.right = '20px';
    notification.style.zIndex = '9999';
    notification.style.minWidth = '300px';
    notification.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.1)';
    
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    document.body.appendChild(notification);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 5000);
}

// Data table enhancements
function initializeDataTable() {
    const tables = document.querySelectorAll('.data-table');
    
    tables.forEach(table => {
        // Add sorting functionality
        const headers = table.querySelectorAll('th[data-sortable]');
        headers.forEach(header => {
            header.style.cursor = 'pointer';
            header.addEventListener('click', function() {
                const column = this.cellIndex;
                const rows = Array.from(table.querySelectorAll('tbody tr'));
                const isAscending = this.classList.contains('sort-asc');
                
                // Remove sort classes from all headers
                headers.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
                
                // Add sort class to current header
                this.classList.add(isAscending ? 'sort-desc' : 'sort-asc');
                
                // Sort rows
                rows.sort((a, b) => {
                    const aValue = a.cells[column].textContent.trim();
                    const bValue = b.cells[column].textContent.trim();
                    
                    if (isAscending) {
                        return bValue.localeCompare(aValue);
                    } else {
                        return aValue.localeCompare(bValue);
                    }
                });
                
                // Reorder rows
                const tbody = table.querySelector('tbody');
                rows.forEach(row => tbody.appendChild(row));
            });
        });
    });
}

// Export functionality
function initializeExportButtons() {
    const exportButtons = document.querySelectorAll('.btn-export');
    
    exportButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            
            const format = this.dataset.format || 'csv';
            const table = document.querySelector(this.dataset.table);
            
            if (table) {
                exportTable(table, format);
            }
        });
    });
}

function exportTable(table, format) {
    const rows = Array.from(table.querySelectorAll('tr'));
    let content = '';
    
    if (format === 'csv') {
        rows.forEach(row => {
            const cells = Array.from(row.querySelectorAll('th, td'));
            const rowData = cells.map(cell => `"${cell.textContent.trim()}"`).join(',');
            content += rowData + '\n';
        });
        
        downloadFile(content, 'table-export.csv', 'text/csv');
    } else if (format === 'json') {
        const headers = Array.from(rows[0].querySelectorAll('th')).map(th => th.textContent.trim());
        const data = [];
        
        for (let i = 1; i < rows.length; i++) {
            const cells = Array.from(rows[i].querySelectorAll('td'));
            const rowData = {};
            
            headers.forEach((header, index) => {
                rowData[header] = cells[index] ? cells[index].textContent.trim() : '';
            });
            
            data.push(rowData);
        }
        
        downloadFile(JSON.stringify(data, null, 2), 'table-export.json', 'application/json');
    }
}

function downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

// Initialize additional features when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    initializeDataTable();
    initializeExportButtons();
});

// Add keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + K for search
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.querySelector('input[type="search"], .search-box');
        if (searchInput) {
            searchInput.focus();
        }
    }
    
    // Escape to close modals and dropdowns
    if (e.key === 'Escape') {
        // Close modals
        const modals = document.querySelectorAll('.modal.show');
        modals.forEach(modal => {
            const closeBtn = modal.querySelector('.btn-close');
            if (closeBtn) {
                closeBtn.click();
            }
        });
        
        // Close dropdowns
        document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
            menu.classList.remove('show');
        });
        
        // Close mobile navigation
        const navbarNav = document.querySelector('.main-header .navbar-nav');
        if (navbarNav && navbarNav.classList.contains('show')) {
            navbarNav.classList.remove('show');
            const mobileToggle = document.querySelector('.navbar-toggler');
            if (mobileToggle) {
                const icon = mobileToggle.querySelector('i');
                icon.className = 'fas fa-bars';
            }
        }
    }
});
