from hotpost import studio_ai


def test_missing_visual_match_keeps_selected_script_and_continues_edit(tmp_path, monkeypatch):
    import copy
    import hashlib
    from types import SimpleNamespace
    from hotpost.studio_runtime.editing import EditingMixin
    voice=tmp_path/'voice.wav';voice.write_bytes(b'voice')
    text='다진 마늘, 또 얼리려고요? 잠깐만요! 필요한 만큼 떠서 넣어요.'
    state={'id':'work','scripts':[{'id':'script','text':text}],
           'voices':[{'id':'voice','script_id':'script','path':str(voice),'sha256':hashlib.sha256(b'voice').hexdigest()}],
           'sources':[{'id':'source','path':'context.mp4'}]}
    before=copy.deepcopy(state)
    plan={'shots':[], 'beats':[{'id':'beat','text':text}], 'warnings':[]}
    class Editor(EditingMixin):
        settings=SimpleNamespace(script_model='local')
        def folder(self, *a): return tmp_path
        def _source_records(self, *a): return state['sources']
        def _process(self, *a): return {'plan':copy.deepcopy(plan)}
        def render_feedback(self, _state, _job, chosen):
            assert chosen['beats'][0]['text'] == text
            assert chosen['narration_priority']['script_sha256'] == hashlib.sha256(text.encode()).hexdigest()
            assert chosen['warnings']
            return {'rendered':True}
    (tmp_path/'edit').mkdir()
    def fail(*a): raise RuntimeError('일치하는 장면 확인 불가')
    monkeypatch.setattr(studio_ai,'describe_shots',fail)
    result=Editor()._edit(state,{'id':'edit','payload':{'voice_id':'voice','script_id':'script'}})
    assert result['rendered'] and state == before


def test_scene_model_uses_narration_and_images_without_cyclic_fallback(monkeypatch,tmp_path):
    frame=tmp_path/'frame.jpg';frame.write_bytes(b'actual-frame')
    seen=[]
    def generate(settings,instruction,evidence,media):
        seen.append({'evidence':evidence,'media':media})
        return {'shots':[{'id':'writing','observation':'펜으로 쓰는 모습'}],
                'beats':[{'id':'b1','options':[{'shot_id':'writing','relation':'direct','reason':'목록을 씀'},
                                              {'shot_id':'invented','relation':'direct'}]}]}
    monkeypatch.setattr(studio_ai,'_generate',generate)
    catalog=[{'id':'writing','start':15,'end':17,'frames':[str(frame)]}]
    beats=[{'id':'b1','text':'목록을 적어요','start':0,'end':2,
            'options':[{'shot_id':'unrelated-fallback','relation':'direct'}],
            'selected_shot_id':'unrelated-fallback'}]
    observations,choices=studio_ai.describe_shots(None,catalog,beats)
    assert len(seen)==2
    assert seen[1]['evidence']['beats']==[{'id':'b1','text':'목록을 적어요','start':0,'end':2}]
    assert seen[0]['media'][0]['text'].startswith('SHOT writing at 15.00')
    assert seen[1]['media']==[]
    assert observations['writing']['observation']=='펜으로 쓰는 모습'
    assert [o['shot_id'] for o in choices['b1']['options']]==['writing']


def test_context_source_never_promoted_to_direct_by_model_or_cached_plan(monkeypatch,tmp_path):
    frame=tmp_path/'frame.jpg';frame.write_bytes(b'frame')
    path=tmp_path/'chicken.mp4'
    source={'path':str(path),'sha256':'abc','functional_review':{'reviewed':True,'same_core_function':False,
        'context_usable':True,'context_usage_limits':['General meal preparation only'],'source_sha256':'abc'}}
    plan={'shots':[{'id':'chicken','path':str(path),'start':1,'end':3,'frames':[str(frame)]}],
          'beats':[{'id':'b1','text':'다진 마늘을 덜어요','start':0,'end':2,
                    'options':[{'shot_id':'chicken','relation':'direct'}]}]}
    studio_ai.restrict_context_shots(plan,[source])
    assert plan['beats'][0]['options'][0]['relation']=='context'
    assert plan['shots'][0]['source_role']=='context_only'
    monkeypatch.setattr(studio_ai,'_generate',lambda *a,**k:{'shots':[{'id':'chicken','observation':'닭고기를 조리하는 손'}],
        'beats':[{'id':'b1','options':[{'shot_id':'chicken','relation':'direct'}]}]})
    _,choices=studio_ai.describe_shots(None,plan['shots'],plan['beats'])
    assert choices['b1']['options'][0]['relation']=='context'
