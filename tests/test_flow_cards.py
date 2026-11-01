import base64,unittest
from playwright.sync_api import sync_playwright
from videopilot import flow_browser as B,flow_concurrent as C
from test_flow_browser import png
from videopilot.core import UserError


class CardIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()
        try:cls.browser=cls.pw.chromium.launch(executable_path=str(B.browser_executable()),headless=True)
        except UserError as error:
            cls.pw.stop()
            raise unittest.SkipTest(str(error))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop()

    def setUp(self):
        self.page=self.browser.new_page()
        self.url='data:image/png;base64,'+base64.b64encode(png()).decode()
        self.shots=[{'id':'one','prompt':'A red boat'},{'id':'two','prompt':'A red boat beside a blue ship'}]

    def tearDown(self):self.page.close()

    def cards(self,markup):
        self.page.set_content(markup.replace('IMAGE',self.url))
        self.page.wait_for_function('[...document.images].every(i=>i.complete&&i.naturalWidth>=512)')
        return self.page.evaluate(C.CARDS_JS,self.shots)

    def test_unrelated_longer_prompt_cannot_claim_shorter_prompt(self):
        cards=self.cards('<article><p>A red boat beside a green ship</p><img src="IMAGE"></article>')
        self.assertTrue(cards);self.assertTrue(all(c['owner'] is None for c in cards))

    def test_exact_history_prompt_with_controls_and_prefix_neighbor(self):
        cards=self.cards('<flow-editor-page><flow-editor-history-step-image><p>A red boat beside a blue ship</p><button>Reuse prompt</button><img data-media-id="media-123456789012" src="IMAGE"></flow-editor-history-step-image></flow-editor-page>')
        self.assertEqual([c['owner'] for c in cards],['two'])

    def test_ambiguous_history_is_not_assigned(self):
        cards=self.cards('<flow-editor-page><flow-editor-history-step-image><p>A red boat</p><p>A red boat beside a blue ship</p><img data-media-id="media-123456789012" src="IMAGE"></flow-editor-history-step-image></flow-editor-page>')
        self.assertFalse(cards)

    def test_duplicate_prompts_remain_unresolved(self):
        self.shots[1]['prompt']=self.shots[0]['prompt']
        cards=self.cards('<article><p>A red boat</p><img src="IMAGE"></article>')
        self.assertTrue(all(c['owner'] is None for c in cards))


if __name__=='__main__':unittest.main()
