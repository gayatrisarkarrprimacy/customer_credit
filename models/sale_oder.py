from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import json


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Make partner_id required
    partner_id = fields.Many2one(
        'res.partner',
        required=True,
        string='Customer',
        # ... keep all other existing attributes
    )

    # Make business_unit required
    business_unit = fields.Many2one(
        required=True,
        # ... keep all other existing attributes
    )

    product_category_id = fields.Many2one(
        'product.category',
        string='Product Category',
        help='Select child category under the business unit',
        domain="[('parent_id', '=', business_unit)]",
        required=True

    )

    # Make payment_term_id required
    payment_term_id = fields.Many2one(
        'account.payment.term',
        required=True,
        # ... keep all other existing attributes
    )

    # Hidden storage fields
    snd_products_json = fields.Text(
        string='SND Products Storage',
        default='[]'
    )

    fertilizer_products_json = fields.Text(
        string='Fertilizer Products Storage',
        default='[]'
    )

    # Credit control fields
    credit_checked = fields.Boolean(
        string='Credit Checked',
        default=False,
        help='Indicates if credit limit has been checked'
    )

    credit_exceeded = fields.Boolean(
        string='Credit Exceeded',
        default=False,
        help='Indicates if credit limit has been exceeded'
    )

    # Credit Override fields
    credit_override_requested = fields.Boolean(
        string='Credit Override Requested',
        default=False,
        help='User has requested credit limit override'
    )

    credit_override_approved = fields.Boolean(
        string='Credit Override Approved',
        default=False,
        help='Administrator has approved credit limit override'
    )

    # NEW OVERDUE CHECK FIELDS
    overdue_checked = fields.Boolean(
        string='Overdue Checked',
        default=False,
        help='Indicates if overdue amount has been checked'
    )

    has_overdue = fields.Boolean(
        string='Has Overdue',
        default=False,
        help='Customer has overdue amount greater than 0'
    )

    overdue_check_requested = fields.Boolean(
        string='Overdue Check Requested',
        default=False,
        help='Sales person has requested overdue check from accounting'
    )

    overdue_check_approved = fields.Boolean(
        string='Overdue Check Approved',
        default=False,
        help='Accounting person has approved overdue check'
    )

    customer_overdue_amount = fields.Float(
        string='Customer Overdue Amount',
        compute='_compute_customer_overdue',
        help='Total overdue amount for customer'
    )

    # Button visibility fields - COMPUTED FIELDS
    show_check_credit_button = fields.Boolean(
        string='Show Check Credit Button',
        compute='_compute_button_visibility'
    )

    show_credit_override_button = fields.Boolean(
        string='Show Credit Override Button (Sales)',
        compute='_compute_button_visibility'
    )

    show_overdue_check_button = fields.Boolean(
        string='Show Overdue Check Button (Accounting)',
        compute='_compute_button_visibility'
    )

    show_confirm_button = fields.Boolean(
        string='Show Confirm Button',
        compute='_compute_button_visibility'
    )

    # Credit limit information fields
    assigned_limit = fields.Float(
        string='Assigned Limit',
        compute='_compute_credit_info',
        help='Credit limit assigned to customer for selected category'
    )

    limit_used = fields.Float(
        string='Limit Used',
        compute='_compute_credit_info',
        help='Amount of credit used from confirmed sales orders'
    )

    limit_remaining = fields.Float(
        string='Limit Remaining',
        compute='_compute_credit_info',
        help='Remaining credit available for customer'
    )

    credit_info_visible = fields.Boolean(
        string='Show Credit Info',
        compute='_compute_credit_info_visible'
    )

    @api.depends('partner_id')
    def _compute_customer_overdue(self):
        """Compute customer's total overdue amount"""
        for order in self:
            overdue_amount = 0.0
            if order.partner_id:
                # Get partner's total_overdue field (assuming it exists in res.partner)
                if hasattr(order.partner_id, 'total_overdue'):
                    overdue_amount = order.partner_id.total_overdue
                else:
                    # Fallback: Calculate overdue from invoices
                    overdue_invoices = self.env['account.move'].search([
                        ('partner_id', '=', order.partner_id.id),
                        ('move_type', '=', 'out_invoice'),
                        ('state', '=', 'posted'),
                        ('amount_residual', '>', 0),
                        ('invoice_date_due', '<', fields.Date.today())
                    ])
                    overdue_amount = sum(overdue_invoices.mapped('amount_residual'))

            order.customer_overdue_amount = overdue_amount

    @api.depends('credit_checked', 'credit_exceeded', 'credit_override_approved', 'has_overdue',
                 'overdue_check_approved', 'state', 'partner_id', 'product_category_id', 'order_line')
    def _compute_button_visibility(self):
        """Compute button visibility based on current state and user permissions"""
        for order in self:
            # Reset all buttons
            show_check_credit = False
            show_credit_override = False
            show_overdue_check = False
            show_confirm = False

            if order.state == 'draft':
                # Get current user permissions
                current_user = self.env.user
                is_sales_person = current_user.is_sales_person_credit
                is_accounting_person = current_user.is_accounting_person_credit

                # Step 1: Show Check Credit button when order is ready but credit not checked
                if (order.partner_id and order.product_category_id and
                        order.order_line and not order.credit_checked):
                    show_check_credit = True

                # Step 2: After credit check - determine next action based on user role
                elif order.credit_checked:

                    # Case A: Credit exceeded - show override button for sales person, nothing for others
                    if order.credit_exceeded and not order.credit_override_approved:
                        if is_sales_person:
                            show_credit_override = True
                        # For non-sales persons, don't show any button if credit exceeded

                    # Case B: Credit OK but has overdue - show overdue check ONLY for accounting person
                    elif not order.credit_exceeded and order.has_overdue and not order.overdue_check_approved:
                        if is_accounting_person:
                            show_overdue_check = True
                        # For non-accounting persons, don't show any button if overdue exists

                    # Case C: Both credit exceeded AND has overdue
                    elif order.credit_exceeded and order.has_overdue:
                        # Priority 1: Credit override needed first (sales person only)
                        if not order.credit_override_approved:
                            if is_sales_person:
                                show_credit_override = True
                        # Priority 2: After credit override, overdue check needed (accounting person only)
                        elif order.credit_override_approved and not order.overdue_check_approved:
                            if is_accounting_person:
                                show_overdue_check = True
                        # Priority 3: Both approvals done - show confirm
                        elif order.credit_override_approved and order.overdue_check_approved:
                            show_confirm = True

                    # Case D: No issues OR all approvals done - show confirm
                    elif ((not order.credit_exceeded or order.credit_override_approved) and
                          (not order.has_overdue or order.overdue_check_approved)):
                        show_confirm = True

            # Set the computed values
            order.show_check_credit_button = show_check_credit
            order.show_credit_override_button = show_credit_override
            order.show_overdue_check_button = show_overdue_check
            order.show_confirm_button = show_confirm

    # In your sale_order.py file, update the action_check_credit_limit method:

    def action_check_credit_limit(self):
        """Check credit limit and overdue amount with checkbox control"""
        self.ensure_one()

        if not self.partner_id or not self.product_category_id:
            raise ValidationError("Please select customer and product category first.")
        if not self.order_line:
            raise ValidationError("Please add at least one product line.")

        # Compute credit info
        self._compute_credit_info()

        # Check credit line exists
        credit_line = self.env['res.partner.credit.line'].search([
            ('partner_id', '=', self.partner_id.id),
            ('product_category_id', '=', self.product_category_id.id)
        ], limit=1)

        if not credit_line:
            raise ValidationError(
                f"No credit limit found for customer '{self.partner_id.name}' "
                f"and category '{self.product_category_id.name}'.\n\n"
                f"Please set up credit limit in customer form first."
            )

        # Reset all flags
        self.credit_checked = True
        self.credit_override_requested = False
        self.credit_override_approved = False
        self.overdue_check_requested = False
        self.overdue_check_approved = False

        # Check credit limit
        if self.limit_remaining != float('inf') and self.limit_remaining < self.amount_total:
            self.credit_exceeded = True
        else:
            self.credit_exceeded = False

        # Calculate overdue amount
        today = fields.Date.today()
        all_overdue_invoices = self.env['account.move'].search([
            ('partner_id', '=', self.partner_id.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('amount_residual', '>', 0),
            ('invoice_date_due', '!=', False),
            ('invoice_date_due', '<', today)
        ])

        total_overdue_amount = sum(all_overdue_invoices.mapped('amount_residual'))
        self.customer_overdue_amount = total_overdue_amount

        # Initialize has_overdue
        self.has_overdue = False

        # Check overdue logic ONLY for business units with FERTILIZER or SND
        if total_overdue_amount > 0 and self.business_unit:
            business_unit_name = self.business_unit.name.upper()

            # Only apply checkbox logic for FERTILISER/FERTILIZER and SND
            if 'FERTILISER' in business_unit_name or 'FERTILIZER' in business_unit_name or 'SND' in business_unit_name:
                # Try to get the checkbox value
                try:
                    checkbox_value = self.business_unit.override_credit_days

                    if checkbox_value:
                        # CHECKED = Need accounting approval
                        self.has_overdue = True
                        # message = f"Override Credit Days CHECKED on '{self.business_unit.name}' - Accounting approval REQUIRED"
                        message = "Override period exiciding period days - Accounting approval REQUIRED"
                    else:
                        # UNCHECKED = Bypass accounting approval
                        self.has_overdue = False
                        message = f"Override Credit Days UNCHECKED on '{self.business_unit.name}' - Accounting approval BYPASSED"

                except AttributeError:
                    # Field doesn't exist - default behavior
                    self.has_overdue = True
                    message = f"Override Credit Days field not found - Accounting approval required by default"
            else:
                # Other business units - always require approval if overdue
                self.has_overdue = True
                message = f"Business unit '{self.business_unit.name}' - Accounting approval required"
        else:
            message = "No overdue amount found"

        # Build status message
        credit_text = f"Credit Limit: {'Unlimited' if self.assigned_limit == float('inf') else f'₹{self.assigned_limit:,.2f}'}"
        used_text = f"Used: ₹{self.limit_used:,.2f}"
        remaining_text = f"Available: {'Unlimited' if self.limit_remaining == float('inf') else f'₹{self.limit_remaining:,.2f}'}"
        overdue_text = f"Overdue Amount: ₹{self.customer_overdue_amount:,.2f}"

        status_message = f"Credit & Overdue Check Results\n\n{credit_text}\n{used_text}\n{remaining_text}\n{overdue_text}\n\nOrder Amount: ₹{self.amount_total:,.2f}\n\n"

        if self.credit_exceeded:
            status_message += "Credit limit exceeded - Sales approval required\n\n"

        if total_overdue_amount > 0:
            status_message += message

        if not self.credit_exceeded and not self.has_overdue:
            status_message += "All checks passed - Ready to confirm"

        # Post to chatter
        self.message_post(
            body=status_message,
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

        # Return notification
        if self.credit_exceeded or self.has_overdue:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Approval Required' if (self.credit_exceeded or self.has_overdue) else 'Checks Bypassed',
                    'message': status_message,
                    'type': 'warning' if (self.credit_exceeded or self.has_overdue) else 'success',
                    'sticky': True
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
                'params': {
                    'title': 'All Checks Passed',
                    'message': 'Credit and overdue checks completed successfully.',
                    'type': 'success',
                }
            }
        # Prepare notification messages
        credit_text = f"Credit Limit: {'Unlimited' if self.assigned_limit == float('inf') else f'₹{self.assigned_limit:,.2f}'}"
        used_text = f"Used: ₹{self.limit_used:,.2f}"
        remaining_text = f"Available: {'Unlimited' if self.limit_remaining == float('inf') else f'₹{self.limit_remaining:,.2f}'}"
        overdue_text = f"Overdue Amount: ₹{self.customer_overdue_amount:,.2f}"

        # Post message to chatter
        status_message = f"💰 **Credit & Overdue Check Results**\n\n{credit_text}\n{used_text}\n{remaining_text}\n{overdue_text}\n\nOrder Amount: ₹{self.amount_total:,.2f}"

        if self.credit_exceeded:
            status_message += "\n\n⚠️ Credit limit exceeded - Sales approval required"

        # Show bypass message
        if total_overdue_amount > 0:
            if bypass_approval:
                status_message += f"\n\n✅ {bypass_message}"
            else:
                status_message += f"\n\n⚠️ {bypass_message}"

        if not self.credit_exceeded and not self.has_overdue:
            status_message += "\n\n✅ All checks passed - Ready to confirm"

        self.message_post(
            body=status_message,
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

        # Return appropriate notification
        if self.credit_exceeded or self.has_overdue:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Approval Required',
                    'message': f"{status_message}",
                    'type': 'warning',
                    'sticky': True
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
                'params': {
                    'title': 'All Checks Passed',
                    'message': 'Credit limit and overdue checks completed successfully.',
                    'type': 'success',
                }
            }

    # @api.depends('credit_checked', 'credit_exceeded', 'credit_override_approved', 'has_overdue',
    #              'overdue_check_approved', 'state', 'partner_id', 'product_category_id', 'order_line')
    # def _compute_button_visibility(self):
    #     """Compute button visibility based on current state and user permissions"""
    #     for order in self:
    #         # Reset all buttons
    #         show_check_credit = False
    #         show_credit_override = False
    #         show_overdue_check = False
    #         show_confirm = False
    #
    #         if order.state == 'draft':
    #             # Get current user permissions
    #             current_user = self.env.user
    #             is_sales_person = current_user.is_sales_person_credit
    #             is_accounting_person = current_user.is_accounting_person_credit
    #
    #             # Step 1: Show Check Credit button when order is ready but credit not checked
    #             if (order.partner_id and order.product_category_id and
    #                     order.order_line and not order.credit_checked):
    #                 show_check_credit = True
    #
    #             # Step 2: After credit check - determine next action based on user role
    #             elif order.credit_checked:
    #
    #                 # Case A: Credit exceeded - show override button for sales person, nothing for others
    #                 if order.credit_exceeded and not order.credit_override_approved:
    #                     if is_sales_person:
    #                         show_credit_override = True
    #                     # For non-sales persons, don't show any button if credit exceeded
    #
    #                 # Case B: Credit OK but has overdue - show overdue check ONLY for accounting person
    #                 elif not order.credit_exceeded and order.has_overdue and not order.overdue_check_approved:
    #                     if is_accounting_person:
    #                         show_overdue_check = True
    #                     # For non-accounting persons, don't show any button if overdue exists
    #
    #                 # Case C: Both credit exceeded AND has overdue
    #                 elif order.credit_exceeded and order.has_overdue:
    #                     # Priority 1: Credit override needed first (sales person only)
    #                     if not order.credit_override_approved:
    #                         if is_sales_person:
    #                             show_credit_override = True
    #                     # Priority 2: After credit override, overdue check needed (accounting person only)
    #                     elif order.credit_override_approved and not order.overdue_check_approved:
    #                         if is_accounting_person:
    #                             show_overdue_check = True
    #                     # Priority 3: Both approvals done - show confirm
    #                     elif order.credit_override_approved and order.overdue_check_approved:
    #                         show_confirm = True
    #
    #                 # Case D: No issues OR all approvals done - show confirm
    #                 elif ((not order.credit_exceeded or order.credit_override_approved) and
    #                       (not order.has_overdue or order.overdue_check_approved)):
    #                     show_confirm = True
    #
    #         # Set the computed values
    #         order.show_check_credit_button = show_check_credit
    #         order.show_credit_override_button = show_credit_override
    #         order.show_overdue_check_button = show_overdue_check
    #         order.show_confirm_button = show_confirm
    #
    # def action_check_credit_limit(self):
    #     """Check credit limit and overdue amount with 1-31 days bypass"""
    #     self.ensure_one()
    #
    #     if not self.partner_id or not self.product_category_id:
    #         raise ValidationError("Please select customer and product category first.")
    #     if not self.order_line:
    #         raise ValidationError("Please add at least one product line.")
    #
    #     # Compute credit info
    #     self._compute_credit_info()
    #
    #     # Check credit line exists
    #     credit_line = self.env['res.partner.credit.line'].search([
    #         ('partner_id', '=', self.partner_id.id),
    #         ('product_category_id', '=', self.product_category_id.id)
    #     ], limit=1)
    #
    #     if not credit_line:
    #         raise ValidationError(
    #             f"No credit limit found for customer '{self.partner_id.name}' "
    #             f"and category '{self.product_category_id.name}'.\n\n"
    #             f"Please set up credit limit in customer form first."
    #         )
    #
    #     # Mark as checked and reset override flags
    #     self.credit_checked = True
    #     self.credit_override_requested = False
    #     self.credit_override_approved = False
    #     self.overdue_check_requested = False
    #     self.overdue_check_approved = False
    #
    #     # Check credit limit
    #     if self.limit_remaining != float('inf') and self.limit_remaining < self.amount_total:
    #         self.credit_exceeded = True
    #     else:
    #         self.credit_exceeded = False
    #
    #     # CALCULATE TOTAL OVERDUE AMOUNT AND CHECK BYPASS (ANY 1-31 days = bypass)
    #     today = fields.Date.today()
    #
    #     # Find ALL overdue invoices
    #     all_overdue_invoices = self.env['account.move'].search([
    #         ('partner_id', '=', self.partner_id.id),
    #         ('move_type', '=', 'out_invoice'),
    #         ('state', '=', 'posted'),
    #         ('amount_residual', '>', 0),
    #         ('invoice_date_due', '!=', False),
    #         ('invoice_date_due', '<', today)
    #     ])
    #
    #     # Calculate total overdue amount from all overdue invoices
    #     total_overdue_amount = sum(all_overdue_invoices.mapped('amount_residual'))
    #     self.customer_overdue_amount = total_overdue_amount
    #
    #     # Check bypass logic - bypass if ANY amount is in 1-31 days
    #     if total_overdue_amount > 0:
    #         has_amount_within_31_days = False
    #         for invoice in all_overdue_invoices:
    #             days_overdue = (today - invoice.invoice_date_due).days
    #             if 1 <= days_overdue <= 31:
    #                 has_amount_within_31_days = True
    #                 break  # Found at least one invoice within 1-31 days, so bypass
    #
    #         # Bypass if ANY amount is within 1-31 days
    #         bypass_approval = has_amount_within_31_days
    #         self.has_overdue = not bypass_approval  # Only require approval if no bypass
    #     else:
    #         self.has_overdue = False
    #         bypass_approval = False
    #
    #     # Prepare notification messages
    #     credit_text = f"Credit Limit: {'Unlimited' if self.assigned_limit == float('inf') else f'₹{self.assigned_limit:,.2f}'}"
    #     used_text = f"Used: ₹{self.limit_used:,.2f}"
    #     remaining_text = f"Available: {'Unlimited' if self.limit_remaining == float('inf') else f'₹{self.limit_remaining:,.2f}'}"
    #     overdue_text = f"Overdue Amount: ₹{self.customer_overdue_amount:,.2f}"
    #
    #     # Post message to chatter
    #     status_message = f"💰 **Credit & Overdue Check Results**\n\n{credit_text}\n{used_text}\n{remaining_text}\n{overdue_text}\n\nOrder Amount: ₹{self.amount_total:,.2f}"
    #
    #     if self.credit_exceeded:
    #         status_message += "\n\n⚠️ Credit limit exceeded - Sales approval required"
    #
    #     # Show bypass message
    #     if total_overdue_amount > 0:
    #         if bypass_approval:
    #             status_message += "\n\n✅ Customer has overdue amount within 1-31 days - Accounting approval bypassed"
    #         else:
    #             status_message += "\n\n⚠️ Customer has overdue amount with no amounts in 1-31 days range - Accounting approval required"
    #
    #     if not self.credit_exceeded and not self.has_overdue:
    #         status_message += "\n\n✅ All checks passed - Ready to confirm"
    #
    #     self.message_post(
    #         body=status_message,
    #         message_type='notification',
    #         subtype_xmlid='mail.mt_note'
    #     )
    #
    #     # Return appropriate notification
    #     if self.credit_exceeded or self.has_overdue:
    #         return {
    #             'type': 'ir.actions.client',
    #             'tag': 'display_notification',
    #             'params': {
    #                 'title': 'Approval Required',
    #                 'message': f"{status_message}",
    #                 'type': 'warning',
    #                 'sticky': True
    #             }
    #         }
    #     else:
    #         return {
    #             'type': 'ir.actions.client',
    #             'tag': 'reload',
    #             'params': {
    #                 'title': 'All Checks Passed',
    #                 'message': 'Credit limit and overdue checks completed successfully.',
    #                 'type': 'success',
    #             }
    #         }

    # def action_check_credit_limit(self):

    #     """Check credit limit and overdue amount"""
    #     self.ensure_one()
    #
    #     if not self.partner_id or not self.product_category_id:
    #         raise ValidationError("Please select customer and product category first.")
    #     if not self.order_line:
    #         raise ValidationError("Please add at least one product line.")
    #
    #     # Compute credit info
    #     self._compute_credit_info()
    #     self._compute_customer_overdue()
    #
    #     # Check credit line exists
    #     credit_line = self.env['res.partner.credit.line'].search([
    #         ('partner_id', '=', self.partner_id.id),
    #         ('product_category_id', '=', self.product_category_id.id)
    #     ], limit=1)
    #
    #     if not credit_line:
    #         raise ValidationError(
    #             f"No credit limit found for customer '{self.partner_id.name}' "
    #             f"and category '{self.product_category_id.name}'.\n\n"
    #             f"Please set up credit limit in customer form first."
    #         )
    #
    #     # Mark as checked and reset override flags
    #     self.credit_checked = True
    #     self.credit_override_requested = False
    #     self.credit_override_approved = False
    #     self.overdue_check_requested = False
    #     self.overdue_check_approved = False
    #
    #     # Check credit limit
    #     if self.limit_remaining != float('inf') and self.limit_remaining < self.amount_total:
    #         self.credit_exceeded = True
    #     else:
    #         self.credit_exceeded = False
    #
    #     # Check overdue amount
    #     if self.customer_overdue_amount > 0:
    #         self.has_overdue = True
    #     else:
    #         self.has_overdue = False
    #
    #     # Prepare notification messages
    #     credit_text = f"Credit Limit: {'Unlimited' if self.assigned_limit == float('inf') else f'₹{self.assigned_limit:,.2f}'}"
    #     used_text = f"Used: ₹{self.limit_used:,.2f}"
    #     remaining_text = f"Available: {'Unlimited' if self.limit_remaining == float('inf') else f'₹{self.limit_remaining:,.2f}'}"
    #     overdue_text = f"Overdue Amount: ₹{self.customer_overdue_amount:,.2f}"
    #
    #     # Post message to chatter
    #     status_message = f"💰 **Credit & Overdue Check Results**\n\n{credit_text}\n{used_text}\n{remaining_text}\n{overdue_text}\n\nOrder Amount: ₹{self.amount_total:,.2f}"
    #
    #     if self.credit_exceeded:
    #         status_message += "\n\n⚠️ Credit limit exceeded - Sales approval required"
    #     if self.has_overdue:
    #         status_message += "\n\n⚠️ Customer has overdue amount - Accounting approval required"
    #     if not self.credit_exceeded and not self.has_overdue:
    #         status_message += "\n\n✅ All checks passed - Ready to confirm"
    #
    #     self.message_post(
    #         body=status_message,
    #         message_type='notification',
    #         subtype_xmlid='mail.mt_note'
    #     )
    #
    #     # Return appropriate notification
    #     if self.credit_exceeded or self.has_overdue:
    #         return {
    #             'type': 'ir.actions.client',
    #             'tag': 'display_notification',
    #             'params': {
    #                 'title': 'Approval Required',
    #                 'message': f"{status_message}",
    #                 'type': 'warning',
    #                 'sticky': True
    #             }
    #         }
    #     else:
    #         return {
    #             'type': 'ir.actions.client',
    #             'tag': 'reload',
    #             'params': {
    #                 'title': 'All Checks Passed',
    #                 'message': 'Credit limit and overdue checks completed successfully.',
    #                 'type': 'success',
    #             }
    #         }

    def action_approve_credit_override(self):
        """Sales person approves credit limit override"""
        self.ensure_one()

        # Check if user has sales person credit rights
        if not self.env.user.is_sales_person_credit:
            raise ValidationError("Only sales persons with credit rights can override credit limits.")

        if not self.credit_exceeded:
            raise ValidationError("Credit override is only available when credit limit is exceeded.")

        # Mark as override approved
        self.credit_override_approved = True

        # Post message to chatter
        sales_person = self.env.user.name
        self.message_post(
            body=f"✅ Credit limit overridden by Sales Person: {sales_person}",
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
            'params': {
                'title': 'Credit Override Approved',
                'message': f'✅ Credit limit overridden by {sales_person}',
                'type': 'success',
            }
        }

    def action_approve_overdue_check(self):
        """Accounting person approves overdue check"""
        self.ensure_one()

        # Check if user has accounting person credit rights
        if not self.env.user.is_accounting_person_credit:
            raise ValidationError("Only accounting persons can approve overdue checks.")

        if not self.has_overdue:
            raise ValidationError("Overdue check is only available when customer has overdue amount.")

        # Mark as overdue check approved
        self.overdue_check_approved = True

        # Post message to chatter
        accounting_person = self.env.user.name
        self.message_post(
            body=f"✅ Overdue amount approved by Accounting Person: {accounting_person}. Overdue Amount: ₹{self.customer_overdue_amount:,.2f}",
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
            'params': {
                'title': 'Overdue Check Approved',
                'message': f'✅ Overdue amount approved by {accounting_person}',
                'type': 'success',
            }
        }

    def update_button_visibility(self):
        """Public method to force refresh button visibility - can be called from button"""
        self._compute_button_visibility()
        return True

    @api.onchange('business_unit')
    def _onchange_business_unit(self):
        """Clear product category when business unit changes"""
        if self.business_unit:
            self.product_category_id = False
            # Reset all checks
            self.credit_checked = False
            self.credit_override_approved = False
            self.overdue_check_approved = False

    @api.onchange('partner_id')
    def _onchange_partner_license_check(self):
        """Check license when customer is selected"""
        # Reset all checks when customer changes
        self.credit_checked = False
        self.credit_override_approved = False
        self.overdue_check_approved = False

        if self.partner_id and self.partner_id.customer_rank > 0:
            error_messages = []

            if not self.partner_id.license_number:
                error_messages.append("License Number field is empty")

            if not self.partner_id.license_valid_upto:
                error_messages.append("License Valid Date field is empty")
            else:
                from datetime import date
                today = date.today()
                if self.partner_id.license_valid_upto < today:
                    error_messages.append(
                        f"License has expired on {self.partner_id.license_valid_upto.strftime('%d/%m/%Y')}. Current date is {today.strftime('%d/%m/%Y')}")

            if error_messages:
                self.partner_id = False
                return {
                    'warning': {
                        'title': 'Cannot Select Customer - License Issues',
                        'message': f"Customer has license issues:\n" +
                                   "\n".join(f"• {msg}" for msg in error_messages) +
                                   "\n\nPlease update the customer's license information before selecting."
                    }
                }

    @api.onchange('product_category_id')
    def _onchange_product_category(self):
        """Switch between SND and Fertilizer products and auto-fill payment terms"""
        # Reset all checks when category changes
        self.credit_checked = False
        self.credit_override_approved = False
        self.overdue_check_approved = False

        if self.product_category_id:
            self._save_current_lines()
            self.order_line = [(5, 0, 0)]
            self._load_saved_lines()
            self._compute_credit_info()
            self._compute_credit_info_visible()
            self._auto_fill_payment_terms()

    def _auto_fill_payment_terms(self):
        """Auto-fill payment terms based on credit period configuration"""
        if not self.product_category_id or not self.partner_id:
            return

        customer_state = None
        if self.partner_id.state_id:
            customer_state = self.partner_id.state_id
        elif self.partner_id.parent_id and self.partner_id.parent_id.state_id:
            customer_state = self.partner_id.parent_id.state_id

        if not customer_state:
            return

        credit_period = self.env['credit.period'].search([
            ('category_id', '=', self.product_category_id.id),
            ('state_id', '=', customer_state.id)
        ], limit=1)

        if credit_period and credit_period.credit_days:
            self.payment_term_id = credit_period.credit_days

    @api.onchange('order_line')
    def _onchange_order_line(self):
        """Reset checks when order lines change"""
        if self.order_line:
            self.credit_checked = False
            self.credit_override_approved = False
            self.overdue_check_approved = False

    def _save_current_lines(self):
        """Save current order lines to storage"""
        if not self.order_line:
            return

        lines_data = []
        for line in self.order_line:
            if line.product_id:
                line_data = {
                    'product_id': line.product_id.id,
                    'qty': line.product_uom_qty,
                    'price': line.price_unit,
                    'name': line.name
                }
                lines_data.append(line_data)

        if lines_data:
            first_product = self.order_line[0].product_id
            if first_product and first_product.categ_id:
                category_name = first_product.categ_id.name.upper()
                if 'SND' in category_name:
                    self.snd_products_json = json.dumps(lines_data)
                elif 'FERTILIZER' in category_name:
                    self.fertilizer_products_json = json.dumps(lines_data)

    def _load_saved_lines(self):
        """Load saved lines for selected category"""
        if not self.product_category_id:
            return

        category_name = self.product_category_id.name.upper()
        stored_data = None

        try:
            if 'SND' in category_name and self.snd_products_json:
                stored_data = json.loads(self.snd_products_json)
            elif 'FERTILIZER' in category_name and self.fertilizer_products_json:
                stored_data = json.loads(self.fertilizer_products_json)
        except:
            stored_data = None

        if stored_data:
            new_lines = []
            for line_data in stored_data:
                vals = {
                    'product_id': line_data.get('product_id'),
                    'product_uom_qty': line_data.get('qty', 1.0),
                    'price_unit': line_data.get('price', 0.0),
                    'name': line_data.get('name', '')
                }
                new_lines.append((0, 0, vals))
            if new_lines:
                self.order_line = new_lines

    @api.depends('partner_id', 'product_category_id', 'state', 'amount_total')
    def _compute_credit_info(self):
        """Compute credit info - STEP BY STEP"""
        for order in self:
            assigned_limit = 0.0
            limit_used = 0.0
            limit_remaining = 0.0

            if order.partner_id and order.product_category_id:
                credit_line = self.env['res.partner.credit.line'].search([
                    ('partner_id', '=', order.partner_id.id),
                    ('product_category_id', '=', order.product_category_id.id)
                ], limit=1)

                if credit_line:
                    credit_line._compute_credit_usage()
                    if credit_line.is_infinite_credit:
                        assigned_limit = float('inf')
                        limit_used = credit_line.credit_used
                        limit_remaining = float('inf')
                    else:
                        assigned_limit = credit_line.credit_limit
                        limit_used = credit_line.credit_used
                        limit_remaining = credit_line.credit_remaining

            order.assigned_limit = assigned_limit
            order.limit_used = limit_used
            order.limit_remaining = limit_remaining

    @api.depends('partner_id', 'product_category_id', 'credit_checked')
    def _compute_credit_info_visible(self):
        """Control when to show credit information fields"""
        for order in self:
            order.credit_info_visible = bool(order.partner_id and order.product_category_id and order.credit_checked)

    def _check_customer_license(self, partner):
        """Check if customer has license information filled and not expired"""
        if partner and partner.customer_rank > 0:
            error_messages = []

            if not partner.license_number:
                error_messages.append("License Number field is empty")

            if not partner.license_valid_upto:
                error_messages.append("License Valid Date field is empty")
            else:
                from datetime import date
                today = date.today()
                if partner.license_valid_upto < today:
                    error_messages.append(
                        f"License has expired on {partner.license_valid_upto.strftime('%d/%m/%Y')}. Current date is {today.strftime('%d/%m/%Y')}")

            if error_messages:
                raise ValidationError(
                    f"Customer '{partner.name}' has license issues:\n" +
                    "\n".join(f"• {msg}" for msg in error_messages) +
                    "\n\nPlease update the customer's license information before saving the sales order."
                )

    @api.model
    def create(self, vals):
        """Check license when creating sales order"""
        # Check license only
        if 'partner_id' in vals:
            partner = self.env['res.partner'].browse(vals['partner_id'])
            self._check_customer_license(partner)

        return super(SaleOrder, self).create(vals)

    def write(self, vals):
        """Save lines when order is saved and check license validation"""
        # Reset checks if critical fields change
        if any(field in vals for field in ['partner_id', 'product_category_id', 'order_line']):
            vals.update({
                'credit_checked': False,
                'credit_override_approved': False,
                'overdue_check_approved': False,
            })

        # Check license fields before saving
        if 'partner_id' in vals or 'order_line' in vals:
            for order in self:
                partner = self.env['res.partner'].browse(
                    vals.get('partner_id')) if 'partner_id' in vals else order.partner_id
                self._check_customer_license(partner)

        result = super(SaleOrder, self).write(vals)

        # Save lines after write
        for order in self:
            if 'order_line' in vals:
                order._save_current_lines()

        return result

    def action_confirm(self):
        """When order is confirmed - check all validations"""
        # Check if credit has been verified
        if not self.credit_checked:
            raise ValidationError("Please check credit limit before confirming the order.")

        # Check credit limit approval
        if self.credit_exceeded and not self.credit_override_approved:
            raise ValidationError("Credit limit exceeded. Sales person approval required before confirmation.")

        # Check overdue approval
        if self.has_overdue and not self.overdue_check_approved:
            raise ValidationError(
                "Customer has overdue amount. Accounting person approval required before confirmation.")

        # Check license before confirming
        self._check_customer_license(self.partner_id)

        result = super(SaleOrder, self).action_confirm()

        # Post confirmation message
        confirmation_msg = "✅ Order confirmed"
        if self.credit_exceeded and self.credit_override_approved:
            confirmation_msg += " with credit override approval"
        if self.has_overdue and self.overdue_check_approved:
            confirmation_msg += " with overdue approval"
        confirmation_msg += "."

        self.message_post(
            body=confirmation_msg,
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

        # Force refresh credit to show deduction immediately
        if self.partner_id and self.product_category_id:
            credit_line = self.env['res.partner.credit.line'].search([
                ('partner_id', '=', self.partner_id.id),
                ('product_category_id', '=', self.product_category_id.id)
            ], limit=1)
            if credit_line:
                credit_line.force_refresh_credit()

        return result

    def action_cancel(self):
        """When order is cancelled - credit should be restored"""
        result = super(SaleOrder, self).action_cancel()

        # Force refresh credit to show restoration
        if self.partner_id and self.product_category_id:
            credit_line = self.env['res.partner.credit.line'].search([
                ('partner_id', '=', self.partner_id.id),
                ('product_category_id', '=', self.product_category_id.id)
            ], limit=1)
            if credit_line:
                credit_line.force_refresh_credit()

        return result


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.onchange('product_id')
    def _onchange_product_id_validation(self):
        """Show validation when user tries to select a product"""
        if self.order_id:
            missing_fields = []

            if not self.order_id.partner_id:
                missing_fields.append("Customer")
            if not self.order_id.business_unit:
                missing_fields.append("Business Unit")
            if not self.order_id.product_category_id:
                missing_fields.append("Product Category")
            if not self.order_id.payment_term_id:
                missing_fields.append("Payment Terms")

            if missing_fields:
                # Clear any selected product
                self.product_id = False
                return {
                    'warning': {
                        'title': 'Required Fields Missing',
                        'message': f"Please fill the following required fields before selecting products:\n\n" +
                                   "• " + "\n• ".join(missing_fields)
                    }
                }

    @api.model_create_multi
    def create(self, vals_list):
        """Backup validation when creating order lines"""
        for vals in vals_list:
            if 'order_id' in vals and 'product_id' in vals:
                order = self.env['sale.order'].browse(vals['order_id'])
                missing_fields = []

                if not order.partner_id:
                    missing_fields.append("Customer")
                if not order.business_unit:
                    missing_fields.append("Business Unit")
                if not order.product_category_id:
                    missing_fields.append("Product Category")
                if not order.payment_term_id:
                    missing_fields.append("Payment Terms")

                if missing_fields:
                    raise ValidationError(
                        f"Please fill the following required fields before adding products:\n\n" +
                        "• " + "\n• ".join(missing_fields)
                    )

        return super(SaleOrderLine, self).create(vals_list)


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

                    # # Auto-fill payment terms from sale order
                    # if sale_order and sale_order.payment_term_id:
                    #     result.property_payment_term_id = sale_order.payment_term_id.id

        return records

    def action_post(self):
        """STEP 2: When invoice is posted - credit calculation switches to invoice-based"""
        result = super(AccountMove, self).action_post()

        for invoice in self:
            if invoice.move_type == 'out_invoice' and invoice.partner_id:
                if invoice.invoice_origin:
                    sale_order = self.env['sale.order'].search([
                        ('name', '=', invoice.invoice_origin)
                    ], limit=1)
                    if sale_order and sale_order.product_category_id:
                        credit_line = self.env['res.partner.credit.line'].search([
                            ('partner_id', '=', invoice.partner_id.id),
                            ('product_category_id', '=', sale_order.product_category_id.id)
                        ], limit=1)
                        if credit_line:
                            credit_line.force_refresh_credit()

        return result

    def write(self, vals):
        """STEP 3: When invoice amount_residual changes (due to payment) - refresh credit"""
        old_residuals = {}
        if any(field in vals for field in ['amount_residual', 'payment_state']):
            for invoice in self:
                if invoice.move_type == 'out_invoice':
                    old_residuals[invoice.id] = invoice.amount_residual

        result = super(AccountMove, self).write(vals)

        if old_residuals:
            for invoice in self:
                if (invoice.move_type == 'out_invoice' and
                        invoice.partner_id and
                        invoice.id in old_residuals):

                    old_residual = old_residuals[invoice.id]
                    new_residual = invoice.amount_residual

                    if old_residual != new_residual:
                        credit_lines = self.env['res.partner.credit.line'].search([
                            ('partner_id', '=', invoice.partner_id.id)
                        ])
                        for credit_line in credit_lines:
                            credit_line.force_refresh_credit()

        return result


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    product_category_id = fields.Many2one(
        'product.category',
        string='Product Category',
        help='Select the product category for this payment',
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


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        """STEP 5: When reconciliation happens - THIS IS THE KEY MOMENT"""
        records = super(AccountPartialReconcile, self).create(vals_list)

        customers_to_refresh = set()

        for result in records:
            if result.debit_move_id and result.credit_move_id:
                for move_line in [result.debit_move_id, result.credit_move_id]:
                    move = move_line.move_id
                    if move.move_type == 'out_invoice' and move.partner_id:
                        customers_to_refresh.add(move.partner_id)

        for partner in customers_to_refresh:
            credit_lines = self.env['res.partner.credit.line'].search([
                ('partner_id', '=', partner.id)
            ])

            for credit_line in credit_lines:
                credit_line.force_refresh_credit()

        return records

    def unlink(self):
        """When reconciliation is undone"""
        customers_to_refresh = set()

        for reconcile in self:
            if reconcile.debit_move_id and reconcile.credit_move_id:
                for move_line in [reconcile.debit_move_id, reconcile.credit_move_id]:
                    move = move_line.move_id
                    if move.move_type == 'out_invoice' and move.partner_id:
                        customers_to_refresh.add(move.partner_id)

        result = super(AccountPartialReconcile, self).unlink()

        for partner in customers_to_refresh:
            credit_lines = self.env['res.partner.credit.line'].search([
                ('partner_id', '=', partner.id)
            ])

            for credit_line in credit_lines:
                credit_line.force_refresh_credit()

        return result
