"""
文件上传模块
支持图片识别和文档文件读取
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Header
from typing import Optional
import os
import uuid
from datetime import datetime

router = APIRouter()

# ========== 扩展名白名单（不再依赖 MIME type） ==========
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
DOC_EXTS = {".pdf", ".xlsx", ".xls", ".docx", ".doc", ".csv"}
TEXT_EXTS = {".txt", ".md"}
ALLOWED_EXTS = IMAGE_EXTS | DOC_EXTS | TEXT_EXTS

# ========== 分类型文件大小限制 ==========
MAX_IMAGE_SIZE = 5 * 1024 * 1024   # 图片 5MB
MAX_DOC_SIZE = 20 * 1024 * 1024    # 文档 20MB

# 文本截断字数
MAX_CONTENT_CHARS = 30000

# 上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")


@router.post("/api/upload/file")
async def upload_file(
    file: UploadFile = File(...),
    authorization: str = Header(...)
):
    """
    上传文件并识别内容

    支持格式：
    - 图片: jpg, png, gif, webp → 调用 Vision Agent 识别
    - 文本: txt, md → charset-normalizer 自动嗅探编码
    - 文档: pdf, xlsx, xls, docx, doc, csv → 调用 parse_document 提取文本

    返回：
    - file_url: 文件访问 URL
    - file_name: 原始文件名
    - file_type: MIME 类型
    - file_size: 文件大小（字节）
    - file_category: "image" | "document"
    - content: 识别/提取的文本内容（截断到 30000 字）
    - type: 处理结果类型
    """
    # 验证 Token
    from app.common.auth import verify_token, parse_authorization

    try:
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)
    except Exception as e:
        raise HTTPException(status_code=401, detail="认证失败")

    # ========== 按扩展名验证（不依赖 MIME，因为 Office MIME 不统一） ==========
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ""
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail="不支持的文件类型: {}。支持的类型: {}".format(ext, ", ".join(sorted(ALLOWED_EXTS)))
        )

    # 读取文件内容
    content = await file.read()

    # ========== 按类型校验大小 ==========
    if ext in IMAGE_EXTS:
        if len(content) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="图片大小超过限制（最大 5MB）")
        file_category = "image"
    else:
        if len(content) > MAX_DOC_SIZE:
            raise HTTPException(status_code=400, detail="文件大小超过限制（最大 20MB）")
        file_category = "document"

    # 生成文件名
    filename = f"{uuid.uuid4().hex}{ext}"

    # 保存文件
    shop_dir = os.path.join(UPLOAD_DIR, str(user_context.shop_id))
    os.makedirs(shop_dir, exist_ok=True)
    filepath = os.path.join(shop_dir, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    # 文件访问 URL
    file_url = f"/file/upload/{user_context.shop_id}/{filename}"

    # 构建返回结果
    result = {
        "file_url": file_url,
        "file_type": file.content_type,
        "file_name": file.filename,
        "file_size": len(content),
        "file_category": file_category,
    }

    # ========== 按类别处理内容 ==========
    if ext in IMAGE_EXTS:
        # 图片：调用 Vision Agent 识别
        try:
            from app.multi_agent.vision_agent import get_vision_agent

            vision_agent = get_vision_agent()
            image_url = f"/file/upload/{user_context.shop_id}/{filename}"

            agent_result = await vision_agent.execute(
                task="请识别这张图片中的所有文字信息，保持原始格式。",
                context=user_context,
                image_url=image_url,
            )

            if agent_result.success:
                result["content"] = agent_result.result
                result["type"] = "image_recognized"
            else:
                result["content"] = ""
                result["type"] = "image_failed"
                result["error"] = agent_result.error
        except Exception as e:
            result["content"] = ""
            result["type"] = "image_failed"
            result["error"] = str(e)

    elif ext in TEXT_EXTS:
        # 文本：使用 charset-normalizer 自动嗅探编码
        try:
            from charset_normalizer import from_bytes
            detected = from_bytes(content).best()
            text_content = str(detected) if detected else content.decode("utf-8", errors="replace")
        except Exception:
            try:
                text_content = content.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text_content = content.decode("gbk", errors="replace")
                except Exception:
                    result["content"] = ""
                    result["type"] = "text_failed"
                    result["error"] = "文本解码失败"
                    return result

        result["content"] = text_content[:MAX_CONTENT_CHARS]
        result["type"] = "text"

    elif ext in DOC_EXTS:
        # 文档：调用 parse_document 提取文本
        from app.file.parser import parse_document, ParseError
        try:
            text_content = parse_document(file.filename, content)
            result["content"] = text_content[:MAX_CONTENT_CHARS]
            result["type"] = "document_parsed"
        except ParseError as e:
            result["content"] = ""
            result["type"] = "document_failed"
            result["error"] = str(e)
        except Exception as e:
            result["content"] = ""
            result["type"] = "document_failed"
            result["error"] = "文档解析失败: {}".format(str(e))

    return result


@router.get("/api/upload/file/{shop_id}/{filename}")
async def get_file(shop_id: int, filename: str):
    """
    获取上传的文件（用于下载/预览）
    """
    filepath = os.path.join(UPLOAD_DIR, str(shop_id), filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")

    from fastapi.responses import FileResponse
    return FileResponse(filepath)
