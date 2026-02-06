#==============================================================================
#
# Copyright (c) 2026, Qualcomm Innovation Center, Inc. All rights reserved.
# 
# SPDX-License-Identifier: BSD-3-Clause
#
#==============================================================================

import os
import sys
import cv2
import time
import queue
import signal
import argparse
from datetime import datetime
import multiprocessing as mp

import numpy as np
from flask import Flask, render_template, request, send_from_directory, Response, jsonify

from yolov8 import Yolov8Seg
from sam2 import SAM2
from utils import draw_detect_res

class WebUI(object):
    """
    WebUI Class
    
    Wraps the Flask application, AI models (YOLOv8 + SAM2), and video processing logic.
    Implements a producer-consumer pattern using queues for real-time inference.
    """
    def __init__(self, 
                 source: str, 
                 resolution: list, 
                 save_dir: str,
                 target_class_id: int = 0):
        """
        Args:
            source: Camera ID (int) or Video Path (str).
            resolution: Tuple of (width, height).
            save_dir: Directory to save results.
            target_class_id: Class ID to filter (default 0).
        """
        self.app = Flask(__name__)

        try:
            video_source = int(source)
        except ValueError:
            video_source = source

        self.width, self.height = resolution
        self.cap = cv2.VideoCapture(video_source)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        # self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YUYV'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)


        self.input_queue = mp.Queue(maxsize=1)
        self.result_queue = mp.Queue(maxsize=1)

        self.is_active = mp.Value('b', False) 
        self.inference_interval = mp.Value('d', 4.0)
        self.target_class_id = target_class_id

        self.save_dir = os.path.normpath(os.path.abspath(save_dir)) if save_dir else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result')
        print("Saving Results to:", self.save_dir)
        os.makedirs(self.save_dir, exist_ok=True)
        
        self.p = mp.Process(target=self.inference_worker, args=(
            self.input_queue,
            self.result_queue,
            self.is_active,
            self.inference_interval,
            self.save_dir
        ))
        self.p.daemon = True
        self.p.start()

        self._register_routes()

        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)
    
    def _register_routes(self):
        """Internal method to register Flask routes."""
        self.app.route('/')(self.index)
        self.app.route('/video_feed')(self.video_feed)
        self.app.route('/start_patrol', methods=['POST'])(self.start_patrol)
        self.app.route('/end_patrol', methods=['POST'])(self.end_patrol)
        self.app.route('/set_det_step', methods=['POST'])(self.set_interval)
        self.app.route('/get_status')(self.get_status)
        self.app.route('/get_result')(self.get_result)
        self.app.route('/result_files/<filename>')(self.serve_result_file)

    def index(self):
        """
        Render the main dashboard page.
        """
        return render_template('index.html')

    def inference_worker(self, input_queue, result_queue, is_active_val, interval_val, save_dir):
        """
        Background worker thread.
        Consumes frames from input_queue, runs inference, and puts masks into result_queue.
        """
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        yolov8 = Yolov8Seg(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../resources/cutoff_yolov8s-seg_qcs8550_w8a16.qnn236.ctx.bin"), 640, 640, 1)
        sam2 = SAM2(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../resources/sam2unet_large_fix_w8a16.qnn231.ctx.bin"))

        while True:
            try:
                frame, timestamp = input_queue.get(timeout=1.0)
                if frame is None:
                    break
            except queue.Empty:
                continue

            boxes, segments = yolov8(frame)
            if boxes is None:
                continue

            masks = np.zeros(frame.shape[:2], dtype=np.uint8)
            detect_flag = False

            for i in range(len(boxes)):
                cls_id = int(boxes[i][5]) 
                if cls_id == self.target_class_id:
                    x1, y1, x2, y2 = [int(t) for t in boxes[i][:4]]
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(self.width, x2), min(self.height, y2)

                    if (x2 - x1) * (y2 - y1) < 10000:
                        continue

                    if len(segments[i]) > 0:
                        mask_temp = np.zeros((self.height, self.width), dtype=np.uint8)
                        poly = np.int32([segments[i]])
                        cv2.fillPoly(mask_temp, poly, 255)

                        masked_frame = cv2.bitwise_and(frame, frame, mask=mask_temp)
                        crop_img = masked_frame[y1:y2, x1:x2]

                        new_mask = sam2(crop_img)
                        masks[y1:y2, x1:x2] = masks[y1:y2, x1:x2] + new_mask
                        detect_flag = True

            if detect_flag:
                masks = np.where(masks > 0, 255, 0).astype(np.uint8)
                contours, _ = cv2.findContours(masks[:,:], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                if contours:
                    valid_contours = [c for c in contours if (cv2.contourArea(c) > 10 and cv2.contourArea(c) < 100000)]
                    if valid_contours:      
                        cv2.drawContours(frame, valid_contours, -1, (0, 255, 0), 3)
                        for seg in segments:
                            cv2.polylines(frame, np.int32([seg]), True, (255, 0, 0), 3)
                        save_path = os.path.join(save_dir, timestamp.strftime("%Y_%m_%d_%H_%M_%S_%f")[:-3] + ".jpg")
                        cv2.imwrite(save_path, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                result_queue.put((masks, segments))

    def generate_frames(self):
        """
        Generator function for video streaming.
        Captures video, manages queue I/O, overlays masks, and yields MJPEG frames.
        """

        latest_mask = None
        hold_count = 10
        last_time = time.time()
        while True:
            success, frame = self.cap.read()
            if not success:
                break
            
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if self.is_active.value and (time.time() - last_time >= self.inference_interval.value):
                try:
                    last_time = time.time()
                    self.input_queue.put_nowait((frame, datetime.now()))
                except mp.queues.Full:
                    pass

            try:
                (latest_mask, segments) = self.result_queue.get_nowait()
                hold_count = 10
            except queue.Empty:
                pass

            if latest_mask is not None and self.is_active.value and hold_count > 0:
                contours, _ = cv2.findContours(latest_mask[:,:], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(frame, contours, -1, (0, 255, 0), 2)
                for seg in segments:
                    cv2.polylines(frame, np.int32([seg]), True, (255, 0, 0), 3)
                hold_count -= 1

            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ret, buffer = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

    def video_feed(self):
        """
        Flask route for the video stream.
        Returns a multipart response.
        """
        return Response(self.generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

    def start_patrol(self):
        """
        API to start the patrol system.
        Updates status flag and returns JSON response.
        """
        self.is_active.value = True
        return jsonify({
                "status": "success",
                "message": "Inspection System Active!",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }), 200
    
    def end_patrol(self):
        """
        API to stop the patrol system.
        """
        self.is_active.value = False
        return jsonify({
                "status": "success",
                "message": "Inspection System Deactivated!",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }), 200

    def get_status(self):
        """
        API to get current system status.
        """
        if self.is_active.value:
            status = "Active"
        else:
            status = "Inactive"
        return jsonify({
            "patrol_status": status,
            "text": status,
            "det_step": str(self.inference_interval.value),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    def set_interval(self):
        json_data = request.get_json()
        try:
            self.inference_interval.value = float(json_data["step"])
            return jsonify({
                    "status": "success",
                    "message": "Interval set successfully.",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }), 200
        except:
            return jsonify({
                    "status": "failure",
                    "message": "Failed to set interval.",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }), 200

    def serve_result_file(self, filename):
        return send_from_directory(self.save_dir, filename)

    def get_result(self):
        base_url = request.host_url.rstrip('/')
        data_list = []
        try:
            files = sorted(os.listdir(self.save_dir))
            for filename in files:
                if filename.endswith(".jpg"):
                    name = filename.replace(".jpg", "")
                    timestamp = name[:10].replace("_", "-") + " " + name[11:19].replace("_", ":") + "." + name[20:]
                    file_url = f"{base_url}/result_files/{filename}"
                    data_list.append({'time': timestamp, 'path': file_url})
        except FileNotFoundError:
            pass
        return jsonify(data_list)
     
    def handle_exit(self, signum, frame):
        self.stop()
        sys.exit(0)

    def stop(self):
        self.is_active.value = False

        if hasattr(self, 'input_queue'):
            try:
                while not self.input_queue.empty():
                    self.input_queue.get_nowait()
                self.input_queue.put((None, None)) 
            except:
                pass
        
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()

        if hasattr(self, 'p') and self.p.is_alive():
            self.p.join(timeout=2.0)
            if self.p.is_alive():
                self.p.terminate()
                self.p.join()

    def run(self, port=3333, host='0.0.0.0'):
        """
        Register routes and start the Flask server.
        """
        try:
            self.app.run(host=host, port=port, debug=False, use_reloader=False)
        finally:
            self.stop()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="YOLOv8 + SAM2 WebUI")
    parser.add_argument('--source', type=str, required=True, help='Camera ID')
    parser.add_argument('--resolution', type=int, nargs=2, default=[1280, 720], help='Width and height of the window (default: 1280 720)')   
    parser.add_argument('--class-id', type=int, default=0, help='Class ID to detect')
    parser.add_argument('--port', type=int, default=3333, help='Web server port')
    parser.add_argument('--save-dir', type=str, default=None, help='Directory to save results')
    args = parser.parse_args()

    if "ADSP_LIBRARY_PATH" not in os.environ:
        raise("ADSP_LIBRARY_PATH is not set.")

    ui = WebUI(
        source=args.source,
        resolution=args.resolution,
        save_dir=args.save_dir,
        target_class_id=args.class_id
    )

    ui.run(port=args.port)
