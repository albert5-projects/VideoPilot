// Shared, deterministic geometry: photo, diagram and captions never intersect.
function compositionLayout(width, height, scene = 1) {
  const mx = width * .04, gap = width * .025, top = height * .045;
  const bottom = height * .79, usable = bottom - top;
  let image, graphic;
  if (width > height * 1.15) {
    const photoWidth = (width - 2 * mx - gap) * .60;
    const diagramWidth = width - 2 * mx - gap - photoWidth;
    const imageLeft = scene % 2 ? mx : mx + diagramWidth + gap;
    const graphicLeft = scene % 2 ? mx + photoWidth + gap : mx;
    image = {left:imageLeft,top,width:photoWidth,height:usable};
    graphic = {left:graphicLeft,top,width:diagramWidth,height:usable};
  } else {
    const verticalGap = height * .025, photoHeight = usable * .59;
    image = {left:mx,top,width:width-2*mx,height:photoHeight};
    graphic = {left:mx,top:top+photoHeight+verticalGap,width:width-2*mx,height:usable-photoHeight-verticalGap};
  }
  return {image,graphic,diagramTall:graphic.height>graphic.width,
    captions:{left:mx,top:height*.82,width:width-2*mx,height:height*.14}};
}
module.exports = {compositionLayout};
