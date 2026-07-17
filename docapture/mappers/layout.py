# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

# raw_ocr_json (docapture/ocr/schema.py) has no document-level flattened
# text — only structured pages/lines/words with pixel boxes. reconstruct()
# is the named step (docs/PHASE_3_MAPPER_PLAN.md "Text reconstruction")
# that turns that into one reading-order text block per document: lines are
# grouped into horizontal bands by y-overlap, bands ordered top-to-bottom,
# and lines within a band ordered left-to-right — so multi-column content
# (e.g. a letterhead with company info left and a document title/number
# right, or a label-left/value-right bill row) doesn't interleave.


def reconstruct(ocr_json: dict) -> str:
	return "\n\n".join(reconstruct_pages(ocr_json))


def reconstruct_pages(ocr_json: dict) -> list[str]:
	"""Same per-page reconstruction as reconstruct(), but kept separate instead
	of joined — bank_statement_mapper.py extracts a page's transaction table at
	a time rather than the whole document in one LLM call, since a long
	multi-page statement risks context/accuracy limits in a single call."""
	return [_reconstruct_page(page) for page in ocr_json.get("pages", [])]


def _reconstruct_page(page: dict) -> str:
	band_texts = []
	for band in _group_into_bands(page.get("lines", [])):
		band.sort(key=lambda line: line["bbox"][0])
		band_texts.append("  ".join(line["text"] for line in band))
	return "\n".join(band_texts)


# ponytail: O(n^2) pairwise y-overlap check, fine for a page's line count
# (tens, not thousands); upgrade to a sweep-line pass if a fixture ever has
# enough lines to make that show up.
def _group_into_bands(lines: list[dict]) -> list[list[dict]]:
	n = len(lines)
	parent = list(range(n))

	def find(i):
		while parent[i] != i:
			parent[i] = parent[parent[i]]
			i = parent[i]
		return i

	def union(i, j):
		ri, rj = find(i), find(j)
		if ri != rj:
			parent[ri] = rj

	for i in range(n):
		for j in range(i + 1, n):
			if _y_overlaps(lines[i]["bbox"], lines[j]["bbox"]):
				union(i, j)

	groups: dict[int, list[dict]] = {}
	for i, line in enumerate(lines):
		groups.setdefault(find(i), []).append(line)

	bands = list(groups.values())
	bands.sort(key=lambda band: min(line["bbox"][1] for line in band))
	return bands


def _y_overlaps(a_bbox: list[int], b_bbox: list[int]) -> bool:
	a_y0, a_y1 = a_bbox[1], a_bbox[3]
	b_y0, b_y1 = b_bbox[1], b_bbox[3]
	overlap = min(a_y1, b_y1) - max(a_y0, b_y0)
	shorter_height = min(a_y1 - a_y0, b_y1 - b_y0)
	return shorter_height > 0 and overlap / shorter_height > 0.5
