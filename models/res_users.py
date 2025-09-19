from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    is_sales_person_credit = fields.Boolean(
        string='Sales Person (Credit)',
        help='Check this to allow user to see over credit limit functionality'
    )

    is_accounting_person_credit = fields.Boolean(
        string='Accounting Person (Credit)',
        help='Check this to allow user to see overdue check functionality'
    )