import requests
import frappe
import hashlib
import json

import taxjar


def set_sales_tax(doc, method):
	taxjar_settings = frappe.get_single("TaxJar Settings")

	valid_doctypes = []

	if taxjar_settings.enable_for_quotation:
		valid_doctypes.append("Quotation") 

	if taxjar_settings.enable_for_sales_order:
		valid_doctypes.append("Sales Order") 

	if taxjar_settings.enable_for_sales_invoice:
		valid_doctypes.append("Sales Invoice") 

	if not doc.doctype in valid_doctypes:
		return

	if not (taxjar_settings.api_key or taxjar_settings.tax_account_head):
		return

	client = taxjar.Client(api_key=taxjar_settings.get_password("api_key"))

	company_address = frappe.get_doc("Address", {"is_your_company_address": 1})
	if company_address and doc.shipping_address_name:
		shipping_address = frappe.get_doc("Address", doc.shipping_address_name)
	else:
		return

	if not shipping_address.country == "United States":
		return

	for tax in doc.taxes:
		if tax.account_head == "Freight and Forwarding Charges - JA":
			shipping = tax.tax_amount

	tax_dict = {
			'to_country': 'US',
			'to_zip': shipping_address.pincode,
			'to_city': shipping_address.city,
			'to_state': shipping_address.state,
			'from_country': 'US',
			'from_zip': company_address.pincode,
			'from_city': company_address.city,
			'shipping': shipping,
			'line_items': []
		}

	index = 1
	for item in doc.items:
		tax_dict["line_items"].append({
			"id" : index,
			"unit_price": item.rate,
			"quantity": item.qty,
		})

		index = index + 1

	taxdata = client.tax_for_order(tax_dict)

	doc.append("taxes", {
		"charge_type": "Actual",
		"description": "Sales Tax",
		"account_head": taxjar_settings.tax_account_head,
		"tax_amount": taxdata.amount_to_collect
	})
	doc.run_method("calculate_taxes_and_totals")