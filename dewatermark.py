#!/usr/bin/env python3
"""
视频去水印工具 (Video De-watermark Tool)

支持水印在任意位置(左下角、右下角、中间等)。流程:
  1. select  —— 从视频中抽一帧,交互式框选(或手动输入)水印区域,保存为 regions.json
  2. preview —— 只处理一帧,生成处理前/后对比图,先确认效果
  3. remove  —— 处理整段视频,保留原音轨

两种去水印算法:
  - delogo  (默认): 调用 ffmpeg delogo 滤镜,用区域边缘像素插值填充。速度快,适合半透明小水印。
  - inpaint        : 用 OpenCV 逐帧图像修复(TELEA/NS),对复杂背景质量更高,但更慢。

用法示例:
  # 1) 框选水印(会弹出窗口,鼠标拖框,回车确认;可框多个,ESC 结束)
  python dewatermark.py select input.mp4

  # 1') 无窗口环境,直接给坐标(可多个 --region)
  python dewatermark.py select input.mp4 --region 470,560,90,90

  # 2) 预览单帧效果
  python dewatermark.py preview input.mp4

  # 3) 正式处理
  python dewatermark.py remove input.mp4 -o output.mp4 --method delogo
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np

REGIONS_FILE = "regions.json"


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def run(cmd, **kw):
    """运行子进程,出错时打印命令并抛异常。"""
    return subprocess.run(cmd, check=True, **kw)


def ffprobe_info(video):
    """返回 (width, height, fps, has_audio)。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "json", video],
        check=True, capture_output=True, text=True).stdout
    v = json.loads(out)["streams"][0]
    num, den = v["r_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 25.0

    a = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=index", "-of", "json", video],
        check=True, capture_output=True, text=True).stdout
    has_audio = bool(json.loads(a).get("streams"))
    return int(v["width"]), int(v["height"]), fps, has_audio


def grab_frame(video, timestamp):
    """抽取指定时间戳的一帧,返回 BGR ndarray。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(timestamp),
         "-i", video, "-frames:v", "1", tmp.name])
    img = cv2.imread(tmp.name)
    os.unlink(tmp.name)
    if img is None:
        sys.exit(f"无法从 {video} 在 {timestamp}s 处抽帧")
    return img


def load_regions(path=REGIONS_FILE):
    if not os.path.exists(path):
        sys.exit(f"找不到 {path},请先运行 `select` 框选水印区域。")
    with open(path) as f:
        data = json.load(f)
    regions = [tuple(r) for r in data["regions"]]
    if not regions:
        sys.exit(f"{path} 中没有任何水印区域。")
    return regions


def clamp_regions(regions, W, H):
    """把区域裁进画面范围,delogo 要求边缘留 1px。"""
    out = []
    for x, y, w, h in regions:
        x = max(1, min(int(x), W - 2))
        y = max(1, min(int(y), H - 2))
        w = max(1, min(int(w), W - x - 1))
        h = max(1, min(int(h), H - y - 1))
        out.append((x, y, w, h))
    return out


# --------------------------------------------------------------------------- #
# select —— 框选/录入水印区域
# --------------------------------------------------------------------------- #
def cmd_select(args):
    img = grab_frame(args.input, args.timestamp)
    H, W = img.shape[:2]
    regions = []

    if args.region:
        for r in args.region:
            parts = [int(p) for p in r.split(",")]
            if len(parts) != 4:
                sys.exit(f"--region 格式应为 x,y,w,h,收到: {r}")
            regions.append(tuple(parts))
        print(f"已录入 {len(regions)} 个区域(手动坐标)。")
    else:
        try:
            print("拖动鼠标框选水印,回车/空格确认一个;可继续框选多个;按 ESC 结束。")
            boxes = cv2.selectROIs("框选水印区域 (回车确认 / ESC 结束)", img,
                                   showCrosshair=True)
            cv2.destroyAllWindows()
            regions = [tuple(int(v) for v in b) for b in boxes if b[2] > 0 and b[3] > 0]
        except cv2.error:
            sys.exit("当前环境无法弹出窗口。请用 --region x,y,w,h 手动指定坐标。\n"
                     f"提示:画面尺寸为 {W}x{H}。")

    if not regions:
        sys.exit("没有选择任何区域。")

    regions = clamp_regions(regions, W, H)
    with open(REGIONS_FILE, "w") as f:
        json.dump({"video_size": [W, H], "regions": [list(r) for r in regions]},
                  f, indent=2)
    print(f"已保存 {len(regions)} 个区域到 {REGIONS_FILE}: {regions}")
    print("接下来可运行:  python dewatermark.py preview", args.input)


# --------------------------------------------------------------------------- #
# 去水印核心
# --------------------------------------------------------------------------- #
def build_delogo_filter(regions):
    """把多个区域串成 ffmpeg delogo 链。"""
    return ",".join(f"delogo=x={x}:y={y}:w={w}:h={h}" for x, y, w, h in regions)


def build_mask(regions, W, H, feather=3):
    """为 inpaint 构造水印掩膜(白=待修复)。"""
    mask = np.zeros((H, W), np.uint8)
    for x, y, w, h in regions:
        mask[y:y + h, x:x + w] = 255
    if feather > 0:
        mask = cv2.dilate(mask, np.ones((feather, feather), np.uint8))
    return mask


def inpaint_frame(frame, mask, radius=3, method=cv2.INPAINT_TELEA):
    return cv2.inpaint(frame, mask, radius, method)


# --------------------------------------------------------------------------- #
# 移动水印追踪
# --------------------------------------------------------------------------- #
def make_cv_tracker(name):
    """构造 OpenCV 追踪器。优先 CSRT(需 opencv-contrib),否则 KCF / MIL。"""
    order = {"csrt": ["TrackerCSRT", "TrackerKCF", "TrackerMIL"],
             "kcf":  ["TrackerKCF", "TrackerMIL"],
             "mil":  ["TrackerMIL"]}.get(name, ["TrackerMIL"])
    for cls in order:
        ctor = getattr(cv2, cls + "_create", None) or \
               getattr(getattr(cv2, cls, None), "create", None)
        if ctor:
            return ctor(), cls
    raise RuntimeError("没有可用的 OpenCV 追踪器。")


def track_bboxes(video, init_bbox, tracker_name, search=2.0):
    """
    逐帧返回水印 bbox 列表 [(x,y,w,h), ...](与帧一一对应)。
    tracker_name == 'template' 时用模板匹配(对半透明水印更稳):
      用首帧水印裁片作模板,在上一位置附近窗口内做归一化互相关搜索。
    其它名字走 OpenCV 视觉追踪器。
    """
    cap = cv2.VideoCapture(video)
    ok, frame = cap.read()
    if not ok:
        cap.release()
        sys.exit("无法读取视频。")
    H, W = frame.shape[:2]
    x, y, w, h = [int(v) for v in init_bbox]
    bboxes = [(x, y, w, h)]

    if tracker_name == "template":
        template = frame[y:y + h, x:x + w].copy()
        sw, sh = int(w * search), int(h * search)
        last = (x, y)
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            lx, ly = last
            x0 = max(0, lx - sw); y0 = max(0, ly - sh)
            x1 = min(W, lx + w + sw); y1 = min(H, ly + h + sh)
            roi = frame[y0:y1, x0:x1]
            if roi.shape[0] < h or roi.shape[1] < w:
                bboxes.append((lx, ly, w, h)); continue
            res = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
            _, _, _, loc = cv2.minMaxLoc(res)
            nx, ny = x0 + loc[0], y0 + loc[1]
            last = (nx, ny)
            bboxes.append((nx, ny, w, h))
        cap.release()
        return bboxes, "template"

    tracker, used = make_cv_tracker(tracker_name)
    tracker.init(frame, (x, y, w, h))
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ok, box = tracker.update(frame)
        if ok:
            x, y, w, h = [int(v) for v in box]
        bboxes.append((x, y, w, h))  # 跟丢时沿用上一帧位置
    cap.release()
    return bboxes, used


# --------------------------------------------------------------------------- #
# preview —— 单帧前后对比
# --------------------------------------------------------------------------- #
def cmd_preview(args):
    regions = load_regions()
    img = grab_frame(args.input, args.timestamp)
    H, W = img.shape[:2]
    regions = clamp_regions(regions, W, H)

    if args.method == "delogo":
        flt = build_delogo_filter(regions)
        src = tempfile.NamedTemporaryFile(suffix=".png", delete=False); src.close()
        dst = tempfile.NamedTemporaryFile(suffix=".png", delete=False); dst.close()
        cv2.imwrite(src.name, img)
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", src.name,
             "-vf", flt, dst.name])
        result = cv2.imread(dst.name)
        os.unlink(src.name); os.unlink(dst.name)
    else:
        mask = build_mask(regions, W, H, args.feather)
        result = inpaint_frame(img, mask, args.radius,
                               cv2.INPAINT_NS if args.ns else cv2.INPAINT_TELEA)

    before = img.copy()
    for x, y, w, h in regions:
        cv2.rectangle(before, (x, y), (x + w, y + h), (0, 0, 255), 2)
    combo = np.hstack([before, result])
    out = args.out or "preview.png"
    cv2.imwrite(out, combo)
    print(f"已生成预览(左=原图标红框 / 右=去水印后): {out}")
    print(f"方法={args.method} 区域={regions}")


# --------------------------------------------------------------------------- #
# remove —— 处理整段视频
# --------------------------------------------------------------------------- #
def cmd_remove(args):
    regions = load_regions()
    W, H, fps, has_audio = ffprobe_info(args.input)
    regions = clamp_regions(regions, W, H)
    out = args.out or _default_out(args.input)

    if args.motion:
        _remove_motion(args, out, regions, W, H, fps, has_audio)
    elif args.method == "delogo":
        _remove_delogo(args.input, out, regions, has_audio, args.crf)
    else:
        _remove_inpaint(args, out, regions, W, H, fps, has_audio)
    print(f"\n完成 → {out}")


def _default_out(inp):
    base, ext = os.path.splitext(inp)
    return f"{base}_nowm{ext or '.mp4'}"


def _remove_delogo(inp, out, regions, has_audio, crf):
    flt = build_delogo_filter(regions)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stats", "-i", inp, "-vf", flt,
           "-c:v", "libx264", "-crf", str(crf), "-preset", "medium"]
    cmd += ["-c:a", "copy"] if has_audio else ["-an"]
    cmd.append(out)
    print("delogo 处理中...")
    run(cmd)


def _remove_inpaint(args, out, regions, W, H, fps, has_audio):
    """逐帧 OpenCV 修复,再用 ffmpeg 合回音轨。"""
    mask = build_mask(regions, W, H, args.feather)
    method = cv2.INPAINT_NS if args.ns else cv2.INPAINT_TELEA

    tmp_video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_video.close()

    cap = cv2.VideoCapture(args.input)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(tmp_video.name, fourcc, fps, (W, H))

    print(f"inpaint 逐帧处理中 (共约 {total} 帧)...")
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        writer.write(inpaint_frame(frame, mask, args.radius, method))
        i += 1
        if total and i % 30 == 0:
            print(f"  {i}/{total}  ({i * 100 // total}%)", end="\r")
    cap.release()
    writer.release()
    print(f"  {i} 帧处理完成。" + " " * 20)
    _encode_and_mux(tmp_video.name, args.input, out, args.crf, has_audio)


def _encode_and_mux(raw_video, src_for_audio, out, crf, has_audio):
    """把逐帧产物重新编码成 H.264,并合回原音轨。"""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", raw_video]
    if has_audio:
        cmd += ["-i", src_for_audio, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
            "-pix_fmt", "yuv420p", out]
    print("合成音视频中...")
    run(cmd)
    os.unlink(raw_video)


def _remove_motion(args, out, regions, W, H, fps, has_audio):
    """移动水印:逐帧追踪 bbox → 逐帧 inpaint。仅用第一个区域作为初始框。"""
    init = regions[0]
    if len(regions) > 1:
        print("注意:移动模式只追踪第一个区域,其余忽略。")
    print(f"追踪水印中 (tracker={args.tracker})...")
    bboxes, used = track_bboxes(args.input, init, args.tracker, args.search)
    print(f"追踪完成,使用 {used},共 {len(bboxes)} 帧。")

    method = cv2.INPAINT_NS if args.ns else cv2.INPAINT_TELEA
    tmp_video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False); tmp_video.close()
    cap = cv2.VideoCapture(args.input)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or len(bboxes)
    writer = cv2.VideoWriter(tmp_video.name, cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (W, H))
    print(f"逐帧修复中 (共约 {total} 帧)...")
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        box = bboxes[i] if i < len(bboxes) else bboxes[-1]
        mask = build_mask(clamp_regions([box], W, H), W, H, args.feather)
        writer.write(inpaint_frame(frame, mask, args.radius, method))
        i += 1
        if total and i % 30 == 0:
            print(f"  {i}/{total}  ({i * 100 // total}%)", end="\r")
    cap.release()
    writer.release()
    print(f"  {i} 帧处理完成。" + " " * 20)
    _encode_and_mux(tmp_video.name, args.input, out, args.crf, has_audio)


# --------------------------------------------------------------------------- #
# track-preview —— 画出追踪框,验证追踪质量(不修复)
# --------------------------------------------------------------------------- #
def cmd_track_preview(args):
    regions = load_regions()
    W, H, fps, has_audio = ffprobe_info(args.input)
    init = clamp_regions(regions, W, H)[0]
    print(f"追踪水印中 (tracker={args.tracker})...")
    bboxes, used = track_bboxes(args.input, init, args.tracker, args.search)
    print(f"追踪完成,使用 {used}。生成带框预览视频...")

    out = args.out or "track_preview.mp4"
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False); tmp.close()
    cap = cv2.VideoCapture(args.input)
    writer = cv2.VideoWriter(tmp.name, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        x, y, w, h = bboxes[i] if i < len(bboxes) else bboxes[-1]
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
        writer.write(frame)
        i += 1
    cap.release()
    writer.release()
    _encode_and_mux(tmp.name, args.input, out, args.crf, has_audio)
    print(f"红框跟得住水印就说明追踪 OK,然后用 `remove --motion` 正式处理 → {out}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="视频去水印工具(支持任意位置)")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("select", help="框选/录入水印区域")
    ps.add_argument("input")
    ps.add_argument("-t", "--timestamp", type=float, default=1.0, help="抽帧时间(秒)")
    ps.add_argument("--region", action="append",
                    help="手动坐标 x,y,w,h(可重复指定多个)")
    ps.set_defaults(func=cmd_select)

    pp = sub.add_parser("preview", help="单帧预览处理效果")
    pp.add_argument("input")
    pp.add_argument("-t", "--timestamp", type=float, default=1.0)
    pp.add_argument("-o", "--out", help="输出图片(默认 preview.png)")
    _add_method_args(pp)
    pp.set_defaults(func=cmd_preview)

    pr = sub.add_parser("remove", help="处理整段视频")
    pr.add_argument("input")
    pr.add_argument("-o", "--out", help="输出视频(默认 *_nowm.mp4)")
    pr.add_argument("--crf", type=int, default=18, help="H.264 质量,越小越好(默认18)")
    _add_method_args(pr)
    _add_motion_args(pr)
    pr.set_defaults(func=cmd_remove)

    pt = sub.add_parser("track-preview", help="移动水印:导出带追踪框的视频以验证追踪")
    pt.add_argument("input")
    pt.add_argument("-o", "--out", help="输出视频(默认 track_preview.mp4)")
    pt.add_argument("--crf", type=int, default=23)
    _add_motion_args(pt)
    pt.set_defaults(func=cmd_track_preview)

    args = p.parse_args()
    args.func(args)


def _add_method_args(sp):
    sp.add_argument("--method", choices=["delogo", "inpaint"], default="delogo")
    sp.add_argument("--feather", type=int, default=3, help="inpaint 掩膜外扩像素")
    sp.add_argument("--radius", type=int, default=3, help="inpaint 修复半径")
    sp.add_argument("--ns", action="store_true", help="inpaint 用 NS 算法(默认 TELEA)")


def _add_motion_args(sp):
    sp.add_argument("--motion", action="store_true",
                    help="移动水印模式:逐帧追踪后修复(自动走 inpaint)")
    sp.add_argument("--tracker", choices=["template", "csrt", "kcf", "mil"],
                    default="template",
                    help="追踪算法。template=模板匹配(对半透明水印更稳),"
                         "csrt 需 opencv-contrib")
    sp.add_argument("--search", type=float, default=2.0,
                    help="template 模式搜索窗口倍数(相对水印尺寸)")


if __name__ == "__main__":
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("需要安装 ffmpeg / ffprobe。")
    main()
