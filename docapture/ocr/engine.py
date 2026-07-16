# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

from typing import Protocol, runtime_checkable


@runtime_checkable
class OCREngine(Protocol):
	def extract_page(self, image, dpi: int) -> dict:
		"""image (np.ndarray, BGR or grayscale) -> a page dict per schema.make_page,
		minus page_number (the caller assigns that)."""
		...
