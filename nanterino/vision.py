"""Vision (cahier des charges step 6, F01/F02): RealSense color + depth -> YuNet face detection.

logging: robotlog via nanterino.log (fps, counts, errors only).
Privacy (cahier §7): frames live in RAM only and are dropped immediately. No image, no face
embedding, no identity is ever stored or logged. "Tracking" = keeping the same anonymous box
from one frame to the next (IoU), never recognising who it is.

Published state (`Vision.state`), read by the UI 10x/s:
  present: bool, x/y: face centre in [-1, 1] (image coordinates, x right, y down),
  dist_m: median depth inside the face box, track_id: stable while it is the same box, fps.
"""
import threading
import time

import numpy as np

from .log import log

MODEL = "/opt/robot/nanterino/models/vision/face_detection_yunet_2023mar.onnx"
TRT_ENGINE = "/opt/robot/nanterino/models/vision/yunet_640_fp16.engine"  # GPU path (build-yunet-trt)
W, H, FPS = 640, 480, 15  # 15 fps is plenty for gaze following; 30 fps cost ~1.75 CPU cores
DETECT_W = 320          # detection runs on a half-size image: ~4x cheaper, enough at 3 m
IDLE_SKIP = 3           # no face for LOST_AFTER_S: process 1 frame in 3 (15 -> 5 fps)
LOST_AFTER_S = 0.6      # keep the last position briefly so the eyes do not jump on a missed frame


def _iou(a, b) -> float:
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix, iy = max(0, min(ax + aw, bx + bw) - max(ax, bx)), max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / float(aw * ah + bw * bh - inter + 1e-6)


class Vision:
    def __init__(self, max_dist_m: float = 3.0, lost_face_s: float = 10.0):
        self.max_dist_m = max_dist_m
        self.lost_face_s = lost_face_s  # absence needed before on_face_lost fires
        self.state = {"present": False, "x": 0.0, "y": 0.0, "dist_m": None, "track_id": None, "fps": 0.0,
                      "camera": False, "faces": 0}
        self._box, self._last_seen, self._next_id = None, 0.0, 1
        self.on_face = None  # optional callback(dist_m) when a face appears within max_dist_m
        self.on_face_lost = None  # optional callback() once, after lost_face_s without any face
        self.on_faces = None  # optional callback(count) for every processed frame: faces seen within max_dist_m
        self._lost_fired = False
        threading.Thread(target=self._run, daemon=True, name="vision").start()

    def _run(self):
        while True:  # survives camera unplug/replug: retry every 5 s
            try:
                self._loop()
            except Exception as e:
                self.state = {**self.state, "present": False, "camera": False, "faces": 0}
                if self.on_faces:
                    self.on_faces(0)
                log.warning("vision stopped: %s (retry in 5 s)", e)
                time.sleep(5)

    def _loop(self):
        import cv2
        import pyrealsense2 as rs
        cv2.setNumThreads(2)  # leave CPU for STT/TTS/LLM orchestration
        pipe, cfg = rs.pipeline(), rs.config()
        cfg.enable_stream(rs.stream.color, W, H, rs.format.bgr8, FPS)
        cfg.enable_stream(rs.stream.depth, W, H, rs.format.z16, FPS)
        prof = pipe.start(cfg)
        scale = prof.get_device().first_depth_sensor().get_depth_scale()
        align = rs.align(rs.stream.color)
        dh = int(H * DETECT_W / W)
        # GPU first (TensorRT, full resolution, ~8% CPU); CPU OpenCV at half resolution as fallback.
        try:
            from .yunet_trt import YuNetTRT
            gpu = YuNetTRT(TRT_ENGINE)
            detect, k, backend = gpu.detect, 1.0, "tensorrt-gpu"
        except Exception as e:
            log.warning("tensorrt detector unavailable (%s): using CPU fallback", e)
            det = cv2.FaceDetectorYN.create(MODEL, "", (DETECT_W, dh), score_threshold=0.75)
            detect = lambda img: det.detect(cv2.resize(img, (DETECT_W, dh)))[1]  # noqa: E731
            k, backend = W / DETECT_W, "opencv-cpu"
        self.state["backend"] = backend
        log.info("vision started camera=RealSense %dx%d@%d backend=%s", W, H, FPS, backend)
        frames, t_fps, skip = 0, time.monotonic(), 0
        try:
            while True:
                raw = pipe.wait_for_frames(5000)
                # Idle throttle: with nobody in view, look at 1 frame in IDLE_SKIP (~5 fps) and drop
                # the rest unprocessed; the first detection brings full rate back at once.
                now = time.monotonic()
                idle = not self.state["present"] and now - self._last_seen > LOST_AFTER_S
                if idle:
                    skip = (skip + 1) % IDLE_SKIP
                    if skip:
                        continue
                else:
                    skip = 0
                # align_to(color) leaves the colour frame untouched, so detect on the raw colour
                # frame and pay for depth alignment only when a face was found (same distances).
                color = np.asanyarray(raw.get_color_frame().get_data())
                faces = detect(color)
                depth = None
                if faces is not None and len(faces):
                    depth = np.asanyarray(align.process(raw).get_depth_frame().get_data())
                self._update(faces, depth, scale, k)
                del color, depth, raw  # nothing kept beyond this frame
                frames += 1
                now = time.monotonic()
                if now - t_fps >= 2:
                    self.state["fps"] = round(frames / (now - t_fps), 1)
                    frames, t_fps = 0, now
                self.state["camera"] = True
        finally:
            pipe.stop()

    def _update(self, faces, depth, scale, k):
        now = time.monotonic()
        cands = []
        for f in (faces if faces is not None else []):
            x, y, w, h = (f[:4] * k).astype(int)
            x, y = max(0, x), max(0, y)
            roi = depth[y:y + h, x:x + w]
            v = roi[roi > 0]
            dist = float(np.median(v)) * scale if v.size else None
            if dist is not None and dist > self.max_dist_m:
                continue  # people further than 3 m are ignored (F01)
            cands.append(((x, y, w, h), dist))
        # Every detection within range counts (the tracker below keeps following ONE face); an anonymous
        # count only, used for the `personnes_multiples` event and the idle timer.
        self.state["faces"] = len(cands)
        if self.on_faces:
            self.on_faces(len(cands))
        if not cands:
            if self.state["present"] and now - self._last_seen > LOST_AFTER_S:
                self.state.update(present=False, track_id=None)
                self._box = None
            # Fire once per absence, only after a face was really seen (_last_seen > 0).
            if (self.on_face_lost and not self._lost_fired and self._last_seen
                    and now - self._last_seen > self.lost_face_s):
                self._lost_fired = True
                self.on_face_lost()
            return
        self._lost_fired = False
        # F02: keep following the same person (best overlap with the previous box); otherwise the
        # largest (closest) face. A second person passing behind does not steal the gaze.
        if self._box is not None:
            best = max(cands, key=lambda c: _iou(c[0], self._box))
            if _iou(best[0], self._box) < 0.2:
                best = max(cands, key=lambda c: c[0][2] * c[0][3])
                self._next_id += 1
        else:
            best = max(cands, key=lambda c: c[0][2] * c[0][3])
            self._next_id += 1
            if self.on_face:
                self.on_face(best[1])
        (x, y, w, h), dist = best
        self._box, self._last_seen = (x, y, w, h), now
        self.state.update(present=True, track_id=self._next_id,
                          x=round((x + w / 2) / W * 2 - 1, 3), y=round((y + h / 2) / H * 2 - 1, 3),
                          dist_m=round(dist, 2) if dist else None)
