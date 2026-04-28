import os
import sys
import json
import asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
from database import init_db, get_conn
from rag import retrieve_examples, add_session

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="AI面试练习系统", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── 生成面试题 ──────────────────────────────────────────
class JDRequest(BaseModel):
    jd: str
    role_name: str = ""
    question_count: int = 5

@app.post("/session")
async def create_session(req: JDRequest):
    examples = retrieve_examples(req.jd, k=3)
    examples_block = ""
    if examples:
        lines = []
        for ex in examples:
            role = ex["role_name"] or "未命名岗位"
            qs = "\n".join(f"  - {q}" for q in ex["questions"][:5])
            lines.append(f"【{role}】\n{qs}")
        examples_block = "以下是历史相似岗位的面试题，供参考：\n" + "\n\n".join(lines) + "\n\n---\n\n"

    prompt = f"""你是一位资深技术面试官。根据以下岗位描述，生成 {req.question_count} 道面试题。

{examples_block}岗位描述：
{req.jd}

要求：
- 覆盖技术深度、项目经验、场景问题
- 每道题单独一行
- 只输出题目，不要编号，不要其他内容"""

    resp = await client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.choices[0].message.content.strip()
    questions = [q.strip() for q in raw.split("\n") if q.strip()]

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (role_name, jd) VALUES (%s, %s)",
                (req.role_name, req.jd)
            )
            session_id = cur.lastrowid
            for i, q in enumerate(questions):
                cur.execute(
                    "INSERT INTO questions (session_id, order_num, question) VALUES (%s, %s, %s)",
                    (session_id, i + 1, q)
                )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM questions WHERE session_id=%s ORDER BY order_num", (session_id,))
            qs = cur.fetchall()
    finally:
        conn.close()

    asyncio.create_task(_save_to_rag(req.jd, req.role_name, questions))

    return {"session_id": session_id, "role_name": req.role_name, "questions": qs}


async def _save_to_rag(jd, role_name, questions):
    try:
        await asyncio.to_thread(add_session, jd, role_name, questions)
        print("[RAG] 向量存储完成")
    except Exception as e:
        print(f"[RAG] 存储失败: {e}")


# ── 提交回答（流式评分）──────────────────────────────────
class AnswerRequest(BaseModel):
    question_id: int
    answer: str

@app.post("/answer-stream")
async def answer_stream(req: AnswerRequest):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT question FROM questions WHERE id=%s", (req.question_id,))
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="题目不存在")

    question = row["question"]
    prompt = f"""你是一位资深技术面试官，请对候选人的回答进行评分和点评。

面试题：{question}

候选人回答：{req.answer}

请按以下格式输出：
【评分】X/10
【优点】...
【不足】...
【建议】...
【参考答案要点】..."""

    async def event_stream():
        full = ""
        stream = await client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                full += delta
                yield f"data: {json.dumps({'t': delta})}\n\n"
                await asyncio.sleep(0)

        # 解析评分并存库
        score = 5
        for line in full.split("\n"):
            if "评分" in line and "/" in line:
                try:
                    score = int(line.split("【评分】")[-1].split("/")[0].strip())
                except:
                    pass

        conn2 = get_conn()
        try:
            with conn2.cursor() as cur:
                cur.execute(
                    "INSERT INTO answers (question_id, answer, score, feedback) VALUES (%s, %s, %s, %s)",
                    (req.question_id, req.answer, score, full)
                )
            conn2.commit()
        finally:
            conn2.close()

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 历史记录 ────────────────────────────────────────────
@app.get("/sessions")
def get_sessions():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, role_name, created_at FROM sessions ORDER BY created_at DESC")
            return cur.fetchall()
    finally:
        conn.close()

@app.get("/session/{session_id}")
def get_session(session_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE id=%s", (session_id,))
            session = cur.fetchone()
            if not session:
                raise HTTPException(status_code=404, detail="不存在")
            cur.execute("SELECT * FROM questions WHERE session_id=%s ORDER BY order_num", (session_id,))
            questions = cur.fetchall()
            for q in questions:
                cur.execute("SELECT * FROM answers WHERE question_id=%s ORDER BY created_at DESC LIMIT 1", (q["id"],))
                q["answer"] = cur.fetchone()
        return {"session": session, "questions": questions}
    finally:
        conn.close()

@app.delete("/session/{session_id}")
def delete_session(session_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE id=%s", (session_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}

@app.get("/health")
def health():
    return {"status": "running"}
