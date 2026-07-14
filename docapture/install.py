import frappe

ROLES = ["Docapture Uploader", "Docapture Reviewer"]


def after_install():
	for role_name in ROLES:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert()
