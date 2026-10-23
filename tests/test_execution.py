import tempfile
import unittest
from pathlib import Path
from wallex_agent.execution import Intent,OrderState,Executor
from wallex_agent.journal import Journal


class FakeBroker:
    simulation=True
    def __init__(self):self.submits=0;self.remote=None
    def submit(self,client_id,intent):
        self.submits+=1
        self.remote=OrderState('PARTIAL','0.5','1')
        raise TimeoutError('accepted remotely, response lost')
    def lookup(self,client_id):return self.remote


class ExecutionTests(unittest.TestCase):
    def test_timeout_restart_partial_fill_no_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            file=str(Path(d)/'orders.db');j=Journal(file);b=FakeBroker();e=Executor(b,j)
            intent=Intent('BTCTMN','BUY','1','100000','test-1','TEST DOUBLE only')
            id1,s=e.execute(intent);self.assertEqual(s.status,'UNKNOWN');j.close()
            j=Journal(file);e=Executor(b,j)
            id2,s=e.execute(intent);self.assertEqual(id1,id2);self.assertEqual(s.status,'PARTIAL')
            b.remote=OrderState('FILLED','1','2');_,s=e.execute(intent)
            self.assertEqual(s.status,'FILLED');self.assertEqual(b.submits,1)
            e.execute(intent);self.assertEqual(b.submits,1);j.close()

    def test_missing_order_never_resubmits(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(str(Path(d)/'j.db'));b=FakeBroker();e=Executor(b,j)
            intent=Intent('BTCTMN','SELL','1','100','id','reason')
            e.execute(intent);b.remote=None
            self.assertEqual(e.execute(intent)[1].status,'UNKNOWN')
            self.assertEqual(b.submits,1);j.close()

    def test_reconciliation_invalid_and_live_adapter_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(str(Path(d)/'j.db'));b=FakeBroker();e=Executor(b,j)
            intent=Intent('BTCTMN','BUY','1','100','id','reason')
            for bad in (OrderState('FILLED','.5'),OrderState('PARTIAL','2'),OrderState('OPEN','NaN')):
                with self.assertRaises(ValueError):e.record('id',intent,bad)
            b.simulation=False
            with self.assertRaises(PermissionError):Executor(b,j)
            j.close()
