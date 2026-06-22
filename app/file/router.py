"""
文件上传模块
支持图片识别和文本文件读取
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Header
from typing import Optional
import os
import uuid
from datetime import datetime

router = APIRouter()

# 支持的文件类型
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_TEXT_TYPES = {"text/plain", "text/markdown"}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_TEXT_TYPES

# 文件大小限制（10MB）
MAX_FILE_SIZE = 10 * 1024 * 1024

# 上传目录
UPLOAD_DIR = "C:/shop-operate/uploads"


@router.post("/api/upload/file")
async def upload_file(
    file: UploadFile = File(...),
    authorization: str = Header(...)
):
    """
    上传文件并识别内容
    
    支持格式：
    - 图片: jpg, png, gif, webp → 调用 MiMo-V2.5 识别
    - 文本: txt, md → 直接读取内容
    
    返回：
    - file_url: 文件访问URL
    - content: 识别/读取的内容
    - file_type: 文件类型
    """
    # 验证 Token
    from app.common.auth import verify_token, parse_authorization
    
    try:
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)
    except Exception as e:
        raise HTTPException(status_code=401, detail="认证失败")
    
    # 验证文件类型
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}"
        )
    
    # 读取文件内容
    content = await file.read()
    
    # 验证文件大小
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制（最大10MB）"
        )
    
    # 生成文件名
    ext = os.path.splitext(file.filename)[1] if file.filename else ""
    filename = f"{uuid.uuid4().hex}{ext}"
    
    # 保存文件
    shop_dir = os.path.join(UPLOAD_DIR, str(user_context.shop_id))
    os.makedirs(shop_dir, exist_ok=True)
    filepath = os.path.join(shop_dir, filename)
    
    with open(filepath, "wb") as f:
        f.write(content)
    
    # 文件URL
    file_url = f"/file/upload/{user_context.shop_id}/{filename}"
    
    # 根据文件类型处理内容
    result = {
        "file_url": file_url,
        "file_type": file.content_type,
        "file_name": file.filename,
        "file_size": len(content),
    }
    
    if file.content_type in ALLOWED_IMAGE_TYPES:
        # 图片：调用 MiMo-V2.5 识别
        try:
            from app.multi_agent.vision_agent import get_vision_agent
            from app.common.user_context import UserContext
            
            vision_agent = get_vision_agent()
            
            # 构建图片URL（使用相对路径，Vision Agent 会转为 base64）
            image_url = f"/file/upload/{user_context.shop_id}/{filename}"
            
            # 调用视觉Agent识别
            agent_result = await vision_agent.execute(
                task="请识别这张图片中的所有文字信息，保持原始格式。",
                context=user_context,
                image_url=image_url,
            )
            
            if agent_result.success:
                result["content"] = agent_result.result
                result["type"] = "image_recognized"
            else:
                result["content"] = "图片识别失败"
                result["type"] = "image_failed"
                result["error"] = agent_result.error
        except Exception as e:
            result["content"] = f"图片识别失败: {str(e)}"
            result["type"] = "image_failed"
            result["error"] = str(e)
    
    elif file.content_type in ALLOWED_TEXT_TYPES:
        # 文本：直接读取内容
        try:
            text_content = content.decode("utf-8")
            result["content"] = text_content
            result["type"] = "text"
        except UnicodeDecodeError:
            try:
                text_content = content.decode("gbk")
                result["content"] = text_content
                result["type"] = "text"
            except:
                result["content"] = "文本解码失败"
                result["type"] = "text_failed"
    
    return result


@router.get("/api/upload/file/{shop_id}/{filename}")
async def get_file(shop_id: int, filename: str):
    """
    获取上传的文件
    """
    filepath = os.path.join(UPLOAD_DIR, str(shop_id), filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    from fastapi.responses import FileResponse
    return FileResponse(filepath)
