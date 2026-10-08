"""Lightweight spoken-ending checks; no service or model dependency."""
import re

def ending_issues(text):
    issues=[]
    for match in re.finditer(r'[^.!?。！？~～…\n]+',text):
        sentence=match.group(0)
        clean=sentence.strip().rstrip('"\'”’」』)]} ').strip()
        clean=re.sub(r'[^가-힣A-Za-z0-9]+$','',clean)
        start=match.start()+sentence.find(clean)
        end=start+len(clean)
        if re.search(r'[가-힣]+다$',clean):
            issues.append({'rule':'다 종결 금지','excerpt':clean[-100:],'start':start,'end':end})
        # Check explicit informal predicates, not every final 아/어 syllable:
        # short noun phrases such as "설치 끝" remain valid spoken fragments.
        if re.search(r'(?:(?:했|봤|샀|됐|되었|없|있|좋|맞|같|않|받|작|낮|높|짧|길|몰랐|생겼|달라졌|끝났|편해졌)[어아]|'
                     r'(?:이|거|할|될|끝인)야|(?:했|봤|샀|있|없|몰랐|끝났)거든|'
                     r'(?:편|깔끔|간단)해|(?:쓰|보|해)봐|잖아|더라고)$',clean):
            issues.append({'rule':'반말 종결 대신 자연스러운 해요체 사용','excerpt':clean[-100:],'start':start,'end':end})
    for match in re.finditer(r'죠(?![가-힣A-Za-z0-9_?？])',text):
        issues.append({'rule':'죠는 바로 물음표가 붙는 질문으로만 사용',
                       'excerpt':text[max(0,match.start()-35):match.end()+10],
                       'start':match.start(),'end':match.end()})
    return issues
