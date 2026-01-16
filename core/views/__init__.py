# Views Module
# Organized by domain for better maintainability

from .public import landing_page, signup_view
from .dashboard import dashboard
from .products import product_list, product_create, product_edit, product_detail, product_delete
from .movements import create_movement, movement_list, create_movement_mobile
from .imports import import_list, import_create, import_detail, delete_import
from .employees import employee_list, employee_create, employee_detail
from .categories import category_brand_list, category_create, brand_create, category_delete, brand_delete
from .reports import inventory_reports
from .settings import system_settings
from .billing import billing_view, billing_upgrade
from .admin import admin_panel_view, admin_tenant_update
