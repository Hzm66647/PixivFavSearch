import sys
import re

# Read the preview HTML
with open("C:/temp/PixivFavSearch-unified.html", "r", encoding="utf-8") as f:
    preview = f.read()
preview_lines = preview.split("\n")

# Extract CSS (lines 2-192 in 1-indexed = indices 1-191)
preview_css = "\n".join(preview_lines[1:192]).strip()

# Extract HTML body (lines 194-345 in 1-indexed = indices 193-344)
preview_html = "\n".join(preview_lines[193:345]).strip()

# Extract keyframes (lines 488-490 in 1-indexed = indices 487-489)
preview_keyframes = "\n".join(preview_lines[487:490]).strip()

print(f"Preview CSS length: {len(preview_css)}")
print(f"Preview HTML length: {len(preview_html)}")
print(f"Preview keyframes length: {len(preview_keyframes)}")

# Build the new JS with API calls
new_js = '''<script>
let works=[];
let folders=[];
let safe=true;
let searchQuery='';

const fxState={lightTrail:true,magnetic:true,tilt3d:true,ripple:true,breathing:true,particles:true,aurora:true,waves:true,grid:false,nebula:false,contour:false};
const fxIntensity={lightTrail:60,magnetic:50,tilt3d:70,ripple:80,breathing:50,particles:60,aurora:50,waves:40};

const conflicts=[
 {effects:['tilt3d','magnetic'],msg:'3D倾斜与磁吸按钮冲突'},
 {effects:['tilt3d','ripple'],msg:'3D倾斜与波纹点击冲突'},
 {effects:['particles','nebula'],msg:'粒子场与星云雾冲突'},
 {effects:['aurora','waves'],msg:'极光流体与波浪层冲突'},
];

function colorHash(id){
 let h=0;const s=String(id);
 for(let i=0;i<s.length;i++){h=s.charCodeAt(i)+((h<<5)-h);}
 return 'hsl('+(Math.abs(h)%360)+', 60%, 50%)';
}

function workCard(w){
 const c=colorHash(w.id);
 const thumbUrl='/thumb/'+w.id;
 const author=w.userName||'Unknown';
 const title=w.title||'Untitled';
 return '<div class="card" data-id="'+w.id+'" onclick="openWork(\\''+w.id+'\\')">'+
 '<img class="card-img" src="'+thumbUrl+'" loading="lazy" style="width:100%;height:auto;min-height:120px;background:'+c+'" onerror="this.style.background=\\'linear-gradient(135deg,'+c+','+c+'dd)\\'">'+
 '<div class="card-ov"><div class="card-tt">'+title+'</div><div class="card-au">'+author+'</div>'+
 '<div class="card-act"><button class="card-btn" onclick="event.stopPropagation();showTags(\\''+w.id+'\\')">⭐</button>'+
 '<button class="card-btn" onclick="event.stopPropagation();this.classList.toggle(\\'liked\\')">❤️</button>'+
 '<button class="card-btn" onclick="event.stopPropagation()">🔗</button></div></div></div>';
}

function wallHTML(list){
 return list.filter(w=>safe?(!w.aiType||w.aiType<2):true).map(w=>workCard(w)).join('');
}

async function renderWall(){
 try{
  const p=new URLSearchParams({mode:'pixiv',q:searchQuery});
  const r=await fetch('/api/search?'+p);
  const d=await r.json();
  works=d.items||[];
  document.getElementById('wall').innerHTML=wallHTML(works);
 }catch(e){
  document.getElementById('wall').innerHTML='<div style="padding:40px;color:var(--sub)">加载失败</div>';
 }
}

async function renderFavs(){
 try{
  const r=await fetch('/api/coltags');
  const d=await r.json();
  folders=(d.tags||[]).map(t=>({name:t.tag,count:t.count,color:colorHash(t.tag)}));
  document.getElementById('fav-grid').innerHTML=folders.map((f,i)=>'<div class="fav-card" onclick="openFav('+i+')"><div class="fav-card-bg" style="background:linear-gradient(135deg,'+f.color+','+f.color+'88)"></div><div class="fav-card-info"><div class="fav-card-name">'+f.name+'</div><div class="fav-card-count">'+f.count+' 幅</div></div></div>').join('');
 }catch(e){
  document.getElementById('fav-grid').innerHTML='<div style="padding:40px;color:var(--sub)">加载失败</div>';
 }
}

let pageTransitioning=false;
function go(targetPage){
 if(pageTransitioning)return;
 const cur=document.querySelector('.page.active');
 const next=document.getElementById('pg-'+targetPage);
 if(!cur||!next||cur===next)return;
 pageTransitioning=true;
 cur.classList.remove('active');
 cur.classList.add('exit');
 next.classList.add('active');
 document.querySelectorAll('.sb-item').forEach((s,i)=>{
  const isActive=(targetPage==='search'&&i===0)||((targetPage==='fav'||targetPage==='inner')&&i===1)||(targetPage==='settings'&&i===2);
  s.classList.toggle('active',isActive);
 });
 setTimeout(()=>{cur.classList.remove('exit');pageTransitioning=false},400);
 if(targetPage==='search')renderWall();
 else if(targetPage==='fav')renderFavs();
 else if(targetPage==='inner')openFav(window.currentFavIdx);
}

async function openFav(idx){
 window.currentFavIdx=idx;
 const f=folders[idx];
 if(!f)return;
 document.getElementById('inner-title').textContent=f.name;
 try{
  const r=await fetch('/api/coltags/'+encodeURIComponent(f.name)+'/works');
  const d=await r.json();
  const items=d.items||[];
  document.getElementById('inner-wall').innerHTML=wallHTML(items);
 }catch(e){
  document.getElementById('inner-wall').innerHTML='<div style="padding:40px;color:var(--sub)">加载失败</div>';
 }
 go('inner');
}

function togSearch(){
 const p=document.getElementById('search-p');
 p.classList.toggle('open');
 if(p.classList.contains('open'))p.querySelector('input').focus();
}

document.addEventListener('DOMContentLoaded',function(){
 const input=document.querySelector('.search-float input');
 if(input){
  input.addEventListener('input',function(){
   searchQuery=this.value.trim();
   renderWall();
  });
  input.addEventListener('keydown',function(e){
   if(e.key==='Enter'){searchQuery=this.value.trim();renderWall();}
  });
 }
});

async function doImport(){
 const b=document.getElementById('prog');
 b.classList.remove('active');
 b.style.width='0%';
 requestAnimationFrame(()=>{b.classList.add('active')});
 try{
  const r=await fetch('/api/import',{method:'POST',body:'{}'});
  const d=await r.json();
  if(d.ok){
   const poll=setInterval(async()=>{
    try{
     const sr=await fetch('/api/import-status');
     const sd=await sr.json();
     if(sd.status==='done'||sd.status==='error'){
      clearInterval(poll);
      b.classList.remove('active');
      b.style.width='0%';
      if(sd.status==='done'){renderWall();renderFavs();}
     }
    }catch(e){clearInterval(poll);}
   },2000);
  }
 }catch(e){
  b.classList.remove('active');
  b.style.width='0%';
 }
}

function showTags(id){document.getElementById('tag-modal').classList.add('open');}
document.getElementById('tag-modal').addEventListener('click',function(e){if(e.target===this)this.classList.remove('open')});

function togSafe(){
 safe=!safe;
 document.getElementById('safe-tog').classList.toggle('on',safe);
 document.getElementById('safe-dot').classList.toggle('on',safe);
 renderWall();
}

function newFolder(){
 const n=prompt('收藏夹名称：');
 if(n){folders.push({name:n,count:0,color:colorHash(n)});renderFavs();}
}

function togTheme(){document.getElementById('theme-panel').classList.toggle('open');}

function renderPresets(){
 const presets=[
  {n:'紫梦',a:'#c77dff',b:'#000'},{n:'深海',a:'#4a90d9',b:'#000814'},
  {n:'森林',a:'#27ae60',b:'#0a1a10'},{n:'樱粉',a:'#e91e63',b:'#1a0810'},
  {n:'暖橙',a:'#f39c12',b:'#1a1008'},{n:'烈焰',a:'#e74c3c',b:'#1a0808'},
  {n:'青色',a:'#1abc9c',b:'#081a18'},{n:'靛蓝',a:'#3f51b5',b:'#0a0e28'},
  {n:'玫瑰',a:'#ff6b6b',b:'#1a0a0a'},{n:'薄荷',a:'#10b981',b:'#061a14'},
  {n:'葡萄',a:'#8b5cf6',b:'#0e0820'},{n:'柠檬',a:'#eab308',b:'#1a1606'}
 ];
 document.getElementById('preset-themes').innerHTML=presets.map(t=>'<div class="color-swatch" style="background:'+t.a+'" onclick="applyTheme(\\''+a+'\\','+b+'\\')" title="'+t.n+'"></div>').join('');
}

function applyTheme(a,b){
 document.documentElement.style.setProperty('--accent',a);
 document.documentElement.style.setProperty('--accent-g',a+'80');
 document.documentElement.style.setProperty('--bg',b);
 document.getElementById('pick-accent').value=a;
 document.getElementById('txt-accent').value=a;
 document.getElementById('pick-bg').value=b;
 document.getElementById('txt-bg').value=b;
 document.body.style.backgroundColor=b;
}

function applyAccent(v){if(/^#[0-9a-fA-F]{6}$/.test(v)){document.documentElement.style.setProperty('--accent',v);document.documentElement.style.setProperty('--accent-g',v+'80');document.getElementById('pick-accent').value=v;}}
function applyBg(v){if(/^#[0-9a-fA-F]{6}$/.test(v)){document.documentElement.style.setProperty('--bg',v);document.body.style.backgroundColor=v;document.getElementById('pick-bg').value=v;}}

function handleBg(input){
 if(input.files&&input.files[0]){
  const r=new FileReader();
  r.onload=function(e){
   const p=document.getElementById('bg-preview');
   p.classList.add('has-img');
   p.innerHTML='<img src="'+e.target.result+'"><button class="bg-rm" onclick="event.stopPropagation();rmBg()">✕</button>';
   document.body.style.backgroundImage='url('+e.target.result+')';
   document.body.style.backgroundSize='cover';
  };
  r.readAsDataURL(input.files[0]);
 }
}

function rmBg(){
 const p=document.getElementById('bg-preview');
 p.classList.remove('has-img');
 p.innerHTML='<span class="bg-txt">📷 点击导入图片</span><button class="bg-rm" onclick="event.stopPropagation();rmBg()">✕</button>';
 document.body.style.backgroundImage='';
}

function changeBounce(v){
 document.getElementById('bounce-val').textContent=v+'%';
 const y2=(1+v/100*0.8).toFixed(2);
 document.documentElement.style.setProperty('--ease-bounce','cubic-bezier(.22,'+y2+',.36,1)');
}

function toggleFx(el){
 el.classList.toggle('on');
 fxState[el.dataset.fx]=el.classList.contains('on');
 checkConflicts();
 updateSliders();
}

function updateSliders(){
 ['lightTrail','magnetic','tilt3d','ripple','breathing','particles','aurora','waves'].forEach(fx=>{
  const slider=document.getElementById(fx+'-slider');
  const val=document.getElementById(fx+'-val');
  if(slider&&val){
   slider.disabled=!fxState[fx];
   slider.parentElement.style.opacity=fxState[fx]?'1':'.4';
   val.textContent=slider.value+'%';
   slider.oninput=()=>{val.textContent=slider.value+'%';fxIntensity[fx]=parseInt(slider.value);};
  }
 });
}

function checkConflicts(){
 const warn=document.getElementById('conflict-warn');
 const txt=document.getElementById('conflict-text');
 for(const c of conflicts){
  if(c.effects.every(e=>fxState[e])){warn.classList.add('show');txt.textContent=c.msg;return;}
 }
 warn.classList.remove('show');
}

function resetAll(){
 applyTheme('#c77dff','#000');
 rmBg();
 document.getElementById('bounce-slider').value=100;
 changeBounce(100);
 document.querySelectorAll('.fx-tog').forEach(t=>{t.classList.add('on');fxState[t.dataset.fx]=true;});
 checkConflicts();
 updateSliders();
 document.getElementById('lightTrail-slider').value=60;
 document.getElementById('magnetic-slider').value=50;
 document.getElementById('tilt3d-slider').value=70;
 document.getElementById('ripple-slider').value=80;
 document.getElementById('breathing-slider').value=50;
 document.getElementById('particles-slider').value=60;
 document.getElementById('aurora-slider').value=50;
 document.getElementById('waves-slider').value=40;
 updateSliders();
}

function saveAll(){
 const b=event.target;
 b.textContent='已保存 ✓';
 b.style.background='#27ae60';
 setTimeout(()=>{b.textContent='保存';b.style.background='';},1500);
}

document.addEventListener('mousemove',e=>{
 if(!fxState.lightTrail)return;
 const intensity=fxIntensity.lightTrail/100;
 document.querySelectorAll('.card').forEach(card=>{
  const r=card.getBoundingClientRect();
  const cx=r.left+r.width/2;const cy=r.top+r.height/2;
  const dx=e.clientX-cx;const dy=e.clientY-cy;const dist=Math.sqrt(dx*dx+dy*dy);
  if(dist<200){card.style.boxShadow='0 '+(-dy*0.05)+'px '+(30-dist*0.1)+'px rgba(199,125,255,'+(0.3*(1-dist/200)*intensity)+')';}
  else{card.style.boxShadow='';}
 });
});

document.addEventListener('mousemove',e=>{
 if(!fxState.magnetic)return;
 const strength=fxIntensity.magnetic/100;
 document.querySelectorAll('.card').forEach(card=>{
  const r=card.getBoundingClientRect();
  const cx=r.left+r.width/2;const cy=r.top+r.height/2;
  const dx=e.clientX-cx;const dy=e.clientY-cy;const dist=Math.sqrt(dx*dx+dy*dy);
  if(dist<120){
   const force=(120-dist)/120*8*strength;
   card.querySelectorAll('.card-btn').forEach((btn,i)=>{
    const angle=(i-1)*0.3;
    btn.style.transform='translate('+Math.cos(angle)*force+'px,'+(Math.sin(angle)*force+force*0.5)+'px)';
   });
  }
 });
});

document.addEventListener('mousemove',e=>{
 if(!fxState.tilt3d)return;
 const maxAngle=fxIntensity.tilt3d/100*8;
 document.querySelectorAll('.card').forEach(card=>{
  const r=card.getBoundingClientRect();
  if(e.clientX>r.left&&e.clientX<r.right&&e.clientY>r.top&&e.clientY<r.bottom){
   const px=(e.clientX-r.left)/r.width-0.5;const py=(e.clientY-r.top)/r.height-0.5;
   card.style.transform='perspective(800px) rotateY('+(px*maxAngle)+'deg) rotateX('+(-py*maxAngle)+'deg) translateY(-8px) scale(1.03)';
  }
 });
});

document.addEventListener('click',e=>{
 if(!fxState.ripple)return;
 const ripple=document.createElement('div');
 ripple.style.cssText='position:fixed;left:'+(e.clientX-20)+'px;top:'+(e.clientY-20)+'px;width:40px;height:40px;border-radius:50%;background:radial-gradient(circle,rgba(199,125,255,.4),transparent);pointer-events:none;z-index:9999;animation:rippleExpand .6s ease-out forwards';
 document.body.appendChild(ripple);
 setTimeout(()=>ripple.remove(),600);
});

let lastMove=Date.now();
document.addEventListener('mousemove',()=>lastMove=Date.now());
function breathingLoop(){
 if(fxState.breathing&&Date.now()-lastMove>3000){
  const btn=document.querySelectorAll('.island-btn')[2];if(btn)btn.style.animation='breathe 2s ease-in-out infinite';
 }else{
  const btn=document.querySelectorAll('.island-btn')[2];if(btn)btn.style.animation='';
 }
 requestAnimationFrame(breathingLoop);
}
breathingLoop();

renderWall();renderFavs();renderPresets();updateSliders();
</script>'''

# Build the new INDEX
# Format: <meta charset="UTF-8"><title>...</title><style>CSS</style>\n\nHTML\n\nJS\n\nkeyframes
new_index = '<meta charset="UTF-8"><title>PixivFavSearch — 整合版</title><style>\n' + preview_css + '</style>\n\n' + preview_html + '\n\n' + new_js + '\n\n' + preview_keyframes

print(f"New INDEX length: {len(new_index)}")

# Read the current file
with open("C:/temp/Hermes/PixivFavSearch/pix_search_server.py", "r", encoding="utf-8") as f:
    full_content = f.read()
full_lines = full_content.split("\n")

# Find the INDEX line and the end of INDEX
index_start_line = None
index_end_line = None

for i,' if line.startswith('INDEX = r"""'):
        index_start_line = i
    elif index_start_line is not None and line.strip() == '"""' and i > index_start_line:
        index_end_line = i
        break

print(f"INDEX starts at line {index_start_line + 1}, ends at line {index_end_line + 1}")

# Build new file content
before_index = full_lines[:index_start_line]
after_index = full_lines[index_end_line + 1:]

# The INDEX line content
new_index_line = 'INDEX = r"""' + new_index + '"""'

new_content = "\n".join(before_index) + "\n" + new_index_line + "\n" + "\n".join(after_index)

print(f"New file line count: {len(new_content.split(chr(10)))}")

# Write to file
with open("C:/temp/Hermes/PixivFavSearch/pix_search_server.py", "w", encoding="utf-8") as f:
    f.write(new_content)

print("File written successfully!")