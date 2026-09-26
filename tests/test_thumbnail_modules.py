import json
from pathlib import Path

import pytest
from PIL import Image

from hotpost.thumbnail_planner import create_plan, flow_prompt
from hotpost.flow_image_adapter import GoogleFlowImageAdapter


def plan():
    return create_plan(subject="백팩", script="나일론 재질 백팩의 수납을 살펴봐요", feature="수납")


def test_seven_editorial_levers_without_invented_scarcity():
    value = plan()
    assert len(value["candidates"]) == 7
    assert {c["lever"] for c in value["candidates"] if not c["eligible"]} == {"scarcity", "social_proof"}
    assert "\n" not in value["selected"]["text"]
    assert value["review_required"]
    assert "No captions" in flow_prompt(value)
    assert "reference" in flow_prompt(value)


def test_two_line_hook_and_desire_led_visual_direction(tmp_path):
    value = create_plan(subject="백팩", script="명품 감성 코디를 살펴봐요",
        custom_hook={"text": "명품인 줄?\n이 백팩의 반전", "lever": "contrast", "script_quote": "명품 감성 코디"},
        caption_placement="top",
        visual_direction={"desire": "나도 입고 싶은 스타일", "scene": "charcoal tailored outfit",
                          "composition": "large cream bag, dark headline band"})
    prompt = flow_prompt(value)
    assert "Viewer desire:" in prompt and "charcoal tailored outfit" in prompt
    assert "soft directional lighting" not in prompt
    image = tmp_path / "reference.png"
    Image.new("RGB", (576, 1024)).save(image)
    adapter = GoogleFlowImageAdapter(tmp_path)
    adapter.prepare(tmp_path / "job", value, [image])
    adapter.accept_image(tmp_path / "job", image, reviewed=True, flow_url="https://flow.google/project/example")
    assert adapter.editing_thumbnail(tmp_path / "job")["text"] == "명품인 줄?\n이 백팩의 반전"
    assert adapter.editing_thumbnail(tmp_path / "job")["placement"] == "top"


@pytest.mark.parametrize("text", ["\n빈줄", "첫\n\n둘", "첫\n둘\n셋", "가"*21])
def test_custom_hook_rejects_invalid_line_layout(text):
    with pytest.raises(ValueError):
        create_plan(subject="백팩", script="코디", custom_hook={
            "text": text, "lever": "contrast", "script_quote": "코디"})


def test_specificity_requires_script_evidence_and_claims_require_review():
    with pytest.raises(ValueError, match="verbatim"):
        create_plan(subject="백팩", script="가방", feature="100만개 판매")
    with pytest.raises(ValueError, match="reviewed evidence"):
        create_plan(subject="백팩", script="가방", claims={"scarcity": {"text": "품절 직전"}})


def test_flow_pending_review_accept_and_tamper_detection(tmp_path):
    reference = tmp_path / "reference.png"
    image = tmp_path / "flow.png"
    Image.new("RGB", (576, 1024)).save(reference)
    Image.new("RGB", (576, 1024), "green").save(image)
    adapter = GoogleFlowImageAdapter(tmp_path)
    job = tmp_path / "job"
    result = adapter.prepare(job, plan(), [reference])
    assert result["status"] == "awaiting_image"
    with pytest.raises(ValueError, match="pending"):
        adapter.editing_thumbnail(job)
    with pytest.raises(ValueError, match="Review"):
        adapter.accept_image(job, image, flow_url="https://labs.google/fx/tools/flow/project/example")
    result = adapter.accept_image(job, image, reviewed=True,
                                  flow_url="https://labs.google/fx/tools/flow/project/example")
    thumbnail = adapter.editing_thumbnail(job)
    assert thumbnail["text"] == plan()["selected"]["text"]
    assert thumbnail["provider"] == "google_flow"
    with pytest.raises(FileExistsError):
        adapter.accept_image(job, image, reviewed=True, flow_url="https://flow.google/example")
    Path(result["image_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        adapter.editing_thumbnail(job)


def test_flow_rejects_outside_paths_and_changed_reference(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "outside.png"
    Image.new("RGB", (576, 1024)).save(outside)
    adapter = GoogleFlowImageAdapter(root)
    with pytest.raises(ValueError, match="under data_dir"):
        adapter.prepare(root / "bad", plan(), [outside])
    ref = root / "ref.png"
    Image.new("RGB", (576, 1024)).save(ref)
    adapter.prepare(root / "job", plan(), [ref])
    Image.new("RGB", (576, 1024), "red").save(ref)
    with pytest.raises(ValueError, match="Reference changed"):
        adapter.accept_image(root / "job", ref, reviewed=True, flow_url="https://flow.google/example")
