import frappe
import taxjar
import traceback
from frappe.client import get_password


def get_client():
	api_key = get_password("TaxJar Settings", "TaxJar Settings", "api_key")
	client = taxjar.Client(api_key=api_key)
	return client


def set_sales_tax(doc, method):
	if not doc.items:
		return

	# Allow skipping calculation of tax for dev environment
	# if taxjar_calculate_tax isn't defined in site_config we assume
	# we DO want to calculate tax all the time.
	if not frappe.local.conf.get("taxjar_calculate_tax", 1):
		return

	if frappe.db.get_value("Customer", doc.customer, "exempt_from_sales_tax"):
		for tax in doc.taxes:
			if tax.description == "Sales Tax":
				tax.tax_amount = 0
				break
		doc.run_method("calculate_taxes_and_totals")
		return

	tax_account_head = frappe.db.get_single_value("TaxJar Settings", "tax_account_head")

	client = get_client()
	tax_dict = get_tax_data(doc)

	if not tax_dict:
		taxes_list = []
		for tax in doc.taxes:
			if tax.account_head != tax_account_head:
				taxes_list.append(tax)
				break
		setattr(doc, "taxes", taxes_list)
		return

	try:
		taxdata = client.tax_for_order(tax_dict)
	except:
		return

	if "Sales Tax" in [tax.description for tax in doc.taxes]:
		for tax in doc.taxes:
			if tax.description == "Sales Tax":
				tax.tax_amount = taxdata.amount_to_collect
				break
	elif taxdata.amount_to_collect > 0:
		doc.append("taxes", {
			"charge_type": "Actual",
			"description": "Sales Tax",
			"account_head": tax_account_head,
			"tax_amount": taxdata.amount_to_collect
		})

		doc.run_method("calculate_taxes_and_totals")


def create_transaction(doc, method):

	# Allow skipping creation of transaction for dev environment
	# if taxjar_create_transactions isn't defined in site_config we assume
	# we DO want to create transactions all the time.
	if not frappe.local.conf.get("taxjar_create_transactions", 1):
		return

	client = get_client()
	sales_tax = 0
	for tax in doc.taxes:
		if tax.account_head == "Sales Tax - JA":
			sales_tax = tax.tax_amount

	if not sales_tax:
		return

	tax_dict = get_tax_data(doc)
	if not tax_dict:
		return

	tax_dict['transaction_id'] = doc.name
	tax_dict['transaction_date'] = frappe.utils.today()
	tax_dict['sales_tax'] = sales_tax
	tax_dict['amount'] = doc.total + tax_dict['shipping']

	try:
		client.create_order(tax_dict)
	except Exception as ex:
		print(traceback.format_exc(ex))

def delete_transaction(doc, method):
	client = get_client()
	client.delete_order(doc.name)


def get_tax_data(doc):
	from shipment_management.utils import get_state_code
	taxjar_settings = frappe.get_single("TaxJar Settings")

	client = get_client()
	if not (taxjar_settings.api_key or taxjar_settings.tax_account_head):
		return

	client = taxjar.Client(api_key=taxjar_settings.get_password("api_key"))

	company_address = frappe.get_list("Dynamic Link", filters = {"link_doctype" : "Company"}, fields=["parent"])[0]
	company_address = frappe.get_doc("Address", company_address.parent)
	if company_address and not doc.shipping_address_name:
		shipping_address = company_address
	elif company_address and doc.shipping_address_name:
		shipping_address = frappe.get_doc("Address", doc.shipping_address_name)
	else:
		return

	if not shipping_address.country == "United States":
		return

	shipping = 0
	for tax in doc.taxes:
		if tax.account_head == "Freight and Forwarding Charges - JA":
			shipping = tax.tax_amount

	tax_dict = {
		'to_country': 'US',
		'to_zip': shipping_address.pincode,
		'to_city': shipping_address.city,
		'to_state': get_state_code(shipping_address),
		'shipping': shipping,
		'amount': doc.net_total
	}
	return tax_dict