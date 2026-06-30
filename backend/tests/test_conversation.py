from app.services.analyzer import _is_knowledge_question, _merge_followup


def _data_history():
    return [
        {"role": "user", "content": "分析近10天各地区销售额趋势", "payload": None},
        {
            "role": "assistant",
            "content": "分析完成",
            "payload": {
                "answer_type": "data_analysis",
                "effective_question": "分析近10天各地区销售额趋势",
            },
        },
    ]


def test_followup_inherits_previous_question() -> None:
    effective, applied = _merge_followup("只看华东，并改成柱状图", _data_history())
    assert applied is True
    assert "近10天" in effective
    assert "销售额" in effective
    assert "华东" in effective
    assert "柱状图" in effective


def test_dimension_followup_adds_dimension_without_dropping_region() -> None:
    effective, applied = _merge_followup("按产品类别拆分", _data_history())
    assert applied is True
    assert "产品类别" in effective
    assert "各地区" in effective


def test_explicit_dimension_replace_can_drop_region() -> None:
    effective, applied = _merge_followup("只按产品类别拆分", _data_history())
    assert applied is True
    assert "产品类别" in effective
    assert "各地区" not in effective


def test_knowledge_question_detection_and_followup() -> None:
    assert _is_knowledge_question("投诉率的计算口径是什么", []) is True
    history = [
        {"role": "assistant", "content": "回答", "payload": {"answer_type": "knowledge_qa"}},
    ]
    assert _is_knowledge_question("这个指标适用于什么范围", history) is True
