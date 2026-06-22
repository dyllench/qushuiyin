"""
去水印处理逻辑(供 Web 后端调用)。
复用命令行工具 dewatermark.py 里的核心函数,只是把"用 args 对象"改成普通参数,
并支持进度回调 progress_cb(已处理帧, 总帧)。
"""
import os
import tempfile

import cv2

import dewatermark as dw


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
           "-c:v", "libx264", "-crf", str(crf), "-preset", "medium"]
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
