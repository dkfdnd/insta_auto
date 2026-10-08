"""Keep lossless evidence on disk while fitting the visual writer's transport cap."""
import base64
import io

from PIL import Image


def frame_inline_data(path, *, max_bytes=1024*1024):
    """JPEG encoding only: never resize, crop, or change the coordinate system."""
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1024*1024:
        raise ValueError('Invalid visual transport byte limit')
    with Image.open(path) as image:
        if image.width*image.height>4_000_000:
            raise ValueError('분석 프레임 해상도가 너무 큽니다.')
        rgb=image.convert('RGB')
        for quality in (90,80,70,60,50):
            encoded=io.BytesIO();rgb.save(encoded,format='JPEG',quality=quality)
            raw=encoded.getvalue()
            if len(raw)<=max_bytes:
                return {'mimeType':'image/jpeg','data':base64.b64encode(raw).decode('ascii')}
    raise ValueError('분석 프레임을 같은 해상도로 전달할 수 없습니다.')
