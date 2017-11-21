import traceback

import pycountry

import frappe
import taxjar
from erpnext import get_default_company
from frappe import _
from frappe.contacts.doctype.address.address import get_company_address


def get_client():
	api_key = frappe.get_doc("TaxJar Settings", "TaxJar Settings").get_password("api_key")
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

	client = get_client()
	tax_account_head = frappe.db.get_single_value("TaxJar Settings", "tax_account_head")
	tax_dict = get_tax_data(doc)

	if not tax_dict:
		taxes_list = []

		for tax in doc.taxes:
			if tax.account_head != tax_account_head:
				taxes_list.append(tax)

		setattr(doc, "taxes", taxes_list)
		return

	try:
		taxdata = client.tax_for_order(tax_dict)
	except taxjar.exceptions.TaxJarResponseError as err:
		frappe.throw(_(sanitize_error_response(err)))
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
	except taxjar.exceptions.TaxJarResponseError as err:
		frappe.throw(_(sanitize_error_response(err)))
	except Exception as ex:
		print(traceback.format_exc(ex))


def delete_transaction(doc, method):
	client = get_client()
	client.delete_order(doc.name)


def get_tax_data(doc):
	company_address = get_company_address(get_default_company()).company_address
	company_address = frappe.get_doc("Address", company_address)

	if company_address:
		if doc.shipping_address_name:
			shipping_address = frappe.get_doc("Address", doc.shipping_address_name)
		else:
			shipping_address = company_address
	else:
		return

	if not shipping_address.country == "United States":
		return

	us_states = pycountry.subdivisions.get(country_code='US')
	us_states = [state.code.split('-')[1] for state in us_states]
	address_state = shipping_address.get("state")

	if address_state in us_states:
		shipping_state = address_state
	else:
		try:
			state = pycountry.subdivisions.lookup(address_state)
		except LookupError:
			error_message = """{} is not a valid state!
							Check for typos or enter the
							2-digit code for your state
							found <a href="https://www.ups.com/worldshiphelp/WS16/ENU/AppHelp/Codes/State_Province_Codes.htm">
							here</a>."""

			frappe.throw(_(error_message.format(address_state)))
			return
		else:
			shipping_state = state.code.split('-')[1]

	taxjar_settings = frappe.get_single("TaxJar Settings")

	client = get_client()

	if not (taxjar_settings.api_key or taxjar_settings.tax_account_head):
		return

	api_key = frappe.get_doc("TaxJar Settings", "TaxJar Settings").get_password("api_key")
	client = taxjar.Client(api_key=api_key)

	shipping = 0

	for tax in doc.taxes:
		if tax.account_head == "Freight and Forwarding Charges - JA":
			shipping = tax.tax_amount

	tax_dict = {
		'to_country': 'US',
		'to_zip': shipping_address.pincode,
		'to_city': shipping_address.city,
		'to_state': shipping_state,
		'shipping': shipping,
		'amount': doc.net_total
	}

	return tax_dict


def sanitize_error_response(response):
	response = response.full_response.get("detail")

	sanitized_responses = {
		"to_zip": "Zipcode",
		"to_city": "City",
		"to_state": "State",
		"to_country": "Country",
		"sales_tax": "Sales Tax"
	}

	for r in sanitized_responses:
		response = response.replace(r, sanitized_responses.get(r))

	return response
