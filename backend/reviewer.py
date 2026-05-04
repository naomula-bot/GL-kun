"""
GL-kun: Claude APIを使った自動レビューエンジン
- プロンプトキャッシュで静的ガイドライン（PMBOK/Terasoluna）を効率化
- adaptive thinkingで複雑な設計レビューに対応
- ストリーミングでリアルタイム出力
"""
from pathlib import Path
import anthropic

_PROMPTS_DIR = Path(__file__).parent / "prompts"

def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")

# ガイドラインを起動時に一度だけ読み込む
PMBOK_GUIDE = _load_prompt("pmbok.md")
TERASOLUNA_GUIDE = _load_prompt("terasoluna.md")
DOC_FORMAT_GUIDE = _load_prompt("doc_formats.md")

DOC_TYPE_LABELS = {
    "basic_design": "基本設計書",
    "test_spec": "試験項目書",
    "test_result": "試験結果報告書",
}

def build_system_prompt() -> list[dict]:
    """
    システムプロンプトをキャッシュ可能なブロックとして構築する。
    静的なガイドライン部分にcache_controlを付与して、繰り返しリクエスト時のコストを削減。
    """
    return [
        {
            "type": "text",
            "text": (
                "あなたはシステム開発プロジェクトのグループリーダーを支援する、"
                "高度なレビューAIアシスタント「GL-kun」です。\n\n"
                "以下のレビューガイドラインを熟知した上で、提供されたドキュメントを"
                "厳密かつ建設的にレビューしてください。\n\n"
                "レビュー結果は以下の形式で出力してください：\n"
                "1. **総合評価**（A:問題なし / B:軽微な指摘 / C:要修正 / D:重大な問題）\n"
                "2. **観点別レビュー**（各観点で指摘事項・改善提案を箇条書き）\n"
                "3. **重要指摘事項**（C/D判定に相当する必須対応項目を優先順に列挙）\n"
                "4. **改善提案**（品質向上のための追加提案）\n"
                "5. **総評**（グループリーダーとして次のアクションを示す）\n\n"
                "---\n\n"
                "## PMBOK レビューガイドライン\n\n"
            ),
        },
        {
            "type": "text",
            "text": PMBOK_GUIDE,
        },
        {
            "type": "text",
            "text": "\n\n---\n\n## Terasoluna レビューガイドライン\n\n",
        },
        {
            "type": "text",
            "text": TERASOLUNA_GUIDE,
        },
        {
            "type": "text",
            "text": "\n\n---\n\n## ドキュメントフォーマット ガイドライン\n\n",
        },
        {
            "type": "text",
            "text": DOC_FORMAT_GUIDE,
            # 最後の静的ブロックにキャッシュポイントを設定
            "cache_control": {"type": "ephemeral"},
        },
    ]


def build_user_message(
    doc_type: str,
    doc_content: str,
    project_context: dict,
) -> str:
    """レビュー対象ドキュメントとプロジェクトコンテキストをユーザーメッセージとして構築する。"""
    doc_label = DOC_TYPE_LABELS.get(doc_type, doc_type)

    context_parts = []

    if project_context.get("project_overview"):
        context_parts.append(
            f"### プロジェクト概要\n{project_context['project_overview']}"
        )

    if project_context.get("project_rules"):
        context_parts.append(
            f"### プロジェクト固有ルール・規約\n{project_context['project_rules']}"
        )

    if project_context.get("recent_issues"):
        context_parts.append(
            f"### 最近の課題・障害・インシデント\n{project_context['recent_issues']}"
        )

    if project_context.get("custom_checklist"):
        context_parts.append(
            f"### 追加チェックリスト\n{project_context['custom_checklist']}"
        )

    context_section = ""
    if context_parts:
        context_section = (
            "## プロジェクトコンテキスト\n\n"
            + "\n\n".join(context_parts)
            + "\n\n---\n\n"
        )

    return (
        f"{context_section}"
        f"## レビュー依頼\n\n"
        f"以下の**{doc_label}**をレビューしてください。\n\n"
        f"レビュー観点：\n"
        f"- PMBOKガイドラインへの準拠\n"
        f"- Terasolunaフレームワーク・開発標準への準拠\n"
        f"- ドキュメントフォーマット・品質基準への準拠\n"
        f"- プロジェクト固有ルール・最近の課題への対応\n\n"
        f"---\n\n"
        f"## {doc_label} 本文\n\n"
        f"{doc_content}"
    )


async def stream_review(
    doc_type: str,
    doc_content: str,
    project_context: dict,
    api_key: str,
):
    """
    Claude APIでレビューをストリーミング実行するジェネレーター。
    FastAPIのStreamingResponseから呼び出す。
    """
    client = anthropic.Anthropic(api_key=api_key)

    system_blocks = build_system_prompt()
    user_message = build_user_message(doc_type, doc_content, project_context)

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for event in stream:
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    yield event.delta.text
            elif event.type == "message_delta":
                # 使用トークン情報を最後に送信
                if hasattr(event, "usage"):
                    usage = event.usage
                    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
                    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
                    yield (
                        f"\n\n---\n*トークン使用量: 入力={usage.input_tokens}, "
                        f"出力={usage.output_tokens}, "
                        f"キャッシュ読込={cache_read}, "
                        f"キャッシュ作成={cache_create}*"
                    )
