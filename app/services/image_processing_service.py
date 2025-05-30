from dataclasses import dataclass
from typing import Tuple, List, Optional
from PIL import Image, ImageDraw
import os
import logging
from app.config import TRIMMED_FOLDER
import cv2
import numpy as np

@dataclass
class TrimConfig:
    percent_expand: float = 0.5
    min_width: int = 100
    min_height: int = 100
    max_width: Optional[int] = None
    max_height: Optional[int] = None
    quality: int = 95

class ImageProcessingService:
    def __init__(self, config: TrimConfig = None):
        self.config = config or TrimConfig()
        self.logger = logging.getLogger(__name__)

    def trim_image(
        self,
        input_path: str,
        bounding_boxes: List[List[Tuple[float, float]]],
        output_path: Optional[str] = None
    ) -> Tuple[str, dict]:
        """
        Trim image based on bounding boxes with validation and logging
        Args:
            input_path: Path to input image
            bounding_boxes: List of bounding box coordinates
            output_path: Optional output path
        Returns:
            Tuple of (output_path, metadata)
        """
        try:
            img = Image.open(input_path)
            original_size = img.size
            all_vertices = []
            for box in bounding_boxes:
                all_vertices.extend(box)
            if not all_vertices:
                self.logger.warning("No bounding boxes provided")
                return input_path, {"error": "No bounding boxes"}
            xs, ys = zip(*all_vertices)
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            box_width = max_x - min_x
            box_height = max_y - min_y
            expand_x = box_width * (self.config.percent_expand / 2)
            expand_y = box_height * (self.config.percent_expand / 2)
            left = max(int(min_x - expand_x), 0)
            top = max(int(min_y - expand_y), 0)
            right = min(int(max_x + expand_x), img.width)
            bottom = min(int(max_y + expand_y), img.height)
            crop_width = right - left
            crop_height = bottom - top
            if crop_width < self.config.min_width or crop_height < self.config.min_height:
                self.logger.warning(f"Crop dimensions too small: {crop_width}x{crop_height}")
                return input_path, {"error": "Crop too small"}
            cropped_img = img.crop((left, top, right, bottom))
            if not output_path:
                output_path = self._generate_output_path(input_path)
            metadata = {
                "original_size": original_size,
                "crop_size": cropped_img.size,
                "crop_coordinates": (left, top, right, bottom),
                "expansion_percent": self.config.percent_expand
            }
            cropped_img.save(output_path, quality=self.config.quality)
            self.logger.info(f"Image trimmed successfully: {metadata}")
            return output_path, metadata
        except Exception as e:
            self.logger.error(f"Error trimming image: {str(e)}")
            return input_path, {"error": str(e)}

    def detect_card_by_edges(self, input_path: str, output_path: Optional[str] = None) -> Tuple[str, dict]:
        """
        Detect the card in the image using Canny edge detection and contour finding.
        Returns the cropped card image path and debug info.
        """
        try:
            image = cv2.imread(input_path)
            orig = image.copy()
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edged = cv2.Canny(blurred, 75, 200)
            contours, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            contours = sorted(contours, key=cv2.contourArea, reverse=True)
            card_contour = None
            max_area = 0
            best_aspect = None
            debug_img = orig.copy()
            found_quads = []
            for idx, c in enumerate(contours):
                peri = cv2.arcLength(c, True)
                approx = cv2.approxPolyDP(c, 0.02 * peri, True)
                if len(approx) == 4:
                    area = cv2.contourArea(approx)
                    x, y, w, h = cv2.boundingRect(approx)
                    aspect = w / float(h) if h > 0 else 0
                    found_quads.append((area, aspect, approx))
                    # Draw all 4-sided contours in blue
                    cv2.drawContours(debug_img, [approx], -1, (255, 0, 0), 2)
                    # Prefer largest area, reasonable aspect ratio (card: 1.2-1.8)
                    if area > max_area and 1.2 < aspect < 1.8 and area > 10000:
                        card_contour = approx
                        max_area = area
                        best_aspect = aspect
                        # Draw selected contour in green
                        cv2.drawContours(debug_img, [approx], -1, (0, 255, 0), 3)
            # Fallback: if no good quad, crop the whole image
            if card_contour is None:
                self.logger.warning("Could not find a valid card contour. Falling back to full image crop.")
                h, w = image.shape[:2]
                card_contour = np.array([
                    [[0, 0]],
                    [[w - 1, 0]],
                    [[w - 1, h - 1]],
                    [[0, h - 1]]
                ])
                max_area = w * h
                best_aspect = w / float(h) if h > 0 else 0
            # Perspective transform to get a top-down view
            pts = card_contour.reshape(4, 2)
            rect = self._order_points(pts)
            (tl, tr, br, bl) = rect
            widthA = np.linalg.norm(br - bl)
            widthB = np.linalg.norm(tr - tl)
            maxWidth = max(int(widthA), int(widthB))
            heightA = np.linalg.norm(tr - br)
            heightB = np.linalg.norm(tl - bl)
            maxHeight = max(int(heightA), int(heightB))
            dst = np.array([
                [0, 0],
                [maxWidth - 1, 0],
                [maxWidth - 1, maxHeight - 1],
                [0, maxHeight - 1]
            ], dtype="float32")
            M = cv2.getPerspectiveTransform(rect, dst)
            warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
            if not output_path:
                output_path = self._generate_output_path(input_path).replace('_trimmed', '_contour_trimmed')
            cv2.imwrite(output_path, warped)
            debug_path = output_path.replace('.jpg', '_debug.jpg').replace('.JPG', '_debug.JPG')
            cv2.imwrite(debug_path, debug_img)
            metadata = {
                "contour_points": rect.tolist(),
                "output_path": output_path,
                "debug_path": debug_path,
                "maxWidth": maxWidth,
                "maxHeight": maxHeight,
                "selected_area": max_area,
                "selected_aspect": best_aspect
            }
            self.logger.info(f"Card detected and cropped using contour: {metadata}")
            return output_path, metadata
        except Exception as e:
            self.logger.error(f"Error in detect_card_by_edges: {str(e)}")
            return input_path, {"error": str(e)}

    def _order_points(self, pts):
        # Order points: top-left, top-right, bottom-right, bottom-left
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

    def _generate_output_path(self, input_path: str) -> str:
        filename = os.path.basename(input_path)
        name, ext = os.path.splitext(filename)
        return os.path.join(TRIMMED_FOLDER, f"{name}_trimmed{ext}")

    def crop_between_fields(self, input_path: str, box1: list, box2: list, output_path: Optional[str] = None) -> tuple:
        """
        Crop the image to the rectangle that encloses both box1 and box2.
        box1, box2: lists of (x, y) tuples (usually 4 points each)
        """
        try:
            img = Image.open(input_path)
            all_points = box1 + box2
            xs = [pt[0] for pt in all_points]
            ys = [pt[1] for pt in all_points]
            min_x, max_x = int(min(xs)), int(max(xs))
            min_y, max_y = int(min(ys)), int(max(ys))
            # Optionally expand a bit
            expand_x = int((max_x - min_x) * 0.05)
            expand_y = int((max_y - min_y) * 0.05)
            left = max(min_x - expand_x, 0)
            top = max(min_y - expand_y, 0)
            right = min(max_x + expand_x, img.width)
            bottom = min(max_y + expand_y, img.height)
            cropped_img = img.crop((left, top, right, bottom))
            if not output_path:
                output_path = self._generate_output_path(input_path).replace('_trimmed', '_fields_trimmed')
            cropped_img.save(output_path, quality=self.config.quality)
            metadata = {
                "crop_rectangle": (left, top, right, bottom),
                "output_path": output_path,
                "box1": box1,
                "box2": box2
            }
            self.logger.info(f"Image cropped between fields: {metadata}")
            return output_path, metadata
        except Exception as e:
            self.logger.error(f"Error in crop_between_fields: {str(e)}")
            return input_path, {"error": str(e)}

    def crop_using_page_poly(self, input_path: str, bounding_poly: list, output_path: Optional[str] = None) -> tuple:
        """
        Crop the image using the page bounding_poly (list of 4 (x, y) points) with a perspective transform.
        """
        try:
            img = cv2.imread(input_path)
            pts = np.array(bounding_poly, dtype="float32")
            # Order points: top-left, top-right, bottom-right, bottom-left
            rect = self._order_points(pts)
            (tl, tr, br, bl) = rect
            widthA = np.linalg.norm(br - bl)
            widthB = np.linalg.norm(tr - tl)
            maxWidth = max(int(widthA), int(widthB))
            heightA = np.linalg.norm(tr - br)
            heightB = np.linalg.norm(tl - bl)
            maxHeight = max(int(heightA), int(heightB))
            dst = np.array([
                [0, 0],
                [maxWidth - 1, 0],
                [maxWidth - 1, maxHeight - 1],
                [0, maxHeight - 1]
            ], dtype="float32")
            M = cv2.getPerspectiveTransform(rect, dst)
            warped = cv2.warpPerspective(img, M, (maxWidth, maxHeight))
            if not output_path:
                output_path = self._generate_output_path(input_path).replace('_trimmed', '_pagepoly_trimmed')
            cv2.imwrite(output_path, warped)
            metadata = {
                "bounding_poly": bounding_poly,
                "output_path": output_path,
                "maxWidth": maxWidth,
                "maxHeight": maxHeight
            }
            self.logger.info(f"Image cropped using page bounding_poly: {metadata}")
            return output_path, metadata
        except Exception as e:
            self.logger.error(f"Error in crop_using_page_poly: {str(e)}")
            return input_path, {"error": str(e)}

    def crop_from_first_to_last_field(self, input_path: str, first_box: list, last_box: list, output_path: Optional[str] = None, padding: int = 20) -> tuple:
        """
        Crop the image using the min/max of all 8 points from both boxes, with padding.
        Prints the coordinates and saves the cropped image.
        """
        try:
            img = Image.open(input_path)
            all_points = first_box + last_box
            xs = [pt[0] for pt in all_points]
            ys = [pt[1] for pt in all_points]
            left = int(min(xs)) - padding
            top = int(min(ys)) - padding
            right = int(max(xs)) + padding
            bottom = int(max(ys)) + padding
            left = max(left, 0)
            top = max(top, 0)
            right = min(right, img.width)
            bottom = min(bottom, img.height)
            print(f"Cropping coordinates: left={left}, top={top}, right={right}, bottom={bottom}")
            cropped_img = img.crop((left, top, right, bottom))
            if not output_path:
                output_path = self._generate_output_path(input_path).replace('_trimmed', '_firstlast_trimmed')
            cropped_img.save(output_path, quality=self.config.quality)
            metadata = {
                "crop_rectangle": (left, top, right, bottom),
                "output_path": output_path,
                "first_box": first_box,
                "last_box": last_box
            }
            self.logger.info(f"Image cropped from first to last field: {metadata}")
            print(f"Cropped image saved to: {output_path}")
            return output_path, metadata
        except Exception as e:
            self.logger.error(f"Error in crop_from_first_to_last_field: {str(e)}")
            print(f"Error in crop_from_first_to_last_field: {str(e)}")
            return input_path, {"error": str(e)}

    def debug_draw_field_boxes(self, input_path: str, field_data: dict, output_path: Optional[str] = None) -> str:
        """
        Draw all field bounding boxes on the image and save as a debug image. Print coordinates for each field.
        """
        img = Image.open(input_path).convert('RGB')
        draw = ImageDraw.Draw(img)
        for field, data in field_data.items():
            box = data.get('bounding_box')
            if box and len(box) == 4:
                # Draw polygon
                draw.polygon(box, outline='red', width=3)
                # Draw field name at the first vertex
                draw.text(box[0], field, fill='blue')
                print(f"{field}: {box}")
        if not output_path:
            output_path = input_path.replace('.JPG', '_fieldboxes_debug.JPG').replace('.jpg', '_fieldboxes_debug.jpg')
        img.save(output_path)
        print(f"Debug image with field boxes saved to: {output_path}")
        return output_path

    def auto_rotate_to_portrait(self, input_path: str, output_path: Optional[str] = None) -> str:
        """
        Rotate the image to portrait orientation (height > width) if needed.
        Returns the path to the rotated (or original) image.
        """
        img = Image.open(input_path)
        if img.width > img.height:
            img = img.rotate(270, expand=True)  # Rotate 90 degrees counterclockwise
            if not output_path:
                output_path = input_path.replace('.JPG', '_portrait.JPG').replace('.jpg', '_portrait.jpg')
            img.save(output_path)
            print(f"Image auto-rotated to portrait and saved to: {output_path}")
            return output_path
        else:
            print("Image already in portrait orientation.")
            return input_path

    def crop_using_all_fields(self, input_path: str, field_data: dict, first_field: str, last_field: str, output_path: Optional[str] = None, padding_top_pct: float = 0.10, padding_bottom_pct: float = 0.15, padding_left_pct: float = 0.08, padding_right_pct: float = 0.12) -> tuple:
        """
        Crop the image using min/max X from all field boxes for width, min Y from first field, max Y from last field for height, with percentage-based paddings.
        Prints the coordinates and saves the cropped image.
        """
        try:
            img = Image.open(input_path)
            all_points = []
            for field, data in field_data.items():
                box = data.get('bounding_box')
                if box and len(box) == 4:
                    all_points.extend(box)
                    print(f"[CROP LOG] Field: {field}, Bounding box: {box}")
            xs = [pt[0] for pt in all_points]
            # Use min Y from first field, max Y from last field
            first_box = field_data[first_field]['bounding_box']
            last_box = field_data[last_field]['bounding_box']
            ys_first = [pt[1] for pt in first_box]
            ys_last = [pt[1] for pt in last_box]
            crop_left = min(xs)
            crop_right = max(xs)
            crop_top = min(ys_first)
            crop_bottom = max(ys_last)
            crop_width = crop_right - crop_left
            crop_height = crop_bottom - crop_top
            left = int(crop_left - crop_width * padding_left_pct)
            right = int(crop_right + crop_width * padding_right_pct)
            top = int(crop_top - crop_height * padding_top_pct)
            bottom = int(crop_bottom + crop_height * padding_bottom_pct)
            left = max(left, 0)
            top = max(top, 0)
            right = min(right, img.width)
            bottom = min(bottom, img.height)
            print(f"[CROP LOG] Cropping coordinates: left={left}, top={top}, right={right}, bottom={bottom}, output_path={output_path}")
            cropped_img = img.crop((left, top, right, bottom))
            if not output_path:
                output_path = self._generate_output_path(input_path).replace('_trimmed', '_allfields_fullcard_trimmed')
            cropped_img.save(output_path, quality=self.config.quality)
            metadata = {
                "crop_rectangle": (left, top, right, bottom),
                "output_path": output_path,
                "first_field": first_field,
                "last_field": last_field
            }
            self.logger.info(f"Image cropped using all fields (full card, percent padding): {metadata}")
            print(f"Cropped image saved to: {output_path}")
            return output_path, metadata
        except Exception as e:
            self.logger.error(f"Error in crop_using_all_fields: {str(e)}")
            print(f"Error in crop_using_all_fields: {str(e)}")
            return input_path, {"error": str(e)} 