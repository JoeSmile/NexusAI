# Task 10: 文件上传加固

> ⚠️ MIME 校验读文件头，**不看** HTTP Content-Type。
> 不上传目录挂 `StaticFiles`。

## Subtask 10.01: file_sanitizer.py

**文件:** `backend/core/file_sanitizer.py`
- MIME 校验（magic bytes）
- UUID 重命名存储
- 大小限制 10MB + 类型白名单
- 通过 `/files/{id}` 接口返回

```python
ALLOWED_MIME = {"image/jpeg", "image/png", "image/gif", "application/pdf", "text/plain"}

def validate_file(content: bytes, content_type: str) -> bool:
    """读文件头判断真实 MIME，不信任 Content-Type"""
    magic = content[:8]
    # JPEG: \xff\xd8\xff, PNG: \x89PNG, PDF: %PDF
    ...
```

## Subtask 10.02: 修改 chat.py

**文件:** `backend/routers/chat.py`
- 移除 `app.mount("/uploads", StaticFiles(...))`
- 引用 `file_sanitizer`

## 验证

上传 `.html` 伪装 `image/png` → blocked
`/uploads/` → 404
