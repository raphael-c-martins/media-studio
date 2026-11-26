"""Rastreamento de placas e exportação MP4 com desfoque, corte e controle de áudio.

Funções síncronas pensadas para execução em thread dedicada via asyncio.to_thread.
Toda coordenada recebida e emitida é normalizada [0.0, 1.0] no espaço pós-rotação,
e o tempo canônico de sincronização é sempre o timestamp real em segundos (PTS).
"""
from bisect import bisect_right
from collections import deque
from fractions import Fraction
import logging
from typing import Callable, Dict, List, Optional, Tuple

import av
import cv2
import numpy as np

from app import config
from app.frames import engine

logger = logging.getLogger("media_studio.frames.video_blur")

CONTEXT_EXPAND = 1.35
TRACK_SCALES = (0.96, 1.0, 1.04)
SCALE_CHECK_INTERVAL = 4
ACCEPT_SCORE = 0.42
UPDATE_SCORE = 0.72
INIT_VERIFY_SCORE = 0.55
REACQUIRE_SCORE = 0.58
LOST_STREAK_LIMIT = 3
LOW_CONFIDENCE_THRESHOLD = 0.55
VALID_AAC_RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _clamp_box(x: float, y: float, w: float, h: float) -> Tuple[float, float, float, float]:
    cw = max(0.004, min(1.0, float(w)))
    ch = max(0.004, min(1.0, float(h)))
    cx = max(0.0, min(1.0 - cw, float(x)))
    cy = max(0.0, min(1.0 - ch, float(y)))
    return cx, cy, cw, ch


def _check_abort(should_stop: Optional[Callable[[], bool]]) -> None:
    if should_stop and should_stop():
        raise RuntimeError("Operação interrompida porque o vídeo foi fechado.")


def resolve_box_at_time(keyframes: List[Dict], t: float) -> Optional[Tuple[float, float, float, float]]:
    """Resolve a caixa normalizada (x, y, w, h) no instante `t`, sem interpolar sobre lacunas ocultas."""
    if not keyframes:
        return None
    if len(keyframes) == 1:
        kf = keyframes[0]
        if not kf.get("visible", True):
            return None
        return _clamp_box(kf["x"], kf["y"], kf["w"], kf["h"])

    times = [float(k["t"]) for k in keyframes]
    if t < times[0] - 1e-4 or t > times[-1] + 1e-4:
        return None
    if t <= times[0] + 1e-4:
        first = keyframes[0]
        return _clamp_box(first["x"], first["y"], first["w"], first["h"]) if first.get("visible", True) else None
    if t >= times[-1] - 1e-4:
        last = keyframes[-1]
        return _clamp_box(last["x"], last["y"], last["w"], last["h"]) if last.get("visible", True) else None

    idx = bisect_right(times, t) - 1
    idx = max(0, min(len(keyframes) - 2, idx))
    k0 = keyframes[idx]
    k1 = keyframes[idx + 1]

    if abs(t - float(k1["t"])) <= 1e-4:
        return _clamp_box(k1["x"], k1["y"], k1["w"], k1["h"]) if k1.get("visible", True) else None
    if not k0.get("visible", True):
        return None
    if not k1.get("visible", True):
        return _clamp_box(k0["x"], k0["y"], k0["w"], k0["h"])

    dt = float(k1["t"]) - float(k0["t"])
    if dt <= 1e-6:
        return _clamp_box(k0["x"], k0["y"], k0["w"], k0["h"])

    alpha = max(0.0, min(1.0, (t - float(k0["t"])) / dt))
    x = float(k0["x"]) + (float(k1["x"]) - float(k0["x"])) * alpha
    y = float(k0["y"]) + (float(k1["y"]) - float(k0["y"])) * alpha
    w = float(k0["w"]) + (float(k1["w"]) - float(k0["w"])) * alpha
    h = float(k0["h"]) + (float(k1["h"]) - float(k0["h"])) * alpha
    return _clamp_box(x, y, w, h)


def _obfuscate_roi(roi: np.ndarray, style: str, strength: int) -> np.ndarray:
    roi_h, roi_w = roi.shape[:2]
    if style == "solid":
        mean_bgr = np.mean(roi.reshape(-1, 3), axis=0) * 0.25
        filled = np.empty_like(roi)
        filled[:, :] = np.clip(mean_bgr, 12, 64).astype(np.uint8)
        return filled

    if style == "blur":
        k = int(round(min(roi_w, roi_h) * (0.35 + strength / 40.0))) | 1
        k = max(15, min(99, k))
        blurred = cv2.GaussianBlur(roi, (k, k), 0)
        return cv2.GaussianBlur(blurred, (k, k), 0)

    # pixelate (padrão): reduz a poucos blocos e suaviza bordas para tornar ilegível.
    step = max(6, int(strength))
    cols = max(3, min(14, int(round(roi_w / step))))
    rows = max(2, min(8, int(round(roi_h / step))))
    tiny = cv2.resize(roi, (cols, rows), interpolation=cv2.INTER_AREA)
    pixelated = cv2.resize(tiny, (roi_w, roi_h), interpolation=cv2.INTER_LINEAR)
    k = max(3, min(15, (min(roi_w, roi_h) // 10) | 1))
    return cv2.GaussianBlur(pixelated, (k, k), 0)


def apply_masks_to_frame(image: np.ndarray, t: float, tracks: List[Dict]) -> np.ndarray:
    """Aplica todas as máscaras ativas no instante `t` sobre `image` (in-place)."""
    if not tracks:
        return image
    img_h, img_w = image.shape[:2]
    for track in tracks:
        keyframes = track.get("keyframes") or []
        box = resolve_box_at_time(keyframes, t)
        if box is None:
            continue
        nx, ny, nw, nh = box
        margin = max(0.0, min(0.5, float(track.get("margin", 0.15))))
        style = str(track.get("style", "pixelate"))
        strength = int(track.get("strength", 16))

        cx = nx + nw * 0.5
        cy = ny + nh * 0.5
        ew = nw * (1.0 + 2.0 * margin)
        eh = nh * (1.0 + 2.0 * margin)

        x1 = max(0, min(img_w - 2, int(round((cx - ew * 0.5) * img_w))))
        y1 = max(0, min(img_h - 2, int(round((cy - eh * 0.5) * img_h))))
        x2 = max(x1 + 2, min(img_w, int(round((cx + ew * 0.5) * img_w))))
        y2 = max(y1 + 2, min(img_h, int(round((cy + eh * 0.5) * img_h))))

        roi = image[y1:y2, x1:x2]
        if roi.size == 0:
            continue
        image[y1:y2, x1:x2] = _obfuscate_roi(roi, style, strength)
    return image


def _work_dimensions(width: int, height: int) -> Tuple[int, int]:
    max_side = 640
    scale = min(1.0, max_side / max(1, max(width, height)))
    work_w = max(2, int(round(width * scale)))
    work_h = max(2, int(round(height * scale)))
    if width >= 360 and work_w < 360:
        scale_min = min(1.0, 360.0 / width)
        work_w = int(round(width * scale_min))
        work_h = int(round(height * scale_min))
    return max(16, work_w), max(16, work_h)


def _to_work_gray(bgr: np.ndarray, work_w: int, work_h: int) -> np.ndarray:
    resized = cv2.resize(bgr, (work_w, work_h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (3, 3), 0)


def _extract_context_patch(
    gray: np.ndarray, cx: float, cy: float, bw: float, bh: float
) -> Optional[Tuple[np.ndarray, int, int]]:
    img_h, img_w = gray.shape[:2]
    pw = max(8, min(img_w - 2, int(round(bw * CONTEXT_EXPAND))))
    ph = max(8, min(img_h - 2, int(round(bh * CONTEXT_EXPAND))))
    x1 = max(0, min(img_w - pw, int(round(cx - pw * 0.5))))
    y1 = max(0, min(img_h - ph, int(round(cy - ph * 0.5))))
    patch = gray[y1:y1 + ph, x1:x1 + pw]
    if patch.shape[0] < 6 or patch.shape[1] < 6:
        return None
    return patch.astype(np.float32), x1, y1


def _match_in_window(
    gray: np.ndarray,
    tpl: np.ndarray,
    pred_cx: float,
    pred_cy: float,
    bw: float,
    bh: float,
    lost_streak: int,
    allow_scales: bool,
) -> Tuple[float, float, float, float, float]:
    """Busca o melhor casamento em janela local (retorna score, cx, cy, scale_factor, best_tpl)."""
    img_h, img_w = gray.shape[:2]
    tpl_h, tpl_w = tpl.shape[:2]
    mult = 2.0 if lost_streak > 0 else 1.0
    pad_x = max(int(round(bw * 1.6 * mult)), int(round(img_w * 0.10 * mult)))
    pad_y = max(int(round(bh * 1.6 * mult)), int(round(img_h * 0.10 * mult)))

    sx1 = max(0, int(round(pred_cx - tpl_w * 0.5 - pad_x)))
    sy1 = max(0, int(round(pred_cy - tpl_h * 0.5 - pad_y)))
    sx2 = min(img_w, int(round(pred_cx + tpl_w * 0.5 + pad_x)))
    sy2 = min(img_h, int(round(pred_cy + tpl_h * 0.5 + pad_y)))

    search = gray[sy1:sy2, sx1:sx2]
    if search.shape[0] < 8 or search.shape[1] < 8:
        return 0.0, pred_cx, pred_cy, 1.0, 0.0

    scales = TRACK_SCALES if allow_scales else (1.0,)
    best_score = -1.0
    best_cx, best_cy, best_scale = pred_cx, pred_cy, 1.0
    for sc in scales:
        tw = max(6, int(round(tpl_w * sc)))
        th = max(6, int(round(tpl_h * sc)))
        if tw >= search.shape[1] or th >= search.shape[0]:
            continue
        scaled_tpl = tpl if sc == 1.0 else cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(search, scaled_tpl.astype(np.uint8), cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = float(max_val)
            best_cx = sx1 + max_loc[0] + tw * 0.5
            best_cy = sy1 + max_loc[1] + th * 0.5
            best_scale = sc
    return best_score, best_cx, best_cy, best_scale, best_score


class _DirectionalTracker:
    """Estado de rastreamento unidirecional a partir de um quadro âncora."""

    def __init__(self, anchor_gray: np.ndarray, norm_box: Tuple[float, float, float, float]):
        self.img_h, self.img_w = anchor_gray.shape[:2]
        nx, ny, nw, nh = norm_box
        self.bw = max(6.0, nw * self.img_w)
        self.bh = max(6.0, nh * self.img_h)
        self.init_bw = self.bw
        self.init_bh = self.bh
        self.cx = (nx + nw * 0.5) * self.img_w
        self.cy = (ny + nh * 0.5) * self.img_h
        self.vx = 0.0
        self.vy = 0.0
        self.lost_streak = 0
        self.step_idx = 0

        extracted = _extract_context_patch(anchor_gray, self.cx, self.cy, self.bw, self.bh)
        if extracted is None:
            raise ValueError("A região marcada é pequena demais para rastrear.")
        self.tpl_init = extracted[0]
        self.tpl_curr = self.tpl_init.copy()

    def step(self, gray: np.ndarray, t: float) -> Dict:
        self.step_idx += 1
        max_step = max(8.0, 0.6 * max(self.bw, self.bh))
        pred_vx = max(-max_step, min(max_step, 0.5 * self.vx))
        pred_vy = max(-max_step, min(max_step, 0.5 * self.vy))
        pred_cx = max(0.0, min(float(self.img_w), self.cx + pred_vx))
        pred_cy = max(0.0, min(float(self.img_h), self.cy + pred_vy))

        allow_scales = (self.step_idx % SCALE_CHECK_INTERVAL == 0) or (self.lost_streak > 0)
        score, found_cx, found_cy, sc, _ = _match_in_window(
            gray, self.tpl_curr, pred_cx, pred_cy, self.bw, self.bh, self.lost_streak, allow_scales
        )

        # Verifica contra o template inicial caso tenha entrado em streak perdido ou para evitar drift.
        init_score = score
        if self.lost_streak >= LOST_STREAK_LIMIT:
            init_score, init_cx, init_cy, init_sc, _ = _match_in_window(
                gray, self.tpl_init, pred_cx, pred_cy, self.init_bw, self.init_bh, self.lost_streak, True
            )
            if init_score >= REACQUIRE_SCORE:
                score, found_cx, found_cy, sc = init_score, init_cx, init_cy, init_sc
                self.bw = max(6.0, min(self.init_bw * 2.0, self.init_bw * init_sc))
                self.bh = max(6.0, min(self.init_bh * 2.0, self.init_bh * init_sc))
            else:
                score = min(score, init_score)

        threshold = REACQUIRE_SCORE if self.lost_streak >= LOST_STREAK_LIMIT else ACCEPT_SCORE
        if score >= threshold:
            new_cx = 0.8 * found_cx + 0.2 * pred_cx if self.lost_streak == 0 else found_cx
            new_cy = 0.8 * found_cy + 0.2 * pred_cy if self.lost_streak == 0 else found_cy
            self.vx = new_cx - self.cx
            self.vy = new_cy - self.cy
            self.cx, self.cy = new_cx, new_cy

            if sc != 1.0:
                self.bw = max(6.0, max(self.init_bw * 0.5, min(self.init_bw * 2.0, self.bw * sc)))
                self.bh = max(6.0, max(self.init_bh * 0.5, min(self.init_bh * 2.0, self.bh * sc)))

            self.lost_streak = 0
            if score >= UPDATE_SCORE:
                cand = _extract_context_patch(gray, self.cx, self.cy, self.bw, self.bh)
                if cand is not None:
                    patch = cand[0]
                    resized_init = cv2.resize(
                        self.tpl_init.astype(np.uint8), (patch.shape[1], patch.shape[0]), interpolation=cv2.INTER_AREA
                    )
                    corr = cv2.matchTemplate(patch.astype(np.uint8), resized_init, cv2.TM_CCOEFF_NORMED)
                    if float(corr[0, 0]) >= INIT_VERIFY_SCORE:
                        curr_resized = cv2.resize(
                            self.tpl_curr, (patch.shape[1], patch.shape[0]), interpolation=cv2.INTER_AREA
                        )
                        self.tpl_curr = 0.85 * curr_resized + 0.15 * patch

            nx, ny, nw, nh = _clamp_box(
                (self.cx - self.bw * 0.5) / self.img_w,
                (self.cy - self.bh * 0.5) / self.img_h,
                self.bw / self.img_w,
                self.bh / self.img_h,
            )
            return {
                "t": round(t, 4),
                "x": round(nx, 5),
                "y": round(ny, 5),
                "w": round(nw, 5),
                "h": round(nh, 5),
                "visible": True,
                "source": "auto",
                "confidence": round(max(0.0, min(1.0, score)), 3),
            }

        self.lost_streak += 1
        self.vx *= 0.4
        self.vy *= 0.4
        visible = self.lost_streak < LOST_STREAK_LIMIT
        nx, ny, nw, nh = _clamp_box(
            (self.cx - self.bw * 0.5) / self.img_w,
            (self.cy - self.bh * 0.5) / self.img_h,
            self.bw / self.img_w,
            self.bh / self.img_h,
        )
        return {
            "t": round(t, 4),
            "x": round(nx, 5),
            "y": round(ny, 5),
            "w": round(nw, 5),
            "h": round(nh, 5),
            "visible": visible,
            "source": "auto",
            "confidence": round(max(0.0, min(1.0, score)), 3),
        }


def track_region_in_video(
    path: str,
    rotation: int,
    anchor_time: float,
    box: Dict[str, float],
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    direction: str = "both",
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict:
    """Rastreia uma placa no intervalo pedido a partir de `anchor_time`."""
    norm_box = _clamp_box(box["x"], box["y"], box["w"], box["h"])
    want_backward = direction in ("both", "backward")
    want_forward = direction in ("both", "forward")
    truncated = False

    with av.open(path) as container:
        if not container.streams.video:
            raise ValueError("Nenhuma faixa de vídeo encontrada.")
        stream = container.streams.video[0]
        time_base = float(stream.time_base)
        src_fps = float(stream.average_rate) if stream.average_rate else 30.0
        sample_step = max(1, int(round(src_fps / 30.0)))

        work_w: Optional[int] = None
        work_h: Optional[int] = None
        backward_buf: deque = deque(maxlen=config.MAX_BACKWARD_BUFFER)
        backward_dropped = False

        anchor_t: Optional[float] = None
        anchor_gray: Optional[np.ndarray] = None
        forward_tracker: Optional[_DirectionalTracker] = None
        forward_frames: List[Dict] = []
        sampled_count = 0
        raw_idx = -1

        seek_target = max(0.0, float(start_time))
        if direction == "forward":
            seek_target = max(seek_target, float(anchor_time) - 0.5)
        if seek_target > 0.2:
            try:
                container.seek(int(seek_target / time_base), stream=stream)
            except Exception:
                pass

        for frame in container.decode(stream):
            _check_abort(should_stop)
            raw_idx += 1
            pts_sec = float(frame.pts * time_base) if frame.pts is not None else (raw_idx / max(1.0, src_fps))
            if pts_sec < start_time - 1e-4:
                continue
            if end_time is not None and pts_sec > end_time + 1e-4:
                break

            # Mantém o frame mais próximo do anchor mesmo quando sample_step > 1.
            near_anchor = anchor_gray is None and pts_sec >= anchor_time - (0.5 / max(1.0, src_fps))
            if (raw_idx % sample_step != 0) and not near_anchor:
                continue

            sampled_count += 1
            if sampled_count > config.MAX_TRACK_SAMPLES:
                truncated = True
                break

            bgr = engine.orient_pyav_frame(frame.to_ndarray(format="bgr24"), rotation)
            if work_w is None or work_h is None:
                work_w, work_h = _work_dimensions(bgr.shape[1], bgr.shape[0])
            gray = _to_work_gray(bgr, work_w, work_h)

            if anchor_gray is None:
                if pts_sec >= anchor_time - (0.5 / max(1.0, src_fps)):
                    anchor_gray = gray
                    anchor_t = pts_sec
                    if want_forward:
                        forward_tracker = _DirectionalTracker(anchor_gray, norm_box)
                else:
                    if want_backward:
                        if len(backward_buf) == backward_buf.maxlen:
                            backward_dropped = True
                        backward_buf.append((pts_sec, gray))
                    else:
                        # Guarda o último frame antes da âncora para caso anchor_time esteja além do último frame.
                        backward_buf.clear()
                        backward_buf.append((pts_sec, gray))
            elif want_forward and forward_tracker is not None:
                forward_frames.append(forward_tracker.step(gray, pts_sec))

        # Se anchor_time caiu após o último frame lido, usa o último disponível como âncora.
        if anchor_gray is None and backward_buf:
            anchor_t, anchor_gray = backward_buf.pop()

        if anchor_gray is None or anchor_t is None:
            raise ValueError("Não foi possível localizar o quadro inicial para rastreamento.")

        backward_frames: List[Dict] = []
        if want_backward and backward_buf:
            back_tracker = _DirectionalTracker(anchor_gray, norm_box)
            for b_t, b_gray in reversed(backward_buf):
                _check_abort(should_stop)
                backward_frames.append(back_tracker.step(b_gray, b_t))
            backward_frames.reverse()
            if backward_dropped:
                truncated = True

    anchor_kf = {
        "t": round(anchor_t, 4),
        "x": round(norm_box[0], 5),
        "y": round(norm_box[1], 5),
        "w": round(norm_box[2], 5),
        "h": round(norm_box[3], 5),
        "visible": True,
        "source": "manual",
        "confidence": 1.0,
    }
    keyframes = backward_frames + [anchor_kf] + forward_frames
    return {
        "anchor_time": round(anchor_t, 4),
        "keyframes": keyframes,
        "tracked_frames": len(keyframes),
        "visible_frames": sum(1 for k in keyframes if k["visible"]),
        "low_confidence_frames": sum(
            1 for k in keyframes if k["visible"] and float(k["confidence"]) < LOW_CONFIDENCE_THRESHOLD
        ),
        "truncated": truncated,
    }


def _fit_export_frame(
    bgr: np.ndarray,
    apply_crop: bool,
    aspect_ratio: str,
    focus_x: float,
    focus_y: float,
    zoom: float,
    standardize: bool,
    fit_mode: str,
) -> np.ndarray:
    if apply_crop:
        target_size = engine.resolve_output_size(aspect_ratio, standardize=standardize)
        bgr = engine.apply_aspect_ratio_crop(
            bgr,
            aspect_ratio,
            focus_x=focus_x,
            focus_y=focus_y,
            zoom=zoom,
            output_size=target_size,
            fit_mode=fit_mode,
        )
    max_dim = config.MAX_EXPORT_DIMENSION
    h, w = bgr.shape[:2]
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        bgr = cv2.resize(bgr, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)
        h, w = bgr.shape[:2]

    even_w = max(2, w & ~1)
    even_h = max(2, h & ~1)
    if even_w != w or even_h != h:
        bgr = bgr[:even_h, :even_w]
    return bgr


def _pick_aac_rate(raw_rate: Optional[int]) -> int:
    if raw_rate and raw_rate in VALID_AAC_RATES:
        return int(raw_rate)
    if raw_rate:
        return min(VALID_AAC_RATES, key=lambda r: abs(r - int(raw_rate)))
    return 44100


def _mux_trimmed_audio(
    input_path: str,
    out_container: av.container.OutputContainer,
    out_audio: av.audio.stream.AudioStream,
    t0: float,
    audio_end: float,
    should_stop: Optional[Callable[[], bool]] = None,
) -> None:
    """Decodifica, recorta no intervalo [t0, audio_end] e re-encoda para AAC alinhado em PTS=0."""
    resampler = av.AudioResampler(format="fltp", layout=out_audio.layout.name, rate=out_audio.rate)
    fifo = av.AudioFifo()
    frame_size = out_audio.codec_context.frame_size or 1024
    audio_pts = 0

    with av.open(input_path) as audio_container:
        if not audio_container.streams.audio:
            return
        in_audio = audio_container.streams.audio[0]
        time_base = float(in_audio.time_base)
        if t0 > 0.25:
            try:
                audio_container.seek(int(max(0.0, t0 - 0.1) / time_base), stream=in_audio)
            except Exception:
                pass

        for af in audio_container.decode(in_audio):
            _check_abort(should_stop)
            af_start = float(af.pts * time_base) if af.pts is not None else 0.0
            af_rate = af.sample_rate or out_audio.rate
            af_dur = af.samples / max(1, af_rate)
            af_end = af_start + af_dur
            if af_end <= t0 + 1e-5:
                continue
            if af_start >= audio_end - 1e-5:
                break

            resampled_list = resampler.resample(af)
            for rf in resampled_list:
                arr = rf.to_ndarray()
                rf_rate = rf.sample_rate or out_audio.rate
                rf_dur = rf.samples / max(1, rf_rate)
                # Estima janela de rf relativa a af_start.
                start_cut = max(0, int(round((t0 - af_start) * rf_rate))) if af_start < t0 else 0
                end_cut = rf.samples
                if af_start + rf_dur > audio_end:
                    end_cut = min(rf.samples, max(0, int(round((audio_end - af_start) * rf_rate))))
                if end_cut <= start_cut:
                    continue
                if start_cut > 0 or end_cut < rf.samples:
                    arr = np.ascontiguousarray(arr[:, start_cut:end_cut])
                    trimmed = av.AudioFrame.from_ndarray(arr, format="fltp", layout=out_audio.layout.name)
                    trimmed.sample_rate = rf_rate
                    fifo.write(trimmed)
                else:
                    fifo.write(rf)

                while fifo.samples >= frame_size:
                    chunk = fifo.read(frame_size)
                    if chunk is None:
                        break
                    chunk.pts = audio_pts
                    chunk.time_base = Fraction(1, out_audio.rate)
                    audio_pts += chunk.samples
                    for packet in out_audio.encode(chunk):
                        out_container.mux(packet)

        for rf in resampler.resample(None):
            fifo.write(rf)
        while fifo.samples >= frame_size:
            chunk = fifo.read(frame_size)
            if chunk is None:
                break
            chunk.pts = audio_pts
            chunk.time_base = Fraction(1, out_audio.rate)
            audio_pts += chunk.samples
            for packet in out_audio.encode(chunk):
                out_container.mux(packet)
        if fifo.samples > 0:
            tail = fifo.read(fifo.samples, partial=True)
            if tail is not None:
                tail.pts = audio_pts
                tail.time_base = Fraction(1, out_audio.rate)
                for packet in out_audio.encode(tail):
                    out_container.mux(packet)
        for packet in out_audio.encode():
            out_container.mux(packet)


def export_processed_video(
    input_path: str,
    output_path: str,
    rotation: int,
    tracks: List[Dict],
    trim_start: float = 0.0,
    trim_end: Optional[float] = None,
    mute_audio: bool = False,
    apply_crop: bool = False,
    aspect_ratio: str = "original",
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
    standardize: bool = False,
    fit_mode: str = "crop",
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict:
    """Exporta cópia MP4 (H.264 yuv420p + AAC opcional) com máscaras, corte e recorte aplicados."""
    in_container = av.open(input_path)
    out_container = av.open(output_path, mode="w", format="mp4", options={"movflags": "faststart"})
    out_video = None
    out_audio = None
    has_input_audio = False
    written_frames = 0
    t0: Optional[float] = None
    last_pts_sec = 0.0
    prev_pts = -1
    out_fps = Fraction(30, 1)

    try:
        if not in_container.streams.video:
            raise ValueError("Nenhuma faixa de vídeo encontrada.")
        in_video = in_container.streams.video[0]
        time_base = float(in_video.time_base)
        avg = in_video.average_rate
        if avg and 1 <= float(avg) <= 120:
            out_fps = Fraction(avg).limit_denominator(1000)

        has_input_audio = len(in_container.streams.audio) > 0
        if trim_start > 0.25:
            try:
                in_container.seek(int(max(0.0, trim_start - 0.1) / time_base), stream=in_video)
            except Exception:
                pass

        raw_idx = -1
        for frame in in_container.decode(in_video):
            _check_abort(should_stop)
            raw_idx += 1
            pts_sec = float(frame.pts * time_base) if frame.pts is not None else (raw_idx / float(out_fps))
            if pts_sec < trim_start - 1e-4:
                continue
            if trim_end is not None and pts_sec > trim_end + 1e-4:
                break

            bgr = engine.orient_pyav_frame(frame.to_ndarray(format="bgr24"), rotation)
            if tracks:
                apply_masks_to_frame(bgr, pts_sec, tracks)

            bgr = _fit_export_frame(
                bgr,
                apply_crop=apply_crop,
                aspect_ratio=aspect_ratio,
                focus_x=focus_x,
                focus_y=focus_y,
                zoom=zoom,
                standardize=standardize,
                fit_mode=fit_mode,
            )

            if out_video is None:
                t0 = pts_sec
                out_h, out_w = bgr.shape[:2]
                out_video = out_container.add_stream("libx264", rate=out_fps)
                out_video.width = out_w
                out_video.height = out_h
                out_video.pix_fmt = "yuv420p"
                out_video.options = {"crf": "20", "preset": "veryfast"}
                out_video.codec_context.time_base = Fraction(1, 90000)

                if not mute_audio and has_input_audio:
                    in_audio = in_container.streams.audio[0]
                    target_rate = _pick_aac_rate(in_audio.rate)
                    target_layout = "mono" if in_audio.channels == 1 else "stereo"
                    out_audio = out_container.add_stream("aac", rate=target_rate, layout=target_layout)
                    out_audio.bit_rate = 160000
            elif bgr.shape[1] != out_video.width or bgr.shape[0] != out_video.height:
                bgr = cv2.resize(bgr, (out_video.width, out_video.height), interpolation=cv2.INTER_AREA)

            assert t0 is not None
            vf = av.VideoFrame.from_ndarray(bgr, format="bgr24")
            pts_val = int(round((pts_sec - t0) * 90000))
            vf.pts = max(prev_pts + 1, pts_val)
            vf.time_base = Fraction(1, 90000)
            prev_pts = vf.pts

            for packet in out_video.encode(vf):
                out_container.mux(packet)
            written_frames += 1
            last_pts_sec = pts_sec

        if written_frames == 0 or out_video is None or t0 is None:
            raise ValueError("Nenhum quadro encontrado no trecho escolhido.")

        for packet in out_video.encode():
            out_container.mux(packet)

        in_container.close()
        frame_step = 1.0 / max(1.0, float(out_fps))
        audio_end = trim_end if trim_end is not None else (last_pts_sec + frame_step)

        if out_audio is not None:
            _mux_trimmed_audio(input_path, out_container, out_audio, t0, audio_end, should_stop=should_stop)

        duration = round(max(frame_step, last_pts_sec - t0 + frame_step), 3)
        audio_state = "muted" if mute_audio else ("kept" if out_audio is not None else "none")
        return {
            "frames": written_frames,
            "width": out_video.width,
            "height": out_video.height,
            "duration": duration,
            "audio": audio_state,
        }
    finally:
        try:
            in_container.close()
        except Exception:
            pass
        try:
            out_container.close()
        except Exception:
            pass
