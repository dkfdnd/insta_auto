import base64
import hashlib
import io

from PIL import Image

from hotpost.visual_media import frame_inline_data


def test_large_lossless_frame_fits_transport_without_resizing_or_changing_evidence(tmp_path):
    path=tmp_path/'actual-frame.png'
    Image.effect_noise((1080,1920),100).convert('RGB').save(path)
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.stat().st_size>1024*1024
    encoded=frame_inline_data(path);raw=base64.b64decode(encoded['data'],validate=True)
    assert encoded['mimeType']=='image/jpeg' and len(raw)<=1024*1024
    with Image.open(io.BytesIO(raw)) as frame:
        assert frame.size==(1080,1920) and frame.format=='JPEG'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before


def test_function_review_receives_valid_bounded_jpeg_for_png_evidence(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from hotpost import script_rewriter
    from hotpost.source_functional import review_function
    path=tmp_path/'actual-frame.png';Image.new('RGB',(1080,1920),'white').save(path)
    def visual(settings,instruction,data,*,media):
        image=next(m['inlineData'] for m in media if 'inlineData' in m)
        with Image.open(io.BytesIO(base64.b64decode(image['data']))) as frame:
            assert frame.format=='JPEG' and frame.size==(1080,1920)
        return {'same_core_function':True,'observed_actions':['actual assembly']}
    monkeypatch.setattr(script_rewriter,'_generate',visual)
    result=review_function(None,SimpleNamespace(file_sha256='test-sha'),[path],[path])
    assert result['same_core_function'] and str(path) in result['evidence_frames']


def test_overlay_transport_cap_keeps_exact_canvas_and_rejects_unfit_evidence(tmp_path):
    import pytest
    path=tmp_path/'bounded.png';Image.new('RGB',(1080,1920),'white').save(path)
    encoded=frame_inline_data(path,max_bytes=384*1024)
    raw=base64.b64decode(encoded['data'],validate=True)
    assert len(raw)<=384*1024
    with Image.open(io.BytesIO(raw)) as image:assert image.size==(1080,1920)
    with pytest.raises(ValueError):frame_inline_data(path,max_bytes=1)
    with pytest.raises(ValueError):frame_inline_data(path,max_bytes=0)
