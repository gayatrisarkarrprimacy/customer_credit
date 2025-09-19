from odoo import models, fields, api


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    product_category_id = fields.Many2one(
        'product.category',
        string='Product Category',
        help='Select the product category for this payment',
        # required=True,
        store=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super(AccountPayment, self).create(vals_list)
        return records

    def action_post(self):
        """When payment is posted - RESTORE CREDIT IMMEDIATELY"""
        result = super(AccountPayment, self).action_post()

        for payment in self:
            if (payment.partner_type == 'customer' and
                    payment.partner_id and
                    payment.product_category_id):
                # SIMPLE: Directly reduce credit used by payment amount
                self._restore_credit_directly(payment)

        return result

    def _restore_credit_directly(self, payment):
        """SIMPLE: Directly restore credit when payment is made"""
        # Find credit line for this customer and category
        credit_line = self.env['res.partner.credit.line'].search([
            ('partner_id', '=', payment.partner_id.id),
            ('product_category_id', '=', payment.product_category_id.id)
        ], limit=1)

        if credit_line:
            # Find the corresponding sale order and invoice
            sale_orders = self.env['sale.order'].search([
                ('partner_id', '=', payment.partner_id.id),
                ('product_category_id', '=', payment.product_category_id.id),
                ('state', 'in', ['sale', 'done'])
            ])

            for order in sale_orders:
                # Find invoice for this order
                invoices = order.invoice_ids.filtered(
                    lambda inv: inv.move_type == 'out_invoice' and inv.state == 'posted'
                )

                for invoice in invoices:
                    if invoice.amount_residual > 0:
                        # DIRECTLY reduce the invoice amount_residual
                        payment_amount = min(payment.amount, invoice.amount_residual)
                        new_residual = invoice.amount_residual - payment_amount

                        # Update invoice residual directly
                        invoice.write({'amount_residual': new_residual})

                        # Force credit refresh
                        credit_line._compute_credit_usage()

                        # Force sale order refresh
                        order._compute_credit_info()

                        break

    def action_cancel(self):
        """When payment is cancelled - restore the credit usage"""
        result = super(AccountPayment, self).action_cancel()

        for payment in self:
            if (payment.partner_type == 'customer' and
                    payment.partner_id and
                    payment.product_category_id):
                # Restore credit usage when payment is cancelled
                self._restore_credit_on_cancel(payment)

        return result

    def _restore_credit_on_cancel(self, payment):
        """Restore credit usage when payment is cancelled"""
        # Find credit line
        credit_line = self.env['res.partner.credit.line'].search([
            ('partner_id', '=', payment.partner_id.id),
            ('product_category_id', '=', payment.product_category_id.id)
        ], limit=1)

        if credit_line:
            # Find sale orders and invoices
            sale_orders = self.env['sale.order'].search([
                ('partner_id', '=', payment.partner_id.id),
                ('product_category_id', '=', payment.product_category_id.id),
                ('state', 'in', ['sale', 'done'])
            ])

            for order in sale_orders:
                invoices = order.invoice_ids.filtered(
                    lambda inv: inv.move_type == 'out_invoice' and inv.state == 'posted'
                )

                for invoice in invoices:
                    # Increase the amount_residual back
                    new_residual = invoice.amount_residual + payment.amount
                    invoice.write({'amount_residual': new_residual})

                    # Force refresh
                    credit_line._compute_credit_usage()
                    order._compute_credit_info()

                    break


class AccountMove(models.Model):
    _inherit = 'account.move'

    product_category_id = fields.Many2one(
        'product.category',
        string='Product Category',
        help='Product category for this invoice',
        store=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super(AccountMove, self).create(vals_list)

        # Auto-populate product category from sales order
        for result in records:
            if result.move_type == 'out_invoice' and result.invoice_origin:
                sale_order = self.env['sale.order'].search([
                    ('name', '=', result.invoice_origin)
                ], limit=1)
                if sale_order and hasattr(sale_order, 'product_category_id') and sale_order.product_category_id:
                    result.product_category_id = sale_order.product_category_id.id

        return records
