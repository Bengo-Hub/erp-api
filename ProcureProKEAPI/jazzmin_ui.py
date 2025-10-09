# Jazzmin UI Configuration for BengoBox ERP

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-primary",
    "accent": "accent-primary",
    "navbar": "navbar-dark",
    "no_navbar_border": False,
    "navbar_fixed": False,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": False,
    "sidebar": "sidebar-dark-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": False,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "theme": "cosmo",
    "dark_mode_theme": None,
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success"
    },
    "actions_sticky_top": False
}

# Additional UI customizations
JAZZMIN_UI_TWEAKS.update({
    # Modern color scheme
    "navbar": "navbar-dark",
    "sidebar": "sidebar-dark-primary",
    "brand_colour": "navbar-primary",
    "accent": "accent-primary",
    
    # Layout improvements
    "navbar_fixed": True,
    "sidebar_fixed": True,
    "footer_fixed": False,
    "layout_boxed": False,
    
    # Typography
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "sidebar_nav_small_text": False,
    
    # Sidebar enhancements
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    
    # Theme
    "theme": "cosmo",
    "dark_mode_theme": None,
    
    # Button styling
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success"
    },
    
    # Actions positioning
    "actions_sticky_top": True,
    
    # Additional modern features
    "show_ui_builder": True,
    "changeform_format": "horizontal_tabs",
    "related_modal_active": True,
    "language_chooser": True,
    
    # Custom CSS classes for modern styling
    "custom_css_classes": {
        "navbar": "navbar-modern",
        "sidebar": "sidebar-modern",
        "content": "content-modern",
        "card": "card-modern",
        "table": "table-modern",
        "form": "form-modern",
        "button": "btn-modern",
    }
})
