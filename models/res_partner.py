from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    license_number = fields.Char(
        string='License Number',
        help='Customer license number'
    )

    license_valid_upto = fields.Date(
        string='License Valid Upto',
        help='License validity date'
    )

    credit_line_ids = fields.One2many(
        'res.partner.credit.line',
        'partner_id',
        string='Credit Lines'
    )


class ResPartnerCreditLine(models.Model):
    _name = 'res.partner.credit.line'
    _description = 'Customer Credit Line'

    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        ondelete='cascade'
    )

    product_category_id = fields.Many2one(
        'product.category',
        string='Category',
        required=True,
        help="Product category from inventory"
    )

    is_infinite_credit = fields.Boolean(
        string='Infinite Credit',
        default=False,
        help="Check this to allow unlimited credit for this category"
    )

    credit_limit = fields.Float(
        string='Credit Limit',
        required=False,
        default=0.0,
        help="Credit limit"
    )

    credit_used = fields.Float(
        string='Credit Used',
        compute='_compute_credit_usage',
        help='Amount of credit used from confirmed orders'
    )

    credit_remaining = fields.Float(
        string='Credit Remaining',
        compute='_compute_credit_usage',
        help='Remaining credit available'
    )

    credit_remaining_display = fields.Char(
        string='Credit Remaining Display',
        compute='_compute_credit_usage',
        help='Remaining credit for display'
    )

    @api.depends('partner_id', 'product_category_id', 'credit_limit', 'is_infinite_credit')
    def _compute_credit_usage(self):
        """Calculate credit - STEP BY STEP METHOD"""
        for line in self:
            credit_used = 0.0

            if line.partner_id and line.product_category_id:
                # STEP 1: Find confirmed orders (when order is confirmed, this shows credit used)
                confirmed_orders = self.env['sale.order'].search([
                    ('partner_id', '=', line.partner_id.id),
                    ('product_category_id', '=', line.product_category_id.id),
                    ('state', 'in', ['sale', 'done'])
                ])

                for order in confirmed_orders:
                    # STEP 2: Check if order has invoices
                    posted_invoices = order.invoice_ids.filtered(
                        lambda inv: inv.move_type == 'out_invoice' and inv.state == 'posted'
                    )

                    if posted_invoices:
                        # STEP 3: For invoiced orders, use amount_residual (reduces when payment made)
                        for invoice in posted_invoices:
                            credit_used += invoice.amount_residual
                    else:
                        # STEP 4: For confirmed but not invoiced orders, use full amount
                        credit_used += order.amount_total

            line.credit_used = credit_used

            # Calculate remaining credit
            if line.is_infinite_credit:
                line.credit_remaining = float('inf')
                line.credit_remaining_display = '∞'
            else:
                line.credit_remaining = line.credit_limit - credit_used
                line.credit_remaining_display = f"{line.credit_remaining:,.2f}"

    @api.constrains('credit_limit', 'is_infinite_credit')
    def _check_credit_limit(self):
        for record in self:
            if not record.is_infinite_credit:
                if record.credit_limit < 0:
                    raise ValidationError(_("Credit limit cannot be negative."))

    @api.constrains('partner_id', 'product_category_id')
    def _check_unique_category(self):
        for record in self:
            existing = self.search([
                ('partner_id', '=', record.partner_id.id),
                ('product_category_id', '=', record.product_category_id.id),
                ('id', '!=', record.id)
            ])
            if existing:
                raise ValidationError(_("Credit line for this category already exists."))

    @api.onchange('is_infinite_credit')
    def _onchange_is_infinite_credit(self):
        if self.is_infinite_credit:
            self.credit_limit = 0.0

    def force_refresh_credit(self):
        """Method to force refresh credit calculation"""
        self._compute_credit_usage()
        return True

