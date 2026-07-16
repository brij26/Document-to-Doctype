// Copyright (c) 2026, Frappe Bench and contributors
// For license information, please see license.txt

frappe.ui.form.on("Captured Document", {
	refresh(frm) {
		frm.set_df_property("file", "options", {
			restrictions: {
				// Keep in sync with ALLOWED_EXTENSIONS in captured_document.py.
				allowed_file_types: [".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"],
			},
		});
	},
});
