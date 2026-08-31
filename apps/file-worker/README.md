# apps/file-worker — 部署名

```bash
python -m apps.file_worker
```

代码：`apps/file_worker/`。必须与 API 共用 `./uploads` 卷；不要把解析塞进未挂卷的 memory-worker。
