"""Pure advisory checks and hash-bound receipts; never rewrites saved text."""
from .script_integrity import inspect, digest
from .script_quality import naturalness_review
from .script_style import ending_issues
from .reference_evidence import choose_keyword, comment_issues
from .contract import receipt


def review(text, reference, evidence_mode='benchmark', keyword=None, contract=None):
    integrity = inspect(reference, text)
    if evidence_mode == 'self_shot':
        integrity['issues'] = [i for i in integrity['issues'] if i['severity'] != 'copy']
        integrity['status'] = 'issues_found' if integrity['issues'] else 'no_flags'
    natural = naturalness_review(text)
    reasons = [i['message'] for i in integrity['issues']]
    reasons += [i['message'] for i in natural['issues']]
    reasons += [i['rule'] for i in ending_issues(text)]
    reasons += comment_issues(text, keyword or choose_keyword(reference)[0] or '나도')
    reasons = list(dict.fromkeys(reasons))
    hashes = {'script_sha256':digest(text),'reference_sha256':digest(reference)}
    return {'text':text,'writing_contract':receipt(contract), 'integrity_review':integrity,
            'naturalness_review':natural,
            'rewrite_review':{**hashes,'policy_version':'internal-rewrite-v1','status':'advisory',
                              'blocking':False,'reasons':reasons},
            'quality_summary':{**hashes,'status':'issues_found' if reasons else 'not_evaluated',
                               'issues':reasons,'advisory_only':True,'blocking':False}}
