# Copyright (c) 2026, Frappe Bench and contributors
# See license.txt

import cv2
import numpy as np
from frappe.tests import UnitTestCase
from PIL import Image, ImageDraw, ImageFont

from docapture.ocr import preprocess

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _text_image(size=(1000, 800), lines=6):
	font = ImageFont.truetype(FONT_PATH, 24)
	img = Image.new("L", size, color=255)
	draw = ImageDraw.Draw(img)
	line = "The quick brown fox jumps over the lazy dog repeatedly for testing purposes."
	y = 40
	for _ in range(lines):
		draw.text((60, y), line, fill=0, font=font)
		y += 60
	return np.array(img)


class UnitTestPreprocess(UnitTestCase):
	def test_ensure_min_dpi_upscales_low_resolution_image(self):
		small = np.full((100, 100), 200, dtype="uint8")
		upscaled = preprocess.ensure_min_dpi(small)
		self.assertGreater(upscaled.shape[0], small.shape[0])

	def test_ensure_min_dpi_leaves_high_resolution_image_alone(self):
		big = np.full((1654, 1654), 200, dtype="uint8")
		result = preprocess.ensure_min_dpi(big)
		self.assertIs(result, big)

	def test_threshold_produces_binary_image(self):
		gray = np.random.default_rng(0).integers(0, 255, (200, 200), dtype="uint8")
		result = preprocess.threshold(gray)
		self.assertListEqual(sorted(np.unique(result).tolist()), [0, 255])

	def test_correct_orientation_coarse_undoes_180_rotation(self):
		import pytesseract

		upright = _text_image(lines=10)
		rotated = cv2.rotate(upright, cv2.ROTATE_180)

		fixed = preprocess.correct_orientation_coarse(rotated)

		osd = pytesseract.image_to_osd(fixed, output_type=pytesseract.Output.DICT)
		self.assertEqual(osd["rotate"], 0)

	def test_correct_orientation_coarse_returns_input_when_osd_cant_decide(self):
		blank = np.full((100, 100), 255, dtype="uint8")
		result = preprocess.correct_orientation_coarse(blank)
		self.assertIs(result, blank)

	def test_deskew_reduces_residual_skew(self):
		upright = _text_image()
		h, w = upright.shape
		matrix = cv2.getRotationMatrix2D((w / 2, h / 2), 8, 1.0)
		skewed = cv2.warpAffine(upright, matrix, (w, h), borderValue=255)

		fixed = preprocess.deskew(skewed)

		diff_before = np.mean(np.abs(skewed.astype(int) - upright.astype(int)))
		diff_after = np.mean(np.abs(fixed.astype(int) - upright.astype(int)))
		self.assertLess(diff_after, diff_before / 2)

	def test_correct_perspective_leaves_flat_image_unchanged(self):
		blank = np.full((300, 300), 255, dtype="uint8")
		result = preprocess.correct_perspective(blank)
		self.assertTrue((result == blank).all())

	def test_correct_perspective_warps_detected_quadrilateral(self):
		canvas = np.zeros((600, 600), dtype="uint8")
		quad = np.array([[150, 80], [480, 130], [520, 520], [80, 480]], dtype="int32")
		cv2.fillConvexPoly(canvas, quad, 255)

		result = preprocess.correct_perspective(canvas)

		self.assertFalse(result.shape == canvas.shape and (result == canvas).all())

	def test_preprocess_page_runs_full_pipeline_on_real_fixture(self):
		from pathlib import Path

		import frappe

		fixture = (
			Path(frappe.get_app_path("docapture")).parent
			/ "tests/fixtures/ocr/sales_order_page1/input.jpg"
		)
		image = cv2.imread(str(fixture))

		result = preprocess.preprocess_page(image)

		self.assertEqual(result.ndim, 2)
		self.assertListEqual(sorted(np.unique(result).tolist()), [0, 255])

	def test_deskew_does_not_rotate_an_already_upright_dense_document(self):
		# Regression: minAreaRect's angle over a full-page, multi-line foreground mass
		# was misread as ~90deg residual skew on an unrotated document, deskew() then
		# "corrected" it into an actual 90deg rotation. See preprocess.deskew's comment.
		from pathlib import Path

		import frappe
		import pytesseract

		fixture = (
			Path(frappe.get_app_path("docapture")).parent
			/ "tests/fixtures/ocr/sales_order_page1/input.jpg"
		)
		image = cv2.imread(str(fixture))
		gray = preprocess.to_grayscale(preprocess.ensure_min_dpi(image))

		fixed = preprocess.deskew(gray)

		data = pytesseract.image_to_data(fixed, output_type=pytesseract.Output.DICT)
		widths = [data["width"][i] for i in range(len(data["text"])) if data["text"][i].strip()]
		heights = [data["height"][i] for i in range(len(data["text"])) if data["text"][i].strip()]
		# Real words on this fixture are wide/short, never tall/narrow.
		self.assertGreater(sum(widths), sum(heights))

	def test_preprocess_page_applies_perspective_correction_only_for_photo_sources(self):
		image = np.full((600, 600, 3), 255, dtype="uint8")
		# should not raise regardless of source_type
		preprocess.preprocess_page(image, source_type="Expense Voucher")
		preprocess.preprocess_page(image, source_type="Bank Statement")
		preprocess.preprocess_page(image, source_type=None)

	def test_correct_perspective_preserves_color_channels(self):
		canvas = np.zeros((600, 600, 3), dtype="uint8")
		quad = np.array([[150, 80], [480, 130], [520, 520], [80, 480]], dtype="int32")
		cv2.fillConvexPoly(canvas, quad, (255, 255, 255))

		result = preprocess.correct_perspective(canvas)

		self.assertEqual(result.ndim, 3)
		self.assertEqual(result.shape[2], 3)

	def test_preprocess_for_paddle_only_upscales_and_corrects_perspective(self):
		# Light pipeline for paddle: no grayscale/threshold/deskew — paddle's own
		# orientation/unwarping models handle that (see paddle_engine.py).
		image = np.full((600, 600, 3), 255, dtype="uint8")

		result = preprocess.preprocess_for_paddle(image, source_type="Bank Statement")

		self.assertEqual(result.ndim, 3)
		self.assertEqual(result.shape[2], 3)

	def test_preprocess_for_paddle_upscales_low_resolution_image(self):
		small = np.full((100, 100, 3), 200, dtype="uint8")
		result = preprocess.preprocess_for_paddle(small)
		self.assertGreater(result.shape[0], small.shape[0])
