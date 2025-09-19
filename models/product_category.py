from odoo import models, fields

class ProductCategory(models.Model):
    _inherit = 'product.category'

    override_credit_days = fields.Boolean(
        string='Override Credit Days',
        default=False,
        help='Check this box to override automatic payment terms from credit period'
    )