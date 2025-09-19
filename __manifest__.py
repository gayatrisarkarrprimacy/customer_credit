{
    'name': 'Customer Credit Limit',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Credit limit management for customers with Fertilizer and SND categories',
    'description': """
        This module adds credit limit functionality for customers only.
        Features:
        - Credit limits for Fertilizer and SND categories
        - Only available for customers (not vendors)
        - Integration with contact module
    """,
    'author': 'Primacy Infotech Pvt. Ltd.',
    'depends': ['base', 'contacts', 'sale', 'product', 'account', 'pi_ceredit_period'],
    'data': [
        # 'security/security_groups.xml',
        'security/res_groups.xml',
        'security/ir.model.access.csv',
        'views/account_payment_views.xml',
        'views/product_category_views.xml',
        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
        'views/res_users_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
