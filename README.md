# Telegram 频道内容采集机器人

一个功能强大的Telegram机器人，用于自动采集频道中的视频和图片内容，并提供智能分类和去重功能。

## 功能特性

- 🤖 **智能机器人**: 友好的用户交互界面
- 📺 **内容采集**: 自动采集频道中的视频和图片
- 🏷️ **自动分类**: 基于关键词和规则的智能分类系统
- 🔍 **去重检测**: 高效的重复内容检测和处理
- 📊 **统计分析**: 详细的采集和存储统计信息
- ⚙️ **灵活配置**: 丰富的配置选项和用户设置

## 快速开始

### 1. 环境准备

确保你的系统已安装Python 3.8或更高版本。

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置设置

1. 复制配置文件模板：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入必要的配置：
```env
# Telegram Bot配置
BOT_TOKEN=your_bot_token_here
API_ID=your_api_id_here
API_HASH=your_api_hash_here

# 其他配置项...
```

### 4. 获取Telegram配置

#### 获取Bot Token
1. 在Telegram中找到 [@BotFather](https://t.me/botfather)
2. 发送 `/newbot` 创建新机器人
3. 按提示设置机器人名称和用户名
4. 获得Bot Token并填入配置文件

#### 获取API ID和API Hash
1. 访问 [my.telegram.org](https://my.telegram.org)
2. 登录你的Telegram账号
3. 进入 "API development tools"
4. 创建新应用获取API ID和API Hash

### 5. 运行机器人

```bash
python main.py
```

## 使用指南

### 基本命令

- `/start` - 启动机器人并查看欢迎信息
- `/help` - 查看所有可用命令
- `/status` - 查看机器人运行状态

### 频道管理

- `/add_channel <频道链接>` - 添加要监控的频道
- `/list_channels` - 查看所有监控的频道
- `/remove_channel <频道ID>` - 移除频道

### 统计和搜索

- `/stats` - 查看采集统计信息
- `/search <关键词>` - 搜索已采集的内容

### 设置配置

- `/settings` - 配置机器人设置

## 项目结构

```
├── main.py                 # 主程序入口
├── requirements.txt        # 依赖包列表
├── .env.example           # 配置文件模板
├── src/                   # 源代码目录
│   ├── bot/              # 机器人模块
│   │   ├── telegram_bot.py      # 主机器人类
│   │   └── channel_manager.py   # 频道管理器
│   ├── collector/        # 内容采集模块
│   │   └── message_collector.py # 消息采集器
│   ├── classifier/       # 自动分类模块
│   ├── deduplicator/     # 去重检测模块
│   ├── storage/          # 存储管理模块
│   ├── database/         # 数据库模块
│   │   ├── models.py            # 数据模型
│   │   └── database_manager.py  # 数据库管理器
│   ├── config/           # 配置模块
│   │   └── settings.py          # 配置管理
│   └── utils/            # 工具模块
│       └── logger.py            # 日志工具
├── data/                 # 数据目录
├── downloads/            # 下载文件目录
└── logs/                 # 日志目录
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `BOT_TOKEN` | Telegram Bot Token | 必填 |
| `API_ID` | Telegram API ID | 必填 |
| `API_HASH` | Telegram API Hash | 必填 |
| `DATABASE_URL` | 数据库连接URL | `sqlite:///./data/bot.db` |
| `STORAGE_PATH` | 文件存储路径 | `./downloads` |
| `MAX_FILE_SIZE_MB` | 最大文件大小(MB) | `100` |
| `ENABLE_VIDEO_COLLECTION` | 启用视频采集 | `true` |
| `ENABLE_IMAGE_COLLECTION` | 启用图片采集 | `true` |

更多配置选项请参考 `.env.example` 文件。

## 开发状态

当前项目正在开发中，已完成的功能模块：

- ✅ 项目结构和配置管理
- ✅ 数据库模型设计
- ✅ Telegram机器人基础框架
- ✅ 频道管理功能
- ✅ 消息采集引擎基础
- 🚧 自动分类系统（开发中）
- 🚧 去重检测算法（开发中）
- 🚧 存储管理系统（开发中）
- 🚧 完整的用户界面（开发中）

## 贡献

欢迎提交Issue和Pull Request来帮助改进这个项目。

## 许可证

本项目采用MIT许可证。

## 注意事项

1. 请确保遵守Telegram的使用条款和API限制
2. 建议在使用前仔细阅读相关法律法规
3. 请勿用于非法用途
4. 建议定期备份数据库和配置文件
