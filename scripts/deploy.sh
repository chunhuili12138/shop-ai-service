#!/bin/bash
# ============================================
# ShopCopilot AI Service 部署脚本
# ============================================

set -e

echo "=========================================="
echo "🚀 ShopCopilot AI Service 部署脚本"
echo "=========================================="

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    echo "   安装指南: https://docs.docker.com/get-docker/"
    exit 1
fi

# 检查 Docker Compose 是否安装
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose 未安装，请先安装 Docker Compose"
    echo "   安装指南: https://docs.docker.com/compose/install/"
    exit 1
fi

# 进入 docker 目录
cd "$(dirname "$0")/../docker"

# 创建 .env 文件（如果不存在）
if [ ! -f .env ]; then
    echo "📝 创建 .env 文件..."
    cat > .env << 'EOF'
# ============================================
# ShopCopilot AI Service 配置
# ============================================

# LLM 配置（必填）
LLM_API_KEY=your_deepseek_api_key_here
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# MySQL 配置
MYSQL_USER=root
MYSQL_PASSWORD=root
MYSQL_DATABASE=shop_operate_system

# LangFuse 配置（可选，用于监控）
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
EOF
    echo "⚠️  请编辑 docker/.env 文件配置正确的参数"
    echo "   特别是 LLM_API_KEY（DeepSeek API Key）"
    echo ""
fi

# 解析命令行参数
ACTION=${1:-"up"}

case $ACTION in
    "up")
        echo "🚀 启动服务..."
        docker-compose up -d
        
        echo ""
        echo "⏳ 等待服务启动..."
        sleep 10
        
        echo ""
        echo "📊 检查服务状态..."
        docker-compose ps
        
        echo ""
        echo "⏳ 等待 Ollama 服务就绪..."
        sleep 10
        
        echo ""
        echo "📐 Embedding 模型已切换为阿里百炼 text-embedding-v4（云端服务）"
        
        echo ""
        echo "=========================================="
        echo "✅ 部署完成！"
        echo "=========================================="
        echo ""
        echo "🌐 服务地址:"
        echo "   - AI Service: http://localhost:8000"
        echo "   - API 文档:   http://localhost:8000/docs"
        echo "   - 健康检查:   http://localhost:8000/health"
        echo ""
        echo "📊 服务状态:"
        docker-compose ps
        ;;
    
    "down")
        echo "🛑 停止服务..."
        docker-compose down
        echo "✅ 服务已停止"
        ;;
    
    "restart")
        echo "🔄 重启服务..."
        docker-compose restart
        echo "✅ 服务已重启"
        ;;
    
    "logs")
        echo "📋 查看日志..."
        docker-compose logs -f
        ;;
    
    "status")
        echo "📊 服务状态:"
        docker-compose ps
        ;;
    
    "update")
        echo "🔄 更新服务..."
        docker-compose down
        docker-compose build --no-cache
        docker-compose up -d
        echo "✅ 服务已更新"
        ;;
    
    *)
        echo "用法: $0 [up|down|restart|logs|status|update]"
        echo ""
        echo "命令说明:"
        echo "  up      - 启动服务（默认）"
        echo "  down    - 停止服务"
        echo "  restart - 重启服务"
        echo "  logs    - 查看日志"
        echo "  status  - 查看状态"
        echo "  update  - 更新并重启服务"
        exit 1
        ;;
esac
