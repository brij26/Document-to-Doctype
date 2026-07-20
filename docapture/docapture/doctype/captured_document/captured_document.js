// Copyright (c) 2026, Frappe Bench and contributors
// For license information, please see license.txt

frappe.ui.form.on("Captured Document", {
	refresh(frm) {
		frm.set_df_property("file", "options", {
			restrictions: {
				// Keep in sync with ALLOWED_EXTENSIONS in captured_document.py.
				allowed_file_types: [".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"],
			},
		});

		// Review queue actions (docapture/router.py) — the review queue itself
		// is just the standard List View filtered to status="In Review"; no
		// custom board needed for that part.
		const can_review = frappe.user.has_role("Docapture Reviewer") || frappe.user.has_role("System Manager");
		if (frm.doc.status === "In Review" && can_review) {
			frm.add_custom_button(__("Preview"), () => show_preview_dialog(frm));

			frm.add_custom_button(__("Approve"), () => {
				frappe.call({
					method: "docapture.router.approve",
					args: { captured_document: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating draft..."),
					callback: () => frm.reload_doc(),
				});
			}).addClass("btn-primary");

			frm.add_custom_button(__("Reject"), () => {
				frappe.prompt(
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
					(values) => {
						frappe.call({
							method: "docapture.router.reject",
							args: { captured_document: frm.doc.name, reason: values.reason },
							callback: () => frm.reload_doc(),
						});
					},
					__("Reject Capture")
				);
			});
		}
	},
});

// Preview dialog (docapture.router.preview/save_corrections) — one render
// function handles all 4 source types: header_fields renders as a Link
// input when the field is Capture Alias-eligible (mapped_doctype set,
// docapture/mappers/schema.py's FieldValue) and plain Data otherwise;
// rows/transactions (when present) render as an HTML table of plain
// inputs, since there's no Table-fieldtype/child-doctype backing this
// ephemeral preview. Low-confidence fields (docapture/mappers/schema.py's
// per-field confidence) get a visible hint so the reviewer knows what's
// worth double-checking; an unmapped alias-eligible field gets a more
// specific hint instead (picking one there also saves a Capture Alias
// server-side, so future documents auto-resolve).
function show_preview_dialog(frm) {
	frappe.call({
		method: "docapture.router.preview",
		args: { captured_document: frm.doc.name },
		freeze: true,
		callback: (r) => {
			if (r.message) render_preview_dialog(frm, r.message);
		},
	});
}

function render_preview_dialog(frm, data) {
	const fields = data.header_fields.map((f) => ({
		fieldname: `hf__${f.field_name}`,
		fieldtype: f.mapped_doctype ? "Link" : "Data",
		options: f.mapped_doctype || undefined,
		label: frappe.model.unscrub(f.field_name),
		default: f.value,
		description: field_hint(f),
	}));

	if (data.rows) {
		fields.push({ fieldname: "rows_html", fieldtype: "HTML" });
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Preview: {0}", [data.target_doctype || frm.doc.source_type]),
		fields: fields,
		primary_action_label: __("Save Corrections"),
		primary_action: (values) => save_preview_corrections(frm, dialog, data, values),
	});

	if (data.rows) {
		dialog.fields_dict.rows_html.$wrapper.html(build_rows_table_html(data));
		dialog.$wrapper.on("click", ".docapture-row-remove-btn", (e) => {
			$(e.currentTarget).closest("tr").toggleClass("docapture-row-deleted");
		});
	}

	dialog.show();
}

function save_preview_corrections(frm, dialog, data, values) {
	const header_fields = {};
	data.header_fields.forEach((f) => {
		header_fields[f.field_name] = values[`hf__${f.field_name}`];
	});

	let rows = null;
	let deleted_row_indices = [];
	if (data.rows) {
		rows = data.rows.map((row, row_index) => {
			const row_values = {};
			row.forEach((f) => {
				row_values[f.field_name] = dialog.$wrapper.find(`[data-row="${row_index}"][data-field="${f.field_name}"]`).val();
			});
			return row_values;
		});
		deleted_row_indices = dialog.$wrapper
			.find("tr.docapture-row-deleted")
			.map(function () {
				return parseInt($(this).attr("data-row"), 10);
			})
			.get();
	}

	frappe.call({
		method: "docapture.router.save_corrections",
		args: { captured_document: frm.doc.name, corrections: JSON.stringify({ header_fields, rows, deleted_row_indices }) },
		freeze: true,
		freeze_message: __("Saving corrections..."),
		callback: () => {
			frappe.show_alert({ message: __("Corrections saved"), indicator: "green" });
			dialog.hide();
			frm.reload_doc();
		},
	});
}

function build_rows_table_html(data) {
	if (!data.rows.length) {
		return `<p class="text-muted">${__("No rows extracted.")}</p>`;
	}

	const field_names = data.rows[0].map((f) => f.field_name);
	const header = field_names.map((name) => `<th>${frappe.utils.escape_html(frappe.model.unscrub(name))}</th>`).join("");
	const body = data.rows
		.map((row, row_index) => {
			const cells = row
				.map((f) => {
					const value = f.value === null || f.value === undefined ? "" : f.value;
					return `<td class="${is_low_confidence(f.confidence) ? "docapture-low-confidence" : ""}">
						<input type="text" class="form-control input-sm" data-row="${row_index}" data-field="${frappe.utils.escape_html(f.field_name)}" value="${frappe.utils.escape_html(String(value))}">
					</td>`;
				})
				.join("");
			const remove_cell = `<td><button type="button" class="btn btn-xs btn-default docapture-row-remove-btn">${__("Remove")}</button></td>`;
			return `<tr data-row="${row_index}"><th class="text-muted">${frappe.utils.escape_html(data.row_label || "Row")} ${row_index + 1}</th>${cells}${remove_cell}</tr>`;
		})
		.join("");

	return `
		<div class="table-responsive">
			<table class="table table-bordered table-sm docapture-preview-rows">
				<thead><tr><th></th>${header}<th></th></tr></thead>
				<tbody>${body}</tbody>
			</table>
		</div>
		<style>
			.docapture-low-confidence input { border-color: #f0ad4e; background-color: #fff8ec; }
			.docapture-row-deleted { opacity: 0.4; text-decoration: line-through; }
			.docapture-row-deleted .docapture-row-remove-btn { text-decoration: none; }
		</style>
	`;
}

function is_low_confidence(confidence) {
	return confidence !== null && confidence !== undefined && confidence < 0.5;
}

function field_hint(f) {
	if (f.mapped_doctype && !f.mapped_docname) {
		return __("Not mapped to a {0} yet — pick one to save for future documents", [f.mapped_doctype]);
	}
	if (is_low_confidence(f.confidence)) {
		return __("Low confidence — verify this value");
	}
	return undefined;
}
