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
import uuid

import cv2
from fastapi import FastAPI, File, HTTPException, UploadFile
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

app = FastAPI(title="视频去水印")

# 内存里的任务表(单实例、少量用户场景足够;重启即清空)
jobs: dict[str, dict] = {}


class ProcessReq(BaseModel):
    video_id: str
    regions: list[list[int]]          # [[x, y, w, h], ...](原始像素坐标)
    method: str = "delogo"            # delogo | inpaint
    motion: bool = False              # 移动水印
    tracker: str = "template"         # template | csrt | kcf | mil
    feather: int = 3
    radius: int = 3
    crf: int = 18


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower() or ".mp4"
    if ext not in (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"):
        raise HTTPException(400, f"不支持的格式: {ext}")
    video_id = uuid.uuid4().hex + ext
    path = os.path.join(UPLOAD, video_id)

    size = 0
    limit = MAX_UPLOAD_MB * 1024 * 1024
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                f.close()
                os.remove(path)
                raise HTTPException(413, f"文件超过 {MAX_UPLOAD_MB}MB 上限")
            f.write(chunk)

    try:
        W, H, fps, has_audio = dw.ffprobe_info(path)
        frame = dw.grab_frame(path, 0)
    except Exception as e:
        os.path.exists(path) and os.remove(path)
        raise HTTPException(400, f"无法解析视频: {e}")

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64 = base64.b64encode(buf).decode()
    return {
        "video_id": video_id,
        "width": W, "height": H,
        "has_audio": has_audio,
        "frame": "data:image/jpeg;base64," + b64,
    }


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
