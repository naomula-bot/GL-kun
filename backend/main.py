"""
GL-kun FastAPI アプリケーション
グループリーダー向け自動レビューシステム
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from reviewer import stream_review

load_dotenv()

app = FastAPI(title="GL-kun", description="グループリーダー向け自動レビューシステム")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CONTEXT_FILE = DATA_DIR / "context.json"

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# ---------------------------------------------------------------------------
# Pydantic モデル
# ---------------------------------------------------------------------------

class ProjectContext(BaseModel):
    project_overview: str = ""
    project_rules: str = ""
    recent_issues: str = ""
    custom_checklist: str = ""


class ReviewRequest(BaseModel):
    doc_type: str  # basic_design | test_spec | test_result
    doc_content: str
    # コンテキストは保存済みのものを使うか、リクエスト時に上書き可能
    context_override: ProjectContext | None = None


# ---------------------------------------------------------------------------
# コンテキスト管理エンドポイント
# ---------------------------------------------------------------------------

@app.get("/api/context", response_model=ProjectContext)
def get_context():
    """保存済みのプロジェクトコンテキストを取得する。"""
    if CONTEXT_FILE.exists():
        return ProjectContext(**json.loads(CONTEXT_FILE.read_text("utf-8")))
    return ProjectContext()


@app.post("/api/context", response_model=ProjectContext)
def save_context(ctx: ProjectContext):
    """プロジェクトコンテキストを保存する。"""
    CONTEXT_FILE.write_text(ctx.model_dump_json(indent=2), encoding="utf-8")
    return ctx


# ---------------------------------------------------------------------------
# レビューエンドポイント（ストリーミング）
# ---------------------------------------------------------------------------

@app.post("/api/review")
async def review(req: ReviewRequest):
    """ドキュメントをレビューしてストリーミングで結果を返す。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEYが設定されていません")

    valid_types = {"basic_design", "test_spec", "test_result"}
    if req.doc_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"doc_typeは {valid_types} のいずれかを指定してください")

    if not req.doc_content.strip():
        raise HTTPException(status_code=400, detail="ドキュメント本文が空です")

    # コンテキスト: リクエストで上書きされていればそちらを優先、なければ保存済みを使用
    if req.context_override:
        context = req.context_override.model_dump()
    elif CONTEXT_FILE.exists():
        context = json.loads(CONTEXT_FILE.read_text("utf-8"))
    else:
        context = {}

    async def generate():
        try:
            async for chunk in stream_review(
                doc_type=req.doc_type,
                doc_content=req.doc_content,
                project_context=context,
                api_key=api_key,
            ):
                yield chunk
        except Exception as e:
            yield f"\n\n**エラーが発生しました**: {e}"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


# ---------------------------------------------------------------------------
# ヘルスチェック
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "GL-kun"}


# ---------------------------------------------------------------------------
# フロントエンド静的ファイル配信
# ---------------------------------------------------------------------------

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
