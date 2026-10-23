"""Preregistered validation-only comparison. Never reads/evaluates old final 25%."""
import csv
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wallex_agent.data import read_csv, digest
from wallex_agent.engine import Config, run, propose
from wallex_agent.evaluation import provenance
from wallex_agent.model import OnlineModel, WARMUP


def main():
    out=Path('reports/final_strategy');out.mkdir(parents=True,exist_ok=True)
    protocol={'created_at':datetime.now(timezone.utc).isoformat(),
        'strategies':['momentum','mean_reversion','regime','ai','cash'],
        'cost_scenarios':{'base_assumed':1,'zero_cost_diagnostic':0,'double_cost_stress':2},
        'selection':'base cost only; positive median, >=10 fills total, positive >=4/5 segments, max DD <=4%; maximize mean return minus worst DD; otherwise cash',
        'partitions':'original first 50% warm/train, next 25% validation ONLY; old final 25% was previously exposed and is not fresh untouched evidence',
        'new_final_holdout':'fresh post-2026-10-22T21:00Z data sealed separately; not evaluated by this study',
        'parameter_search':False,'actual_exchange_fees_verified':False,'source':provenance()}
    # Write the protocol before any comparisons. Each rerun retains the same fixed rules.
    (out/'protocol.json').write_text(json.dumps(protocol,indent=2))
    rows=[];diagnostics=[]
    for path in sorted(Path('data').glob('*_validated_segment_*.csv')):
        symbol=path.name.split('_')[0]
        step={'BTCTMN':'0.00000001','ETHTMN':'0.00001','USDTTMN':'0.01'}[symbol]
        bars=read_csv(path,3600);n=len(bars);a,b=int(n*.5),int(n*.75)
        cfg=Config(qty_step=step)
        model=OnlineModel();counts={'uptrend':0,'downtrend':0,'range':0}
        proposals={s:0 for s in protocol['strategies']};max_edge=-float('inf')
        for i in range(WARMUP,b):
            p=model.predict(bars,i)
            if i<a:continue
            trend=bars[i].close/bars[i-24].close-1
            threshold=max(.005,2*p.volatility*24**.5)
            regime='uptrend' if trend>threshold else 'downtrend' if trend < -threshold else 'range'
            counts[regime]+=1;max_edge=max(max_edge,p.expected_return)
            for s in proposals:proposals[s]+=propose(s,bars,i,p,cfg,0).target>0
        diagnostic={'file':str(path),'symbol':symbol,'training_bars':a,'validation_bars':b-a,
            'excluded_final_bars':n-b,'validation_dataset_hash':digest(bars[:b]),
            'regime_counts':counts,'flat_entry_proposal_counts':proposals,
            'maximum_learned_gross_edge':max_edge,'base_roundtrip_cost_plus_buffer':cfg.roundtrip_cost+cfg.edge_buffer}
        diagnostics.append(diagnostic)
        for scenario,multiplier in protocol['cost_scenarios'].items():
            cost=replace(cfg,fee_bps=cfg.fee_bps*multiplier,spread_bps=cfg.spread_bps*multiplier,slippage_bps=cfg.slippage_bps*multiplier)
            for strategy in protocol['strategies']:
                result=run(bars[:b],cost,strategy,start=a)
                rows.append({'symbol':symbol,'segment':path.stem,'scenario':scenario,
                    'strategy':strategy,'roundtrip_cost_assumed':cost.roundtrip_cost,**result['metrics']})
        print(json.dumps({'completed':path.stem,'regimes':counts,'entry_proposals':proposals}),flush=True)
    eligible=[]
    for s in protocol['strategies']:
        selected=[x for x in rows if x['strategy']==s and x['scenario']=='base_assumed']
        mean=statistics.mean(x['net_return'] for x in selected);worst=max(x['max_drawdown'] for x in selected)
        if statistics.median(x['net_return'] for x in selected)>0 and sum(x['trade_count'] for x in selected)>=10 and sum(x['net_return']>0 for x in selected)>=4 and worst<=.04:
            eligible.append((mean-worst,s))
    selected=max(eligible)[1] if eligible else 'cash'
    report={'protocol':protocol,'selected_strategy':selected,'selection_used_holdout':False,
        'holdout_evaluated':False,'validation_only':True,'diagnostics':diagnostics,'results':rows,
        'latency_model':'close decision, next hourly open; no intra-bar order book, actual matching latency or maker fills assumed',
        'live_profitability_proven':False}
    (out/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    with (out/'comparison.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({'selected_strategy':selected,'comparisons':len(rows),'actual_fees_verified':False,'holdout_evaluated':False}))


if __name__=='__main__':main()
