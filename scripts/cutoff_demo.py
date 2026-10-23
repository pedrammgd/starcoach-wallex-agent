"""Complete simulated cutoff lifecycle, explicitly not Wallex account evidence."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from wallex_agent.closing import ClosingController,SettlementSimulator
from wallex_agent.engine import Config,Ledger
from wallex_agent.execution import Executor,Intent
from wallex_agent.journal import Journal

out=Path('reports/cutoff_demo');out.mkdir(exist_ok=True)
j=Journal(':memory:');cfg=Config(min_notional=1,qty_step='0.000001')
ledger=Ledger(cfg.initial_cash);broker=SettlementSimulator(ledger,cfg,fill_fraction=.5)
executor=Executor(broker,j)
executor.execute(Intent('BTCTMN','BUY','100','1000','fixture-entry','synthetic lifecycle only'))
controller=ClosingController(executor,symbol='BTCTMN',deadline=None,buffer=100,route_verified=True,allowed_markets=['BTCTMN'])
args={'ledger':ledger,'reference':1100,'quantity_step':'0.000001','min_notional':1,'capacity':1000}
timeline=[{'synthetic_epoch':1800,**controller.tick(1800,**args)}]
controller.deadline=2000
timeline.append({'synthetic_epoch':1800,**controller.tick(1800,**args)})
broker.fill_fraction=1
timeline.append({'synthetic_epoch':1900,**controller.tick(1900,**args)})
timeline.append({'synthetic_epoch':2000,**controller.tick(2000,**args)})
report={'simulation_only':True,'official_cutoff_used':False,'real_exchange_requests':0,
        'journal_events':j.verify(),'timeline':timeline}
j.export(str(out/'audit.jsonl'));j.close()
(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
