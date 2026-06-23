# 部署到 Render(网页版去水印)

这是一个**一体化**应用:同一个服务既提供网页界面,又负责视频处理。
所以**只需要部署到 Render 这一个地方**(Vercel 这次可以先不用,因为视频处理必须跑在能装 ffmpeg 的后端上)。

## 一、本地先跑起来看效果

```bash
cd /Users/dyllenxmbp/Desktop/qushuiyin
.venv/bin/uvicorn server:app --reload
```

浏览器打开 http://127.0.0.1:8000 ,上传视频 → 拖框圈水印 → 开始去水印 → 下载。

## 二、推到 GitHub

```bash
git init
git add .
git commit -m "视频去水印网页版"
# 在 GitHub 新建一个空仓库,然后:
git remote add origin https://github.com/你的用户名/仓库名.git
git branch -M main
git push -u origin main
```

> `.gitignore` 已经排除了 `.venv/`、`data/`、测试视频等,不会误传。

## 三、在 Render 上部署

1. 登录 [render.com](https://render.com)(用 GitHub 账号)。
2. 点 **New +** → **Web Service**。
3. 选中你刚推上去的 GitHub 仓库。
4. Render 会自动识别到 **Dockerfile**,运行环境选 **Docker**(它通常会自动选好)。
5. 其它保持默认即可:
   - Region:随意(离你近的)
   - Instance Type:先选 **Free**(免费档)
6. 点 **Create Web Service**,等它构建+部署(第一次约 3~6 分钟)。
7. 部署完成后,Render 会给你一个网址,例如 `https://你的应用.onrender.com`,打开就能用。

## 四、免费档要知道的两点

- **会休眠**:一段时间没人访问会睡着,下次打开要等十几秒唤醒。
- **内存 512MB**:处理**短视频/标清**没问题;**长视频或高清**可能内存不足或很慢。
  - 解决:在 Render 把 Instance Type 升级到付费档(更多内存),或只处理较短的片段。

## 五、可调参数(环境变量,可选)

在 Render 的 **Environment** 里可以加:

| 变量 | 作用 | 默认 |
|------|------|------|
| `MAX_UPLOAD_MB` | 上传大小上限(MB) | 200 |
| `CLEANUP_TTL_MIN` | 自动删除上传/成品的保留分钟数(超时即清) | 60 |
| `BG_MODEL` | AI 去背景模型;`u2netp` 轻量省内存,`u2net` 质量更高更吃内存 | u2netp |

## 文件说明

| 文件 | 作用 |
|------|------|
| `server.py` | Web 后端(API + 网页) |
| `processor.py` | 去水印处理逻辑 |
| `dewatermark.py` | 底层算法 + 命令行工具 |
| `static/index.html` | 网页界面(上传/拖框/下载) |
| `Dockerfile` | Render 部署用(含 ffmpeg 安装) |
| `requirements.txt` | Python 依赖 |
