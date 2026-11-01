import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from videopilot.core import read_json
from videopilot.flow_navigation import RecoveryNavigation
from videopilot.flow_concurrent import inspect_next_asset


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.json';self.page=Mock()
        self.page.evaluate.return_value=840

    def test_forward_resumes_persisted_position_and_confirmed_owners(self):
        state={};nav=RecoveryNavigation(self.page,state,self.path,'forward')
        nav.prepare()
        self.assertEqual(self.page.evaluate.call_args.args[1]['action'],'oldest')
        nav.opening();nav.remember([{'proof':'history-step','owner':'002_01','ids':['asset-123456789012']}])
        restored=RecoveryNavigation(self.page,read_json(self.path),self.path,'forward')
        restored.prepare()
        self.assertEqual(self.page.evaluate.call_args.args[1],{'action':'restore','top':840})
        self.assertEqual(restored.owners['asset-123456789012'],'002_01')

    def test_switch_direction_starts_at_opposite_end_but_retains_owners(self):
        saved={'recovery_navigation':{'order':'reverse','top':840,'owners':{'asset':'001_01'}}}
        nav=RecoveryNavigation(self.page,saved,self.path,'forward');nav.prepare()
        self.assertEqual(self.page.evaluate.call_args.args[1]['action'],'oldest')
        self.assertEqual(nav.owners,{'asset':'001_01'})
        verify=RecoveryNavigation(self.page,saved,self.path,'forward',verify=True)
        self.assertEqual(verify.owners,{})

    def test_selection_direction_skips_completed_but_reopens_missing(self):
        newest='newest-123456789012';middle='middle-123456789012';oldest='oldest-123456789012'
        for order,expected in [('forward',middle),('reverse',newest)]:
            page=Mock();page.evaluate.return_value=500
            def locator(selector):
                loc=Mock();loc.count.return_value=0 if selector=='flow-editor-page' else 1
                loc.evaluate_all.return_value=[newest,middle,oldest]
                return loc
            page.locator.side_effect=locator
            nav=RecoveryNavigation(page,{},self.path,order)
            nav.owners={oldest:'001_01',middle:'002_01'}
            tracker=SimpleNamespace(recovery_navigation=nav,active={'002_01':{},'003_01':{}},
                inspected_assets=set(),inspect_id=None,inspect_opened=None,errors=[])
            inspect_next_asset(page,tracker,advance_completed=True)
            self.assertEqual(tracker.inspect_id,expected)

    def test_unproven_identity_is_never_saved_for_skipping(self):
        nav=RecoveryNavigation(self.page,{},self.path,'forward')
        nav.remember([{'owner':'001_01','ids':['unproven']}])
        self.assertEqual(nav.owners,{})
