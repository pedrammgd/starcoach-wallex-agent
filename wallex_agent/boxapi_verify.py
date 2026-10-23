"""Bounded, reproducible BoxAPI catalog and real structured-inference verification."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import os
from pathlib import Path
import statistics
import uuid

from .ai import Agent
from .boxapi import DEFAULT_MODEL, discover_catalog, candidate_models
from .journal import Journal
from .settings import active_llm, key_configured, update_boxapi


def verify(*, online=False, compare=False, samples=2, output='reports/boxapi_verification.json') -> dict:
    from .access import validate_read_only
    from .journal import canonical
    validate_read_only()
    _, requested = active_llm()
    if not 1 <= samples <= 3:
        raise ValueError('BoxAPI verification samples must be 1..3')
    report={'observed_at':datetime.now(timezone.utc).isoformat(),'provider':'boxapi',
            'requested_model':requested,'mode':'shadow','live_orders':False,
            'real_inference_verified':False,'structured_output_verified':False}
    if not online:
        report.update(status='OFFLINE_CONFIGURATION_ONLY',network_calls=0,
                      key_configured=key_configured(os.environ.get('BOXAPI_API_KEY')),
                      note='Run offline SDK transport tests separately; this is not inference.')
    elif not key_configured(os.environ.get('BOXAPI_API_KEY')):
        report.update(status='MISSING_KEY',network_calls=0,
                      action='Replace BOXAPI_API_KEY placeholder in project .env')
    else:
        provider,models,probes=discover_catalog(requested)
        report['endpoint_probes']=probes
        if provider is None:
            report['status']='CATALOG_FAILED'
        else:
            report['available_models']=models
            report['catalog_base_url']=provider.base_url
            candidates=candidate_models(requested,models)
            report['resolved_candidates']=candidates
            candidates=candidates[:2] if compare else candidates[:1]
            report['model_trials']=[]
            run_id=uuid.uuid4().hex
            journal=Journal('state/boxapi_verify_'+run_id+'.sqlite')
            try:
                for model in candidates:
                    provider.model=model
                    agent=Agent(provider,journal,model='boxapi:'+model,max_calls=6, budget_usd=.30)
                    trials=[]
                    for sample in range(samples):
                        decision,trace=agent.decide({'verification_run':run_id,'sample':sample,
                            'features':[1,0,0,0,0,0,0,0],'probability':.5,'expected_return':0,
                            'volatility':.01,'roundtrip_cost':.009,'current_allocation':0,
                            'candidate':{'target':0,'reason':'verification: no net edge','edge':0},
                            'risk_cap':.2})
                        metadata=trace['provider_metadata']
                        usage=metadata.get('usage') or {}
                        usage_ok=all(type(usage.get(k)) is int and usage[k]>=0
                                     for k in ('prompt_tokens','completion_tokens','total_tokens'))
                        trials.append({'status':trace['status'],'decision':asdict(decision),
                            'tokens_recorded':usage_ok,'no_edge_entry_rejected':decision.action!='ENTER',
                            'metadata':metadata})
                        # Authentication/schema/model errors are conclusive; do not spend more calls.
                        if trace['status']!='ok':break
                    ok=len(trials)==samples and all(t['status']=='ok' and t['tokens_recorded']
                        and t['no_edge_entry_rejected'] for t in trials)
                    report['model_trials'].append({'model':model,'all_samples_valid':ok,
                        'trials':trials,'median_latency_ms':statistics.median(
                            t['metadata']['latency_ms'] for t in trials)})
                any_valid=any(t['status']=='ok' for r in report['model_trials'] for t in r['trials'])
                report['real_inference_verified']=any_valid
                report['structured_output_verified']=any_valid
                valid=[r for r in report['model_trials'] if r['all_samples_valid']]
                if valid:
                    # Reliability gate first; compare speed only among the explicitly bounded candidates.
                    selected=min(valid,key=lambda r:r['median_latency_ms'])
                    update_boxapi(provider.base_url,selected['model'])
                    report.update(status='ONLINE_OK',real_inference_verified=True,
                        structured_output_verified=True,selected_model=selected['model'],
                        selection_rule='All samples schema-valid, tokens recorded, no entry without edge; lowest measured median latency among tested candidates',
                        cost_assessment='Tokens and provider cost recorded; billing currency/rates not independently verified')
                else:report['status']='NO_QUALIFIED_MODEL' if candidates else 'NO_CANDIDATE_IN_CATALOG'
                report['journal_events']=journal.verify()
                Path('reports').mkdir(parents=True,exist_ok=True)
                journal.export('reports/boxapi_verification_decisions.jsonl')
                report['decision_log']='reports/boxapi_verification_decisions.jsonl'
            finally:
                provider.close();journal.close()
    dest=Path(output);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(canonical(report)+'\n')
    return report
