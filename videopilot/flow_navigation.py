"""Recovery-only gallery direction and resumable navigation; no image matching."""
from .core import atomic_json

SCROLL_JS=r'''({action,top})=>{
 const elements=[document.scrollingElement,...document.querySelectorAll('main,section,div')];
 const target=elements.filter(e=>e&&e.scrollHeight>e.clientHeight+100&&e.clientHeight>200&&e.querySelector('img')).sort((a,b)=>b.scrollHeight-a.scrollHeight)[0];
 if(!target)return null;
 const max=target.scrollHeight-target.clientHeight;
 if(action==='restore')target.scrollTop=Math.min(max,Math.max(0,top));
 if(action==='oldest')target.scrollTop=max;
 if(action==='forward')target.scrollTop=target.scrollTop<=5?max:Math.max(0,target.scrollTop-Math.max(200,target.clientHeight*.75));
 if(action==='reverse')target.scrollTop=target.scrollTop>=max-5?0:Math.min(max,target.scrollTop+Math.max(200,target.clientHeight*.75));
 return target.scrollTop;
}'''


class RecoveryNavigation:
    def __init__(self,page,state,path,order,verify=False):
        self.page=page;self.state=state;self.path=path;self.order=order
        saved=state.get('recovery_navigation',{}) if not verify else {}
        self.owners=dict(saved.get('owners',{}));self.top=None
        self.resume=saved.get('top') if saved.get('order')==order else None
        self.initialized=False

    def prepare(self):
        if self.initialized:return
        action='restore' if isinstance(self.resume,(int,float)) else ('oldest' if self.order=='forward' else 'restore')
        self.top=self.page.evaluate(SCROLL_JS,{'action':action,'top':self.resume or 0})
        self.page.wait_for_timeout(250)
        self.initialized=True

    def remember(self,cards=()):
        for card in cards:
            if card.get('proof')=='history-step' and card.get('owner'):
                for media_id in card.get('ids',[]):self.owners[media_id]=card['owner']
        self.state['recovery_navigation']={'order':self.order,'top':self.top,'owners':self.owners.copy()}
        atomic_json(self.path,self.state)

    def opening(self):
        self.top=self.page.evaluate(SCROLL_JS,{'action':'read','top':0})
        self.remember()

    def sweep(self):
        self.prepare()
        self.top=self.page.evaluate(SCROLL_JS,{'action':self.order,'top':0})
        self.remember()
