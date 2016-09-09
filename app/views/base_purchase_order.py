# coding=utf-8
from datetime import datetime

from flask.ext.login import current_user
from flask_admin.model import InlineFormAdmin
from flask_babelex import lazy_gettext, gettext
from flask_admin.contrib.sqla.filters import FloatSmallerFilter, \
    FloatGreaterFilter, FloatEqualFilter
from app import service, const
from app.models import PurchaseOrder, EnumValues
from app.utils import security_util
from app.views import ModelViewWithAccess
from app.views.base import DeleteValidator
from app.views.components import DisabledStringField


class PurchaseOrderLineInlineAdmin(InlineFormAdmin):
    form_args = dict(
        product=dict(label=lazy_gettext('Product')),
        unit_price=dict(label=lazy_gettext('Unit Price')),
        quantity=dict(label=lazy_gettext('Quantity')),
        remark=dict(label=lazy_gettext('Remark')),
    )

    def postprocess_form(self, form):
        form.total_amount = DisabledStringField(
            label=lazy_gettext('Total Amount'))
        form.remark = None
        form.pol_receiving_lines = None
        return form


class BasePurchaseOrderAdmin(ModelViewWithAccess, DeleteValidator):
    from app.models import PurchaseOrderLine
    from app.views.formatter import supplier_formatter, expenses_formatter, \
        receivings_formatter, default_date_formatter

    column_labels = {
        'id': lazy_gettext('id'),
        'logistic_amount': lazy_gettext('Logistic Amount'),
        'order_date': lazy_gettext('Order Date'),
        'to_organization': lazy_gettext('Supply Organization'),
        'supplier': lazy_gettext('Supplier'),
        'remark': lazy_gettext('Remark'),
        'status': lazy_gettext('Status'),
        'all_expenses': lazy_gettext('Related Expense'),
        'all_receivings': lazy_gettext('Related Receiving'),
        'total_amount': lazy_gettext('Total Amount'),
        'goods_amount': lazy_gettext('Goods Amount'),
        'lines': lazy_gettext('Lines'),
        'supplier.name': lazy_gettext('Supplier Name'),
        'status.display': lazy_gettext('Status')
    }

    column_formatters = {
        'supplier': supplier_formatter,
        'all_expenses': expenses_formatter,
        'all_receivings': receivings_formatter,
        'order_date': default_date_formatter,
    }

    form_args = dict(
        status=dict(query_factory=PurchaseOrder.status_option_filter,
                    description=lazy_gettext(
                        'Purchase order can only be created in draft status, '
                        'and partially '
                        'received & received status are driven by associated '
                        'receiving document')),
        supplier=dict(description=lazy_gettext(
            'Please select a supplier and save the form, '
            'then add purchase order lines accordingly')),
        logistic_amount=dict(default=0),
        order_date=dict(default=datetime.now()),
    )

    column_filters = ('order_date', 'logistic_amount', 'status.display',
                      FloatSmallerFilter(PurchaseOrder.goods_amount,
                                         lazy_gettext('Goods Amount')),
                      FloatGreaterFilter(PurchaseOrder.goods_amount,
                                         lazy_gettext('Goods Amount')),
                      FloatEqualFilter(PurchaseOrder.goods_amount,
                                       lazy_gettext('Goods Amount')))

    form_excluded_columns = ('expenses', 'receivings')
    column_editable_list = ('remark',)

    """Type code of the purchase orders should be displayed in the subview."""
    type_code = None

    def get_list_columns(self):
        """
        This method is called instantly in list.html
        List of columns is decided runtime during render of the table
        Not decided during flask-admin blueprint startup.
        """
        columns = super(BasePurchaseOrderAdmin, self).get_list_columns()
        cols = ['goods_amount', 'total_amount', 'all_expenses']
        columns = security_util.filter_columns_by_role(
            columns, cols,'purchase_price_view'
        )
        columns = self.filter_columns_by_organization_type(columns)
        return columns

    def filter_columns_by_organization_type(self, columns):
        new_col_list = []
        local_user = current_user._get_current_object()
        if local_user is not None:
            if local_user.organization.type.code == "FRANCHISE_STORE":
                for col in columns:
                    if col[0] != 'supplier':
                        new_col_list.append(col)
            elif local_user.organization.type.code == "DIRECT_SELLING_STORE":
                for col in columns:
                    if col[0] != 'to_organization':
                        new_col_list.append(col)
            return tuple(new_col_list)
        else:
            return columns

    def get_details_columns(self):
        cols = ['goods_amount', 'total_amount', 'all_expenses']
        columns = super(BasePurchaseOrderAdmin, self).get_details_columns()
        columns = security_util.filter_columns_by_role(
            columns, cols,'purchase_price_view'
        )
        columns = self.filter_columns_by_organization_type(columns)
        return columns

    def on_model_change(self, form, model, is_created):
        super(BasePurchaseOrderAdmin, self).on_model_change(form, model, is_created)
        if not security_util.user_has_role('purchase_price_view'):
            for l in model.lines:
                l.unit_price = l.product.purchase_price
        DeleteValidator.validate_status_for_change(
            model, const.PO_RECEIVED_STATUS_KEY,
            gettext('Purchase order can not be update nor delete '
                    'on received status')
        )
        if is_created:
            model.type = EnumValues.find_one_by_code(self.type_code)

    def get_query(self):
        po_type = EnumValues.find_one_by_code(self.type_code)
        return super(BasePurchaseOrderAdmin, self).get_query().filter(self.model.type == po_type)

    def get_count_query(self):
        po_type = EnumValues.find_one_by_code(self.type_code)
        return super(BasePurchaseOrderAdmin, self).get_count_query().filter(self.model.type == po_type)

    def on_model_delete(self, model):
        DeleteValidator.validate_status_for_change(
            model,const.PO_RECEIVED_STATUS_KEY,
            gettext('Purchase order can not be '
                    'update nor delete on received status'))

    inline_models = (PurchaseOrderLineInlineAdmin(PurchaseOrderLine),)

    def after_model_change(self, form, model, is_created):
        if model.status.code == const.PO_ISSUED_STATUS_KEY:
            logistic_exp, goods_exp = model.create_expenses()
            db = service.Info.get_db()
            if logistic_exp is not None:
                db.session.add(logistic_exp)
            if goods_exp is not None:
                db.session.add(goods_exp)
            receiving = model.create_receiving_if_not_exist()
            if receiving is not None:
                db.session.add(receiving)
            db.session.commit()


