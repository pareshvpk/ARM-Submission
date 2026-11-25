// Figma Plugin API script for the use_figma MCP tool (file key 2NEl8jhrQy4CnqK2gVgdSp).
// Builds screens 07 Result · Looks safe and 08 Result · Not checked on page "Screens".
// Not run yet: the Figma Starter plan MCP tool-call limit was reached on 2026-11-07.
// Node and variable ids below are the ones created in that file on 2026-11-07.
const page = figma.root.children.find(p=>p.id==='0:1'); await figma.setCurrentPageAsync(page);
const vid={bg:'1:3',surface:'1:4',surface2:'1:5',glass:'1:6',stroke:'1:7',text:'1:8',text2:'1:9',text3:'1:10',brand:'1:11',brandDeep:'1:12',onAccent:'1:13',danger:'1:14',dangerDeep:'1:15',warn:'1:16',warnDeep:'1:17',safe:'1:18',safeDeep:'1:19'};
const V={}; for (const [k,id] of Object.entries(vid)) V[k]=await figma.variables.getVariableByIdAsync('VariableID:'+id);
const R={}; for (const [k,id] of Object.entries({pill:'1:27',card:'1:28',tile:'1:29',sm:'1:30'})) R[k]=await figma.variables.getVariableByIdAsync('VariableID:'+id);
const S={'Display/XL':'S:569d8e80635522460d29889e41ceb28428fc6244,','Display/L':'S:0ba1d6b860ee702b8ec119f3e79de67273b2ea2e,','Heading/M':'S:7bef487ade5c9b5f63aa3243f3c49644dfbd98c4,','Body/L':'S:0f42906e613f4ac74c66f369f2ceb2a51e9545e0,','Body/M':'S:87646ac923792458e57b730d409045e8dcb7a080,','Label/M':'S:9e2d14aaa38d2b693aeac270d09f52b1efbb9cf2,','Label/S':'S:08a9c0c0bc13fb3a16bca214cc326fac2cb3fd2e,','Mono/M':'S:1aae217a48e437c8c35a463209eca1c056e5ba79,','Mono/S':'S:ae6c5d582c444983b785bc1975bd31141e3a50ca,'};
await Promise.all([['Space Grotesk','Bold'],['Space Grotesk','Medium'],['Inter','Regular'],['Inter','Medium'],['Inter','Semi Bold'],['JetBrains Mono','Regular'],['JetBrains Mono','Medium']].map(([family,style])=>figma.loadFontAsync({family,style})));
const paint=v=>figma.variables.setBoundVariableForPaint({type:'SOLID',color:{r:0,g:0,b:0}},'color',v);
const fill=(n,k)=>{n.fills=[paint(V[k])];}; const stroke=(n,k)=>{n.strokes=[paint(V[k])];n.strokeWeight=1;n.strokeAlign='INSIDE';};
const radius=(n,k)=>{for(const c of ['topLeftRadius','topRightRadius','bottomLeftRadius','bottomRightRadius']) n.setBoundVariable(c,R[k]);};
const text=async(chars,style,colorKey,width)=>{const t=figma.createText();await t.setTextStyleIdAsync(S[style]);t.characters=chars;fill(t,colorKey);if(width){t.resize(width,t.height);t.textAutoResize='HEIGHT';}return t;};
const iconIds={'shield':'2:6','shield-check':'2:10','shield-alert':'2:15','home':'2:19','history':'2:24','settings':'2:30','bell':'2:34','link':'2:38','alert':'2:43','check':'2:47','clipboard':'2:51','arrow-left':'2:55','wifi-off':'2:64','lock':'2:68','message':'2:71','sparkles':'2:74','cpu':'2:86','loader':'2:89','ban':'2:93','flag':'2:96','smartphone':'2:100','info':'2:105'};
const icon=async(name,colorKey='text',size=20)=>{const c=await figma.getNodeByIdAsync(iconIds[name]);const i=c.createInstance();i.resize(size,size);if(colorKey!=='text')for(const v of i.findAll(n=>'strokes' in n&&n.strokes.length))v.strokes=[paint(V[colorKey])];return i;};
const setOf=async id=>await figma.getNodeByIdAsync(id);
const variant=async(setId,name,label)=>{const s=await setOf(setId);const i=s.children.find(c=>c.name===name).createInstance();if(label){const key=Object.keys(s.componentPropertyDefinitions).find(k=>k.startsWith('Label'));i.setProperties({[key]:label});}return i;};
const glowPaint=(hex,a)=>{const n=parseInt(hex.slice(1),16);const c={r:((n>>16)&255)/255,g:((n>>8)&255)/255,b:(n&255)/255};return {type:'GRADIENT_RADIAL',gradientTransform:[[1,0,0],[0,1,0]],gradientStops:[{position:0,color:{...c,a}},{position:0.45,color:{...c,a:a*0.45}},{position:1,color:{...c,a:0}}]};};
const screen=async(name,x,glowHex,glowA=0.7)=>{const f=figma.createFrame();f.name=name;f.resize(360,800);f.x=x;f.y=0;f.clipsContent=true;fill(f,'bg');f.cornerRadius=36;
 const g=figma.createEllipse();g.name='Glow';g.resize(720,560);g.x=-180;g.y=-300;g.fills=[glowPaint(glowHex,glowA)];g.effects=[{type:'LAYER_BLUR',radius:40,visible:true}];f.appendChild(g);
 const sb=(await setOf('3:2')).createInstance();f.appendChild(sb);sb.x=0;sb.y=0;
 const c=figma.createAutoLayout('VERTICAL',{name:'Content',itemSpacing:12});c.fills=[];c.paddingLeft=c.paddingRight=20;c.paddingTop=8;c.paddingBottom=24;f.appendChild(c);c.x=0;c.y=36;c.resize(360,c.height);c.counterAxisSizingMode='FIXED';
 return {f,c};};
const card=(name,gap=10)=>{const k=figma.createAutoLayout('VERTICAL',{name,itemSpacing:gap});fill(k,'glass');stroke(k,'stroke');radius(k,'card');k.paddingLeft=k.paddingRight=k.paddingTop=k.paddingBottom=16;return k;};
const fillW=n=>{n.layoutSizingHorizontal='FILL';};
const iconBtn=async(name,colorKey='text')=>{const b=figma.createAutoLayout('HORIZONTAL',{name:'IconButton/'+name});b.paddingLeft=b.paddingRight=b.paddingTop=b.paddingBottom=10;fill(b,'glass');stroke(b,'stroke');radius(b,'pill');b.appendChild(await icon(name,colorKey,20));return b;};
const topBar=async(c)=>{const t=figma.createAutoLayout('HORIZONTAL',{name:'Top bar'});t.fills=[];t.primaryAxisAlignItems='SPACE_BETWEEN';t.counterAxisAlignItems='CENTER';t.appendChild(await iconBtn('arrow-left'));t.appendChild(await variant('3:34','Tone=Brand','Checked on this phone'));c.appendChild(t);fillW(t);};
const meter=(level,colorKey)=>{const m=figma.createAutoLayout('HORIZONTAL',{name:'Risk meter',itemSpacing:4});m.fills=[];for(let i=0;i<10;i++){const s=figma.createRectangle();s.resize(22,8);s.cornerRadius=4;fill(s,i<level?colorKey:'surface2');m.appendChild(s);}return m;};
const ids=[];
// ---------- 7 Safe
{ const {f,c}=await screen('07 Result · Looks safe',2520,'#1F9D63',0.6); ids.push(f.id);
  await topBar(c);
  const hero=figma.createAutoLayout('VERTICAL',{name:'Verdict',itemSpacing:10});hero.fills=[];c.appendChild(hero);fillW(hero);
  hero.appendChild(await variant('3:58','Level=Low'));
  hero.appendChild(await text('Looks safe.','Display/XL','text',320));
  hero.appendChild(await text('No scam signs found. Still, never share this OTP with anyone, even a caller who says they are the bank.','Body/L','text2',320));
  const mr=figma.createAutoLayout('HORIZONTAL',{name:'Risk row',itemSpacing:12});mr.fills=[];mr.counterAxisAlignItems='CENTER';mr.appendChild(meter(1,'safe'));mr.appendChild(await text('0.04','Mono/M','safe'));hero.appendChild(mr);
  const msg=card('Message',10);c.appendChild(msg);fillW(msg);
  msg.appendChild(await text('The message','Label/S','text3'));
  msg.appendChild(await text('482913 is your OTP for net banking login. Do not share it with anyone. - HDFC Bank','Body/M','text2',286));
  for (const [ic,t] of [['link','No links in this message'],['shield-check','Sender looks like a real bank shortcode']]) {const r=figma.createAutoLayout('HORIZONTAL',{name:'Fact',itemSpacing:10});r.fills=[];r.counterAxisAlignItems='CENTER';r.appendChild(await icon(ic,'safe',16));r.appendChild(await text(t,'Label/S','text'));msg.appendChild(r);}
  c.appendChild(await text('Detect 14 ms · no advice needed for low risk','Mono/S','text3',320));
  const sp=figma.createFrame();sp.name='Spacer';sp.fills=[];sp.resize(320,150);c.appendChild(sp);
  const acts=figma.createAutoLayout('HORIZONTAL',{name:'Actions',itemSpacing:10});acts.fills=[];const a1=await variant('3:18','Style=Secondary','Report anyway');acts.appendChild(a1);a1.layoutGrow=1;const a2=await variant('3:18','Style=Primary','Done');acts.appendChild(a2);a2.layoutGrow=1;c.appendChild(acts);fillW(acts);
}
// ---------- 8 Not checked
{ const {f,c}=await screen('08 Result · Not checked',2940,'#4B5568',0.55); ids.push(f.id);
  await topBar(c);
  const hero=figma.createAutoLayout('VERTICAL',{name:'Verdict',itemSpacing:10});hero.fills=[];c.appendChild(hero);fillW(hero);
  hero.appendChild(await variant('3:58','Level=Unchecked'));
  hero.appendChild(await text('Not checked yet.','Display/XL','text',320));
  hero.appendChild(await text('The detection models are still loading. Wait a few seconds and tap Check again.','Body/L','text2',320));
  const st=card('Model status',12);c.appendChild(st);fillW(st);
  st.appendChild(await text('Getting ready on this phone','Label/S','text3'));
  for (const [ic,colorK,name,state,stateK] of [['check','safe','URL model','Ready','safe'],['loader','brand','SMS model','Loading…','brand'],['sparkles','text3','Llama 3.2 1B','Waits for the SMS model','text3']]) {
    const r=figma.createAutoLayout('HORIZONTAL',{name:'Row/'+name,itemSpacing:12});r.fills=[];r.counterAxisAlignItems='CENTER';
    const b=figma.createAutoLayout('HORIZONTAL',{name:'Icon'});b.paddingLeft=b.paddingRight=b.paddingTop=b.paddingBottom=8;fill(b,'surface2');radius(b,'sm');b.appendChild(await icon(ic,colorK,18));r.appendChild(b);
    const col=figma.createAutoLayout('VERTICAL',{name:'Text',itemSpacing:2});col.fills=[];col.appendChild(await text(name,'Label/M','text'));col.appendChild(await text(state,'Label/S',stateK));r.appendChild(col);
    st.appendChild(r);fillW(r);
  }
  const note=figma.createAutoLayout('HORIZONTAL',{name:'Note',itemSpacing:10});note.fills=[];note.counterAxisAlignItems='CENTER';note.appendChild(await icon('lock','text3',16));note.appendChild(await text('Your message is kept on this phone. Nothing was sent anywhere.','Label/S','text3',280));c.appendChild(note);fillW(note);
  const sp=figma.createFrame();sp.name='Spacer';sp.fills=[];sp.resize(320,120);c.appendChild(sp);
  const p=await variant('3:18','Style=Primary','Check again');c.appendChild(p);fillW(p);
}
return {ids};
