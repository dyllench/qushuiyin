"""
视频去水印 Web 后端 (FastAPI)。

接口:
  POST /api/upload          上传视频,返回 video_id + 首帧图(给前端拖框) + 宽高
  POST /api/process         传入 video_id + 水印框 + 选项,后台开始处理,返回 job_id
  GET  /api/jobs/{job_id}    查询进度/状态
  GET  /api/download/{job_id} 下载成品

同时把 static/index.html 作为网页界面挂在 /。
本地运行:  uvicorn server:app --reload
"""
import base64
import os
import shutil
import threading
import time
import uuid
import zipfile

import cv2
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import dewatermark as dw
import processor

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD = os.path.join(BASE, "data", "uploads")
OUTPUT = os.path.join(BASE, "data", "outputs")
os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))

# 自动清理:删除超过 N 分钟的旧文件(上传 + 成品),默认 60 分钟,每 10 分钟扫一次
CLEANUP_TTL = int(os.environ.get("CLEANUP_TTL_MIN", "60")) * 60
CLEANUP_EVERY = 600


def _sweep():
    """删除 data/ 下超过 TTL 的旧文件。"""
    cutoff = time.time() - CLEANUP_TTL
    for d in (UPLOAD, OUTPUT):
        try:
            for name in os.listdir(d):
                p = os.path.join(d, name)
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
        except Exception:
            pass


def _janitor():
    _sweep()                       # 启动时先清一次(清掉上次遗留)
    while True:
        time.sleep(CLEANUP_EVERY)
        _sweep()


threading.Thread(target=_janitor, daemon=True).start()

app = FastAPI(title="视频去水印")

# 内存里的任务表(单实例、少量用户场景足够;重启即清空)
jobs: dict[str, dict] = {}


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")

# 处理好的图片:result_id -> 文件路径
image_files: dict[str, str] = {}


class ProcessReq(BaseModel):
    video_id: str
    regions: list[list[int]]          # [[x, y, w, h], ...](原始像素坐标)
    method: str = "delogo"            # delogo | inpaint
    motion: bool = False              # 移动水印
    tracker: str = "template"         # template | csrt | kcf | mil
    feather: int = 3
    radius: int = 3
    crf: int = 18


class ImageReq(BaseModel):
    image_id: str
    regions: list[list[int]]
    method: str = "inpaint"           # inpaint | delogo
    feather: int = 3
    radius: int = 3


async def _save_upload(file: UploadFile, allowed: tuple) -> tuple[str, str]:
    """保存上传文件,返回 (文件名, 完整路径);超限或格式不符抛 HTTPException。"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(400, f"不支持的格式: {ext or '未知'}")
    name = uuid.uuid4().hex + ext
    path = os.path.join(UPLOAD, name)
    size, limit = 0, MAX_UPLOAD_MB * 1024 * 1024
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                f.close()
                os.remove(path)
                raise HTTPException(413, f"文件超过 {MAX_UPLOAD_MB}MB 上限")
            f.write(chunk)
    return name, path


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    video_id, path = await _save_upload(file, VIDEO_EXTS)
    try:
        W, H, fps, has_audio = dw.ffprobe_info(path)
        frame = dw.grab_frame(path, 0)
    except Exception as e:
        os.path.exists(path) and os.remove(path)
        raise HTTPException(400, f"无法解析视频: {e}")

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64 = base64.b64encode(buf).decode()
    return {
        "video_id": video_id,
        "width": W, "height": H,
        "has_audio": has_audio,
        "frame": "data:image/jpeg;base64," + b64,
    }


@app.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...)):
    image_id, path = await _save_upload(file, IMAGE_EXTS)
    img = cv2.imread(path)
    if img is None:
        os.path.exists(path) and os.remove(path)
        raise HTTPException(400, "无法读取图片")
    H, W = img.shape[:2]
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64 = base64.b64encode(buf).decode()
    return {
        "image_id": image_id,
        "width": W, "height": H,
        "frame": "data:image/jpeg;base64," + b64,
    }


@app.post("/api/process-image")
def process_image_ep(req: ImageReq):
    path = os.path.join(UPLOAD, req.image_id)
    if not os.path.exists(path):
        raise HTTPException(404, "图片不存在,请重新上传")
    if not req.regions:
        raise HTTPException(400, "请先框选水印区域")

    result_id = uuid.uuid4().hex
    ext = os.path.splitext(req.image_id)[1] or ".png"
    out = os.path.join(OUTPUT, result_id + ext)
    try:
        processor.process_image(
            path, out, [list(r) for r in req.regions],
            method=req.method, feather=req.feather, radius=req.radius)
    except Exception as e:
        raise HTTPException(500, f"处理失败: {e}")
    image_files[result_id] = out
    return {"result_url": f"/api/download-image/{result_id}"}


@app.get("/api/download-image/{result_id}")
def download_image(result_id: str):
    path = image_files.get(result_id)
    if not path or not os.path.exists(path):
        raise HTTPException(404, "成品不存在")
    ext = os.path.splitext(path)[1].lstrip(".") or "png"
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
            "webp": "webp", "bmp": "bmp"}.get(ext, "png")
    return FileResponse(path, media_type=f"image/{mime}",
                        filename=f"nowm_{result_id[:8]}.{ext}")


# ---------------- 去背景(批量) ----------------
@app.post("/api/bg-process")
async def bg_process(files: list[UploadFile] = File(...),
                     mode: str = Form("ai"),
                     export: str = Form("transparent")):
    if not files:
        raise HTTPException(400, "请至少上传一张图片")
    saved = []
    for f in files:
        try:
            name, path = await _save_upload(f, IMAGE_EXTS)
            saved.append((os.path.splitext(f.filename or name)[0], path))
        except HTTPException:
            raise
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"status": "queued", "progress": 0, "error": None,
                    "output": None, "filename": None}
    threading.Thread(target=_run_bg, args=(job_id, saved, mode, export),
                     daemon=True).start()
    return {"job_id": job_id, "count": len(saved)}


def _run_bg(job_id, saved, mode, export):
    job = jobs[job_id]
    job["status"] = "processing"
    total = len(saved)
    outputs = []
    try:
        for i, (stem, path) in enumerate(saved):
            out = os.path.join(OUTPUT, f"{uuid.uuid4().hex}.png")
            processor.remove_background(path, out, mode=mode, export=export)
            outputs.append((stem, out))
            job["progress"] = int((i + 1) * 100 / total)

        if len(outputs) == 1:
            job["output"] = outputs[0][1]
            job["filename"] = f"{outputs[0][0]}_nobg.png"
        else:
            zip_path = os.path.join(OUTPUT, f"{job_id}.zip")
            with zipfile.ZipFile(zip_path, "w") as z:
                seen = {}
                for stem, out in outputs:
                    n = seen.get(stem, 0); seen[stem] = n + 1
                    arc = f"{stem}_nobg.png" if n == 0 else f"{stem}_nobg_{n}.png"
                    z.write(out, arc)
            job["output"] = zip_path
            job["filename"] = "去背景结果.zip"
        job["status"] = "done"
        job["progress"] = 100
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


@app.get("/api/bg-download/{job_id}")
def bg_download(job_id: str):
    job = jobs.get(job_id)
    if not job or job["status"] != "done" or not job["output"]:
        raise HTTPException(404, "成品尚未就绪")
    is_zip = job["output"].endswith(".zip")
    return FileResponse(job["output"],
                        media_type="application/zip" if is_zip else "image/png",
                        filename=job["filename"])


@app.post("/api/process")
def start_process(req: ProcessReq):
    path = os.path.join(UPLOAD, req.video_id)
    if not os.path.exists(path):
        raise HTTPException(404, "视频不存在,请重新上传")
    if not req.regions:
        raise HTTPException(400, "请先框选水印区域")

    job_id = uuid.uuid4().hex
    out = os.path.join(OUTPUT, job_id + ".mp4")
    jobs[job_id] = {"status": "queued", "progress": 0, "error": None, "output": out}
    threading.Thread(target=_run, args=(job_id, path, out, req), daemon=True).start()
    return {"job_id": job_id}


def _run(job_id, path, out, req: ProcessReq):
    job = jobs[job_id]
    job["status"] = "processing"

    def cb(done, total):
        job["progress"] = int(done * 100 / total) if total else 0

    try:
        processor.process_video(
            path, out, [list(r) for r in req.regions],
            method=req.method, motion=req.motion, tracker=req.tracker,
            feather=req.feather, radius=req.radius, crf=req.crf,
            progress_cb=cb)
        job["status"] = "done"
        job["progress"] = 100
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return {"status": job["status"], "progress": job["progress"], "error": job["error"]}


@app.get("/api/download/{job_id}")
def download(job_id: str):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(404, "成品尚未就绪")
    return FileResponse(job["output"], media_type="video/mp4",
                        filename=f"nowm_{job_id[:8]}.mp4")


@app.get("/api/health")
def health():
    return {"ok": True}


# 网页界面(放在最后挂载,避免覆盖上面的 /api 路由)
app.mount("/", StaticFiles(directory=os.path.join(BASE, "static"), html=True),
          name="static")
