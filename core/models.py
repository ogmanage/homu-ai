from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class RiskItem(BaseModel):
    category: str = Field(description="リスクカテゴリ（例: 責任制限）")
    issue: str = Field(description="具体的な指摘内容")
    risk_level: RiskLevel = Field(description="リスクレベル")
    current_clause: str = Field(description="契約書からの該当条文抜粋（なければ空文字）")
    suggested_clause: str = Field(description="修正案となる条文テキスト")
    reason: str = Field(description="修正が必要な理由")
    law_basis: str = Field(description="法的根拠（例: 民法416条1項）")


class ReviewResult(BaseModel):
    overall_grade: Literal["A", "B", "C", "D", "E"] = Field(description="総合評価グレード")
    grade_reason: str = Field(description="グレード判定の理由")
    risk_items: list[RiskItem] = Field(description="リスク項目リスト")
    general_notes: str = Field(description="全体的な所見・補足コメント")


class ContractDraft(BaseModel):
    title: str = Field(description="契約書タイトル")
    body_markdown: str = Field(description="契約書本文（Markdown形式）")
    notes: list[str] = Field(description="要確認事項・締結前チェックリスト")


class ClauseChange(BaseModel):
    clause_number: str = Field(description="条項番号（例: 第5条）")
    change_type: Literal["追加", "削除", "変更"] = Field(description="変更種別")
    old_text: str | None = Field(default=None, description="変更前のテキスト")
    new_text: str | None = Field(default=None, description="変更後のテキスト")
    explanation: str = Field(description="変更内容の説明と法的影響")


class ComparisonResult(BaseModel):
    summary: str = Field(description="比較結果の全体サマリー")
    changes: list[ClauseChange] = Field(description="変更点リスト")
    risk_assessment: str = Field(description="変更によるリスク評価")
