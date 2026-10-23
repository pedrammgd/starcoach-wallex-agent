"""Chronological validation selection and untouched holdout, with explicit online learning."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from dataclasses import asdict, replace
from pathlib import Path

from .data import digest
from .engine import Config, STRATEGIES, Ledger, floor_quantity, run
from .journal import canonical


def provenance() -> dict:
    root = Path(__file__).resolve().parent.parent
    files = sorted(list((root/'wallex_agent').glob('*.py'))+[root/'pyproject.toml'])
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    source_hash = hashlib.sha256(canonical(hashes).encode()).hexdigest()
    try:
        if not (root/'.git').exists():
            raise FileNotFoundError('project has no own Git repository')
        sha = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,stderr=subprocess.DEVNULL,text=True).strip()
        dirty = bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip())
    except (subprocess.CalledProcessError,FileNotFoundError):
        sha, dirty = None, None
    return {"git_sha":sha,"git_dirty":dirty,"source_hash":source_hash,"files":hashes}


def passive_hold(bars, cfg, start, end):
    """20% initial buy, hold, scheduled final-open exit; no active stop/re-entry.

    Both scheduled executions honor prior-bar liquidity. Remaining dust stays marked.
    This benchmark is never a live/shadow strategy or a validation selection candidate.
    """
    book=Ledger(cfg.initial_cash)
    events=[]
    peak=cfg.initial_cash
    max_dd=0
    previous=cfg.initial_cash
    returns=[]
    exposures=[]
    for i in range(start,end):
        c=bars[i]
        fill=None
        if i==start+1:
            price=c.open*(1+(cfg.spread_bps/2+cfg.slippage_bps)/10000)
            quantity=floor_quantity(min(cfg.initial_cash*cfg.max_allocation/(price*(1+cfg.fee_bps/10000)),
                                        bars[i-1].volume*cfg.participation),cfg.qty_step)
            if quantity*price>=cfg.min_notional:fill=book.fill(quantity,c.open,cfg)
        elif i==end-1 and book.quantity:
            quantity=floor_quantity(min(book.quantity,bars[i-1].volume*cfg.participation),cfg.qty_step)
            if quantity*c.open>=cfg.min_notional:fill=book.fill(-quantity,c.open,cfg)
        equity=book.equity(c.close)
        peak=max(peak,equity);max_dd=max(max_dd,1-equity/peak)
        returns.append(equity/previous-1);previous=equity
        exposures.append(book.quantity*c.close/equity)
        events.append({'decision_at':c.timestamp+cfg.interval,'equity':equity,'drawdown':1-equity/peak,'fill':fill})
    import statistics,math
    std=statistics.pstdev(returns)
    liquidation=book.quantity*bars[end-1].close*(cfg.fee_bps+cfg.spread_bps/2+cfg.slippage_bps)/10000
    metrics={'net_return':previous/cfg.initial_cash-1,
        'liquidation_estimate_return':(previous-liquidation)/cfg.initial_cash-1,
        'realized_pnl_TMN':book.realized_pnl,'max_drawdown':max_dd,'fees_TMN':book.fees,
        'spread_slippage_TMN':book.impact,'trade_count':book.trade_count,'turnover_TMN':book.turnover,
        'avg_trade_TMN':book.turnover/max(1,book.trade_count),'mean_exposure':statistics.mean(exposures),
        'sharpe_descriptive':statistics.mean(returns)/std*math.sqrt(365*86400/cfg.interval) if std else 0,
        'final_cash_TMN':book.cash,'remaining_quantity':book.quantity,'flat':book.quantity<float(cfg.qty_step),
        'prequential_brier':None,'model_samples':0,'bars':len(events)}
    return {'metrics':metrics,'events':events}


def benchmark(bars, cfg: Config, output: str, symbol: str) -> dict:
    if len(bars)<500:
        raise ValueError('at least 500 contiguous bars required')
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    n=len(bars)
    train_end=int(n*.5)
    validation_end=int(n*.75)
    rows=[]
    # Fixed presets, no search of holdout. All models learn only labels mature at t.
    for strategy in STRATEGIES:
        result=run(bars,cfg,strategy,start=train_end,end=validation_end)
        rows.append({'phase':'validation','strategy':strategy,**result['metrics']})
    eligible=[r for r in rows if r['strategy'] in ('momentum','mean_reversion','regime','ai')
              and r['net_return']>0 and r['trade_count']>=2 and r['max_drawdown']<cfg.max_drawdown]
    selected=max(eligible,key=lambda r:r['net_return']-r['max_drawdown'])['strategy'] if eligible else 'cash'
    rows.append({'phase':'validation','strategy':'passive_hold',
                 **passive_hold(bars,cfg,train_end,validation_end)['metrics']})
    selected_result=None
    results={}
    for strategy in STRATEGIES:
        result=run(bars,cfg,strategy,start=validation_end)
        rows.append({'phase':'holdout_diagnostic','strategy':strategy,**result['metrics']})
        results[strategy]=result
        if strategy==selected: selected_result=result
    passive=passive_hold(bars,cfg,validation_end,n)
    results['passive_hold']=passive
    rows.append({'phase':'holdout_diagnostic','strategy':'passive_hold',**passive['metrics']})
    # Multiple expanding history evaluations, resets virtual portfolio each fold.
    for fold,(a,b) in enumerate(((.5,.6),(.6,.7),(.7,.75))):
        for strategy in ('momentum','mean_reversion','ai'):
            result=run(bars,cfg,strategy,start=int(n*a),end=int(n*b))
            rows.append({'phase':f'walk_forward_{fold}','strategy':strategy,**result['metrics']})
    for cost_name,cost_cfg in [('zero_cost',replace(cfg,fee_bps=0,spread_bps=0,slippage_bps=0)),
                               ('double_cost',replace(cfg,fee_bps=cfg.fee_bps*2,spread_bps=cfg.spread_bps*2,
                                                      slippage_bps=cfg.slippage_bps*2))]:
        result=run(bars,cost_cfg,selected,start=validation_end)
        rows.append({'phase':cost_name,'strategy':selected,**result['metrics']})
    # Cost sensitivity for AI independently even if validation chooses cash.
    for multiplier in (0,2):
        stress=replace(cfg,fee_bps=cfg.fee_bps*multiplier,spread_bps=cfg.spread_bps*multiplier,
                       slippage_bps=cfg.slippage_bps*multiplier)
        result=run(bars,stress,'ai',start=validation_end)
        rows.append({'phase':f'ai_cost_x{multiplier}','strategy':'ai',**result['metrics']})
    with (out/'summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for row in rows for k in row)));writer.writeheader();writer.writerows(rows)
    manifest={'symbol':symbol,'competition_eligible':False,'dataset_hash':digest(bars),
              'start_utc_epoch':bars[0].timestamp,'end_utc_epoch':bars[-1].timestamp+cfg.interval,
              'bars':n,'train_end':train_end,'validation_end':validation_end,'config':asdict(cfg),
              'costs_status':'assumed; contest fee/depth unverified','selected_on_validation':selected,
              'selection_rule':'positive return, >=2 fills, DD below cap; maximize return-DD; else cash',
              'online_learning':'prequential; learns only mature past labels including during holdout',
              'source':provenance(),'results':rows,'selected_holdout':selected_result['metrics']}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False))
    with (out/'decisions.jsonl').open('w') as f:
        for e in selected_result['events']: f.write(canonical(e)+'\n')
    with (out/'equity.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['timestamp','strategy','equity_TMN','drawdown'])
        for s,r in results.items():
            writer.writerows((e['decision_at'],s,e['equity'],e['drawdown']) for e in r['events'])
    # Standalone SVG plot, no runtime plotting dependency.
    colors=['#444','#858','#1976d2','#f57c00','#00875a','#d22']
    all_eq=[e['equity'] for r in results.values() for e in r['events']]
    lo,hi=min(all_eq),max(all_eq);span=max(hi-lo,1)
    lines=[]
    for (name,result),color in zip(results.items(),colors):
        points=' '.join(f'{70+800*j/max(1,len(result["events"])-1):.2f},{380-300*(e["equity"]-lo)/span:.2f}'
                        for j,e in enumerate(result['events']))
        lines.append(f'<polyline fill="none" stroke="{color}" points="{points}"/>')
        lines.append(f'<text x="{70+140*(len(lines)//2)}" y="430" fill="{color}">{name}</text>')
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="480"><rect width="960" height="480" fill="white"/><text x="70" y="30">{symbol}: holdout virtual equity (TMN), assumed costs</text><text x="5" y="80">{hi:.0f}</text><text x="5" y="380">{lo:.0f}</text>'+''.join(lines)+'</svg>'
    (out/'equity.svg').write_text(svg)
    return manifest
