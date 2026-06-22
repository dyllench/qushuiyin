# 视频去水印工具

去除视频中任意位置(左下角、右下角、中间等)的固定水印,自动保留原音轨。

## 依赖

- `ffmpeg` / `ffprobe`(已用 Homebrew 安装即可)
- Python 3 + `opencv-python` + `numpy`

```bash
pip install opencv-python numpy
```

## 三步流程

### 1. 框选水印区域

```bash
# 弹窗框选:鼠标拖框 → 回车/空格确认 → 可继续框多个 → ESC 结束
python3 dewatermark.py select 你的视频.mp4

# 无窗口环境 / 已知坐标:直接给 x,y,w,h(可多个 --region)
python3 dewatermark.py select 你的视频.mp4 --region 470,560,90,90
```

`-t 2.5` 可指定从第几秒抽帧来框选(默认 1 秒)。结果保存到 `regions.json`。

### 2. 预览单帧效果(强烈建议)

```bash
python3 dewatermark.py preview 你的视频.mp4
```

生成 `preview.png`:左边是原图(红框标出选区),右边是去水印后的效果。
不满意就回到第 1 步重新框选,或换算法(见下)。

### 3. 处理整段视频

```bash
python3 dewatermark.py remove 你的视频.mp4 -o 输出.mp4
```

不指定 `-o` 时默认输出 `你的视频_nowm.mp4`。

## 两种算法

| 算法 | 参数 | 特点 |
|------|------|------|
| `delogo`(默认) | `--method delogo` | ffmpeg 用选区边缘像素插值填充。**快**,适合半透明小水印 |
| `inpaint` | `--method inpaint` | OpenCV 逐帧图像修复。背景复杂时**质量更高**,但更慢 |

inpaint 可调:`--feather 5`(掩膜外扩,水印有羽化边时调大)、`--radius 3`(修复半径)、`--ns`(换 NS 算法)。

`--crf 18` 控制输出质量,数值越小越清晰、文件越大(默认 18,可设 16~23)。

## 参考图水印位置

你那张截图里的星形 ✦ 水印在画面靠下偏中位置。先用 `select` 把它框进去(框稍微比水印大一圈,留点余量),再 `preview` 看效果,通常 `delogo` 对半透明水印就够了;若边缘有残影,改用 `--method inpaint --feather 6`。

## 移动水印(水印会在画面里移动)

如果水印不是固定的,而是会在画面中移动,用 `--motion` 模式:逐帧追踪水印位置后再修复。

```bash
# 1. 框选水印在「起始那一帧」的位置(用 -t 指定起始时刻)
python3 dewatermark.py select 视频.mp4 -t 0.04 --region 40,60,60,60

# 2. 先验证追踪:导出带红框的视频,确认红框全程跟得住水印
python3 dewatermark.py track-preview 视频.mp4 -o track_preview.mp4

# 3. 红框跟得住 → 正式处理
python3 dewatermark.py remove 视频.mp4 -o 输出.mp4 --motion --feather 6
```

追踪算法 `--tracker`:

| 值 | 说明 |
|----|------|
| `template`(默认) | 模板匹配,用首帧水印裁片在附近窗口搜索。对外观稳定的水印很稳 |
| `csrt` | 精度最高,但需要 `pip install opencv-contrib-python`(没装会自动回退) |
| `kcf` / `mil` | OpenCV 内置追踪器,速度快、精度一般 |

`--search 2.0` 控制 template 模式的搜索窗口大小(相对水印尺寸,水印移动快就调大)。移动模式只追踪 `regions.json` 里的**第一个**区域,且始终走 inpaint 修复。

> 提示:移动模式务必先跑 `track-preview` 看红框跟不跟得住。半透明水印在不同背景上外观变化大,追踪可能漂移;若漂移,换 `--tracker csrt` 或调大 `--search`。

## 小贴士

- 水印**位置每个视频都可能不同** → 每个新视频都重新 `select` 一次。
- 框选时**框得比水印略大**,能把半透明边缘也盖住,效果更干净。
- 多个固定水印(如左下 + 右下)→ 框选时连框多个,或多个 `--region`(固定模式支持多区域;移动模式只追第一个)。
