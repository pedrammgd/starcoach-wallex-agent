"""Small predeclared validation-only sweep; never reads holdout outcomes for selection."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from wallex_agent.data import read_csv, digest
from wallex_agent.engine import Config, run
from wallex_agent.evaluation import provenance

presets={'baseline':{}, 'strict_edge':{'edge_buffer':.004,'ai_probability':.60},
         'half_risk':{'max_allocation':.1,'risk_per_trade':.0025}}
results=[]
for symbol,step in [('BTCTMN','0.00000001'),('ETHTMN','0.00001')]:
    source=Path(f'data/{symbol}_validated_segment_1.csv')
    bars=read_csv(source,3600)
    # Physically remove final quarter before passing data to any trial.
    start=int(len(bars)*.5);end=int(len(bars)*.75)
    prefix=bars[:end]
    rows=[]
    for name,changes in presets.items():
        for strategy in ('momentum','mean_reversion','ai'):
            trial={'preset':name,'strategy':strategy,'scenarios':{}}
            for scenario,fee in [('assumed_base',30),('fee_stress',45)]:
                cfg=replace(Config(qty_step=step,fee_bps=fee),**changes)
                r=run(prefix,cfg,strategy,start=start,end=len(prefix))
                trial['scenarios'][scenario]=r['metrics']
            rows.append(trial)
    eligible=[r for r in rows if all(m['net_return']>0 and m['trade_count']>=2
               and m['max_drawdown']<.04 for m in r['scenarios'].values())]
    selected=max(eligible,key=lambda r:min(m['net_return']-m['max_drawdown']
                 for m in r['scenarios'].values())) if eligible else None
    result={'symbol':symbol,'source':str(source),'source_hash':digest(bars),
            'validation_start_index':start,'validation_end_exclusive':end,
            'validation_bars':len(prefix)-start,'rows':rows,
            'selected':{'preset':selected['preset'],'strategy':selected['strategy']} if selected else 'cash',
            'holdout_used':False,'competition_eligible':False}
    results.append(result)
    print(json.dumps({'symbol':symbol,'selected':result['selected'],'trials':len(rows)*2}),flush=True)
report={'source':provenance(),'preset_grid':presets,'results':results,
        'llm_inference_calls':0,'new_forward_performance':False,
        'limitations':'Previously explored historical datasets; no new independent holdout claim. Fee levels are assumptions. Not a BoxAPI profitability test.'}
Path('reports/boxapi_phase_validation_sweep.json').write_text(json.dumps(report,indent=2)+'\n')
