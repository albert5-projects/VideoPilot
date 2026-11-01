import unittest
from videopilot.overlay_planner import validate_overlay
from videopilot.core import UserError
class OverlayTests(unittest.TestCase):
 def mark(self,**kw):
  e=dict(kind='arrow',points=[[.1,.2],[.45,.5]],label='Grip',color='#22aaff',start=0,end=2,reason='Visible handle');e.update(kw);return {'reason':'Grip cue','elements':[e]}
 def test_valid_and_declined(self):
  self.assertEqual(validate_overlay(self.mark(),3)['elements'][0]['kind'],'arrow')
  self.assertEqual(validate_overlay({'elements':[]},3)['elements'],[])
 def test_reject_invalid_geometry_timing_and_clutter(self):
  for kw in [dict(points=[[float('nan'),.2],[.4,.5]]),dict(points=[[.2,.2],[.4,.9]]),dict(kind='highlight'),dict(end=4),dict(label='This label has far too many words'),dict(points=[[.02,.2],[.98,.3]])]:
   with self.subTest(kw=kw),self.assertRaises(UserError):validate_overlay(self.mark(**kw),3)
if __name__=='__main__':unittest.main()

class SkipRenderTests(unittest.TestCase):
 def test_six_declines_skip_all_graphics_and_stop_planning(self):
  import tempfile,threading
  from unittest.mock import patch
  from videopilot.core import Job,Settings,atomic_json,read_json
  from videopilot.remotion_graphics import render_graphics
  for decisions in [[False]*6+[True], [False]*3+[True]+[False]*3+[True]]:
   with self.subTest(decisions=decisions),tempfile.TemporaryDirectory() as tmp:
    job=Job.create(Settings(idea='Unsuitable graphics',remotion_enabled=True,graphics_percent=100),tmp)
    shots=[{'id':f'{i:03d}_01','start':i*3000000,'duration':3000000} for i in range(len(decisions))]
    timeline={'shots':shots,'duration':len(shots)*3000000}
    atomic_json(job.folder/'graphics_report.json',{'clips':{'old':{'path':'old.mp4'}}})
    logs=[]
    with patch('videopilot.overlay_planner.plan_overlay',side_effect=[{'elements':[{'kind':'arrow'}] if useful else []} for useful in decisions]) as planner,patch('videopilot.remotion_graphics.runtime') as runtime,patch('videopilot.remotion_graphics.subprocess.Popen') as renderer:
     report=render_graphics(job,{},timeline,threading.Event(),logs.append)
    self.assertEqual(planner.call_count,len(decisions)-1)
    runtime.assert_not_called();renderer.assert_not_called()
    self.assertEqual(report['clips'],{});self.assertEqual(report['actual_percent'],0)
    self.assertEqual(len(report['skipped']),6)
    self.assertEqual(read_json(job.folder/'graphics_report.json'),report)
    self.assertTrue(job.settings.remotion_enabled)
    self.assertTrue(any('Remotion skipped for this video' in line for line in logs))

 def test_five_declines_still_allow_a_useful_overlay(self):
  import tempfile,threading
  from unittest.mock import patch
  from videopilot.core import Job,Settings
  from videopilot.remotion_graphics import render_graphics
  with tempfile.TemporaryDirectory() as tmp:
   job=Job.create(Settings(idea='Useful graphics',remotion_enabled=True,graphics_percent=100),tmp)
   shots=[{'id':str(i),'start':i*3000000,'duration':3000000} for i in range(6)]
   with patch('videopilot.overlay_planner.plan_overlay',side_effect=[{'elements':[]}]*5+[{'elements':[{'kind':'arrow'}]}]) as planner,patch('videopilot.remotion_graphics.runtime',side_effect=RuntimeError('Rendering reached')):
    with self.assertRaisesRegex(RuntimeError,'Rendering reached'):
     render_graphics(job,{},dict(shots=shots,duration=18000000),threading.Event(),lambda _:None)
   self.assertEqual(planner.call_count,6)

 def test_declined_shots_bypass_dependencies_and_replace_old_report(self):
  import tempfile,threading
  from unittest.mock import patch
  from videopilot.core import Job,Settings,make_timeline,atomic_json,read_json
  from videopilot.remotion_graphics import render_graphics
  from test_system import PLAN
  with tempfile.TemporaryDirectory() as tmp:
   job=Job.create(Settings(idea='Skip graphics',remotion_enabled=True,graphics_percent=100),tmp)
   atomic_json(job.folder/'graphics_report.json',{'clips':{'001_01':{'path':'old.mp4'}}})
   with patch('videopilot.overlay_planner.plan_overlay',return_value={'elements':[],'reason':'Irrelevant'}),patch('videopilot.remotion_graphics.runtime',side_effect=AssertionError('No runtime needed')),patch('videopilot.remotion_graphics.subprocess.Popen',side_effect=AssertionError('No renderer')):
    result=render_graphics(job,PLAN,make_timeline(PLAN,[3,3],job.settings),threading.Event(),lambda _:None)
   self.assertEqual(result['clips'],{});self.assertEqual(result['actual_percent'],0)
   self.assertEqual(len(result['skipped']),2)
   self.assertEqual(read_json(job.folder/'graphics_report.json'),result)
   self.assertFalse((job.folder/'graphics').exists())

 def test_only_accepted_shot_enters_render_request(self):
  import tempfile,threading
  from pathlib import Path
  from unittest.mock import patch
  from PIL import Image
  from videopilot.core import Job,Settings,make_timeline,read_json
  from videopilot.remotion_graphics import render_graphics
  from test_system import PLAN
  with tempfile.TemporaryDirectory() as tmp:
   job=Job.create(Settings(idea='Mixed graphics',remotion_enabled=True,graphics_percent=100),tmp)
   timeline=make_timeline(PLAN,[3,3],job.settings);(job.folder/'images').mkdir()
   for shot in timeline['shots']:Image.new('RGB',(16,16)).save(job.folder/'images'/f'{shot["id"]}.png')
   requests=[]
   class Worker:
    returncode=0
    def __init__(self,args,**kwargs):
     request=read_json(args[-1]);requests.extend(request['items'])
     for item in request['items']:Path(item['output']).with_suffix('.ready.mp4').write_bytes(b'clip')
    def poll(self):return 0
   with patch('videopilot.overlay_planner.plan_overlay',side_effect=[{'elements':[]},{'elements':[{'kind':'arrow'}]}]),patch('videopilot.remotion_graphics.runtime',return_value={'node':'node','version':'4','root':tmp,'browser':'browser'}),patch('videopilot.remotion_graphics.shutil.which',return_value='ffprobe'),patch('videopilot.remotion_graphics.subprocess.Popen',Worker),patch('videopilot.remotion_graphics.probe_video',return_value=3000000):
    result=render_graphics(job,PLAN,timeline,threading.Event(),lambda _:None)
   sid=timeline['shots'][1]['id']
   self.assertEqual([r['id'] for r in requests],[sid]);self.assertEqual(list(result['clips']),[sid]);self.assertEqual(result['actual_percent'],50)

 def test_repair_renders_only_requested_shot_with_saved_overlay(self):
  import tempfile,threading
  from pathlib import Path
  from unittest.mock import patch
  from PIL import Image
  from videopilot.core import Job,Settings,make_timeline,read_json
  from videopilot.remotion_graphics import render_graphics
  from test_system import PLAN
  with tempfile.TemporaryDirectory() as tmp:
   job=Job.create(Settings(idea='Repair graphics',remotion_enabled=True,graphics_percent=100),tmp)
   timeline=make_timeline(PLAN,[3,3],job.settings);shot=timeline['shots'][1];sid=shot['id']
   (job.folder/'images').mkdir();Image.new('RGB',(16,16)).save(job.folder/'images'/f'{sid}.png')
   overlay={'elements':[{'kind':'arrow','points':[[.1,.2],[.4,.5]],'color':'#ffffff','label':'','start':0,'end':2}]}
   requests=[]
   class Worker:
    returncode=0
    def __init__(self,args,**kwargs):
     request=read_json(args[-1]);requests.extend(request['items'])
     for item in request['items']:Path(item['output']).with_suffix('.ready.mp4').write_bytes(b'clip')
    def poll(self):return 0
   with patch('videopilot.overlay_planner.plan_overlay',side_effect=AssertionError('No new planning')),patch('videopilot.remotion_graphics.runtime',return_value={'node':'node','version':'4','root':tmp,'browser':'browser'}),patch('videopilot.remotion_graphics.shutil.which',return_value='ffprobe'),patch('videopilot.remotion_graphics.subprocess.Popen',Worker),patch('videopilot.remotion_graphics.probe_video',return_value=3000000):
    report=render_graphics(job,PLAN,timeline,threading.Event(),lambda _:None,selected_shots=[shot],planned_overlays={sid:overlay})
   self.assertEqual([item['id'] for item in requests],[sid]);self.assertEqual(requests[0]['props']['overlayPlan'],overlay)
   self.assertEqual(list(report['clips']),[sid])
