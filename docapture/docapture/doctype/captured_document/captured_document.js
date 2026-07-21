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
			if (frm.doc.source_type === "Bank Statement") {
				frm.add_custom_button(__("Resolve Unknowns"), () => show_resolve_dialog(frm));
			}

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

		// Send a Failed capture back to In Review without re-uploading —
		// extracted_json (every prior correction/Resolve Unknowns answer) is
		// untouched, so Resolve Unknowns/Preview/Approve just work again once
		// whatever actually caused the failure (shown in Error Log below) is
		// fixed. Safe specifically because journal_entry_creator.create_
		// bank_entries() rolls back any partial Journal Entries on failure —
		// a Failed capture never has real drafts sitting behind it to
		// duplicate on retry.
		if (frm.doc.status === "Failed" && can_review) {
			frm.add_custom_button(__("Retry"), () => {
				frappe.call({
					method: "docapture.router.retry",
					args: { captured_document: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			}).addClass("btn-primary");
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
		// extra-large: the row/transaction table (Bank Statement can have
		// 7+ columns) is unreadable at the default modal width — values
		// were visibly clipping inside their inputs.
		size: "extra-large",
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

	// Rows can carry different fields — e.g. Resolve Unknowns writes
	// party_type/party (or counter_account) onto only the rows a reviewer
	// actually resolved, not every row — so the header can't just be row
	// 0's field list, or a later row's extra fields render as unlabeled
	// trailing cells with no matching header. Union every row's field names
	// instead (first-seen order), and render a blank cell wherever a given
	// row doesn't have that field.
	const field_names = [];
	const seen_field_names = new Set();
	data.rows.forEach((row) => {
		row.forEach((f) => {
			if (!seen_field_names.has(f.field_name)) {
				seen_field_names.add(f.field_name);
				field_names.push(f.field_name);
			}
		});
	});

	const header = field_names.map((name) => `<th>${frappe.utils.escape_html(frappe.model.unscrub(name))}</th>`).join("");
	const body = data.rows
		.map((row, row_index) => {
			const by_field_name = {};
			row.forEach((f) => {
				by_field_name[f.field_name] = f;
			});
			const cells = field_names
				.map((name) => {
					const f = by_field_name[name];
					if (!f) return "<td></td>";
					const value = f.value === null || f.value === undefined ? "" : f.value;
					return `<td class="${is_low_confidence(f.confidence) ? "docapture-low-confidence" : ""}">
						<input type="text" class="form-control input-sm" data-row="${row_index}" data-field="${frappe.utils.escape_html(name)}" value="${frappe.utils.escape_html(String(value))}">
					</td>`;
				})
				.join("");
			const remove_cell = `<td><button type="button" class="btn btn-xs btn-default docapture-row-remove-btn">${__("Remove")}</button></td>`;
			// Row number only, not "Transaction 1" repeated on every one of
			// a few hundred rows — the row kind is already in the dialog
			// title, and the full label was wrapping onto two lines and
			// eating column width.
			return `<tr data-row="${row_index}"><th class="text-muted">#${row_index + 1}</th>${cells}${remove_cell}</tr>`;
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
			.docapture-preview-rows th { white-space: nowrap; }
			.docapture-preview-rows td input { min-width: 90px; }
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

// Resolve Unknowns (docapture.router.unknowns/save_resolutions) — Bank
// Statement only, shown before Preview. A 200-row statement usually has only
// a handful of *distinct* unknown counterparties/dates/duplicates, so this
// asks once per unique unknown instead of once per row (that's what the
// per-row Preview table further down would otherwise force). Party/account
// pickers here are plain text inputs, not Link/awesomplete widgets — same
// simplification already accepted for row-level fields in the Preview table
// below (docs/PHASE_STATUS.md's "Row/transaction table cells in Preview stay
// plain text" note); the server's frappe.db.exists() check on save is the
// real safety net either way.
function show_resolve_dialog(frm) {
	frappe.call({
		method: "docapture.router.unknowns",
		args: { captured_document: frm.doc.name },
		freeze: true,
		callback: (r) => {
			if (r.message) render_resolve_dialog(frm, r.message);
		},
	});
}

function render_resolve_dialog(frm, data) {
	const has_anything =
		!data.bank_account_resolved ||
		(data.counterparties && data.counterparties.length) ||
		(data.uncertain_dates && data.uncertain_dates.length) ||
		(data.unreadable_rows && data.unreadable_rows.length) ||
		(data.duplicates && data.duplicates.length);

	if (!has_anything) {
		frappe.show_alert({ message: __("Nothing to resolve — everything already maps cleanly."), indicator: "green" });
		return;
	}

	const fields = [];

	if (!data.bank_account_resolved) {
		fields.push({ fieldname: "sb_bank", fieldtype: "Section Break", label: __("Bank Account") });
		fields.push({
			fieldname: "bank_account",
			fieldtype: "Link",
			options: "Bank Account",
			label: __("This statement belongs to which bank account?"),
		});
	}

	if (data.counterparties && data.counterparties.length) {
		fields.push({ fieldname: "sb_parties", fieldtype: "Section Break", label: __("Unknown Names") });
		fields.push({ fieldname: "parties_html", fieldtype: "HTML" });
	}

	if (data.uncertain_dates && data.uncertain_dates.length) {
		fields.push({ fieldname: "sb_dates", fieldtype: "Section Break", label: __("Unclear Dates") });
		fields.push({ fieldname: "dates_html", fieldtype: "HTML" });
	}

	if (data.unreadable_rows && data.unreadable_rows.length) {
		fields.push({ fieldname: "sb_unreadable", fieldtype: "Section Break", label: __("Rows Missing Info") });
		fields.push({ fieldname: "unreadable_html", fieldtype: "HTML" });
	}

	if (data.duplicates && data.duplicates.length) {
		fields.push({ fieldname: "sb_dupes", fieldtype: "Section Break", label: __("Possible Duplicates") });
		fields.push({ fieldname: "dupes_html", fieldtype: "HTML" });
	}

	fields.push({ fieldname: "sb_rate", fieldtype: "Section Break", label: __("Currency Rate") });
	fields.push({
		fieldname: "exchange_rate",
		fieldtype: "Float",
		label: __("1 statement-currency unit = ? company-currency"),
		description: __("Leave blank if this statement is already in the company's own currency."),
	});

	const dialog = new frappe.ui.Dialog({
		title: __("Resolve Unknowns"),
		size: "large",
		fields: fields,
		primary_action_label: __("Save & Continue to Preview"),
		primary_action: (values) => save_resolutions(frm, dialog, data, values),
		secondary_action_label: __("Skip"),
		secondary_action: () => {
			dialog.hide();
			show_preview_dialog(frm);
		},
	});

	if (data.counterparties && data.counterparties.length) {
		dialog.fields_dict.parties_html.$wrapper.html(build_parties_html(data.counterparties));
		dialog._party_controls = {};
		bind_party_category_controls(dialog, frm.doc.company);
	}
	if (data.uncertain_dates && data.uncertain_dates.length) {
		dialog.fields_dict.dates_html.$wrapper.html(build_dates_html(data.uncertain_dates));
	}
	if (data.unreadable_rows && data.unreadable_rows.length) {
		dialog.fields_dict.unreadable_html.$wrapper.html(build_unreadable_html(data.unreadable_rows));
	}
	if (data.duplicates && data.duplicates.length) {
		dialog.fields_dict.dupes_html.$wrapper.html(build_dupes_html(data.duplicates));
	}

	// Same column-cramping problem as the Preview table (values clipping
	// inside too-narrow inputs) — same fix, once for every table in this
	// dialog.
	dialog.$wrapper.append(
		"<style>.docapture-resolve-table th { white-space: nowrap; } .docapture-resolve-table td input:not([type=checkbox]), .docapture-resolve-table td select { min-width: 90px; }</style>"
	);

	dialog.show();
}

function build_parties_html(counterparties) {
	const rows = counterparties
		.map(
			(c, i) => `
			<tr>
				<td>${frappe.utils.escape_html(c.counterparty_name)}<br>
					<span class="text-muted small">${__("{0} row(s)", [c.row_count])}</span></td>
				<td>
					<select class="form-control input-sm docapture-party-category" data-party-row="${i}">
						<option value="">${__("-- what is this? --")}</option>
						<option value="Customer">${__("Customer")}</option>
						<option value="Supplier">${__("Supplier")}</option>
						<option value="Employee">${__("Employee")}</option>
						<option value="Internal Transfer">${__("Internal Transfer (own other account)")}</option>
						<option value="Other">${__("Other (bank charge, tax, fee...)")}</option>
					</select>
				</td>
				<td>
					<div class="docapture-party-value-area" data-party-row="${i}">
						<span class="text-muted small">${__("pick a category first")}</span>
					</div>
				</td>
			</tr>`
		)
		.join("");

	return `
		<p class="text-muted small">${__("Answer once per unique name — it applies to every row with that same text. Pick \"what is this\" first, then search for the actual record — reduces typos.")}</p>
		<div class="table-responsive">
			<table class="table table-bordered table-sm docapture-resolve-table">
				<thead><tr><th>${__("Unknown Name")}</th><th>${__("What is this?")}</th><th>${__("Who exactly?")}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`;
}

// Which doctype the "Who exactly?" picker searches, per category answer —
// same mapping docapture/resolve.py's _ENTITY_TYPE_BY_CATEGORY makes
// server-side. Internal Transfer/Other aren't a party at all, so both
// search Account instead of a party doctype.
const PARTY_CATEGORY_DOCTYPE = {
	Customer: "Customer",
	Supplier: "Supplier",
	Employee: "Employee",
	"Internal Transfer": "Account",
	Other: "Account",
};

// Doctypes scoped to a company (Account, Employee) — filtered to the
// capture's own company so a reviewer can't accidentally pick a record
// belonging to a different one. Customer/Supplier aren't company-scoped in
// ERPNext, so they get no filter.
const _COMPANY_SCOPED_DOCTYPES = new Set(["Account", "Employee"]);

// Swaps the "Who exactly?" cell from a plain text box to a real Link field
// (native search-as-you-type against existing records, "Create a new ..."
// built in) once a category is picked — cuts typo risk versus typing an
// exact name by hand. The control has to be rebuilt (not just its options
// mutated) whenever the category changes, since the target doctype itself
// changes — same pattern frappe/ui/filters/filter.js uses for its own
// dynamic-doctype field.
function bind_party_category_controls(dialog, company) {
	dialog.$wrapper.on("change", "select.docapture-party-category", function () {
		const row_index = $(this).attr("data-party-row");
		const category = $(this).val();
		const area = dialog.$wrapper.find(`.docapture-party-value-area[data-party-row="${row_index}"]`).empty();
		delete dialog._party_controls[row_index];

		if (!category) {
			area.append(`<span class="text-muted small">${__("pick a category first")}</span>`);
			return;
		}

		const target_doctype = PARTY_CATEGORY_DOCTYPE[category];
		const control = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				options: target_doctype,
				fieldname: `party_value_${row_index}`,
				placeholder: __("Search {0}...", [target_doctype]),
				filters: company && _COMPANY_SCOPED_DOCTYPES.has(target_doctype) ? { company } : undefined,
			},
			parent: area.get(0),
			only_input: true,
		});
		control.refresh();
		dialog._party_controls[row_index] = control;
	});
}

function build_dates_html(uncertain_dates) {
	const rows = uncertain_dates
		.map(
			(d) => `
			<tr>
				<td>${frappe.utils.escape_html(d.narration || "")}</td>
				<td>${frappe.utils.escape_html(d.guessed_date || "")}</td>
				<td><input type="text" class="form-control input-sm docapture-date-fix" data-row="${d.row_number}" placeholder="YYYY-MM-DD"></td>
			</tr>`
		)
		.join("");

	return `
		<p class="text-muted small">${__("System guessed these dates by copying the date from the row above — confirm or fix, or leave blank to keep the guess.")}</p>
		<div class="table-responsive">
			<table class="table table-bordered table-sm docapture-resolve-table">
				<thead><tr><th>${__("Row Text")}</th><th>${__("Guessed Date")}</th><th>${__("Correct Date")}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`;
}

function build_unreadable_html(unreadable_rows) {
	const rows = unreadable_rows
		.map(
			(u) => `
			<tr data-unreadable-row="${u.row_number}">
				<td>${frappe.utils.escape_html(u.narration || "")}</td>
				<td><input type="text" class="form-control input-sm docapture-unreadable-date" placeholder="YYYY-MM-DD"></td>
				<td><input type="text" class="form-control input-sm docapture-unreadable-amount" placeholder="${__("amount")}"></td>
				<td>
					<select class="form-control input-sm docapture-unreadable-direction">
						<option value="deposit">${__("Money In")}</option>
						<option value="withdrawal">${__("Money Out")}</option>
					</select>
				</td>
			</tr>`
		)
		.join("");

	return `
		<p class="text-muted small">${__("These rows couldn't be fully read. Fill in date + amount to include them, or leave blank to skip (as today).")}</p>
		<div class="table-responsive">
			<table class="table table-bordered table-sm docapture-resolve-table">
				<thead><tr><th>${__("Text Found")}</th><th>${__("Date")}</th><th>${__("Amount")}</th><th>${__("Direction")}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`;
}

function build_dupes_html(duplicates) {
	const rows = duplicates
		.map(
			(d) => `
			<tr>
				<td>${frappe.utils.escape_html(d.narration || "")}</td>
				<td>${d.amount}</td>
				<td>${frappe.utils.escape_html(d.posting_date || "")}</td>
				<td>${__("Already in {0} {1}", [d.existing_target_doctype, d.existing_target_docname])}</td>
				<td><label><input type="checkbox" class="docapture-dupe-force" data-row="${d.row_number}"> ${__("Add anyway")}</label></td>
			</tr>`
		)
		.join("");

	return `
		<p class="text-muted small">${__("These rows look like something already entered. Unchecked = skip (today's default behavior).")}</p>
		<div class="table-responsive">
			<table class="table table-bordered table-sm docapture-resolve-table">
				<thead><tr><th>${__("Row")}</th><th>${__("Amount")}</th><th>${__("Date")}</th><th>${__("Matches")}</th><th></th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`;
}

function save_resolutions(frm, dialog, data, values) {
	const resolutions = {};

	if (values.exchange_rate) {
		resolutions.exchange_rate = values.exchange_rate;
	}
	if (!data.bank_account_resolved && values.bank_account) {
		resolutions.bank_account = values.bank_account;
	}

	if (data.counterparties && data.counterparties.length) {
		resolutions.parties = data.counterparties
			.map((c, i) => {
				const category = dialog.$wrapper.find(`select.docapture-party-category[data-party-row="${i}"]`).val();
				const control = dialog._party_controls && dialog._party_controls[i];
				const party = control ? control.get_value() : null;
				return category && party ? { counterparty_name: c.counterparty_name, category, party } : null;
			})
			.filter(Boolean);
	}

	const row_fixes = [];
	if (data.uncertain_dates && data.uncertain_dates.length) {
		dialog.$wrapper.find("input.docapture-date-fix").each(function () {
			const val = $(this).val();
			if (val) row_fixes.push({ row_number: parseInt($(this).attr("data-row"), 10), date: val });
		});
	}
	if (data.unreadable_rows && data.unreadable_rows.length) {
		dialog.$wrapper.find("tr[data-unreadable-row]").each(function () {
			const row_number = parseInt($(this).attr("data-unreadable-row"), 10);
			const date = $(this).find(".docapture-unreadable-date").val();
			const amount = $(this).find(".docapture-unreadable-amount").val();
			const direction = $(this).find(".docapture-unreadable-direction").val();
			if (date && amount) {
				const fix = { row_number, date };
				fix[direction === "withdrawal" ? "withdrawal" : "deposit"] = amount;
				row_fixes.push(fix);
			}
		});
	}
	if (row_fixes.length) resolutions.row_fixes = row_fixes;

	if (data.duplicates && data.duplicates.length) {
		const overrides = dialog.$wrapper
			.find("input.docapture-dupe-force:checked")
			.map(function () {
				return parseInt($(this).attr("data-row"), 10);
			})
			.get();
		if (overrides.length) resolutions.duplicate_overrides = overrides;
	}

	frappe.call({
		method: "docapture.router.save_resolutions",
		args: { captured_document: frm.doc.name, resolutions: JSON.stringify(resolutions) },
		freeze: true,
		freeze_message: __("Saving..."),
		callback: () => {
			frappe.show_alert({ message: __("Saved"), indicator: "green" });
			dialog.hide();
			frm.reload_doc().then(() => show_preview_dialog(frm));
		},
	});
}
