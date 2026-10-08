"""Read explicit numeric units, including Korean spellings used for TTS.

This deliberately does not infer quantities from vague words or ASR guesses.
"""
import re
from decimal import Decimal

_DIGITS = dict(zip('영공일이삼사오육칠팔구', (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9)))
_SCALES = {'십': 10, '백': 100, '천': 1000}
_NATIVE = {'한': 1, '두': 2, '세': 3, '네': 4, '다섯': 5, '여섯': 6,
           '일곱': 7, '여덟': 8, '아홉': 9, '열': 10, '스무': 20}
_NUMBER = r'(?:\d+(?:\.\d+)?|[영공일이삼사오육칠팔구십백천]+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무)'
_UNIT = r'(?:초|시간|명|식구|사람|인|kg|cm|mm|킬로그램|센티미터|밀리미터)'
# Unit syllables inside a different noun are not quantities: 한 인형, 세명대
# (a transcription error), 사인펜, and 삼 초록 must not become source facts.
_SUFFIX = (r'(?=$|[^가-힣A-Za-z0-9]|가족|용|승|분|만|밖|정도|쯤|가량|'
           r'도|은|는|이|가|을|를|로|에|의|부터|까지|마다|씩|당|보다|짜리|면|라|인|일)')
_PATTERN = re.compile(r'(?<![가-힣\d])(' + _NUMBER + r')\s*(' + _UNIT + r')' + _SUFFIX)
_UNITS = {'킬로그램': 'kg', '센티미터': 'cm', '밀리미터': 'mm', '인': '명', '식구': '명', '사람': '명'}


def number(token):
    if token in _NATIVE:
        return str(_NATIVE[token])
    if token[0].isdigit():
        return str(Decimal(token))
    total = digit = 0
    previous_scale = 10000
    for char in token:
        if char in _SCALES:
            scale = _SCALES[char]
            if scale >= previous_scale:
                return None
            total += (digit or 1) * scale
            digit = 0
            previous_scale = scale
        else:
            # Reject ambiguous digit strings such as 삼사 instead of guessing 34.
            if digit:
                return None
            digit = _DIGITS[char]
    return str(total + digit)


def quantity_readings(text):
    """Expose exact source spans alongside normalized units, not ASR guesses."""
    for match in _PATTERN.finditer(text):
        value = number(match.group(1))
        # "한식구" can mean one household rather than a single person.
        if value is not None and not (match.group(2)=='식구' and value=='1'):
            yield {'value': value, 'unit': _UNITS.get(match.group(2), match.group(2)),
                   'source_text': match.group(), 'start': match.start(), 'end': match.end()}


def quantities(text):
    for item in quantity_readings(text):
        yield item['value'], item['unit']
