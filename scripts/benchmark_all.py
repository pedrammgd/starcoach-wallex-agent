from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from wallex_agent.data import read_csv
from wallex_agent.engine import Config
from wallex_agent.evaluation import benchmark

for symbol,step in [('BTCTMN','0.00000001'),('ETHTMN','0.00001'),('USDTTMN','0.01')]:
 for segment in (0,1):
  file=Path(f'data/{symbol}_validated_segment_{segment}.csv')
  if not file.exists(): continue
  cfg=Config(qty_step=step)
  out=f'reports/{symbol}/segment-{segment}'
  m=benchmark(read_csv(file,3600),cfg,out,symbol)
  print(json.dumps({'symbol':symbol,'segment':segment,'bars':m['bars'],
                    'selected':m['selected_on_validation'],'holdout':m['selected_holdout']}),flush=True)
