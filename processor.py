"""
去水印处理逻辑(供 Web 后端调用)。
复用命令行工具 dewatermark.py 里的核心函数,只是把"用 args 对象"改成普通参数,
并支持进度回调 progress_cb(已处理帧, 总帧)。
"""
import os
import tempfile

import cv2
import numpy as np

import dewatermark as dw

# ---------------- 去背景 / 假透明格子还原 ----------------
_BG_MODEL = os.environ.get("BG_MODEL", "u2netp")   # 免费档用轻量 u2netp;升级后可设 u2net
_bg_session = None


def _bg_session_get():
    """懒加载 rembg 会话(首次会下载模型)。"""
    global _bg_session
    if _bg_session is None:
        from rembg import new_session
        _bg_session = new_session(_BG_MODEL)
    return _bg_session


def _strip_checker(pil_img):
    """把"假透明"棋盘格(烘焙进像素的灰白格子)还原成真透明。返回 RGBA PIL。"""
    from PIL import Image
    rgb = np.array(pil_img.convert("RGB")).astype(np.int16)
    H, W = rgb.shape[:2]
    out = np.dstack([rgb.astype(np.uint8),
                     np.full((H, W), 255, np.uint8)])
    sat = rgb.max(2) - rgb.min(2)          # 低饱和=灰
    val = rgb.mean(2)                      # 亮度
    graylight = (sat <= 18) & (val >= 140)  # 格子是浅灰/白
    if graylight.sum() < 0.03 * H * W:     # 没有明显格子,原样返回(全不透明)
        return Image.fromarray(out, "RGBA")
    # 找格子的两种灰度(直方图两个峰)
    hist = np.bincount(np.clip(val[graylight].astype(int), 0, 255), minlength=256)
    p1 = int(np.argmax(hist))
    hist[max(0, p1 - 12):p1 + 12] = 0
    p2 = int(np.argmax(hist))
    tol = 14
    grid = graylight & ((np.abs(val - p1) <= tol) | (np.abs(val - p2) <= tol))
    out[..., 3][grid] = 0
    return Image.fromarray(out, "RGBA")


def remove_background(input_path, output_path, *, mode="ai", export="transparent"):
    """
    去背景。mode: ai(AI 抠图) | checker(去假透明格子)。
    export: transparent(透明 PNG) | white(白底 PNG)。
    """
    from PIL import Image
    src = Image.open(input_path).convert("RGBA")
    if mode == "checker":
        rgba = _strip_checker(src)
    else:
        from rembg import remove
        # 大图先缩小再喂给模型(省内存),抠出的 alpha 再放大回原尺寸贴回原图
        max_side = int(os.environ.get("BG_MAX_SIDE", "1600"))
        w, h = src.size
        if max(w, h) > max_side:
            s = max_side / max(w, h)
            small = src.resize((max(1, int(w * s)), max(1, int(h * s))))
            cut = remove(small, session=_bg_session_get())
            alpha = cut.getchannel("A").resize((w, h))
            rgba = src.copy()
            rgba.putalpha(alpha)
            del small, cut, alpha
        else:
            rgba = remove(src, session=_bg_session_get())  # 返回 RGBA PIL

    if export == "white":
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        bg.convert("RGB").save(output_path)            # 白底,无透明通道
    else:
        rgba.save(output_path)                         # 透明 PNG


def process_image(input_path, output_path, regions, *,
                  method="inpaint", feather=3, radius=3, ns=False):
    """单张图片去水印。method: inpaint(默认,质量好) | delogo(边缘插值)。"""
    img = cv2.imread(input_path)
    if img is None:
        raise ValueError("无法读取图片")
    H, W = img.shape[:2]
    regions = dw.clamp_regions(regions, W, H)
    if not regions:
        raise ValueError("没有有效的水印区域")

    if method == "delogo":
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        cv2.imwrite(tmp.name, img)
        flt = dw.build_delogo_filter(regions)
        dw.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp.name,
                "-vf", flt, output_path])
        os.unlink(tmp.name)
    else:
        m = cv2.INPAINT_NS if ns else cv2.INPAINT_TELEA
        mask = dw.build_mask(regions, W, H, feather)
        cv2.imwrite(output_path, dw.inpaint_frame(img, mask, radius, m))


def process_video(input_path, output_path, regions, *,
                  method="delogo", motion=False, tracker="template",
                  search=2.0, feather=3, radius=3, crf=18, ns=False,
                  progress_cb=None):
    W, H, fps, has_audio = dw.ffprobe_info(input_path)
    regions = dw.clamp_regions(regions, W, H)
    if not regions:
        raise ValueError("没有有效的水印区域")

    if motion:
        _motion(input_path, output_path, regions[0], W, H, fps, has_audio,
                tracker, search, feather, radius, crf, ns, progress_cb)
    elif method == "delogo":
        _delogo(input_path, output_path, regions, has_audio, crf, progress_cb)
    else:
        _inpaint(input_path, output_path, regions, W, H, fps, has_audio,
                 feather, radius, crf, ns, progress_cb)


def _delogo(inp, out, regions, has_audio, crf, cb):
    if cb:
        cb(0, 100)
    flt = dw.build_delogo_filter(regions)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", inp, "-vf", flt,
           "-c:v", "libx264", "-crf", str(crf), "-preset", dw.VIDEO_PRESET]
    cmd += ["-c:a", "copy"] if has_audio else ["-an"]
    cmd.append(out)
    dw.run(cmd)
    if cb:
        cb(100, 100)


def _inpaint(inp, out, regions, W, H, fps, has_audio, feather, radius, crf, ns, cb):
    method = cv2.INPAINT_NS if ns else cv2.INPAINT_TELEA
    mask = dw.build_mask(regions, W, H, feather)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    cap = cv2.VideoCapture(inp)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    wr = cv2.VideoWriter(tmp.name, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        wr.write(dw.inpaint_frame(fr, mask, radius, method))
        i += 1
        if cb and total and i % 5 == 0:
            cb(i, total)
    cap.release()
    wr.release()
    if cb:
        cb(total or i, total or i)
    dw._encode_and_mux(tmp.name, inp, out, crf, has_audio)


def _motion(inp, out, init_box, W, H, fps, has_audio,
            tracker, search, feather, radius, crf, ns, cb):
    method = cv2.INPAINT_NS if ns else cv2.INPAINT_TELEA
    bboxes, _ = dw.track_bboxes(inp, init_box, tracker, search)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    cap = cv2.VideoCapture(inp)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or len(bboxes)
    wr = cv2.VideoWriter(tmp.name, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        box = bboxes[i] if i < len(bboxes) else bboxes[-1]
        mask = dw.build_mask(dw.clamp_regions([box], W, H), W, H, feather)
        wr.write(dw.inpaint_frame(fr, mask, radius, method))
        i += 1
        if cb and total and i % 5 == 0:
            cb(i, total)
    cap.release()
    wr.release()
    if cb:
        cb(total or i, total or i)
    dw._encode_and_mux(tmp.name, inp, out, crf, has_audio)
