"""Small visible corner-star cleanup, with conservative shape matching.

Works locally on import, before resizing. Originals remain in flow_variants.
This removes a detected visible mark, not invisible provenance metadata.
"""
import numpy as np
from PIL import Image, ImageFilter
from pathlib import Path
from functools import lru_cache
from threading import RLock
from .core import DATA,read_json,atomic_json

CLEANUP_VERSION=3
FLOW_STAR_PROFILES=DATA/'flow-star-profiles.json'
_profile_lock=RLock()


@lru_cache(maxsize=1)
def _alpha_template():
    # Small opacity-only calibration from a flat-background Flow mark.
    # Contains no source artwork. Used only if local edge quality improves.
    with Image.open(Path(__file__).parent/'assets'/'gemini-star-alpha.png') as im:
        alpha=np.array(im.convert('L'))
        alpha[alpha>59]=79 # Constant-opacity interior; discard calibration grain.
        return Image.fromarray(alpha)


def _reverse_star(image,found):
    """Undo a translucent white mark, preserving lines through its interior."""
    best=None;cx=found['x']+(found['size']-1)/2;cy=found['y']+(found['size']-1)/2
    for size in range(max(24,found['size']-4),found['size']+5,2):
        extent=round(size*64/48)
        alpha=np.asarray(_alpha_template().resize((extent,extent),Image.Resampling.LANCZOS),dtype=np.float32)/255
        support=alpha>.025
        # Score just the outline; sharp background lines are excluded by trimming.
        dilated=np.asarray(Image.fromarray((support*255).astype('uint8')).filter(ImageFilter.MaxFilter(5)))>0
        eroded=np.asarray(Image.fromarray((support*255).astype('uint8')).filter(ImageFilter.MinFilter(5)))>0
        edge=dilated & ~eroded;edge[[0,-1],:]=False;edge[:,[0,-1]]=False
        def quality(patch):
            gray=patch.mean(2)
            lap=(np.abs(gray-np.roll(gray,1,0))+np.abs(gray-np.roll(gray,1,1)))[edge]
            return float(np.sort(lap)[:max(1,int(len(lap)*.8))].mean())
        for dy in range(-3,4):
            for dx in range(-3,4):
                x=round(cx-(extent-1)/2)+dx;y=round(cy-(extent-1)/2)+dy
                if x<0 or y<0 or x+extent>image.width or y+extent>image.height:continue
                patch=np.asarray(image.crop((x,y,x+extent,y+extent)),dtype=np.float32)
                restored=(patch-255*alpha[:,:,None])/(1-alpha[:,:,None])
                before=quality(patch);after=quality(restored)
                if before<1 or after>before*.95 or before-after<.6:continue
                # Standard Flow exports use a 48px mark. Boundary matching may
                # underestimate it when a dark line obscures one quadrant.
                size_penalty=.12*abs(size-48) if 40<=found['size']<=56 else 0
                score=after/before+size_penalty
                if best is None or score<best[0]:best=(score,x,y,restored,edge)
    if best is None:return None
    _,x,y,patch,edge=best
    # Edge-aware diffusion repairs antialiasing without washing a dark outline
    # into its light surroundings. Only the narrow boundary is touched.
    neighbors=[(1,0),(-1,0),(1,1),(-1,1)]
    weights=[np.exp(-np.mean((patch-np.roll(patch,shift,axis))**2,axis=2)/(22**2))[:,:,None]
             for shift,axis in neighbors]
    denominator=np.maximum(.001,sum(weights))
    for _ in range(30):
        average=sum(weight*np.roll(patch,shift,axis) for weight,(shift,axis) in zip(weights,neighbors))/denominator
        patch[edge]=average[edge]
    result=image.copy();result.paste(Image.fromarray(patch.clip(0,255).astype('uint8')),(x,y))
    return result


def _edge_match(tile):
    """Match the star boundary when a background line spoils whole-patch correlation.

    Require three well-supported quadrants. Work on coarse corner grids, then
    refine a few candidates; never allocate an image-sized floating-point array.
    """
    side=tile.shape[0];best=None
    angles=np.arange(96)*2*np.pi/96;dx=np.cos(angles);dy=np.sin(angles)
    for size in range(24,min(161,side-12),4):
        radius=(size/2)/(np.abs(dx)**.75+np.abs(dy)**.75)**(1/.75)
        inner=np.stack([dy*(radius-2),dx*(radius-2)])
        outer=np.stack([dy*(radius+2),dx*(radius+2)])
        def scores(ys,xs):
            cy=ys[:,None]+(size-1)/2;cx=xs[:,None]+(size-1)/2
            inside=tile[np.rint(cy+inner[0]).astype(int),np.rint(cx+inner[1]).astype(int)]
            outside=tile[np.rint(cy+outer[0]).astype(int),np.rint(cx+outer[1]).astype(int)]
            delta=inside-outside
            quadrants=(delta>6).reshape(-1,4,24).mean(2)
            votes=quadrants.mean(1)
            supported=(quadrants>=.83).sum(1)>=3
            return np.where(supported & (votes>=.70) & (np.median(delta,axis=1)>=12),votes,0)
        yy,xx=np.mgrid[4:side-size-4:4,4:side-size-4:4];ys=yy.ravel();xs=xx.ravel()
        if not len(xs):continue
        values=scores(ys,xs)
        for index in np.argsort(values)[-3:]:
            if values[index]<.70:continue
            ry,rx=np.mgrid[max(3,ys[index]-3):min(side-size-3,ys[index]+4),max(3,xs[index]-3):min(side-size-3,xs[index]+4)]
            refined=scores(ry.ravel(),rx.ravel());j=int(np.argmax(refined));confidence=float(refined[j])
            if confidence>=.70 and (best is None or confidence>best['confidence']):
                best={'x':int(rx.ravel()[j]),'y':int(ry.ravel()[j]),'size':size,'confidence':confidence,'method':'boundary'}
    return best


def _star(size):
    y,x=np.mgrid[:size,:size].astype(float)
    x=np.abs((x-(size-1)/2)/(size/2)); y=np.abs((y-(size-1)/2)/(size/2))
    return (x**.75+y**.75<=1).astype(np.float32)


def _sum_windows(a,size):
    p=np.pad(a,((1,0),(1,0))).cumsum(0).cumsum(1)
    return p[size:,size:]-p[:-size,size:]-p[size:,:-size]+p[:-size,:-size]


def detect_star(image):
    """Return only a strong star-shape match near either lower corner."""
    w,h=image.size; side=min(256,min(h,w)//3)
    best=None
    for x0 in (0,w-side):
        y0=h-side
        tile=np.asarray(image.crop((x0,y0,x0+side,h)).convert('RGB'),dtype=np.float32).mean(2)
        if tile.size==0 or float(np.ptp(tile))<12:continue
        # Resized landscape exports commonly have a 60-72 px mark. Searching
        # only 48/64/80 missed intermediate sizes; original Flow sizes vary too.
        for size in range(24,min(161,side),4):
            if size>=side: continue
            blur=np.asarray(Image.fromarray(tile.astype('uint8')).filter(ImageFilter.GaussianBlur(size/6)),dtype=float)
            signal=tile-blur
            mask=_star(size); template=mask-mask.mean()
            shape=(side+size-1,side+size-1)
            corr=np.fft.irfft2(np.fft.rfft2(signal,s=shape)*np.fft.rfft2(template[::-1,::-1],s=shape),s=shape)
            corr=corr[size-1:side,size-1:side]
            variance=np.maximum(0,_sum_windows(signal**2,size)-_sum_windows(signal,size)**2/(size*size))
            score=corr/np.maximum(1,np.sqrt(variance*np.sum(template**2)))
            yy,xx=np.mgrid[:score.shape[0],:score.shape[1]]
            edge_x=xx+size/2 if x0==0 else side-xx-size/2
            edge_y=side-yy-size/2
            score[(edge_x>size*4)|(edge_y>size*4)]=-1
            row,col=np.unravel_index(np.argmax(score),score.shape)
            confidence=float(score[row,col])
            patch=tile[row:row+size,col:col+size]
            contrast=float(patch[mask>0].mean()-patch[mask==0].mean())
            if confidence>=.65 and contrast>=12 and (best is None or confidence>best['confidence']):
                best={'x':int(x0+col),'y':int(y0+row),'size':size,'confidence':confidence}
    if best:return best
    for x0 in (0,w-side):
        tile=np.asarray(image.crop((x0,h-side,x0+side,h)).convert('RGB'),dtype=np.float32).mean(2)
        if tile.size==0 or float(np.ptp(tile))<12:continue
        found=_edge_match(tile)
        if found and (best is None or found['confidence']>best['confidence']):
            best=dict(found,x=found['x']+x0,y=found['y']+h-side)
    return best


def clean_flow_star(image):
    """Learn a bottom-right position on raw Flow images, shared across projects."""
    image=image.convert('RGB');w,h=image.size;key=f'{w}x{h}'
    with _profile_lock:
        try:profiles=read_json(FLOW_STAR_PROFILES)
        except (OSError,ValueError):profiles={}
        if not isinstance(profiles,dict):profiles={}
        found=profiles.get(key)
        if not (isinstance(found,dict) and all(type(found.get(k)) is int for k in ('x','y','size')) and
                24<=found['size']<=160 and w*.5<found['x']<=w-found['size'] and h*.5<found['y']<=h-found['size']):
            found=None
        reused=found is not None
        if found is None:
            found=detect_star(image)
            if found and found['x']>w*.5 and found['y']>h*.5:
                profiles[key]={k:int(found[k]) for k in ('x','y','size')}
                try:atomic_json(FLOW_STAR_PROFILES,profiles)
                except OSError:pass  # Cleanup still works if preferences cannot be saved.
    if not found:return image,{'status':'no_confident_match','version':CLEANUP_VERSION}
    # Fixed-region inpainting does not depend on watermark opacity. Avoid
    # transparency reversal here: a faint mark may have a different alpha.
    cleaned,report=_clean_at(image,found,reverse=False)
    report['position_source']='saved Flow profile' if reused else 'detected'
    return cleaned,report


def clean_visible_star(image):
    image=image.convert('RGB'); found=detect_star(image)
    if not found: return image,{'status':'no_confident_match','version':CLEANUP_VERSION}
    return _clean_at(image,found)


def _clean_at(image,found,reverse=True):
    reversed_image=_reverse_star(image,found) if reverse else None
    if reversed_image is not None:
        return reversed_image,dict(found,status='cleaned',repair='transparency reversal',version=CLEANUP_VERSION)
    x,y,size=found['x'],found['y'],found['size']
    # Expand the shape slightly to include antialiasing; interpolate only inside it.
    pad=7; x0=max(0,x-pad); y0=max(0,y-pad)
    x1=min(image.width,x+size+pad); y1=min(image.height,y+size+pad)
    mask=Image.new('L',(x1-x0,y1-y0))
    mask.paste(Image.fromarray((_star(size)*255).astype('uint8')),(x-x0,y-y0))
    mask=np.asarray(mask.filter(ImageFilter.MaxFilter(11)))>0
    mask[[0,-1],:]=False; mask[:,[0,-1]]=False
    patch=np.array(image.crop((x0,y0,x1,y1)),dtype=np.float32)
    patch[mask]=np.median(patch[~mask],axis=0)
    for _ in range(500):
        average=(np.roll(patch,1,0)+np.roll(patch,-1,0)+np.roll(patch,1,1)+np.roll(patch,-1,1))*.25
        patch[mask]=average[mask]
    result=image.copy();result.paste(Image.fromarray(np.clip(patch,0,255).astype('uint8')),(x0,y0))
    return result,dict(found,status='cleaned',version=CLEANUP_VERSION)


def erase_region(image,box):
    """User-selected repair for a mark outside the automatic detector's profiles."""
    x0,y0,x1,y1=map(int,box)
    if x1-x0<3 or y1-y0<3 or x1-x0>image.width*.2 or y1-y0>image.height*.2:
        raise ValueError('Select a small rectangle around the star (at most 20% of each image dimension).')
    if x0<0 or y0<0 or x1>image.width or y1>image.height:raise ValueError('Selection is outside the image.')
    left=max(0,x0-6);top=max(0,y0-6);right=min(image.width,x1+6);bottom=min(image.height,y1+6)
    patch=np.array(image.convert('RGB').crop((left,top,right,bottom)),dtype=np.float32)
    mask=np.zeros(patch.shape[:2],dtype=bool);mask[y0-top:y1-top,x0-left:x1-left]=True
    mask[[0,-1],:]=False;mask[:,[0,-1]]=False
    patch[mask]=np.median(patch[~mask],axis=0)
    for _ in range(700):
        avg=(np.roll(patch,1,0)+np.roll(patch,-1,0)+np.roll(patch,1,1)+np.roll(patch,-1,1))*.25
        patch[mask]=avg[mask]
    result=image.convert('RGB').copy();result.paste(Image.fromarray(patch.clip(0,255).astype('uint8')),(left,top))
    return result


def upgrade_project_images(job,timeline,log):
    """Refresh old cleanup before rendering/export; valid image cache isn't enough."""
    from .core import read_json,atomic_json,file_hash
    from .pipeline import cached_image
    from PIL import ImageOps
    import os
    job.require_mutable();updated=0
    for shot in timeline['shots']:
        if not cached_image(job,shot):continue
        path=job.folder/'images'/f'{shot["id"]}.png';meta=path.with_suffix('.json');data=read_json(meta)
        cleanup=data.get('visible_star_cleanup',{})
        if cleanup.get('version')==CLEANUP_VERSION or cleanup.get('status')=='manual_cleaned':continue
        variant=job.folder/'flow_variants'/shot['id']/f'v{data.get("selected_variant",1)}.png'
        # A manually replaced selection must not be replaced with an old variant.
        use_variant='Google Flow' in data.get('source','') and variant.is_file()
        source=variant if use_variant else path
        with Image.open(source) as im:
            cleaned,report=clean_visible_star(ImageOps.exif_transpose(im))
            if report['status']=='cleaned' or use_variant:
                if source==path:
                    import shutil
                    backup=job.folder/'images_before_cleanup'/path.name;backup.parent.mkdir(exist_ok=True)
                    if not backup.exists():shutil.copy2(path,backup)
                cleaned=ImageOps.fit(cleaned,job.settings.dimensions,method=Image.Resampling.LANCZOS)
                tmp=path.with_suffix('.partial.png');cleaned.save(tmp,'PNG');os.replace(tmp,path);updated+=1
        data.update(sha256=file_hash(path),visible_star_cleanup=report);atomic_json(meta,data)
    if updated:log(f'Reprocessed visible-star cleanup on {updated} cached images; dependent graphics will rebuild.')
    return updated
