from odoo import models, fields, api
from datetime import date


class ResPartner(models.Model):
    _inherit = 'res.partner'

    total_overdue = fields.Float(
        string='Total Overdue',
        compute='_compute_total_overdue',
        store=False,
        help='Overdue amount from aged receivable (1-30 days only)'
    )

    bypass_approval = fields.Boolean(
        string='Bypass Approval',
        compute='_compute_bypass_approval',
        store=False,
        help='True if overdue is within 1-31 days range - bypass approval'
    )

    @api.depends('name')  # Dummy dependency to trigger computation
    def _compute_total_overdue(self):
        """Compute overdue amount for 1-30 days only - matches aged receivable report"""
        for partner in self:
            partner.total_overdue = 0.0

            if not partner.customer_rank:
                continue

            # Get today's date
            today = date.today()

            # Find all posted customer invoices with remaining amount
            invoices = self.env['account.move'].search([
                ('partner_id', '=', partner.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('amount_residual', '>', 0),
                ('invoice_date_due', '!=', False)
            ])

            overdue_1_30 = 0.0

            for invoice in invoices:
                # Calculate days overdue
                due_date = invoice.invoice_date_due
                if due_date < today:
                    days_overdue = (today - due_date).days

                    # Only 1-30 days overdue amount
                    if 1 <= days_overdue <= 30:
                        overdue_1_30 += invoice.amount_residual

            # Set the total overdue (only 1-30 days)
            partner.total_overdue = overdue_1_30

    @api.depends('name')  # Dummy dependency to trigger computation
    def _compute_bypass_approval(self):
        """Check if all overdue amounts are within 1-31 days - bypass approval"""
        for partner in self:
            partner.bypass_approval = False

            if not partner.customer_rank:
                continue

            # Get today's date
            today = date.today()

            # Find all posted customer invoices with remaining amount
            invoices = self.env['account.move'].search([
                ('partner_id', '=', partner.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('amount_residual', '>', 0),
                ('invoice_date_due', '!=', False)
            ])

            has_overdue_beyond_31_days = False
            has_overdue_within_31_days = False

            for invoice in invoices:
                # Calculate days overdue
                due_date = invoice.invoice_date_due
                if due_date < today:
                    days_overdue = (today - due_date).days

                    if 1 <= days_overdue <= 31:
                        has_overdue_within_31_days = True
                    elif days_overdue > 31:
                        has_overdue_beyond_31_days = True
                        break

            # Bypass approval only if has overdue within 1-31 days and no overdue beyond 31 days
            partner.bypass_approval = has_overdue_within_31_days and not has_overdue_beyond_31_days


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    customer_overdue_amount = fields.Float(
        string='Customer Overdue Amount',
        compute='_compute_customer_overdue',
        store=False
    )

    @api.depends('partner_id')
    def _compute_customer_overdue(self):
        """Use the 1-30 days overdue amount"""
        for order in self:
            overdue_amount = 0.0
            if order.partner_id and order.partner_id.customer_rank:
                # Force computation of overdue amount
                order.partner_id._compute_total_overdue()
                overdue_amount = order.partner_id.total_overdue

            order.customer_overdue_amount = overdue_amount

    def _is_fertilizer_or_snd_category(self):
        """Check if current sale order belongs to fertilizer or SND business unit"""
        if hasattr(self, 'business_unit') and self.business_unit:
            business_unit_name = self.business_unit.name.upper()
            return 'FERTILIZER' in business_unit_name or 'SND' in business_unit_name

        return False

    def check_credit_approval_required(self):
        """Check if any approvals are required - FERTILIZER and SND only"""
        self.ensure_one()
        approval_messages = []

        if not self.partner_id:
            return approval_messages

        # Only process FERTILIZER and SND business units
        if not self.business_unit:
            return approval_messages

        business_unit_name = self.business_unit.name.upper()
        if not ('FERTILIZER' in business_unit_name or 'SND' in business_unit_name):
            return approval_messages

        partner = self.partner_id
        order_amount = self.amount_total

        # Credit limit check (always applies)
        if partner.credit_limit > 0:
            used_credit = partner.credit
            available_credit = partner.credit_limit - used_credit
            if available_credit < order_amount:
                approval_messages.append("Credit limit exceeded - Sales approval required")

        # Overdue check - calculate total overdue from 1-30 and 30-60 days
        today = fields.Date.today()
        all_overdue_invoices = self.env['account.move'].search([
            ('partner_id', '=', partner.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('amount_residual', '>', 0),
            ('invoice_date_due', '!=', False),
            ('invoice_date_due', '<', today)
        ])

        total_overdue_amount = 0.0
        for invoice in all_overdue_invoices:
            days_overdue = (today - invoice.invoice_date_due).days
            # Include both 1-30 days and 30-60 days overdue
            if 1 <= days_overdue <= 60:
                total_overdue_amount += invoice.amount_residual

        if total_overdue_amount > 0:
            # Check the Override Credit Days checkbox from BUSINESS UNIT
            override_credit_days = getattr(self.business_unit, 'override_credit_days', False)

            if override_credit_days:
                # Checkbox CHECKED = need accounting approval
                approval_messages.append("Customer has overdue amount - Accounting approval required")
            # If checkbox UNCHECKED = bypass (no approval needed)

        return approval_messages

    def get_approval_status_message(self):
        """Get formatted approval status message"""
        self.ensure_one()

        partner = self.partner_id
        if not partner:
            return ""

        # Skip status message for non-fertilizer/SND categories
        if not self._is_fertilizer_or_snd_category():
            return "✅ No approval required (Non-FERTILIZER/SND category)"

        # Force computations
        partner._compute_total_overdue()
        partner._compute_bypass_approval()

        # Build status message
        status_lines = []
        status_lines.append("💰 **Credit & Overdue Check Results**")
        status_lines.append(f"Credit Limit: ₹{partner.credit_limit:,.2f}")
        status_lines.append(f"Used: ₹{partner.credit:,.2f}")

        available_credit = partner.credit_limit - partner.credit
        status_lines.append(f"Available: ₹{available_credit:,.2f}")
        status_lines.append(f"Overdue Amount: ₹{partner.total_overdue:,.2f}")
        status_lines.append(f"Order Amount: ₹{self.amount_total:,.2f}")

        # Get approval requirements
        approval_messages = self.check_credit_approval_required()

        if approval_messages:
            status_lines.append("")
            status_lines.append("**Approval Required**")
            for msg in approval_messages:
                status_lines.append(msg)
        else:
            status_lines.append("")
            status_lines.append("✅ No approval required")

            # Show checkbox status for overdue
            if partner.total_overdue > 0:
                override_credit_days = getattr(self.product_category_id, 'override_credit_days', False)
                category_name = self.product_category_id.name.upper()

                if override_credit_days:
                    status_lines.append(
                        f"ℹ️ {category_name} Override Credit Days checkbox is CHECKED - Accounting approval required")
                else:
                    status_lines.append(
                        f"ℹ️ {category_name} Override Credit Days checkbox is UNCHECKED - Accounting approval bypassed")

        return "\n".join(status_lines)

    def action_confirm(self):
        """Override to check approvals before confirmation"""
        for order in self:
            approval_messages = order.check_credit_approval_required()

            if approval_messages:
                # You can customize this behavior:
                # Option 1: Block the confirmation
                # from odoo.exceptions import UserError
                # raise UserError("Approval required:\n" + "\n".join(approval_messages))

                # Option 2: Set order to draft/pending approval state
                # order.state = 'pending_approval'

                # Option 3: Just log and continue (current behavior)
                pass

        return super(SaleOrder, self).action_confirm()


class AccountMove(models.Model):
    _inherit = 'account.move'

    def write(self, vals):
        """Trigger overdue recalculation when invoice changes"""
        result = super(AccountMove, self).write(vals)

        if any(field in vals for field in ['amount_residual', 'payment_state', 'invoice_date_due']):
            partners_to_update = self.mapped('partner_id').filtered('customer_rank')
            for partner in partners_to_update:
                partner.invalidate_recordset(['total_overdue', 'bypass_approval'])

        return result

    def action_post(self):
        """Trigger overdue recalculation when invoice is posted"""
        result = super(AccountMove, self).action_post()

        for invoice in self:
            if invoice.move_type == 'out_invoice' and invoice.partner_id and invoice.partner_id.customer_rank:
                invoice.partner_id.invalidate_recordset(['total_overdue', 'bypass_approval'])

        return result


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        """Update overdue when payment happens"""
        records = super(AccountPartialReconcile, self).create(vals_list)

        customers_to_update = set()
        for reconcile in records:
            if reconcile.debit_move_id and reconcile.credit_move_id:
                for move_line in [reconcile.debit_move_id, reconcile.credit_move_id]:
                    move = move_line.move_id
                    if move.move_type == 'out_invoice' and move.partner_id and move.partner_id.customer_rank:
                        customers_to_update.add(move.partner_id)

        for partner in customers_to_update:
            partner.invalidate_recordset(['total_overdue', 'bypass_approval'])

        return records

    def unlink(self):
        """Update overdue when reconciliation is undone"""
        customers_to_update = set()
        for reconcile in self:
            if reconcile.debit_move_id and reconcile.credit_move_id:
                for move_line in [reconcile.debit_move_id, reconcile.credit_move_id]:
                    move = move_line.move_id
                    if move.move_type == 'out_invoice' and move.partner_id and move.partner_id.customer_rank:
                        customers_to_update.add(move.partner_id)

        result = super(AccountPartialReconcile, self).unlink()

        for partner in customers_to_update:
            partner.invalidate_recordset(['total_overdue', 'bypass_approval'])

        return result
