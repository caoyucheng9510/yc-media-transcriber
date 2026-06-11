from __future__ import annotations

from app.llm.structured import DialogItem, KeyInfo
from app.schemas import Term


KEY_INFO_SYSTEM_PROMPT = "你负责从媒体元数据中提取转录校对会用到的关键信息。只输出 JSON object。"
PLAIN_CALIBRATION_SYSTEM_PROMPT = "你是严谨的中文 ASR 校对助手。只输出校对后的正文，不解释过程。"
STRUCTURED_CALIBRATION_SYSTEM_PROMPT = "你是严谨的中文对话转录校对助手。只输出 JSON object。"
SPEAKER_INFERENCE_SYSTEM_PROMPT = "你负责根据元数据和转录片段推断说话人标签。只输出 JSON object。"
SUMMARY_SINGLE_SPEAKER_SYSTEM_PROMPT = "你擅长把单人转录稿整理成结构清晰的中文总结。"
SUMMARY_MULTI_SPEAKER_SYSTEM_PROMPT = "你擅长把多人对话转录稿整理成结构清晰的中文总结。"
QUALITY_VALIDATION_SYSTEM_PROMPT = "你负责评估 ASR 校对结果质量。只输出 JSON object。"


def build_key_info_user_prompt(metadata: dict) -> str:
    return (
        "请提取可能影响中文转录校对的名称、地点、术语、品牌、缩写、外文词和其他实体。\n"
        "字段固定为 names、places、technical_terms、brands、abbreviations、foreign_terms、other_entities，"
        "每个字段都是字符串数组。不要输出推断理由。\n\n"
        f"平台：{metadata.get('platform') or ''}\n"
        f"标题：{metadata.get('title') or ''}\n"
        f"作者：{metadata.get('author') or metadata.get('uploader') or ''}\n"
        f"简介：{metadata.get('description') or ''}"
    )


def build_plain_calibration_user_prompt(
    *,
    text: str,
    metadata: dict,
    terms: list[Term],
    key_info: KeyInfo,
    speaker_mapping: dict[str, str],
) -> str:
    return (
        "请校对下面的 ASR 文本，修正明显错字、术语、人名、标点和断句。\n"
        "保留原意和事实，不新增内容，不压缩内容；按语义自然分段。\n"
        "如果原文包含说话人标签或姓名，请保留。只输出校对后的正文。\n\n"
        f"参考信息：\n{_reference_text(metadata, terms, key_info, speaker_mapping)}\n\n"
        f"待校对文本：\n{text}"
    )


def build_structured_calibration_user_prompt(
    *,
    dialogs: list[DialogItem],
    metadata: dict,
    terms: list[Term],
    key_info: KeyInfo,
    speaker_mapping: dict[str, str],
) -> str:
    dialog_lines = [
        f"{index}. speaker_label={item.speaker_label}; text={item.text}"
        for index, item in enumerate(dialogs, start=1)
    ]
    return (
        "请逐条校对对话文本，并输出 JSON object。\n"
        "输出格式：{\"calibrated_dialogs\":[{\"speaker_label\":\"Speaker1\",\"text\":\"校对后的文本\"}]}。\n"
        "要求：输入多少条就输出多少条；不得合并、拆分、新增或删除对话；speaker_label 必须逐条保持一致；"
        "不要输出 start/end；不新增事实，不压缩内容，不解释过程。\n\n"
        f"参考信息：\n{_reference_text(metadata, terms, key_info, speaker_mapping)}\n\n"
        f"待校对对话：\n{chr(10).join(dialog_lines)}"
    )


def build_speaker_inference_user_prompt(
    *,
    metadata: dict,
    source_labels: list[str],
    preview: str,
    terms: list[Term],
) -> str:
    terms_text = "\n".join(f"- {term.correct} ({term.context})" for term in terms[:30]) or "无"
    return (
        "请判断说话人标签是否能映射到真实姓名或角色。\n"
        "只能输出 JSON object，字段为 speaker_mapping、confidence、source_labels。\n"
        "confidence 是 0 到 1 的数字；不确定时把标签映射为原标签或留空，不输出理由。\n\n"
        f"标题：{metadata.get('title') or ''}\n"
        f"简介：{metadata.get('description') or ''}\n"
        f"说话人标签：{', '.join(source_labels)}\n"
        f"候选术语：\n{terms_text}\n\n"
        f"转录预览：\n{preview}"
    )


def build_summary_user_prompt(*, text: str, metadata: dict, speaker_mapping: dict[str, str]) -> str:
    speakers = "\n".join(f"- {label} => {name}" for label, name in speaker_mapping.items())
    speaker_section = f"说话人参考：\n{speakers}\n\n" if speakers else ""
    return (
        "请基于转录稿生成中文总结，固定输出 Markdown：\n"
        "## 总结\n一段 100 到 300 字总结。\n\n"
        "## 关键要点\n- 要点 1\n- 要点 2\n- 要点 3\n\n"
        "不要输出原文全文，不解释处理过程。\n\n"
        f"标题：{metadata.get('title') or '未命名媒体'}\n\n"
        f"{speaker_section}"
        f"转录稿：\n{text}"
    )


def build_summary_chunk_user_prompt(*, text: str, metadata: dict) -> str:
    return (
        "请把下面这个转录片段压缩成后续总结合并会用到的中文要点。"
        "只输出要点列表，不解释过程。\n\n"
        f"标题：{metadata.get('title') or '未命名媒体'}\n\n"
        f"转录片段：\n{text}"
    )


def build_quality_validation_user_prompt(*, original_text: str, polished_text: str, mode: str) -> str:
    return (
        "请评估校对稿是否保持原意、完整性、流畅度和格式。\n"
        "只输出 JSON object，字段 accuracy、completeness、fluency、format，取值 0 到 1。\n\n"
        f"模式：{mode}\n\n"
        f"原文：\n{original_text}\n\n"
        f"校对稿：\n{polished_text}"
    )


def _reference_text(
    metadata: dict,
    terms: list[Term],
    key_info: KeyInfo,
    speaker_mapping: dict[str, str],
) -> str:
    lines = [f"- 标题：{metadata.get('title') or '未命名媒体'}"]
    lines.extend(f"- 术语：{term.incorrect or '(常见误写)'} => {term.correct} ({term.context})" for term in terms)
    for group_name in (
        "names",
        "places",
        "technical_terms",
        "brands",
        "abbreviations",
        "foreign_terms",
        "other_entities",
    ):
        values = getattr(key_info, group_name)
        if values:
            lines.append(f"- {group_name}: {', '.join(values[:20])}")
    lines.extend(f"- 说话人：{label} => {name}" for label, name in speaker_mapping.items())
    return "\n".join(lines)
