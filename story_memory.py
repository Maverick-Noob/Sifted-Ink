"""
Lightweight RAG story memory — structured key info per chapter for coherence.

Instead of passing raw text context (which is lossy and noisy), we extract
structured "memories" from each chapter and retrieve the most relevant ones
when writing subsequent chapters.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChapterMemory:
    """Structured key information extracted from a single chapter."""
    chapter_num: int
    ending_location: str = ""          # where characters are at chapter end
    active_characters: list[str] = field(default_factory=list)  # who is present
    key_events: list[str] = field(default_factory=list)         # what happened
    unresolved_threads: list[str] = field(default_factory=list) # dangling plots
    emotional_state: str = ""          # protagonist's mood at chapter end
    new_npcs_introduced: list[str] = field(default_factory=list) # first appearances
    npcs_exited: list[str] = field(default_factory=list)         # departures/deaths
    items_acquired: list[str] = field(default_factory=list)      # key items gained
    scene_summary: str = ""             # 1-2 sentence chapter-end snapshot


class StoryMemoryStore:
    """
    Accumulates ChapterMemory objects and retrieves relevant context
    for the NarrativeWriter when generating a new chapter.
    """

    def __init__(self, max_recent: int = 3, max_unresolved: int = 5):
        self.memories: list[ChapterMemory] = []
        self.max_recent = max_recent
        self.max_unresolved = max_unresolved

    def add(self, memory: ChapterMemory):
        self.memories.append(memory)

    def get_last(self) -> Optional[ChapterMemory]:
        return self.memories[-1] if self.memories else None

    def get_unresolved(self) -> list[str]:
        """Get all unresolved threads still pending resolution."""
        threads = []
        for m in self.memories:
            for t in m.unresolved_threads:
                if t not in threads:
                    threads.append(t)
        return threads[-self.max_unresolved:]

    def get_npc_intros(self, npc_names: list[str]) -> list[str]:
        """Get the first-appearance context for specific NPCs."""
        intros = []
        for m in self.memories:
            for name in npc_names:
                if name in m.new_npcs_introduced:
                    intros.append(f"{name} 首次登场于第{m.chapter_num}章")
        return intros

    def build_context(self, current_chapter: int, active_npc_names: list[str]) -> str:
        """
        Build a RAG context string for the NarrativeWriter.
        Retrieves: last chapter memory + unresolved threads + NPC intros.
        """
        parts = []

        # 1. Last chapter's ending snapshot (most critical for continuity)
        last = self.get_last()
        if last:
            parts.append("## 上一章结尾状态（必须衔接）")
            parts.append(f"- 位置: {last.ending_location or '未知'}")
            parts.append(f"- 在场角色: {', '.join(last.active_characters) if last.active_characters else '未知'}")
            parts.append(f"- 主角情绪: {last.emotional_state or '未知'}")
            if last.key_events:
                parts.append(f"- 关键事件: {'; '.join(last.key_events[-3:])}")
            if last.items_acquired:
                parts.append(f"- 获得物品: {', '.join(last.items_acquired)}")
            if last.scene_summary:
                parts.append(f"- 场景快照: {last.scene_summary}")
            parts.append("")

        # 2. Recent chapters (2-3 back) for broader context
        recent = self.memories[-self.max_recent:-1] if len(self.memories) > 1 else []
        if recent:
            parts.append("## 近期章节摘要")
            for m in recent:
                parts.append(
                    f"- 第{m.chapter_num}章: 位置={m.ending_location or '?'}, "
                    f"事件={'/'.join(m.key_events[-2:]) if m.key_events else '?'}"
                )
            parts.append("")

        # 3. Unresolved plot threads
        unresolved = self.get_unresolved()
        if unresolved:
            parts.append("## 未解决的剧情线索（需要在后续章节中推进）")
            for t in unresolved:
                parts.append(f"- {t}")
            parts.append("")

        # 4. NPC first-appearance context
        npc_intros = self.get_npc_intros(active_npc_names)
        if npc_intros:
            parts.append("## NPC 出场记录")
            for intro in npc_intros:
                parts.append(f"- {intro}")
            parts.append("")

        # 5. Active NPC snapshot
        if active_npc_names:
            parts.append(f"## 当前活跃 NPC: {', '.join(active_npc_names[:8])}")
            parts.append("")

        return "\n".join(parts) if parts else ""


# ═══════════════════════════════════════════════════════════════════════
# LLM-based chapter memory extraction
# ═══════════════════════════════════════════════════════════════════════

MEMORY_EXTRACTION_PROMPT = """你是一位细心的故事记录员。请从以下章节内容中提取关键的结构化信息。

## 章节内容
{chapter_text}

## 输出格式（严格 JSON）
```json
{{
  "ending_location": "章节结尾时角色所在的地点（如：龙眠谷入口、王都大殿）",
  "active_characters": ["在场角色名列表"],
  "key_events": ["本章发生的1-3个关键事件"],
  "unresolved_threads": ["本章新产生或仍未解决的剧情线索，如'铁山被抓走，下落不明'"],
  "emotional_state": "主角在章节结尾时的情绪状态",
  "new_npcs_introduced": ["本章首次出场的新NPC名字"],
  "npcs_exited": ["本章退场/死亡的NPC名字"],
  "items_acquired": ["本章获得的重要物品"],
  "scene_summary": "用1-2句话描述章节结尾的场景状态，确保下一章可以从这里无缝衔接"
}}
```
"""


async def extract_chapter_memory(
    chapter_text: str, chapter_num: int, llm_client,
) -> ChapterMemory:
    """
    Use LLM to extract structured ChapterMemory from chapter narrative text.
    Falls back to a minimal memory if LLM fails.
    """
    if not llm_client or not chapter_text.strip():
        return ChapterMemory(chapter_num=chapter_num)

    # Use last 1500 chars for extraction (ending is most important for continuity)
    snippet = chapter_text[-1500:] if len(chapter_text) > 1500 else chapter_text

    prompt = MEMORY_EXTRACTION_PROMPT.format(chapter_text=snippet)

    try:
        from .utils import extract_json
        text, _ = await llm_client.call(
            prompt, "请提取本章关键信息。", temperature=0.3, max_tokens=500,
        )
        data = extract_json(text)
        if data and isinstance(data, dict):
            return ChapterMemory(
                chapter_num=chapter_num,
                ending_location=data.get("ending_location", ""),
                active_characters=data.get("active_characters", []),
                key_events=data.get("key_events", []),
                unresolved_threads=data.get("unresolved_threads", []),
                emotional_state=data.get("emotional_state", ""),
                new_npcs_introduced=data.get("new_npcs_introduced", []),
                npcs_exited=data.get("npcs_exited", []),
                items_acquired=data.get("items_acquired", []),
                scene_summary=data.get("scene_summary", ""),
            )
    except Exception:
        pass

    # Fallback: extract what we can from state
    return ChapterMemory(chapter_num=chapter_num)
