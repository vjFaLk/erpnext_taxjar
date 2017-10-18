import frappe
import unittest

class TestTaxJarAPI(unittest.TestCase):
	def test_calculate_taxes(self):

		# Create company address
		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Company Address",
				"address_line1": "Test Street",
				"city": "Orlando",
				"state": "Florida",
				"pincode": "32801",
				"country": "United States",
				"is_your_company_address" : 1,
				"links": [{
					"link_doctype": "Company",
					"link_name": "_Test Company"}]
			}).insert()

		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "_Test Address",
				"address_line1": "Test Street",
				"city": "Orlando",
				"state": "Florida",
				"pincode": "32801",
				"country": "United States"
			}).insert()

		qo = frappe.get_doc(
			{
				"doctype": "Quotation",
				"customer": "_Test Customer",
				"items": [{
							"item_code": "_Test Item",
							"rate": 100
				}],
				"shipping_address_name": address.name
			}).insert()

		self.assertTrue(qo.total_taxes_and_charges)
