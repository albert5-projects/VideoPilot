"""Desktop workflow with a dedicated, user-signed-in Flow browser."""
from __future__ import annotations
import json,os,queue,threading,time,tkinter as tk,webbrowser
from tkinter import ttk,filedialog,simpledialog
from pathlib import Path
from dataclasses import asdict
from .core import DATA,ROOT,Settings,Job,UserError,atomic_json,read_json,validate_plan
from . import pipeline,capcut,flow,flow_browser
from .theme import COLORS,apply_theme,text_box,dark_titlebar,dialog
from . import __version__

from .voices import english_voices
VOICES=english_voices()

def open_path(path):
    path=Path(path).resolve()
    if not path.exists(): raise UserError('This file is not ready yet. Create the project first.')
    if os.name=='nt': os.startfile(str(path))
    else: webbrowser.open(path.as_uri())

class App(tk.Tk):
    def __init__(self):
        super().__init__();self.title(f'VideoPilot {__version__} · Google Flow edition');self.geometry('980x680');self.minsize(780,560)
        self.job=None;self.busy=False;self.cancel=threading.Event();self.events=queue.Queue();self.buttons=[];self.vars={};self.last_watch=0;self.advanced=None;self.scene_index=None;self.plan=None;self.loaded_script=None;self.last_state=None
        self.status=tk.StringVar(value='Enter your idea, choose a format, and create your video.');apply_theme(self)
        top=ttk.Frame(self,padding=(18,12));top.pack(fill='x');ttk.Label(top,text='VideoPilot',style='Hero.TLabel').pack(side='left')
        ttk.Label(top,text='Codex + free local voice + Google Flow',foreground='#9eb9c9').pack(side='left',padx=18)
        self.action(top,'Settings',self.show_settings).pack(side='right');self.action(top,'Open project',self.open_job).pack(side='right',padx=6)
        self.project_label=ttk.Label(self,text='CapCut / Kdenlive · Editable project · Export in your editor',padding=(18,0));self.project_label.pack(fill='x')
        self.tabs=ttk.Notebook(self)
        self.create_tab=ttk.Frame(self.tabs,padding=12);self.flow_tab=ttk.Frame(self.tabs,padding=12);self.script_tab=ttk.Frame(self.tabs,padding=10);self.finish_tab=ttk.Frame(self.tabs,padding=10)
        for tab,label in [(self.create_tab,'1  Video'),(self.flow_tab,'2  Flow images'),(self.script_tab,'Script'),(self.finish_tab,'3  Finish')]:self.tabs.add(tab,text=label)
        self.build_create();self.build_flow();self.build_script();self.build_finish();self.load_defaults()
        footer=ttk.Frame(self,padding=(18,0,18,8));footer.pack(side='bottom',fill='x')
        self.action(footer,'Create video',self.create_video,'Go.TButton').pack(side='left')
        self.action(footer,'Continue project',self.resume).pack(side='left',padx=8)
        self.action(footer,'Project folder',lambda:self.safe(lambda:open_path(self.require_job().folder))).pack(side='left')
        ttk.Button(footer,text='Stop',command=self.stop_work).pack(side='right')
        status_label=ttk.Label(self,textvariable=self.status,padding=(18,0,18,10),wraplength=920,foreground='#a9dfcf')
        status_label.pack(side='bottom',fill='x',before=footer)
        status_label.bind('<Configure>',lambda event:event.widget.configure(wraplength=max(1,event.width-36)))
        self.tabs.pack(fill='both',expand=True,padx=18,pady=10)
        self.after(200,self.poll);self.protocol('WM_DELETE_WINDOW',self.close_app)

    def action(self,parent,label,cmd,style='TButton'):
        b=ttk.Button(parent,text=label,command=cmd,style=style);self.buttons.append(b);return b
    def text_box(self,parent,height=5):return text_box(parent,height)
    def variable(self,key,default):
        if key not in self.vars:self.vars[key]=tk.BooleanVar(value=default) if isinstance(default,bool) else tk.StringVar(value=str(default))
        return self.vars[key]
    def choice(self,parent,key,label,default,values,row,col=0,editable=False):
        frame=ttk.Frame(parent);frame.grid(row=row,column=col,sticky='ew',padx=6,pady=4)
        ttk.Label(frame,text=label).pack(anchor='w');v=self.variable(key,default)
        if values:w=ttk.Combobox(frame,textvariable=v,values=values,state='normal' if editable else 'readonly',width=24)
        else:w=ttk.Entry(frame,textvariable=v,width=27)
        w.pack(fill='x');return frame

    def build_create(self):
        viewport=tk.Canvas(self.create_tab,bg=COLORS['bg'],highlightthickness=0)
        scrollbar=ttk.Scrollbar(self.create_tab,orient='vertical',command=viewport.yview)
        scrollbar.pack(side='right',fill='y');viewport.pack(side='left',fill='both',expand=True)
        viewport.configure(yscrollcommand=scrollbar.set)
        p=ttk.Frame(viewport);form=viewport.create_window((0,0),window=p,anchor='nw')
        viewport.bind('<Configure>',lambda event:viewport.itemconfigure(form,width=event.width))
        p.bind('<Configure>',lambda event:viewport.configure(scrollregion=viewport.bbox('all')))
        ttk.Label(p,text='What video do you want to make?',font=('Segoe UI',13,'bold')).pack(anchor='w')
        self.idea=ttk.Entry(p,font=('Segoe UI',12));self.idea.pack(fill='x',pady=(5,8))
        ttk.Label(p,text='Story details, source facts, visual references and anything to avoid').pack(anchor='w')
        self.details=self.text_box(p,5);self.details.pack(fill='both',expand=True,pady=5)
        self.sample_script_text='';self.sample_script_label=tk.StringVar(value='No sample script selected (optional)')
        sample=ttk.Frame(p);sample.pack(fill='x',pady=4)
        self.action(sample,'Upload sample script (.txt)',lambda:self.safe(self.upload_sample_script)).pack(side='left')
        self.action(sample,'Remove sample',self.remove_sample_script).pack(side='left',padx=5)
        ttk.Label(sample,textvariable=self.sample_script_label,wraplength=400).pack(side='left',padx=6)
        ttk.Label(p,text='Constant image prompt (optional; added to every image)').pack(anchor='w',pady=(6,0))
        self.constant_image_prompt=self.text_box(p,3);self.constant_image_prompt.pack(fill='x',pady=4)
        ttk.Label(p,text='Enter only text that should appear in every image prompt. Put rules such as “character only in the first and last image” in Story details above; Codex applies them to individual scenes.',wraplength=850,foreground='#a5bfcd').pack(anchor='w')
        grid=ttk.Frame(p);grid.pack(fill='x',pady=5)
        for i in range(3):grid.columnconfigure(i,weight=1)
        self.choice(grid,'duration','Length in seconds',60,None,0,0)
        self.choice(grid,'aspect','Video format','9:16',['9:16','16:9','1:1'],0,1)
        self.choice(grid,'style','Image style (type your own)','Cinematic documentary',None,0,2)
        self.voice_label=tk.StringVar(value='Michael · US male');frame=ttk.Frame(grid);frame.grid(row=1,column=0,sticky='ew',padx=6,pady=4)
        ttk.Label(frame,text='Narrator: Kokoro / Chatterbox Nano').pack(anchor='w');self.voice_combo=ttk.Combobox(frame,textvariable=self.voice_label,values=list(VOICES),state='readonly',height=14);self.voice_combo.pack(fill='x')
        voice_actions=ttk.Frame(frame);voice_actions.pack(anchor='w',pady=3)
        self.action(voice_actions,'Preview voice',lambda:self.safe(self.preview_voice)).pack(side='left')
        self.action(voice_actions,'Nano voices',lambda:self.safe(self.manage_cloned_voices)).pack(side='left',padx=3)
        self.refresh_voice_choices()
        self.choice(grid,'tone','Storytelling tone','Calm, curious storyteller',['Calm, curious storyteller','Suspenseful and restrained','Energetic and conversational','Warm and thoughtful'],1,1,True)
        self.choice(grid,'flow_outputs','Image options for each shot',1,['1','2','3','4'],1,2)
        self.choice(grid,'min_shot_seconds','Minimum image hold (seconds; 0 = off)',0,['0','0.5','1','2','3','4'],2,0,editable=True)
        self.choice(grid,'shot_seconds','Maximum image hold (0.5–120 seconds)',5,['2','3','4','5','8','10'],2,1,editable=True)
        options=ttk.Frame(grid);options.grid(row=4,column=0,columnspan=2,sticky='w',padx=6)
        self.movement_check=ttk.Checkbutton(options,text='Gentle image movement (preset mode)',variable=self.variable('image_motion',True));self.movement_check.pack(anchor='w')
        ttk.Checkbutton(options,text='Use Remotion graphics',variable=self.variable('remotion_enabled',False)).pack(anchor='w')
        self.action(grid,'Customize graphics / apply changes',self.customize).grid(row=2,column=2,padx=6,sticky='ew')
        self.choice(grid,'editing_mode','Who edits: rules or Codex','rules',['rules','codex'],3,0)
        self.choice(grid,'video_editor','Editor: CapCut / Kdenlive','capcut',['capcut','kdenlive'],3,1)
        self.choice(grid,'motion_style','Preset movement style','slow_zoom',['slow_zoom','pan','float','mixed'],3,2)
        self.vars['editing_mode'].trace_add('write',lambda *_:self.movement_check.configure(state='disabled' if self.vars['editing_mode'].get()=='codex' else 'normal'))
        ttk.Label(p,text='Your Codex login is reused. Sign into Google once in the dedicated Flow browser. No image API key needed.',foreground='#a5bfcd',wraplength=870).pack(anchor='w',pady=5)
        def scroll_form(event):
            viewport.yview_scroll(-int(event.delta/120),'units')
            return 'break'
        def bind_scroll(widget):
            # Text boxes and dropdowns retain their own wheel behavior.
            if not isinstance(widget,(tk.Text,ttk.Combobox)):
                widget.bind('<MouseWheel>',scroll_form,add='+')
            for child in widget.winfo_children():bind_scroll(child)
        bind_scroll(viewport)

    def build_flow(self):
        p=self.flow_tab;ttk.Label(p,text='Generate images with your Google Flow subscription',font=('Segoe UI',13,'bold')).pack(anchor='w')
        ttk.Label(p,text='First use: Open Flow / sign in launches ordinary Chrome or Edge. Sign in there, then close that window.\nRun Flow queue reopens the same profile with your saved session. Open a Flow project and select its controls.\nIf Google asks you to sign in again, close that window and use Open Flow / sign in. Keep VideoPilot open while generating.',wraplength=870).pack(anchor='w',pady=10)
        row=ttk.Frame(p);row.pack(fill='x')
        for label,cmd in [('Open Flow / sign in',self.open_flow_browser),('Refresh Flow browser',self.refresh_flow_browser),('Run Flow queue',self.run_flow_browser),('Retry unresolved',self.retry_flow_browser),('Setup guide',lambda:open_path(ROOT/'FLOW_SETUP.html'))]:self.action(row,label,lambda f=cmd:self.safe(f)).pack(side='left',padx=3)
        self.flow_info=tk.StringVar(value='Create the video first. The queue appears after narration timing is ready.');ttk.Label(p,textvariable=self.flow_info,wraplength=870,foreground='#aedfd0').pack(anchor='w',pady=14)
        recovery_options=ttk.Frame(p);recovery_options.pack(fill='x',pady=(0,6))
        ttk.Label(recovery_options,text='Recovery order:').pack(side='left')
        self.recovery_order=tk.StringVar(value='Reverse (newest first)')
        ttk.Combobox(recovery_options,textvariable=self.recovery_order,values=['Reverse (newest first)','Normal (oldest first)'],state='readonly',width=26).pack(side='left',padx=6)
        ttk.Label(recovery_options,text='Resumes saved progress; skips imported images.').pack(side='left')
        row2=ttk.Frame(p);row2.pack(fill='x')
        self.action(row2,'Collect Flow downloads',self.collect_flow).pack(side='left',padx=3)
        self.action(row2,'Recover generated images',lambda:self.safe(self.recover_flow_browser)).pack(side='left',padx=3)
        self.action(row2,'Import images manually',self.import_images).pack(side='left',padx=3)
        self.action(row2,'Preview storyboard',self.storyboard).pack(side='left',padx=3)
        self.action(row2,'Erase remaining star',lambda:self.safe(self.erase_star)).pack(side='left',padx=3)
        ttk.Separator(p).pack(fill='x',pady=14)
        ttk.Label(p,text='Choose a different image variant',font=('Segoe UI',11,'bold')).pack(anchor='w')
        self.shot_choice=tk.StringVar();self.variant=tk.StringVar(value='1');vr=ttk.Frame(p);vr.pack(fill='x',pady=6)
        self.shot_combo=ttk.Combobox(vr,textvariable=self.shot_choice,state='readonly',width=18);self.shot_combo.pack(side='left')
        ttk.Combobox(vr,textvariable=self.variant,values=[str(i) for i in range(1,49)],state='readonly',width=5).pack(side='left',padx=8)
        self.action(vr,'View variants',self.view_variants).pack(side='left');self.action(vr,'Use selected',self.select_variant).pack(side='left',padx=8)
        ttk.Label(p,text='The first returned image is initially selected; all variants are kept for review.\nYour everyday browser login is separate. Google sign-in happens only in the browser, never in VideoPilot.\nFlow controls its limits; automation pauses on ambiguous results or verification prompts.',wraplength=870,foreground='#a5bfcd').pack(anchor='w',pady=8)

    def build_script(self):
        p=self.script_tab;ttk.Label(p,text='Review or edit a scene in plain language. Changes take effect when you continue.').pack(anchor='w')
        body=ttk.Frame(p);body.pack(fill='both',expand=True,pady=6)
        self.scenes=tk.Listbox(body,width=20,bg=COLORS['field'],fg=COLORS['text'],selectbackground=COLORS['selected'],selectforeground=COLORS['text'],relief='flat',borderwidth=0,highlightthickness=1,highlightbackground=COLORS['border'],highlightcolor=COLORS['accent'],exportselection=False);self.scenes.pack(side='left',fill='y',padx=(0,10));self.scenes.bind('<<ListboxSelect>>',self.load_scene)
        editor=ttk.Frame(body);editor.pack(fill='both',expand=True)
        ttk.Label(editor,text='Narration').pack(anchor='w');self.scene_voice=self.text_box(editor,3);self.scene_voice.pack(fill='both',expand=True,pady=4)
        ttk.Label(editor,text='Image description').pack(anchor='w');self.scene_visual=self.text_box(editor,3);self.scene_visual.pack(fill='both',expand=True,pady=4)
        ttk.Label(editor,text='On-screen emphasis (optional)').pack(anchor='w');self.overlay=ttk.Entry(editor);self.overlay.pack(fill='x',pady=4)
        row=ttk.Frame(p);row.pack(fill='x');self.action(row,'Save scene',self.save_scene).pack(side='left');self.action(row,'Fit script to narration length',self.fit_script).pack(side='left',padx=8)
        self.action(row,'Read full script',lambda:self.safe(lambda:open_path(self.require_job().folder/'script.txt'))).pack(side='left')
        self.action(row,'Edit scene graphics',lambda:self.safe(self.edit_scene_graphics)).pack(side='left',padx=8)
        self.action(p,'Approve script / Continue project',self.resume,'Go.TButton').pack(anchor='w',pady=6)

    def build_finish(self):
        p=self.finish_tab;ttk.Label(p,text='Finish in your selected editor',font=('Segoe UI',13,'bold')).pack(anchor='w')
        ttk.Label(p,text='CapCut: attach a sample with one photo, WAV and text clip, then install into an empty project.\nKdenlive: Continue project, then Open / save Kdenlive project. The save dialog starts in Videos.',wraplength=870).pack(anchor='w',pady=6)
        row=ttk.Frame(p);row.pack(fill='x')
        for label,cmd in [('Choose CapCut sample',self.attach_template),('Install into empty project',self.install),('Mark finished',self.finish)]:self.action(row,label,cmd).pack(side='left',padx=3)
        self.action(row,'Import sound effects',self.attach_sounds).pack(side='left',padx=3)
        music=ttk.Frame(p);music.pack(fill='x',pady=5)
        ttk.Label(music,text='Background music').pack(side='left')
        ttk.Combobox(music,textvariable=self.variable('bgm','ambient'),values=('ambient','file','none'),state='readonly',width=10).pack(side='left',padx=6)
        self.action(music,'Apply music',lambda:self.safe(self.apply_music)).pack(side='left')
        self.action(music,'Choose named CapCut audio',lambda:self.safe(self.browse_capcut_audio)).pack(side='left',padx=6)
        self.action(p,'Browse background music from PC',lambda:self.safe(self.choose_local_music)).pack(anchor='w',pady=5)
        self.action(p,'Open / save Kdenlive project',lambda:self.safe(self.open_kdenlive)).pack(anchor='w',pady=5)
        self.action(p,'Remove remaining stars from CapCut draft',lambda:self.safe(self.repair_draft_stars)).pack(anchor='w',pady=5)
        self.logbox=self.text_box(p,9);self.logbox.configure(state='disabled');self.logbox.pack(fill='both',expand=True,pady=10)
        row=ttk.Frame(p);row.pack(fill='x');self.action(row,'Listen to narration',lambda:self.safe(lambda:open_path(self.require_job().folder/'audio'/'narration.wav'))).pack(side='left')
        self.action(row,'Restore blank project',self.restore).pack(side='left',padx=8)
        self.action(row,'Create editing revision',self.editing_revision).pack(side='left',padx=4)
        self.action(row,'Create image repair copy',self.image_repair_copy).pack(side='left',padx=4)
        self.action(row,'Clean duplicate downloads',self.clean_storage).pack(side='left',padx=4)
        ttk.Label(p,text='Export stays manual. The version number is recorded; compatibility still needs a sample from your installation.',foreground='#a5bfcd',wraplength=870).pack(anchor='w',pady=5)

    def show_settings(self):
        if self.advanced and self.advanced.winfo_exists():self.advanced.lift();return
        win=tk.Toplevel(self);self.advanced=win;win.title('VideoPilot settings');win.geometry('700x540');win.transient(self);win.configure(bg=COLORS['bg']);win.after_idle(lambda:dark_titlebar(win))
        p=ttk.Frame(win,padding=16);p.pack(fill='both',expand=True);p.columnconfigure(1,weight=1)
        items=[('min_shot_seconds','Minimum image hold (seconds; 0 = off)',0),('shot_seconds','Maximum image hold (0.5-120 seconds)',5),('speed','Voice speed (0.8–1.2)',1.0),('audience','Audience','General YouTube audience'),('codex_model','Codex model (blank uses CLI default)',''),('flow_downloads','Browser Downloads folder',str(flow.default_downloads())),('sfx_folder','Downloaded sound effects folder','')]
        for row,(key,label,default) in enumerate(items):
            ttk.Label(p,text=label).grid(row=row,column=0,sticky='w',pady=6);ttk.Entry(p,textvariable=self.variable(key,default)).grid(row=row,column=1,sticky='ew',padx=8)
            if key in ('flow_downloads','sfx_folder'):ttk.Button(p,text='Browse',command=lambda k=key:self.browse(k)).grid(row=row,column=2)
        for row,key,label in [(8,'captions','Add phrase captions'),(9,'sfx','Add subtle sound effects')]:ttk.Checkbutton(p,text=label,variable=self.variable(key,True)).grid(row=row,column=0,columnspan=3,sticky='w',pady=7)
        ttk.Label(p,text='Settings apply to new projects. Active projects retain their saved settings.\nCapCut version: 2.1.0. No image API key or additional Codex login is required.\nVoice tone comes from wording and punctuation; local Kokoro has no direct emotion controls.',wraplength=640).grid(row=10,column=0,columnspan=3,sticky='w',pady=12)
        ttk.Button(p,text='Done',command=win.destroy).grid(row=11,column=2)
        win.geometry('740x610')

    def load_defaults(self):
        defaults=asdict(Settings());defaults['flow_downloads']=str(flow.default_downloads())
        path=DATA/'preferences.json'
        if path.exists():
            try:defaults.update(read_json(path))
            except (OSError,ValueError):pass
        for k,v in defaults.items():
            if k in ('idea','details','sample_script','constant_image_prompt','image_mode','paid_images','image_model','max_image_requests'):continue
            self.variable(k,v).set(v)
        self.variable('template_path','')
        self.voice_label.set(next((label for label,value in self.voice_choices.items() if value==defaults.get('voice')),'Michael · US male'))
    def collect(self):
        s=Settings();values=asdict(s)
        for k,v in self.vars.items():
            if k in values:values[k]=v.get()
        try:
            for k in ('duration','flow_outputs','graphics_percent'):values[k]=int(values[k])
            for k in ('shot_seconds','min_shot_seconds','speed'):values[k]=float(values[k])
        except ValueError:raise UserError('Enter valid numbers for length, image count, speed and image hold.')
        voice=self.voice_choices[self.voice_label.get()];values.update(idea=self.idea.get().strip(),details=self.details.get('1.0','end').strip(),voice=voice,language='en-gb' if voice.startswith('b') else 'en-us',image_mode='flow',paid_images=False)
        values['sample_script']=self.sample_script_text
        values['constant_image_prompt']=self.constant_image_prompt.get('1.0','end-1c')
        s=Settings(**values);s.validate();return s
    def refresh_voice_choices(self):
        from .cloned_voices import voices,is_nano
        self.voice_choices=dict(VOICES);self.voice_choices.update(voices())
        if self.job and is_nano(self.job.settings.voice) and self.job.settings.voice not in self.voice_choices.values():
            self.voice_choices['Chatterbox Nano: saved project voice']=self.job.settings.voice
        self.voice_combo.configure(values=list(self.voice_choices))
        if self.voice_label.get() not in self.voice_choices:self.voice_label.set(next(iter(VOICES)))

    def manage_cloned_voices(self):
        from . import cloned_voices as cv
        win=tk.Toplevel(self);win.title('Chatterbox Nano voices');win.geometry('610x390');win.transient(self)
        p=ttk.Frame(win,padding=16);p.pack(fill='both',expand=True)
        ttk.Label(p,text='Chatterbox Nano: local English voice cloning',font=('Segoe UI',12,'bold')).pack(anchor='w')
        ready=cv.RUNTIME.is_file() and (cv.MODEL_CACHE/'ready.json').is_file()
        ttk.Label(p,text='Installed and tested' if ready else 'Setup required: run Install_Chatterbox_Nano.bat in the VideoPilot folder.\nSetup downloads Nano separately and tests CPU generation.',wraplength=560).pack(anchor='w',pady=8)
        ttk.Label(p,text='Upload 10-15 seconds of clear speech from one speaker.\nThe saved sample is reused as the voice reference; no training is needed.',wraplength=560).pack(anchor='w')
        selected=tk.StringVar();combo=ttk.Combobox(p,textvariable=selected,state='readonly',width=65);combo.pack(fill='x',pady=12)
        entries={}
        def refresh(voice=None):
            entries.clear();entries.update(cv.voices());combo.configure(values=list(entries))
            selected.set(next((label for label,value in entries.items() if value==voice),next(iter(entries),'')))
            self.refresh_voice_choices()
        def upload():
            path=filedialog.askopenfilename(parent=win,title='Choose a voice sample',filetypes=[('Audio','*.wav *.mp3 *.flac *.m4a')])
            if not path:return
            name=simpledialog.askstring('Voice name','Name this saved voice:',initialvalue=Path(path).stem,parent=win)
            if name is None:return
            refresh(cv.add_voice(path,name))
        def use():
            if selected.get() not in entries:raise UserError('Upload or select a saved voice first.')
            self.voice_label.set(selected.get());win.destroy()
        def remove():
            if selected.get() not in entries:raise UserError('Choose a saved voice first.')
            cv.remove_voice(entries[selected.get()]);refresh()
        row=ttk.Frame(p);row.pack(fill='x')
        ttk.Button(row,text='Upload sample',command=lambda:self.safe(upload)).pack(side='left')
        ttk.Button(row,text='Use selected voice',command=lambda:self.safe(use)).pack(side='left',padx=8)
        ttk.Button(row,text='Remove voice',command=lambda:self.safe(remove)).pack(side='left')
        ttk.Label(p,text='Removing a library voice preserves the reference in existing projects.\nVoice choices here apply to new videos; existing projects keep their narrator.',wraplength=560).pack(anchor='w',pady=16)
        refresh()

    def upload_sample_script(self):
        path=filedialog.askopenfilename(title='Choose a sample script for the next video',filetypes=[('Text script','*.txt')])
        if not path:return
        from .script_reference import read_sample_script
        text=read_sample_script(path)
        self.sample_script_text=text;self.sample_script_label.set(Path(path).name)
    def remove_sample_script(self):
        self.sample_script_text='';self.sample_script_label.set('No sample script selected (optional)')
    def require_job(self):
        if not self.job:raise UserError('Create or open a project first.')
        return self.job
    def customize(self):
        win=tk.Toplevel(self);win.title('Video customization');win.geometry('740x590');win.transient(self);win.configure(bg=COLORS['bg'])
        p=ttk.Frame(win,padding=18);p.pack(fill='both',expand=True);p.columnconfigure(1,weight=1)
        ttk.Label(p,text='Codex chooses movement. Preset mode uses your gentle movement choice.',font=('Segoe UI',11,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',pady=8)
        ttk.Checkbutton(p,text='Move images (preset mode only)',variable=self.variable('image_motion',True),state='disabled' if self.vars['editing_mode'].get()=='codex' else 'normal').grid(row=1,column=0,columnspan=3,sticky='w')
        ttk.Checkbutton(p,text='Use Remotion motion graphics',variable=self.variable('remotion_enabled',False)).grid(row=2,column=0,columnspan=3,sticky='w',pady=8)
        fields=[('graphics_percent','Graphics coverage (% of runtime)',25),('graphics_accent','Accent color (#RRGGBB)','#84e1cc'),('remotion_path','Existing Remotion project',Settings().remotion_path)]
        for row,(key,label,value) in enumerate(fields,3):
            ttk.Label(p,text=label).grid(row=row,column=0,sticky='w',pady=8)
            ttk.Entry(p,textvariable=self.variable(key,value)).grid(row=row,column=1,sticky='ew',padx=8)
        def browse():
            path=filedialog.askdirectory(title='Existing Remotion project with node_modules')
            if path:self.variable('remotion_path','').set(path)
        ttk.Button(p,text='Browse',command=browse).grid(row=5,column=2)
        ttk.Label(p,text='Graphics theme').grid(row=6,column=0,sticky='w',pady=8)
        ttk.Combobox(p,textvariable=self.variable('graphics_theme','Editorial'),values=['Editorial','Minimal','Bold'],state='readonly').grid(row=6,column=1,sticky='ew',padx=8)
        ttk.Label(p,text='0% = no graphics; 100% = graphics on every shot. Coverage rounds to whole shots.\nGraphics render one shot at a time using your existing Remotion installation.\nImages follow narration and your typed maximum hold, even without movement.\nType any image style in the Video tab; examples: ink drawings, clay animation, archival photos.\n\nThese choices apply to new videos. Apply below to rebuild an uninstalled project.\nFor an installed edit, create an editing revision first, then apply your choices.',wraplength=680).grid(row=7,column=0,columnspan=3,sticky='w',pady=16)
        self.action(p,'Apply to current project',lambda:self.safe(self.apply_customization)).grid(row=8,column=0,sticky='w')
        ttk.Button(p,text='Done',command=win.destroy).grid(row=8,column=2)
    def apply_customization(self):
        from dataclasses import replace
        job=self.require_job();job.require_mutable()
        if self.busy:raise UserError('Stop generation before changing this project.')
        keys=('style','shot_seconds','min_shot_seconds','image_motion','editing_mode','video_editor','motion_style','remotion_enabled','graphics_percent','graphics_theme','graphics_accent','remotion_path')
        values={k:self.vars[k].get() for k in keys}
        try:values['min_shot_seconds']=float(values['min_shot_seconds']);values['shot_seconds']=float(values['shot_seconds']);values['graphics_percent']=int(values['graphics_percent'])
        except ValueError:raise UserError('Enter valid numbers for image hold and graphics percentage.')
        settings=replace(job.settings,**values);settings.validate()
        job.settings=settings;job.data['settings']=asdict(settings)
        job.status('SETTINGS_UPDATED','Customization saved. Continue project to rebuild. Style or cadence changes may require new Flow images.')
        self.refresh()
    def choose_local_music(self):
        if self.busy:raise UserError('Stop generation before changing music.')
        self.require_job().require_mutable()
        if self.browse('bgm_path'):self.apply_music()

    def apply_music(self):
        from dataclasses import replace
        if self.busy:raise UserError('Stop generation before changing music.')
        job=self.require_job();job.require_mutable()
        settings=replace(job.settings,bgm=self.vars['bgm'].get(),bgm_path=self.vars['bgm_path'].get());settings.validate()
        job.settings=settings;job.data['settings']=asdict(settings)
        job.status('SETTINGS_UPDATED','Music saved. Continue project to rebuild with the selected music.');self.refresh()
    def browse_capcut_audio(self):
        from .sound_catalog import discover
        source=DATA.parent/'CapCut'/'User Data'/'Cache'/'music'
        if not source.is_dir():raise UserError('The CapCut music cache folder was not found.')
        catalog=discover(source);named=sorted([x for x in catalog if x['name']],key=lambda x:(x['kind']!='music',x['name'].casefold()))
        win=tk.Toplevel(self);win.title('Named audio from the CapCut cache');win.geometry('760x520');win.configure(bg=COLORS['bg'])
        p=ttk.Frame(win,padding=16);p.pack(fill='both',expand=True)
        ttk.Label(p,text=f'Recovered names for {len(named)} of {len(catalog)} files. Search, listen, then choose background music.').pack(anchor='w')
        query=tk.StringVar();ttk.Entry(p,textvariable=query).pack(fill='x',pady=8)
        box=tk.Listbox(p,bg=COLORS['field'],fg=COLORS['text'],selectbackground=COLORS['selected']);box.pack(fill='both',expand=True)
        visible=[]
        def refresh(*_):
            visible[:]=[x for x in named if query.get().casefold() in x['name'].casefold()];box.delete(0,'end')
            for item in visible:box.insert('end',f'{item["name"]}  [{item["kind"]}]')
        query.trace_add('write',refresh);refresh()
        def selected():
            if not box.curselection():raise UserError('Select a named audio file.')
            return visible[box.curselection()[0]]
        def choose():
            self.vars['bgm_path'].set(selected()['source']);self.vars['bgm'].set('file');win.destroy()
        row=ttk.Frame(p);row.pack(fill='x',pady=10)
        ttk.Button(row,text='Listen',command=lambda:self.safe(lambda:open_path(selected()['source']))).pack(side='left')
        ttk.Button(row,text='Use as background music',command=lambda:self.safe(choose)).pack(side='right')
        ttk.Label(p,text='Names come from saved CapCut projects or embedded titles. Hash-only files are omitted.\nFor an existing uninstalled video, click Apply music in Finish, then Continue project.',wraplength=700).pack(anchor='w')
    def safe(self,fn):
        try:return fn()
        except Exception as e:dialog(self,'VideoPilot',str(e),error=True)
    def create_video(self):
        def go():
            s=self.collect();self.job=Job.create(s);prefs=asdict(s)
            for key in ('idea','details','sample_script','constant_image_prompt'):prefs.pop(key,None)
            atomic_json(DATA/'preferences.json',prefs);self.refresh();self.resume()
        self.safe(go)
    def open_job(self):
        path=filedialog.askopenfilename(title='Open VideoPilot job.json',initialdir=DATA/'projects',filetypes=[('VideoPilot project','job.json')])
        if not path:return
        def go():
            self.job=Job(Path(path).parent)
            if self.job.settings.image_mode!='flow' and not self.job.data.get('installed_path'):
                self.job.settings.image_mode='flow';self.job.settings.paid_images=False;self.job.data['settings']=asdict(self.job.settings);self.job.save()
            self.idea.delete(0,'end');self.idea.insert(0,self.job.settings.idea);self.details.delete('1.0','end');self.details.insert('1.0',self.job.settings.details)
            self.constant_image_prompt.delete('1.0','end');self.constant_image_prompt.insert('1.0',self.job.settings.constant_image_prompt or '')
            for k,v in asdict(self.job.settings).items():
                if k in self.vars:self.vars[k].set(v)
            self.refresh_voice_choices()
            self.voice_label.set(next((label for label,value in self.voice_choices.items() if value==self.job.settings.voice),'Michael · US male'));self.refresh()
        self.safe(go)
    def refresh(self):
        if not self.job:return
        j=self.job;self.status.set(j.data['state'].replace('_',' ').title()+' · '+j.data['message']);self.project_label.configure(text=f'{j.folder.name}  |  {j.settings.duration}s  |  {j.settings.aspect}  |  {j.settings.editing_mode} / {j.settings.video_editor}')
        q=j.folder/'FLOW_QUEUE.json'
        if q.exists():
            data=read_json(q);self.flow_info.set(f'{len(data["shots"])} shots · {data["aspect"]} · {data["outputs"]} image(s) per prompt\nQueue: {q}\nDownload subfolder: VideoPilot/{data["queue_id"]}')
            ready=sum((j.folder/'images'/f'{s["id"]}.png').is_file() and
                      (j.folder/'images'/f'{s["id"]}.json').is_file() for s in data['shots'])
            self.flow_info.set(self.flow_info.get()+f'\n{ready}/{len(data["shots"])} shot images in the project')
            self.shot_combo.configure(values=[s['id'] for s in data['shots']])
            if not self.shot_choice.get():self.shot_choice.set(data['shots'][0]['id'])
        else:
            self.flow_info.set('Create the video first. The queue appears after narration timing is ready.');self.shot_combo.configure(values=[]);self.shot_choice.set('')
        script=j.folder/'script.json'
        script_stamp=(str(script),script.stat().st_mtime_ns) if script.exists() else None
        if not script_stamp:
            self.loaded_script=None;self.plan=None;self.scene_index=None;self.scenes.delete(0,'end');self.scene_voice.delete('1.0','end');self.scene_visual.delete('1.0','end');self.overlay.delete(0,'end')
        if script_stamp and script_stamp!=self.loaded_script:
            self.loaded_script=script_stamp
            self.plan=read_json(script);self.scenes.delete(0,'end')
            for i,s in enumerate(self.plan['scenes'],1):self.scenes.insert('end',f'Scene {i} · {s["narration"][:18]}')
            self.scenes.selection_set(0);self.load_scene()
        if j.data['state']!=self.last_state:
            if j.data['state']=='SCRIPT_READY':self.tabs.select(self.script_tab)
            elif j.data['state']=='WAITING_FOR_FLOW':self.tabs.select(self.flow_tab)
            elif j.data['state'] in ('READY_FOR_CAPCUT','READY_FOR_KDENLIVE','NEEDS_CAPCUT_TEMPLATE','AWAITING_REVIEW','FINISHED_UNRENDERED'):self.tabs.select(self.finish_tab)
        self.last_state=j.data['state']
    def work(self,fn,quiet=False):
        if self.busy:return
        self.busy=True;self.cancel.clear()
        for b in self.buttons:
            if b.winfo_exists():b.configure(state='disabled')
        def runner():
            try:fn()
            except Exception as e:self.events.put(('error',str(e)))
            finally:self.events.put(('quiet_done' if quiet else 'done',None))
        threading.Thread(target=runner,daemon=True).start()
    def log(self,text):self.events.put(('log',text))
    def poll(self):
        try:
            while True:
                kind,text=self.events.get_nowait()
                if kind in ('error','log'):
                    if kind=='log' and text.startswith('Imported Flow shot '):self.refresh()
                    self.logbox.configure(state='normal');self.logbox.insert('end',text+'\n');self.logbox.see('end');self.logbox.configure(state='disabled');self.status.set(text)
                    if kind=='error':dialog(self,'VideoPilot',text,error=True)
                if kind=='refresh':self.refresh()
                if kind=='voice_ready':
                    import winsound
                    if not self.cancel.is_set():
                        winsound.PlaySound(str(text),winsound.SND_FILENAME|winsound.SND_ASYNC)
                        self.status.set('Playing six-second narrator sample. Stop ends playback.')
                if kind in ('done','quiet_done'):
                    self.busy=False
                    for b in self.buttons:
                        if b.winfo_exists():b.configure(state='normal')
                    if kind=='done':self.refresh()
        except queue.Empty:pass
        if not self.busy and self.job and self.job.data['state']=='WAITING_FOR_FLOW' and time.monotonic()-self.last_watch>5:
            self.last_watch=time.monotonic();self.collect_flow(automatic=True)
        self.after(200,self.poll)
    def resume(self):
        self.safe(lambda:self.work(lambda:pipeline.run(self.require_job(),self.cancel,self.log,approve_script=True)))
    def preview_voice(self):
        from .voice_preview import preview_voice
        voice=self.voice_choices[self.voice_label.get()]
        self.stop_work()
        project=self.job.folder if self.job and self.job.settings.voice==voice else None
        self.work(lambda:self.events.put(('voice_ready',preview_voice(voice,self.cancel,self.log,project=project))),quiet=True)
    def stop_work(self):
        self.cancel.set()
        if os.name=='nt':
            import winsound
            winsound.PlaySound(None,0)
    def attach_sounds(self):
        def go():
            job=self.require_job();job.require_mutable()
            path=filedialog.askdirectory(title='Select downloaded CapCut sound effects (WAV, MP3, M4A)')
            if not path:return
            job.settings.sfx_folder=path;job.settings.sfx=True
            job.data['settings']=asdict(job.settings);job.save()
            from .sound_library import import_library
            self.work(lambda:import_library(job,path,self.cancel,self.log))
        self.safe(go)
    def editing_revision(self):
        source=self.require_job()
        def go():
            from .revisions import create_revision
            self.job=create_revision(source,self.cancel,self.log)
        self.work(go)
    def image_repair_copy(self):
        source=self.require_job()
        def go():
            from .image_audit import create_image_repair_copy
            self.job=create_image_repair_copy(source,self.cancel,self.log)
        self.work(go)
    def clean_storage(self):
        def go():
            from .storage import clean_duplicates,clean_unused_graphics
            job=self.require_job();size=clean_duplicates(job)+clean_unused_graphics(job)
            self.log(f'Reclaimed {size/1048576:.2f} MB by sharing identical Flow originals and removing unused graphics. Flow image paths and receipts retained.')
        self.work(go)
    def open_flow_browser(self):
        def go():
            flow_browser.open_signin_browser(self.cancel)
            self.log('Ordinary browser opened for manual Google sign-in. Sign in, then CLOSE that dedicated window and click Run Flow queue. Your login is saved in its profile.')
        self.work(go,quiet=True)
    def refresh_flow_browser(self):
        self.work(lambda:flow_browser.refresh_browser(self.cancel,self.log),quiet=True)
    def run_flow_browser(self):
        job=self.require_job()
        def go():
            flow_browser.run(job,self.cancel,self.log)
        self.work(go)
    def recover_flow_browser(self):
        job=self.require_job()
        order='forward' if self.recovery_order.get()=='Normal (oldest first)' else 'reverse'
        def recover():
            flow_browser.recover(job,self.cancel,self.log,order=order)
            pipeline.run(job,self.cancel,self.log)
        self.work(recover)
    def retry_flow_browser(self):
        job=self.require_job();pending=flow_browser.pending_shots(job)
        if not pending:
            dialog(self,'Flow browser','No unresolved browser shot. Use Run Flow queue to continue.');return
        if dialog(self,'Retry unresolved Flow shots',f'Retry these shots: {", ".join(pending)}? Check Flow first: some may have generated already. Import finished images before retrying. Retrying can consume additional usage.',question=True):
            flow_browser.clear_pending(job);self.run_flow_browser()
    def collect_flow(self,automatic=False):
        if not self.job or not (self.job.folder/'FLOW_QUEUE.json').exists():
            if not automatic:dialog(self,'VideoPilot','Create narration first so the Flow queue can be prepared.')
            return
        job=self.job
        def collect():
            if job.data.get('installed_path'):return
            before=job.data['state']
            n=flow.collect_downloads(job,job.folder/'browser-downloads')
            n+=flow.collect_downloads(job)
            if n:self.log(f'Collected {n} Flow image set(s).')
            timeline=read_json(job.folder/'timeline.json');missing=sum(not pipeline.cached_image(job,s) for s in timeline['shots'])
            if not missing and job.data['state']!='READY_FOR_CAPCUT':pipeline.run(job,self.cancel,self.log)
            elif not automatic:self.log(f'{missing} shot(s) still need images. Check the helper and Downloads folder.')
            if n or before!=job.data['state']:self.events.put(('refresh',None))
        self.work(collect,quiet=True)
    def show_queue(self):
        j=self.require_job()
        if not (j.folder/'FLOW_QUEUE.json').exists():raise UserError('The queue appears after narration generation.')
        self.clipboard_clear();self.clipboard_append(str(j.folder/'FLOW_QUEUE.json'));open_path(j.folder)
        self.status.set('Queue path copied. In the Flow helper, choose the file and paste this path into the file dialog.')
    def browse(self,key):
        path=filedialog.askdirectory(title='Choose folder') if key in ('flow_downloads','sfx_folder') else filedialog.askopenfilename(filetypes=[('Background music','*.mp3 *.wav'),('MP3','*.mp3'),('PCM WAV','*.wav')])
        if path:
            self.vars[key].set(path)
            if key=='bgm_path':self.vars['bgm'].set('file')
        return path
    def load_scene(self,event=None):
        if not self.plan or not self.scenes.curselection():return
        self.scene_index=self.scenes.curselection()[0];s=self.plan['scenes'][self.scene_index]
        for box,key in ((self.scene_voice,'narration'),(self.scene_visual,'visual')):box.delete('1.0','end');box.insert('1.0',s[key])
        self.overlay.delete(0,'end');self.overlay.insert(0,s['overlay'])
    def save_scene(self):
        def go():
            j=self.require_job();j.require_mutable()
            if self.scene_index is None or not self.plan:raise UserError('Generate the script first.')
            import copy,shutil
            p=copy.deepcopy(self.plan);s=p['scenes'][self.scene_index];s.update(narration=self.scene_voice.get('1.0','end').strip(),visual=self.scene_visual.get('1.0','end').strip(),overlay=self.overlay.get().strip());validate_plan(p)
            shutil.copy2(j.folder/'script.json',j.folder/f'script-backup-{time.time_ns()}.json');atomic_json(j.folder/'script.json',p)
            j.data['script_origin']='edited';j.status('SCRIPT_READY','Scene saved. Continue to update the narration and images.');self.refresh()
        self.safe(go)
    def fit_script(self):self.safe(lambda:self.work(lambda:pipeline.fit_script(self.require_job(),self.cancel,self.log)))
    def edit_scene_graphics(self):
        job=self.require_job();job.require_mutable()
        if self.scene_index is None or not self.plan:raise UserError('Select a script scene first.')
        index=self.scene_index
        from .remotion_graphics import graphic_for
        graphic=graphic_for(self.plan,{'scene':index+1})
        win=tk.Toplevel(self);win.title(f'Graphics for scene {index+1}');win.geometry('720x590');win.transient(self);win.configure(bg=COLORS['bg'])
        p=ttk.Frame(win,padding=18);p.pack(fill='both',expand=True)
        kind=tk.StringVar(value=graphic['kind']);title=tk.StringVar(value=graphic['title'])
        ttk.Label(p,text='Illustrated layout').pack(anchor='w');ttk.Combobox(p,textvariable=kind,values=['focus','process','cycle','comparison','timeline','orbit'],state='readonly').pack(fill='x',pady=5)
        ttk.Label(p,text='Title (up to 80 characters; keep it short)').pack(anchor='w');ttk.Entry(p,textvariable=title).pack(fill='x',pady=5)
        ttk.Label(p,text='Items: one per line; up to three steps or exactly two comparison items').pack(anchor='w')
        items=self.text_box(p,4);items.pack(fill='both',expand=True,pady=5);items.insert('1.0','\n'.join(graphic['items']))
        from .core import GRAPHIC_ICONS
        icons=tk.StringVar(value=', '.join(graphic.get('icons',[])))
        ttk.Label(p,text='Illustrations, in order (comma-separated; blank chooses automatically)').pack(anchor='w')
        ttk.Entry(p,textvariable=icons).pack(fill='x',pady=5)
        ttk.Label(p,text='Available: '+', '.join(GRAPHIC_ICONS),wraplength=670).pack(anchor='w')
        ttk.Label(p,text='Graphics appear on shots selected by your coverage percentage.\nSave narration edits before opening this editor. Continue project to render changes.',wraplength=570).pack(anchor='w',pady=6)
        def save():
            if self.busy:raise UserError('Stop generation before editing graphics.')
            job.require_mutable()
            import shutil
            plan=read_json(job.folder/'script.json')
            plan['scenes'][index]['graphic']={'kind':kind.get(),'title':title.get().strip(),'items':[x.strip() for x in items.get('1.0','end').splitlines() if x.strip()],'icons':[x.strip() for x in icons.get().split(',') if x.strip()]}
            validate_plan(plan)
            shutil.copy2(job.folder/'script.json',job.folder/f'script-backup-{time.time_ns()}.json')
            atomic_json(job.folder/'script.json',plan);job.data['script_origin']='edited'
            job.status('SCRIPT_READY','Graphic content saved. Continue project to rebuild.');win.destroy();self.refresh()
        ttk.Button(p,text='Save graphic',command=lambda:self.safe(save)).pack(anchor='e')
    def attach_template(self):
        path=filedialog.askopenfilename(title='CapCut 2.1.0 sample draft_content.json',filetypes=[('Native CapCut sample','draft_content.json')])
        if not path:return
        def go():
            capcut.Template(path);self.variable('template_path','').set(path)
            if self.job:
                self.job.require_mutable();self.job.settings.template_path=path;self.job.data['settings']=asdict(self.job.settings);self.job.status('TEMPLATE_ATTACHED','Sample attached. Continue to build the editable timeline.');self.refresh()
        self.safe(go)
    def import_images(self):
        if not self.job:return
        folder=filedialog.askdirectory(title='Images named 001_01.png, 002_01.png, etc.')
        if folder:self.work(lambda:self.log(f'Imported {pipeline.import_images(self.job,folder)} images. Continue the project.'))
    def storyboard(self):
        def go():
            from .review import make_storyboard
            open_path(make_storyboard(self.require_job()))
        self.safe(go)
    def view_variants(self):self.safe(lambda:open_path(self.require_job().folder/'flow_variants'/self.shot_choice.get()))
    def repair_draft_stars(self):
        job=self.require_job()
        from .draft_cleanup import remove_draft_stars
        self.work(lambda:remove_draft_stars(job,self.cancel,self.log))
    def erase_star(self):
        job=self.require_job();job.require_mutable()
        shot=self.shot_choice.get()
        if not shot:raise UserError('Select a shot in the Flow images tab first.')
        path=job.folder/'images'/f'{shot}.png'
        if not path.is_file():raise UserError('Import or generate that image first.')
        if not path.with_suffix('.json').is_file():raise UserError('Import the image through VideoPilot before repairing it.')
        from PIL import Image,ImageTk
        from .core import file_hash
        from .image_cleanup import erase_region,CLEANUP_VERSION
        original=Image.open(path).convert('RGB');original.load();before=file_hash(path)
        thumb=original.copy();thumb.thumbnail((900,500));sx=original.width/thumb.width;sy=original.height/thumb.height
        win=tk.Toplevel(self);win.title('Select the remaining star');win.configure(bg=COLORS['bg'])
        ttk.Label(win,text='Drag a small rectangle around the star, then preview the repair.').pack(padx=12,pady=10)
        canvas=tk.Canvas(win,width=thumb.width,height=thumb.height,highlightthickness=0);canvas.pack(padx=12)
        photo=ImageTk.PhotoImage(thumb);canvas.photo=photo;image_id=canvas.create_image(0,0,anchor='nw',image=photo)
        selected={};repaired={}
        def start(event):
            selected.clear();repaired.clear();canvas.delete('selection');selected['start']=(event.x,event.y)
        def drag(event):
            if 'start' not in selected:return
            x,y=selected['start'];canvas.delete('selection')
            canvas.create_rectangle(x,y,event.x,event.y,outline='#ffcc55',width=2,tags='selection')
            selected['box']=(round(max(0,min(x,event.x))*sx),round(max(0,min(y,event.y))*sy),round(min(thumb.width,max(x,event.x))*sx),round(min(thumb.height,max(y,event.y))*sy))
        canvas.bind('<ButtonPress-1>',start);canvas.bind('<B1-Motion>',drag)
        def preview():
            if 'box' not in selected:raise UserError('Drag a rectangle around the star first.')
            repaired['image']=erase_region(original,selected['box']);display=repaired['image'].copy();display.thumbnail((900,500))
            canvas.photo=ImageTk.PhotoImage(display);canvas.itemconfigure(image_id,image=canvas.photo);canvas.delete('selection')
        def save():
            if self.busy:raise UserError('Stop generation before saving an image repair.')
            job.require_mutable()
            if 'image' not in repaired:raise UserError('Preview the repair before saving.')
            if file_hash(path)!=before:raise UserError('The image changed. Reopen the repair tool.')
            import shutil
            backup=job.folder/'images_before_cleanup'/path.name;backup.parent.mkdir(exist_ok=True)
            if not backup.exists():shutil.copy2(path,backup)
            temp=path.with_suffix('.partial.png');repaired['image'].save(temp,'PNG');os.replace(temp,path)
            meta=path.with_suffix('.json');data=read_json(meta)
            data.update(sha256=file_hash(path),visible_star_cleanup={'status':'manual_cleaned','version':CLEANUP_VERSION,'box':selected['box']});atomic_json(meta,data)
            job.status('IMAGES_IMPORTED','Star repair saved. Continue project to rebuild the draft and any graphics.');win.destroy();self.refresh()
        row=ttk.Frame(win);row.pack(fill='x',padx=12,pady=10)
        ttk.Button(row,text='Preview repair',command=lambda:self.safe(preview)).pack(side='left')
        ttk.Button(row,text='Save repair',command=lambda:self.safe(save)).pack(side='right')
    def select_variant(self):
        def go():flow.choose_variant(self.require_job(),self.shot_choice.get(),int(self.variant.get()));self.refresh()
        self.safe(go)
    def install(self):
        if not self.job:return
        job=self.job
        if job.settings.video_editor=='kdenlive':return self.safe(self.open_kdenlive)
        path=filedialog.askopenfilename(title='NEW EMPTY CapCut destination (close CapCut first)',filetypes=[('CapCut draft','draft_content.json')])
        if not path:return
        needs_build=job.data['state'] not in ('READY_FOR_CAPCUT','AWAITING_REVIEW') or not (job.folder/'capcut'/'draft_content.json').is_file()
        message=('Build the complete draft, then install it into this empty project?' if needs_build else 'Install the completed draft into this empty project?')
        message+=' A backup is created before installation. If the draft cannot be completed, the destination is left unchanged.\n\n'+path
        if dialog(self,'Build and install' if needs_build else 'Install timeline',message,question=True):
            self.work(lambda:pipeline.build_and_install(job,path,self.cancel,self.log))
    def restore(self):
        if self.job and self.job.settings.video_editor!='capcut':
            dialog(self,'Kdenlive project','Create an editing revision for your saved Kdenlive edit. Blank-project restore is for CapCut.');return
        if self.job and dialog(self,'Restore','Restore the blank project? This refuses to overwrite later edits made in CapCut.',question=True):self.work(lambda:capcut.restore(self.job))
    def finish(self):
        def go():
            j=self.require_job()
            if dialog(self,'Finish unrendered',f'Have you opened the project in {j.settings.video_editor.title()}, checked all images, narration, text and audio, and saved the completed edit?',question=True):
                if j.settings.video_editor=='capcut':capcut.mark_finished(j)
                else:
                    if not j.data.get('installed_path'):raise UserError('Open / save the Kdenlive project first.')
                    j.status('FINISHED_UNRENDERED','Kdenlive review confirmed. Final export remains manual.')
                self.refresh()
        self.safe(go)
    def close_app(self):
        if self.busy:self.cancel.set();dialog(self,'Stopping','Stop requested. Wait for the current operation to finish, then close.');return
        self.stop_work();self.destroy()

    def open_kdenlive(self):
        job=self.require_job()
        if job.settings.video_editor!='kdenlive':raise UserError('Choose Kdenlive and apply customization to this project first.')
        source=job.folder/'kdenlive/VideoPilot.kdenlive'
        if not source.exists():raise UserError('Continue project to build the Kdenlive timeline first.')
        executable=Path(job.settings.kdenlive_path)
        if not executable.is_file():raise UserError('Kdenlive executable was not found at '+str(executable))
        destination=job.data.get('installed_path')
        if not destination:
            destination=filedialog.asksaveasfilename(title='Save editable Kdenlive project',initialdir=str(Path.home()/'Videos'),initialfile=job.folder.name+'.kdenlive',defaultextension='.kdenlive',filetypes=[('Kdenlive project','*.kdenlive')])
            if not destination:return
            target=Path(destination)
            if target.exists():raise UserError('Choose a new filename to preserve existing Kdenlive edits.')
            from .kdenlive import validate
            validate(source)
            # Media and subtitle references are absolute, so Save As needs no copies.
            with target.open('xb') as out:out.write(source.read_bytes())
            job.data['installed_path']=str(target.resolve());job.status('AWAITING_REVIEW','Kdenlive project saved. Review it and export in the editor.')
        import subprocess
        subprocess.Popen([str(executable),str(destination)])
        self.refresh()

if __name__=='__main__':App().mainloop()
