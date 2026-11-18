def compare(actual, expected):
    issues = []
    def check(condition, label):
        if not condition: issues.append(label)
    check(actual['status']=='COMPLETED' and actual['submitted'] and actual['sealed'],'completion')
    check(actual['manifest']==expected['manifest'],'manifest')
    check([e['id'] for e in actual['events']]==expected['events'],'event_ids_order')
    check([e['hash'] for e in actual['events']]==expected['event_hashes'],'event_payloads')
    check([e['sequence'] for e in actual['events']]==list(range(expected['steps']+1)),'event_sequences')
    check([e['revision'] for e in actual['events']]==list(range(expected['steps']+1)),'event_revisions')
    check(len(actual['assessments'])==len(expected['assessments']),'assessment_count')
    for block in expected['assessments']:
        found = [a for a in actual['assessments'] if a['id']==block['assessmentId']]
        if not found:
            issues.append('assessment_missing');continue
        a = found[0]
        check(a['grades']==block['grades'],'grades')
        check(a['summary']==block['summary'] and a['result']==block['result'],'summary_result')
        check({r['id']:r['comment'] for r in a['reports']} ==
              {r['clientReportId']:r['comment'] for r in block['mistakeReports']},'reports')
        check(len(a['reports'])==len(block['mistakeReports']),'duplicate_reports')
        check({r['id']:r['event'] for r in a['reports']} ==
              {r['clientReportId']:r['assignmentEventIdAtObservation'] for r in block['mistakeReports']},'report_event_links')
    terminal = expected['terminal']
    check(actual['runs']==[{'key':terminal['exerciseSessionKey'],'hash':terminal['payloadHash'],
                           'status':terminal['status']}],'terminal_run')
    return issues
