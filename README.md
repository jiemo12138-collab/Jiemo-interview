# Jiemo-Interview

基于 AI 的面试练习系统，输入岗位描述（JD）自动生成面试题，支持作答后实时流式评分，并通过 RAG 管道使题目质量随练习次数持续提升。

## 项目结构

```
interview-practice/
├── api/main.py       # FastAPI 后端
├── database.py       # MySQL 数据库初始化与连接
├── rag.py            # LangChain + FAISS RAG 管道
├── frontend/         # 前端页面
└── requirements.txt
```

## 快速开始

```bash
pip install -r requirements.txt
```

配置 `.env`：

```
DEEPSEEK_API_KEY=your_key
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DB=interview_practice
```

启动后端：

```bash
uvicorn api.main:app --reload
```

然后直接用浏览器打开 `frontend/index.html`。

## 功能

- 输入 JD 自动生成面试题（支持 3 / 5 / 8 题）
- 作答后 AI 实时流式评分，TTFB < 10ms
- 评分包含优点、不足、建议与参考答案
- 历史练习记录存储，支持回放查看
- RAG 管道：历史 JD 越多，题目生成质量越高

## 技术栈

- **FastAPI** — 后端接口
- **MySQL** — 数据持久化
- **LangChain + FAISS + BGE** — RAG 检索管道
- **DeepSeek** — LLM
- **SSE** — 流式评分输出
