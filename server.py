import os
import io
import cv2
import av
import tempfile
import threading
from typing import Optional, List, Dict
from fastapi import FastAPI, File, UploadFile, Query, HTTPException, BackgroundTasks
from fastapi.responses import Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="FrameStudio Engine", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Estrutura em memoria por video:
# {
#   video_id: {
#       "path": str,
#       "rotation": int,
#       "width": int,
#       "height": int,
#       "fps": float,
#       "duration": float,
#       "total_frames": int,
#       "preview_cache": Dict[int, bytes], # key = int(time * 20) -> jpeg bytes
#       "keyframes": List[dict],
#       "is_indexed": bool
#   }
# }
VIDEO_REGISTRY = {}

def apply_aspect_ratio_crop(image, aspect_ratio: str):
    """Aplica recorte proporcional centralizado preservando resolucao maxima."""
    if not aspect_ratio or aspect_ratio == "original":
        return image

    h, w = image.shape[:2]
    ratios = {
        "16:9": 16 / 9,
        "9:16": 9 / 16,
        "1:1": 1 / 1,
        "4:5": 4 / 5,
    }

    target_ratio = ratios.get(aspect_ratio)
    if not target_ratio:
        return image

    current_ratio = w / h
    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        x_start = int((w - new_w) / 2)
        return image[:, x_start:x_start + new_w]
    else:
        new_h = int(w / target_ratio)
        y_start = int((h - new_h) / 2)
        return image[y_start:y_start + new_h, :]

def correct_frame_orientation(img, rotation: int):
    """Garante que o frame fique sempre na orientacao correta (vertical em pe)."""
    if rotation == 90 and img.shape[0] < img.shape[1]:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    elif rotation == 270 and img.shape[0] < img.shape[1]:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img

def background_index_video(video_id: str):
    """Gera cache rapido de frames de preview em background para permitir scrubbing a 60 FPS."""
    meta = VIDEO_REGISTRY.get(video_id)
    if not meta:
        return

    try:
        container = av.open(meta["path"])
        stream = container.streams.video[0]
        time_base = float(stream.time_base)
        rotation = meta["rotation"]

        for frame in container.decode(stream):
            t = float(frame.pts * time_base) if frame.pts is not None else 0.0
            key = int(round(t, 2) * 20) # 1 frame a cada 0.05s
            if key not in meta["preview_cache"]:
                img = frame.to_ndarray(format="bgr24")
                img = correct_frame_orientation(img, rotation)
                
                # Redimensiona para preview rapido
                h, w = img.shape[:2]
                preview_w = 480
                preview_h = int(h * (preview_w / w))
                preview = cv2.resize(img, (preview_w, preview_h), interpolation=cv2.INTER_LINEAR)
                
                _, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 80])
                meta["preview_cache"][key] = encoded.tobytes()

        container.close()
        meta["is_indexed"] = True
    except Exception as e:
        print(f"[ERRO] Falha na indexacao em background para {video_id}: {e}")

@app.post("/api/upload")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Recebe o video, detecta rotacao, extrai metadados e primeiro frame imediatamente."""
    try:
        file_ext = os.path.splitext(file.filename)[1] or ".mp4"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_ext, dir=CACHE_DIR)
        video_id = os.path.basename(temp_file.name)

        contents = await file.read()
        temp_file.write(contents)
        temp_file.close()

        video_path = temp_file.name

        # Detecta rotacao e metadados via OpenCV
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
        rot_meta = cap.get(cv2.CAP_PROP_ORIENTATION_META)
        rotation = int(rot_meta) if rot_meta else 0

        raw_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        raw_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0.0

        # Le o primeiro frame imediatamente para pre-aquecer
        ret, first_frame = cap.read()
        cap.release()

        # Ajusta dimensoes baseadas na rotacao
        if rotation in (90, 270) and raw_w > raw_h:
            final_width, final_height = raw_h, raw_w
        else:
            final_width, final_height = raw_w, raw_h

        preview_cache = {}
        if ret and first_frame is not None:
            first_frame = correct_frame_orientation(first_frame, rotation)
            h, w = first_frame.shape[:2]
            p_w = 480
            p_h = int(h * (p_w / w))
            first_preview = cv2.resize(first_frame, (p_w, p_h), interpolation=cv2.INTER_LINEAR)
            _, enc = cv2.imencode(".jpg", first_preview, [cv2.IMWRITE_JPEG_QUALITY, 85])
            preview_cache[0] = enc.tobytes()

        # Registra o video
        VIDEO_REGISTRY[video_id] = {
            "path": video_path,
            "rotation": rotation,
            "width": final_width,
            "height": final_height,
            "fps": round(fps, 2),
            "duration": round(duration, 3),
            "total_frames": total_frames,
            "preview_cache": preview_cache,
            "is_indexed": False
        }

        # Dispara indexacao de preview em background
        background_tasks.add_task(background_index_video, video_id)

        return {
            "video_id": video_id,
            "filename": file.filename,
            "width": final_width,
            "height": final_height,
            "fps": round(fps, 2),
            "total_frames": total_frames,
            "duration": round(duration, 3)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar video: {str(e)}")

@app.get("/api/preview")
async def get_preview_frame(video_id: str = Query(...), time: float = Query(0.0)):
    """Retorna o frame de preview do cache em memoria em < 1ms para scrubbing a 60 FPS."""
    meta = VIDEO_REGISTRY.get(video_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Video nao encontrado.")

    key = int(round(time, 2) * 20)
    cache = meta["preview_cache"]

    # Se estiver exatamente no cache
    if key in cache:
        return Response(content=cache[key], media_type="image/jpeg")

    # Busca a chave mais proxima no cache existente
    if cache:
        closest_key = min(cache.keys(), key=lambda k: abs(k - key))
        return Response(content=cache[closest_key], media_type="image/jpeg")

    # Fallback: decodifica diretamente via OpenCV
    cap = cv2.VideoCapture(meta["path"])
    cap.set(cv2.CAP_PROP_POS_MSEC, time * 1000.0)
    ret, frame = cap.read()
    cap.release()

    if ret and frame is not None:
        frame = correct_frame_orientation(frame, meta["rotation"])
        h, w = frame.shape[:2]
        p_w = 480
        p_h = int(h * (p_w / w))
        preview = cv2.resize(frame, (p_w, p_h), interpolation=cv2.INTER_LINEAR)
        _, enc = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return Response(content=enc.tobytes(), media_type="image/jpeg")

    raise HTTPException(status_code=500, detail="Erro ao decodificar preview.")

@app.get("/api/frame")
async def get_full_resolution_frame(
    video_id: str = Query(...),
    time: float = Query(0.0),
    format: str = Query("jpeg"),
    aspect_ratio: str = Query("original")
):
    """Extrai o frame em resolucao nativa maxima (4K original) com orientacao correta."""
    meta = VIDEO_REGISTRY.get(video_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Video nao encontrado.")

    video_path = meta["path"]
    rotation = meta["rotation"]

    try:
        container = av.open(video_path)
        stream = container.streams.video[0]
        time_base = float(stream.time_base)

        target_pts = int(time / time_base)
        container.seek(target_pts, stream=stream)

        best_frame = None
        min_diff = float("inf")

        for frame in container.decode(stream):
            curr_time = float(frame.pts * time_base) if frame.pts is not None else 0.0
            diff = abs(curr_time - time)
            if diff < min_diff:
                min_diff = diff
                best_frame = frame
            if curr_time > time + 0.15:
                break

        container.close()

        if best_frame is None:
            raise HTTPException(status_code=500, detail="Nao foi possivel localizar o frame.")

        img = best_frame.to_ndarray(format="bgr24")
        img = correct_frame_orientation(img, rotation)
        img = apply_aspect_ratio_crop(img, aspect_ratio)

        if format.lower() == "png":
            success, encoded_img = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            media_type = "image/png"
        else:
            success, encoded_img = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 98])
            media_type = "image/jpeg"

        if not success:
            raise HTTPException(status_code=500, detail="Erro ao codificar frame.")

        return Response(content=encoded_img.tobytes(), media_type=media_type)
    except Exception as e:
        # Fallback OpenCV
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, time * 1000.0)
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            frame = correct_frame_orientation(frame, rotation)
            frame = apply_aspect_ratio_crop(frame, aspect_ratio)
            if format.lower() == "png":
                _, enc = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
                return Response(content=enc.tobytes(), media_type="image/png")
            else:
                _, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 98])
                return Response(content=enc.tobytes(), media_type="image/jpeg")

        raise HTTPException(status_code=500, detail=f"Erro ao extrair frame: {str(e)}")

@app.get("/api/samples")
async def get_samples(video_id: str = Query(...), count: int = Query(12)):
    """Gera as miniaturas sugeridas em < 1s com orientacao vertical correta."""
    meta = VIDEO_REGISTRY.get(video_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Video nao encontrado.")

    video_path = meta["path"]
    rotation = meta["rotation"]
    duration = meta["duration"]

    if count < 1:
        count = 12

    margin = duration * 0.02
    effective_duration = duration - (margin * 2)
    step = effective_duration / (count - 1) if count > 1 else 0

    samples = []
    import base64

    # Utiliza PyAV com skip_frame NONKEY para extracao instantanea
    try:
        container = av.open(video_path)
        stream = container.streams.video[0]
        stream.codec_context.skip_frame = "NONKEY"
        time_base = float(stream.time_base)

        keyframes = []
        for frame in container.decode(stream):
            t = float(frame.pts * time_base) if frame.pts is not None else 0.0
            img = frame.to_ndarray(format="bgr24")
            img = correct_frame_orientation(img, rotation)
            h, w = img.shape[:2]
            thumb_w = 270
            thumb_h = int(h * (thumb_w / w))
            thumb = cv2.resize(img, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
            keyframes.append((t, thumb))

        container.close()

        if len(keyframes) >= count:
            # Seleciona N distribuidos
            step_kf = len(keyframes) / count
            selected = [keyframes[int(i * step_kf)] for i in range(count)]
        else:
            selected = keyframes

        for t, thumb in selected:
            _, encoded = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
            base64_str = base64.b64encode(encoded.tobytes()).decode("utf-8")
            data_url = f"data:image/jpeg;base64,{base64_str}"

            hours = int(t // 3600)
            minutes = int((t % 3600) // 60)
            seconds = int(t % 60)
            millis = int((t % 1) * 1000)
            time_formatted = f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"

            samples.append({
                "time": round(t, 3),
                "timeFormatted": time_formatted,
                "dataUrl": data_url
            })
    except Exception as e:
        print(f"[AVISO] Erro na amostragem rapida: {e}")

    return {"samples": samples}

# Servir Frontend
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    print("[INFO] Iniciando FrameStudio Engine na porta 5522...")
    uvicorn.run(app, host="127.0.0.1", port=5522, log_level="info")
