# Copyright (c) 2026, Frappe Bench and contributors
# For license information, please see license.txt

import cv2
import numpy as np
import pytesseract

from docapture.ocr.schema import TARGET_DPI

# Sources captured as phone photos, not flatbed scans (see docs/PHASED_DEVELOPMENT.md
# Phase 2) — the only ones that need perspective (keystone) correction.
PHONE_PHOTO_SOURCE_TYPES = {"Expense Voucher", "Payment Receipt"}

# ponytail: no physical page size is known for a bare raster upload, so effective DPI
# is estimated against an assumed A4/Letter width. Upgrade path: read DPI from image
# EXIF/metadata when present, or let the reviewer confirm/correct source physical size.
ASSUMED_PAGE_WIDTH_INCHES = 8.27


def to_grayscale(image):
	if image.ndim == 3:
		return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
	return image


def ensure_min_dpi(image, min_dpi=TARGET_DPI):
	effective_dpi = image.shape[1] / ASSUMED_PAGE_WIDTH_INCHES
	if effective_dpi >= min_dpi:
		return image
	scale = min_dpi / effective_dpi
	new_size = (round(image.shape[1] * scale), round(image.shape[0] * scale))
	return cv2.resize(image, new_size, interpolation=cv2.INTER_CUBIC)


def correct_orientation_coarse(gray):
	"""Rotate by the nearest 90/180/270 using Tesseract's orientation detection.
	Does nothing (rather than raise) when OSD can't find enough text to decide."""
	try:
		osd = pytesseract.image_to_osd(
			gray, output_type=pytesseract.Output.DICT, config=f"--dpi {TARGET_DPI}"
		)
	except pytesseract.TesseractError:
		return gray
	rotate = osd.get("rotate", 0)
	if not rotate:
		return gray
	rotations = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
	code = rotations.get(rotate)
	return cv2.rotate(gray, code) if code is not None else gray


def deskew(gray):
	"""Fine-angle correction (small residual skew after coarse orientation fix)."""
	thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
	coords = np.column_stack(np.where(thresh > 0))
	if coords.shape[0] < 2:
		return gray
	# cv2.minAreaRect's angle is in [0, 90) and doesn't distinguish "this rect's long
	# side is the page width" from "...is the page height" — for a multi-line document
	# (its foreground mass roughly fills the page) that ambiguity reports angles near
	# 90 for genuinely unskewed pages. Normalize into (-45, 45], the actual residual tilt.
	angle = cv2.minAreaRect(coords)[-1]
	if angle > 45:
		angle -= 90
	if abs(angle) < 0.1:
		return gray
	angle = -angle
	h, w = gray.shape[:2]
	matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
	return cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def denoise(gray):
	return cv2.fastNlMeansDenoising(gray, h=10)


def enhance_contrast(gray):
	clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
	return clahe.apply(gray)


def threshold(gray):
	"""Otsu by default; falls back to per-region adaptive thresholding when Otsu's
	single global cutoff produces a near-blank result (uneven lighting/contrast)."""
	_, otsu_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
	foreground_ratio = float(np.mean(otsu_img == 0))
	if 0.001 < foreground_ratio < 0.5:
		return otsu_img
	return cv2.adaptiveThreshold(
		gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=31, C=15
	)


def correct_perspective(image):
	"""Detect the document's four corners and warp to a flat rectangle. Leaves the
	image unchanged if no clear quadrilateral is found (e.g. it's already flat).
	Accepts grayscale or color — edge detection runs on a grayscale copy, but the
	warp is applied to (and returned in) whatever shape/channel count came in."""
	gray = to_grayscale(image)
	edges = cv2.Canny(gray, 50, 150)
	edges = cv2.dilate(edges, np.ones((5, 5), np.uint8))
	contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
	if not contours:
		return image

	image_area = gray.shape[0] * gray.shape[1]
	candidate = max(contours, key=cv2.contourArea)
	if cv2.contourArea(candidate) < 0.3 * image_area:
		return image

	perimeter = cv2.arcLength(candidate, True)
	approx = cv2.approxPolyDP(candidate, 0.02 * perimeter, True)
	if len(approx) != 4:
		return image

	corners = _order_corners(approx.reshape(4, 2).astype("float32"))
	(tl, tr, br, bl) = corners
	width = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
	height = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
	dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
	matrix = cv2.getPerspectiveTransform(corners, dst)
	return cv2.warpPerspective(image, matrix, (round(width), round(height)))


def _order_corners(pts):
	total = pts.sum(axis=1)
	diff = np.diff(pts, axis=1)
	return np.array(
		[
			pts[np.argmin(total)],  # top-left
			pts[np.argmin(diff)],  # top-right
			pts[np.argmax(total)],  # bottom-right
			pts[np.argmax(diff)],  # bottom-left
		],
		dtype="float32",
	)


def preprocess_page(image, source_type=None):
	"""Full pipeline — for tesseract, a classic algorithm that wants a clean binarized
	image and has no built-in preprocessing of its own."""
	image = ensure_min_dpi(image)
	gray = to_grayscale(image)
	if source_type in PHONE_PHOTO_SOURCE_TYPES:
		gray = correct_perspective(gray)
	gray = correct_orientation_coarse(gray)
	gray = deskew(gray)
	gray = denoise(gray)
	gray = enhance_contrast(gray)
	return threshold(gray)


def preprocess_for_paddle(image, source_type=None):
	"""Light pipeline — for paddleocr, a deep model that (a) does its own orientation/
	unwarping/textline-angle correction (see paddle_engine.py's model kwargs) and (b) is
	trained on natural grayscale/color images, not our hard-binarized output. Keep only
	what paddle has no equivalent for: DPI upscale and phone-photo perspective correction."""
	image = ensure_min_dpi(image)
	if source_type in PHONE_PHOTO_SOURCE_TYPES:
		image = correct_perspective(image)
	return image
