from datetime import datetime

JAZZMIN_SETTINGS = {
    # title of the window (Will default to current_admin_site.site_title if absent or None)
    "site_title": "BengoBox ERP Admin",

    # Title on the login screen (19 chars max) (defaults to current_admin_site.site_header if absent or None)
    "site_header": "BengoBox ERP",

    # Title on the brand (19 chars max) (defaults to current_admin_site.site_header if absent or None)
    "site_brand": "BengoBox ERP",

    # Logo to use for your site, must be present in static files, used for brand on top left
    "site_logo": "/logo/logo.png",

    # CSS classes that are applied to the logo above
    "site_logo_classes": "img-fluid custom-logo-size",

    # Relative path to a favicon for your site, will default to site_logo if absent (ideally 32x32 px)
    "site_icon": "/logo/logo.png",

    # Welcome text on the login screen
    "welcome_sign": "Welcome to BengoBox ERP Administration",

    # Copyright on the footer
    "copyright": f"© {datetime.now().year} BengoBox ERP. All rights reserved.",

    # The model admin to search from the search bar, search bar omitted if excluded
    "search_model": "authmanagement.CustomUser",

    # Field name on user model that contains avatar ImageField/URLField/Charfield or a callable that receives the user
    "user_avatar": "/logo/logo.png",

    ############
    # Top Menu #
    ############

    # Links to put along the top menu
    "topmenu_links": [
        # Url that gets reversed (Permissions can be added)
        {"name": "Home",  "url": "/admin", "permissions": ["authmanagement.view_user"]},
        {"app": "employees","permissions": ["employees.view_employee"], "label": "HRM"},
        {"app": "payroll_settings","permissions": ["payroll_settings.view_payrollsetting"], "label": "Payroll Config"},
        {"app": "payroll","permissions": ["payroll.view_payroll"], "label": "Payroll"},
        {"app": "accounts","permissions": ["accounts.view_account"], "label": "Finance"},
        {"app": "stockinventory","permissions": ["stockinventory.view_inventory"], "label": "Stock Inventory"},
    ],

    #############
    # User Menu #
    #############

    # Additional links to include in the user menu on the top right ("app" url type is not allowed)
    "usermenu_links": [
        {"name": "Profile Settings", "model": "authmanagement.CustomUser"},
        {"name": "Documentation", "url": "https://bengohub.co.ke/docs", "new_window": True},
        {"name": "Support", "url": "https://bengohub.co.ke/support", "new_window": True},
        {"name": "System Status", "url": "https://bengohub.co.ke/status", "new_window": True},
    ],

    #############
    # Side Menu #
    #############

    # Whether to display the side menu
    "show_sidebar": True,

    # Whether to aut expand the menu
    "navigation_expanded": False,

    # Hide these apps when generating side menu e.g (auth)
    "hide_apps": [],

    # Hide these models when generating side menu (e.g authman.CustomUser)
    "hide_models": [],

    # List of apps (and/or models) to base side menu ordering off of (does not need to contain all apps/models)
    "order_with_respect_to": [
        "authmanagement", 
        "auth.group", 
        "core", 
        "business", 
        "accounts", 
        "contacts", 
        "employees", 
        "payroll", 
        "payroll_settings",
        "pos",
        "purchases",
        "stockinventory",
        "taxes",
        "payments",
        "expenses"
    ],

    # Custom links to append to app groups, keyed on app name
    "custom_links": {
        "core": [{
            "name": "System Dashboard",
            "url": "/admin/core/",
            "icon": "fas fa-tachometer-alt",
            "permissions": ["core.view_core"]
        }],
        "business": [{
            "name": "Business Overview",
            "url": "/admin/business/bussiness/",
            "icon": "fas fa-chart-line",
            "permissions": ["business.view_bussiness"]
        }],
        "employees": [{
            "name": "Employee Directory",
            "url": "/admin/employees/employee/",
            "icon": "fas fa-users",
            "permissions": ["employees.view_employee"]
        }],
        "payroll": [{
            "name": "Payroll Overview",
            "url": "/admin/payroll/payroll/",
            "icon": "fas fa-money-bill-wave",
            "permissions": ["payroll.view_payroll"]
        }],
        "pos": [{
            "name": "POS Dashboard",
            "url": "/admin/pos/order/",
            "icon": "fas fa-cash-register",
            "permissions": ["pos.view_order"]
        }],
    },

    # Custom icons for side menu apps/models
    "icons": {
        # Auth Management
        "auth.group": "fas fa-users-cog",
        "authmanagement.CustomUser": "fas fa-user-circle",
        "authmanagement.roles": "fas fa-user-shield",
        "authmanagement.AccountRequest": "fas fa-user-plus",
        "authmanagement.passwordpolicy": "fas fa-lock",
        "authmanagement.backupschedule": "fas fa-database",
        
        # Core
        "core.EmailConfigs": "fas fa-envelope-open-text",
        "core.projects": "fas fa-project-diagram",
        "core.departments": "fas fa-sitemap",
        "core.regions": "fas fa-map-marked-alt",
        "core.banks": "fas fa-university",
        
        # Accounts
        "accounts.Account": "fas fa-wallet",
        "accounts.Transaction": "fas fa-exchange-alt",
        
        # Business
        "business.Business": "fas fa-building",
        "business.Branch": "fas fa-code-branch",
        
        # Contacts
        "contacts.Contact": "fas fa-address-book",
        "contacts.Supplier": "fas fa-truck",
        "contacts.Customer": "fas fa-users",
        
        # Employees
        "employees.employee": "fas fa-user-tie",
        "employees.jobtitle": "fas fa-id-card",
        "employees.Department": "fas fa-users-cog",

        "leave.LeaveCategory": "fas fa-tags",
        "leave.LeaveEntitlement": "fas fa-calendar-check",
        "leave.LeaveRequest": "fas fa-calendar-alt",
        "leave.LeaveBalance": "fas fa-calendar-minus",
        
        # Payroll
        "payroll.Payslip": "fas fa-file-invoice-dollar",
        "payroll.Payroll": "fas fa-money-check-alt",
        "payroll.Deduction": "fas fa-minus-circle",
        "payroll.Benefit": "fas fa-plus-circle",
        
        # Payroll Settings
        "payroll_settings.PayrollSetting": "fas fa-cogs",
        "payroll_settings.TaxBracket": "fas fa-percentage",
        
        # POS
        "pos.Order": "fas fa-cash-register",
        "pos.Invoice": "fas fa-receipt",
        "pos.Cart": "fas fa-shopping-cart",
        
        # Purchases
        "purchases.Purchase": "fas fa-shopping-basket",
        "purchases.PurchaseItem": "fas fa-boxes",
        "purchases.PurchaseOrder": "fas fa-file-invoice",
        
        # Stock Inventory
        "stockinventory.Product": "fas fa-box-open",
        "stockinventory.Category": "fas fa-tags",
        "stockinventory.Inventory": "fas fa-warehouse",
        "stockinventory.StockMovement": "fas fa-dolly",
        
        # Taxes
        "taxes.Tax": "fas fa-receipt",
        
        # Payments
        "payments.payment": "fas fa-credit-card",
        "payments.PaymentMethod": "fas fa-money-bill-wave",
        
        # Expenses
        "expenses.Expense": "fas fa-file-invoice-dollar",
        "expenses.ExpenseCategory": "fas fa-list-alt",
    },
    
    # Icons that are used when one is not manually specified
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
    
    #################
    # Related Modal #
    #################
    # Use modals instead of popups
    "related_modal_active": True,

    #############
    # UI Tweaks #
    #############
    # Relative paths to custom CSS/JS scripts (must be present in static files)
    "custom_css": "/css/admin-custom.css",
    "custom_js": "/js/admin-custom.js",
    # Whether to show the UI customizer on the sidebar
    "show_ui_builder": True,

    ###############
    # Change view #
    ###############
    # Render out the change view as a single form, or in tabs
    "changeform_format": "horizontal_tabs",
    # override change forms on a per modeladmin basis
    "changeform_format_overrides": {
        "authmanagement.CustomUser": "carousel", 
        "auth.group": "carousel",
        "employees.employee": "carousel",
        "business.Bussiness": "carousel",
        "payroll.Payroll": "carousel",
    },
    # Add a language dropdown into the admin
    "language_chooser": True,
}